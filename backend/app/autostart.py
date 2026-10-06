from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Protocol


RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE_NAME = "NovelAI LAN Studio"


class AutostartError(RuntimeError):
    pass


class RunValueStore(Protocol):
    def read(self, name: str) -> str | None: ...

    def write(self, name: str, value: str) -> None: ...

    def delete(self, name: str) -> None: ...


class WindowsRunValueStore:
    def read(self, name: str) -> str | None:
        import winreg

        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                RUN_KEY_PATH,
                0,
                winreg.KEY_READ,
            ) as key:
                value, _ = winreg.QueryValueEx(key, name)
                return str(value).strip() or None
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise AutostartError("Windows 시작 프로그램 상태를 읽지 못했습니다.") from exc

    def write(self, name: str, value: str) -> None:
        import winreg

        try:
            with winreg.CreateKeyEx(
                winreg.HKEY_CURRENT_USER,
                RUN_KEY_PATH,
                0,
                winreg.KEY_SET_VALUE,
            ) as key:
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
        except OSError as exc:
            raise AutostartError("Windows 시작 프로그램에 등록하지 못했습니다.") from exc

    def delete(self, name: str) -> None:
        import winreg

        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                RUN_KEY_PATH,
                0,
                winreg.KEY_SET_VALUE,
            ) as key:
                try:
                    winreg.DeleteValue(key, name)
                except FileNotFoundError:
                    return
        except FileNotFoundError:
            return
        except OSError as exc:
            raise AutostartError("Windows 시작 프로그램 등록을 해제하지 못했습니다.") from exc


def build_autostart_command(executable: Path) -> str:
    return subprocess.list2cmdline([str(executable.resolve()), "--no-browser"])


class WindowsAutostart:
    def __init__(
        self,
        *,
        executable: Path | None = None,
        platform: str | None = None,
        frozen: bool | None = None,
        store: RunValueStore | None = None,
    ):
        self.executable = (executable or Path(sys.executable)).resolve()
        self.platform = platform or sys.platform
        self.frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
        self.store = store

    @property
    def supported(self) -> bool:
        return self.platform == "win32" and self.frozen

    @property
    def expected_command(self) -> str:
        return build_autostart_command(self.executable)

    def _store(self) -> RunValueStore:
        return self.store or WindowsRunValueStore()

    def status(self) -> dict[str, object]:
        if not self.supported:
            return {
                "supported": False,
                "enabled": False,
                "registered": False,
                "matches_current": False,
                "message": "Windows 패키지 실행본에서만 사용할 수 있습니다.",
            }
        registered_command = self._store().read(RUN_VALUE_NAME)
        registered = registered_command is not None
        matches_current = registered_command == self.expected_command
        if matches_current:
            message = "Windows 로그인 시 브라우저 없이 트레이로 자동 실행됩니다."
        elif registered:
            message = "다른 위치의 실행 파일이 등록되어 있습니다. 켜면 현재 경로로 갱신됩니다."
        else:
            message = "자동 실행이 꺼져 있습니다."
        return {
            "supported": True,
            "enabled": matches_current,
            "registered": registered,
            "matches_current": matches_current,
            "message": message,
        }

    def set_enabled(self, enabled: bool) -> dict[str, object]:
        if not self.supported:
            raise AutostartError("Windows 패키지 실행본에서만 자동 시작을 설정할 수 있습니다.")
        store = self._store()
        if enabled:
            store.write(RUN_VALUE_NAME, self.expected_command)
        else:
            store.delete(RUN_VALUE_NAME)
        return self.status()


def get_autostart_status() -> dict[str, object]:
    return WindowsAutostart().status()


def set_autostart_enabled(enabled: bool) -> dict[str, object]:
    return WindowsAutostart().set_enabled(enabled)
