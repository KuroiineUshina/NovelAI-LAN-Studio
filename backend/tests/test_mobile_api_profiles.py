from __future__ import annotations

import base64

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi.testclient import TestClient


def _mobile_public_key() -> tuple[rsa.RSAPrivateKey, str]:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_der = private.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private, base64.b64encode(public_der).decode("ascii")


def test_mobile_api_profile_requires_separate_pc_approval_and_is_encrypted(
    app, authorize_remote
) -> None:
    token = "pst-mobile-profile-secret-token"
    app.state.services.credentials.token = token
    private, public_key_b64 = _mobile_public_key()

    with TestClient(app, client=("192.168.1.77", 41001)) as mobile:
        device_id, _ = authorize_remote(mobile, display_name="Galaxy Fold")
        request = mobile.post(
            "/api/mobile/api-profiles/requests",
            json={
                "profile_name": "개인 Opus",
                "key_id": "android-keystore-key-v1",
                "public_key_b64": public_key_b64,
            },
        )
        assert request.status_code == 202
        pending = request.json()
        assert pending["status"] == "pending"
        assert len(pending["verification_code"]) == 6
        assert token not in request.text

        before = mobile.get(
            f"/api/mobile/api-profiles/requests/{pending['id']}"
        ).json()
        assert before["status"] == "pending"
        assert "encrypted_token_b64" not in before

        with TestClient(app) as desktop:
            listed = desktop.get("/api/admin/api-profile-transfers").json()["items"]
            assert listed[0]["device_id"] == device_id
            assert listed[0]["display_name"] == "Galaxy Fold"
            assert listed[0]["verification_code"] == pending["verification_code"]
            assert "public_key_b64" not in listed[0]
            approved = desktop.post(
                f"/api/admin/api-profile-transfers/{pending['id']}/approve"
            )
            assert approved.status_code == 200
            assert token not in approved.text

        delivered = mobile.get(
            f"/api/mobile/api-profiles/requests/{pending['id']}"
        ).json()
        assert delivered["status"] == "approved"
        assert delivered["server_id"]
        encrypted = base64.b64decode(delivered["encrypted_token_b64"])
        decrypted = private.decrypt(
            encrypted,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA1()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        ).decode("utf-8")
        assert decrypted == token

        record = app.state.services.database.get_api_profile_transfer(
            pending["id"], include_key=True
        )
        assert record is not None
        assert record["delivered_at"] is not None
        assert token not in str(record)


def test_mobile_api_profile_request_rejects_invalid_key(app, authorize_remote) -> None:
    app.state.services.credentials.token = "pst-test-token"
    with TestClient(app, client=("192.168.1.78", 41002)) as mobile:
        authorize_remote(mobile)
        response = mobile.post(
            "/api/mobile/api-profiles/requests",
            json={
                "profile_name": "잘못된 키",
                "key_id": "invalid-key-id",
                "public_key_b64": "A" * 300,
            },
        )
        assert response.status_code == 400


def test_local_browser_cannot_create_mobile_profile_request(client: TestClient) -> None:
    _, public_key_b64 = _mobile_public_key()
    response = client.post(
        "/api/mobile/api-profiles/requests",
        json={
            "profile_name": "PC",
            "key_id": "android-keystore-key-v1",
            "public_key_b64": public_key_b64,
        },
    )
    assert response.status_code == 403
