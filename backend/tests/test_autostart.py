from __future__ import annotations

from pathlib import Path

import pytest

import backend.app.main as main_module
from backend.app.autostart import (
    RUN_VALUE_NAME,
    AutostartError,
    WindowsAutostart,
    build_autostart_command,
)


class FakeRunValueStore:
    def __init__(self):
        self.values: dict[str, str] = {}

    def read(self, name: str) -> str | None:
        return self.values.get(name)

    def write(self, name: str, value: str) -> None:
        self.values[name] = value

    def delete(self, name: str) -> None:
        self.values.pop(name, None)


def test_windows_autostart_registers_current_executable_without_browser(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "NovelAI LAN Studio.exe"
    store = FakeRunValueStore()
    autostart = WindowsAutostart(
        executable=executable,
        platform="win32",
        frozen=True,
        store=store,
    )

    assert autostart.status()["enabled"] is False
    enabled = autostart.set_enabled(True)

    assert store.values[RUN_VALUE_NAME] == build_autostart_command(executable)
    assert store.values[RUN_VALUE_NAME].endswith('" --no-browser')
    assert enabled["enabled"] is True
    assert enabled["matches_current"] is True

    disabled = autostart.set_enabled(False)
    assert RUN_VALUE_NAME not in store.values
    assert disabled["enabled"] is False


def test_windows_autostart_detects_registration_for_another_path(tmp_path: Path) -> None:
    executable = tmp_path / "current.exe"
    store = FakeRunValueStore()
    store.values[RUN_VALUE_NAME] = '"C:\\Old\\NovelAI-LAN-Studio.exe" --no-browser'
    autostart = WindowsAutostart(
        executable=executable,
        platform="win32",
        frozen=True,
        store=store,
    )

    status = autostart.status()
    assert status["registered"] is True
    assert status["enabled"] is False
    assert status["matches_current"] is False


def test_autostart_rejects_non_packaged_runtime(tmp_path: Path) -> None:
    autostart = WindowsAutostart(
        executable=tmp_path / "python.exe",
        platform="win32",
        frozen=False,
        store=FakeRunValueStore(),
    )

    assert autostart.status()["supported"] is False
    with pytest.raises(AutostartError):
        autostart.set_enabled(True)


def test_admin_settings_exposes_and_updates_autostart(client, monkeypatch) -> None:
    current = {
        "supported": True,
        "enabled": False,
        "registered": False,
        "matches_current": False,
        "message": "자동 실행이 꺼져 있습니다.",
    }
    updated = {
        **current,
        "enabled": True,
        "registered": True,
        "matches_current": True,
        "message": "Windows 로그인 시 브라우저 없이 트레이로 자동 실행됩니다.",
    }
    requested: list[bool] = []
    monkeypatch.setattr(main_module, "get_autostart_status", lambda: current)
    monkeypatch.setattr(
        main_module,
        "set_autostart_enabled",
        lambda enabled: requested.append(enabled) or updated,
    )

    settings = client.get("/api/admin/settings")
    response = client.put(
        "/api/admin/settings/autostart",
        json={"enabled": True},
    )

    assert settings.status_code == 200
    assert settings.json()["autostart"] == current
    assert response.status_code == 200
    assert response.json() == updated
    assert requested == [True]
