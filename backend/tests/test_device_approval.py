from __future__ import annotations

import uuid
import pytest

from fastapi.testclient import TestClient

from backend.app.main import create_app


def device_credentials() -> tuple[str, str]:
    return f"mobile-{uuid.uuid4()}", uuid.uuid4().hex + uuid.uuid4().hex


def test_mobile_requires_desktop_approval_and_stays_logged_in(app):
    device_id, pairing_secret = device_credentials()
    with TestClient(app, client=("192.168.1.55", 41000)) as mobile:
        status = mobile.get("/api/status")
        assert status.status_code == 200
        assert status.json()["device_approval_required"] is True
        assert status.json()["device_authorized"] is False
        assert mobile.get("/api/images?favorite=false&page=1").status_code == 401

        requested = mobile.post(
            "/api/device-auth/request",
            json={
                "device_id": device_id,
                "display_name": "Galaxy Fold",
                "pairing_secret": pairing_secret,
            },
        )
        assert requested.status_code == 202
        assert requested.json()["status"] == "pending"

        with TestClient(app) as desktop:
            listed = desktop.get("/api/admin/devices")
            assert listed.status_code == 200
            pending = listed.json()["items"][0]
            assert pending["device_id"] == device_id
            assert pending["display_name"] == "Galaxy Fold"
            assert "credential_hash" not in pending
            assert "pairing_secret" not in listed.text
            assert desktop.get("/api/status").json()["pending_device_count"] == 1
            approved = desktop.post(f"/api/admin/devices/{device_id}/approve")
            assert approved.status_code == 200

        polled = mobile.post(
            "/api/device-auth/poll",
            json={"device_id": device_id, "pairing_secret": pairing_secret},
        )
        assert polled.status_code == 200
        assert polled.json()["status"] == "approved"
        set_cookie = polled.headers["set-cookie"]
        assert "HttpOnly" in set_cookie
        assert "SameSite=strict" in set_cookie

        authorized = mobile.get("/api/status")
        assert authorized.json()["device_authorized"] is True
        assert authorized.json()["device_name"] == "Galaxy Fold"
        assert mobile.get("/api/images?favorite=false&page=1").status_code == 200


def test_same_pc_lan_address_does_not_require_device_approval(tmp_path):
    local_lan_address = "192.168.50.10"
    local_app = create_app(
        data_dir=tmp_path / "same-pc-data",
        start_workers=False,
        local_client_addresses={local_lan_address},
    )
    with TestClient(local_app, client=(local_lan_address, 42000)) as desktop_lan:
        status = desktop_lan.get(
            "/api/status", headers={"host": f"{local_lan_address}:8787"}
        )
        assert status.status_code == 200
        assert status.json()["device_approval_required"] is False
        assert status.json()["device_authorized"] is True
        assert status.json()["admin_available"] is True
        assert desktop_lan.get(
            "/api/presets", headers={"host": f"{local_lan_address}:8787"}
        ).status_code == 200
        assert desktop_lan.get(
            "/api/admin/settings", headers={"host": f"{local_lan_address}:8787"}
        ).status_code == 200


def test_wrong_pairing_secret_cannot_claim_approved_device(app):
    device_id, pairing_secret = device_credentials()
    with TestClient(app, client=("192.168.1.56", 41000)) as mobile:
        assert mobile.post(
            "/api/device-auth/request",
            json={
                "device_id": device_id,
                "display_name": "iPad",
                "pairing_secret": pairing_secret,
            },
        ).status_code == 202
        with TestClient(app) as desktop:
            assert desktop.post(
                f"/api/admin/devices/{device_id}/approve"
            ).status_code == 200
        wrong = "0" * 64 if pairing_secret != "0" * 64 else "1" * 64
        response = mobile.post(
            "/api/device-auth/poll",
            json={"device_id": device_id, "pairing_secret": wrong},
        )
        assert response.status_code == 404
        assert mobile.get("/api/presets").status_code == 401


def test_desktop_can_revoke_an_approved_device(app, authorize_remote):
    with TestClient(app, client=("192.168.1.57", 41000)) as mobile:
        device_id, _ = authorize_remote(mobile, display_name="Revoked phone")
        assert mobile.get("/api/presets").status_code == 200
        with TestClient(app) as desktop:
            assert desktop.delete(f"/api/admin/devices/{device_id}").status_code == 204
        assert mobile.get("/api/presets").status_code == 401
        assert mobile.get("/api/status").json()["device_authorized"] is False


def test_mobile_cannot_manage_device_approvals_after_login(app, authorize_remote):
    with TestClient(app, client=("192.168.1.58", 41000)) as mobile:
        authorize_remote(mobile)
        assert mobile.get("/api/admin/devices").status_code == 403


@pytest.mark.parametrize("origin", ["http://192.168.1.56:8080", "http://testserver:8000", "http://testserver:0", "https://testserver", "null", "http://testserver@192.168.1.56", "http://testserver:invalid"])
def test_other_origin_cannot_approve_device(app, origin):
    device_id, secret = device_credentials()
    with TestClient(app, client=("192.168.1.56", 41000)) as mobile, TestClient(app) as desktop:
        assert mobile.post("/api/device-auth/request", json={"device_id": device_id, "display_name": "Phone", "pairing_secret": secret}).status_code == 202
        result = desktop.post(f"/api/admin/devices/{device_id}/approve", headers={"Origin": origin})
        assert result.status_code == 403
        assert app.state.services.database.get_device_approval(device_id)["status"] == "pending"
        assert desktop.post(f"/api/admin/devices/{device_id}/approve", headers={"Origin": "http://testserver:80"}).status_code == 200


def test_cross_site_without_origin_is_rejected(client):
    assert client.post("/api/admin/cleanup", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
