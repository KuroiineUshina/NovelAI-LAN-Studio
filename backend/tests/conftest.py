from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.main import create_app


class FakeCredentials:
    def __init__(self, token: str | None = None):
        self.token = token
        self.discord_webhooks: dict[str, str] = {}

    def get_token(self) -> str | None:
        return self.token

    def set_token(self, token: str) -> None:
        self.token = token

    def delete_token(self) -> None:
        self.token = None

    def get_discord_webhook_url(self, webhook_id: str) -> str | None:
        return self.discord_webhooks.get(webhook_id)

    def set_discord_webhook_url(self, webhook_id: str, url: str) -> None:
        self.discord_webhooks[webhook_id] = url

    def delete_discord_webhook_url(self, webhook_id: str) -> None:
        self.discord_webhooks.pop(webhook_id, None)


@pytest.fixture(autouse=True)
def testing_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("NOVELAI_STUDIO_TESTING", "1")
    monkeypatch.setenv("NOVELAI_STUDIO_CLAUDE_HOME", str(tmp_path / "claude-home"))
    monkeypatch.setenv("NOVELAI_STUDIO_CLAUDE_CONFIG", str(tmp_path / "claude.json"))
    monkeypatch.setenv("NOVELAI_STUDIO_LAN_ENABLED", "1")
    monkeypatch.setenv("NOVELAI_STUDIO_TAILSCALE_ENABLED", "1")


@pytest.fixture
def app(tmp_path: Path):
    instance = create_app(data_dir=tmp_path / "data", start_workers=False)
    credentials = FakeCredentials()
    instance.state.services.credentials = credentials
    instance.state.services.jobs.credentials = credentials
    return instance


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def authorize_remote(app):
    def authorize(
        remote: TestClient,
        *,
        headers: dict[str, str] | None = None,
        display_name: str = "테스트 모바일",
    ) -> tuple[str, str]:
        device_id = f"mobile-{uuid.uuid4()}"
        pairing_secret = uuid.uuid4().hex + uuid.uuid4().hex
        response = remote.post(
            "/api/device-auth/request",
            headers=headers,
            json={
                "device_id": device_id,
                "display_name": display_name,
                "pairing_secret": pairing_secret,
            },
        )
        assert response.status_code == 202
        with TestClient(app) as desktop:
            approval = desktop.post(f"/api/admin/devices/{device_id}/approve")
            assert approval.status_code == 200
        poll = remote.post(
            "/api/device-auth/poll",
            headers=headers,
            json={"device_id": device_id, "pairing_secret": pairing_secret},
        )
        assert poll.status_code == 200
        assert poll.json()["status"] == "approved"
        return device_id, pairing_secret

    return authorize


@pytest.fixture
def icon_bytes() -> bytes:
    return (Path(__file__).resolve().parents[2] / "assets" / "app-icon.png").read_bytes()
