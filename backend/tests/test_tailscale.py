from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app import config
from backend.app import main as main_module
from backend.app.config import is_tailscale_ipv4, network_urls


def test_tailscale_ipv4_boundaries_are_exact():
    assert is_tailscale_ipv4("100.64.0.0")
    assert is_tailscale_ipv4("100.100.20.30")
    assert is_tailscale_ipv4("100.127.255.255")
    assert not is_tailscale_ipv4("100.63.255.255")
    assert not is_tailscale_ipv4("100.128.0.0")
    assert not is_tailscale_ipv4("192.168.0.2")
    assert not is_tailscale_ipv4("not-an-ip")


def test_network_urls_lists_lan_before_tailscale(monkeypatch):
    monkeypatch.setattr(
        config,
        "_detected_ipv4_addresses",
        lambda: {"100.101.2.3", "192.168.0.2", "127.0.0.1", "8.8.8.8"},
    )
    urls = network_urls(8787)
    assert urls == {
        "lan": ["http://192.168.0.2:8787"],
        "tailscale": ["http://100.101.2.3:8787"],
        "all": ["http://192.168.0.2:8787", "http://100.101.2.3:8787"],
    }


def test_tailscale_peer_requires_device_approval_and_cannot_use_admin(
    app, authorize_remote
):
    with TestClient(app, client=("100.101.2.3", 40000)) as remote:
        headers = {"host": "100.101.20.30:8787"}
        status = remote.get("/api/status", headers=headers)
        assert status.status_code == 200
        assert status.json()["admin_available"] is False
        assert status.json()["remote_access_supported"] is True
        assert status.json()["device_approval_required"] is True
        assert status.json()["device_authorized"] is False
        assert remote.get("/api/presets", headers=headers).status_code == 401
        authorize_remote(remote, headers=headers)
        assert remote.get("/api/presets", headers=headers).status_code == 200
        assert remote.get("/api/admin/settings", headers=headers).status_code == 403


def test_status_separates_lan_and_tailscale_urls(client, monkeypatch):
    monkeypatch.setattr(
        main_module,
        "network_urls",
        lambda port: {
            "lan": [f"http://192.168.0.2:{port}"],
            "tailscale": [f"http://100.101.2.3:{port}"],
            "all": [f"http://192.168.0.2:{port}", f"http://100.101.2.3:{port}"],
        },
    )
    status = client.get("/api/status").json()
    assert status["lan_urls"] == ["http://192.168.0.2:8787"]
    assert status["tailscale_urls"] == ["http://100.101.2.3:8787"]
    assert status["mobile_urls"] == [
        "http://192.168.0.2:8787",
        "http://100.101.2.3:8787",
    ]
    assert status["tailscale_enabled"] is True


def test_tailscale_mode_does_not_reopen_lan_on_public_windows_profile(
    app, monkeypatch
):
    monkeypatch.setenv("NOVELAI_STUDIO_LAN_ENABLED", "0")
    monkeypatch.setenv("NOVELAI_STUDIO_TAILSCALE_ENABLED", "1")
    with TestClient(app, client=("100.101.2.3", 40000)) as tailscale_peer:
        assert tailscale_peer.get(
            "/api/status", headers={"host": "100.101.20.30:8787"}
        ).status_code == 200
    with TestClient(app, client=("192.168.0.20", 40000)) as lan_peer:
        assert lan_peer.get(
            "/api/status", headers={"host": "192.168.0.2:8787"}
        ).status_code == 403


def test_tailscale_peer_is_rejected_when_tailscale_mode_is_not_active(
    app, monkeypatch
):
    monkeypatch.setenv("NOVELAI_STUDIO_TAILSCALE_ENABLED", "0")
    with TestClient(app, client=("100.101.2.3", 40000)) as remote:
        assert remote.get(
            "/api/status", headers={"host": "100.101.20.30:8787"}
        ).status_code == 403


def test_neighboring_cgnat_and_public_ranges_stay_blocked(app):
    for address in ("100.63.255.255", "100.128.0.1", "8.8.8.8"):
        with TestClient(app, client=(address, 40000)) as remote:
            assert remote.get(
                "/api/status", headers={"host": f"{address}:8787"}
            ).status_code == 403
