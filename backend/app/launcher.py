from __future__ import annotations

import argparse
import logging
import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

import pyperclip
import pystray
import uvicorn
from PIL import Image

from .config import DEFAULT_PORT, AppPaths, network_urls, resource_path
from .main import create_app


def private_network_available() -> bool:
    if sys.platform != "win32":
        return True
    command = (
        "Get-NetConnectionProfile | Where-Object {"
        "$_.IPv4Connectivity -ne 'Disconnected' -and "
        "$_.NetworkCategory -in @('Private','DomainAuthenticated')} | "
        "Select-Object -First 1 -ExpandProperty NetworkCategory"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
            text=True,
            timeout=8,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        return result.returncode == 0 and bool(result.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        return False


def port_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.25)
        if probe.connect_ex(("127.0.0.1", port)) == 0:
            return False
    family = socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as sock:
        if sys.platform == "win32" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            sock.bind((host, port))
            return True
        except OSError:
            return False


def preferred_desktop_url(urls: dict[str, list[str]], port: int) -> str:
    reachable = [*urls.get("lan", []), *urls.get("tailscale", [])]
    return reachable[0] if reachable else f"http://127.0.0.1:{port}"


def configure_logging(paths: AppPaths) -> None:
    paths.ensure()
    handlers: list[logging.Handler] = [
        logging.FileHandler(paths.logs / "app.log", encoding="utf-8")
    ]
    if sys.stdout is not None:
        handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=handlers,
        force=True,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


class ServerThread(threading.Thread):
    def __init__(self, host: str, port: int):
        super().__init__(name="uvicorn-server", daemon=True)
        config = uvicorn.Config(
            create_app(),
            host=host,
            port=port,
            log_level="info",
            access_log=False,
            log_config=None,
        )
        self.server = uvicorn.Server(config)
        self.error: BaseException | None = None

    def run(self) -> None:
        try:
            self.server.run()
        except BaseException as exc:
            self.error = exc
            logging.exception("Local server crashed during startup.")

    def stop(self) -> None:
        self.server.should_exit = True


def wait_until_ready(server: ServerThread, port: int, timeout: float = 15) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if server.error is not None or not server.is_alive():
            return False
        if not server.server.started:
            time.sleep(0.15)
            continue
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.25):
                return True
        except OSError:
            time.sleep(0.15)
    return False


class StudioArgumentParser(argparse.ArgumentParser):
    def _print_message(self, message, file=None):
        # PyInstaller's windowed bootloader has no stdout/stderr. Help and
        # invalid arguments must exit normally, not open a traceback dialog.
        stream = file if file is not None else sys.stderr
        if stream is not None:
            super()._print_message(message, stream)


def main() -> int:
    parser = StudioArgumentParser(description="NovelAI LAN Studio")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--no-tray", action="store_true")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()

    paths = AppPaths.from_environment()
    configure_logging(paths)
    lan_enabled = private_network_available()
    urls = network_urls(args.port)
    tailscale_enabled = bool(urls["tailscale"])
    os.environ["NOVELAI_STUDIO_LAN_ENABLED"] = "1" if lan_enabled else "0"
    os.environ["NOVELAI_STUDIO_TAILSCALE_ENABLED"] = "1" if tailscale_enabled else "0"
    os.environ["NOVELAI_STUDIO_PORT"] = str(args.port)
    host = "0.0.0.0" if lan_enabled or tailscale_enabled else "127.0.0.1"
    if not port_available(host, args.port):
        logging.error("Port %s is already in use.", args.port)
        return 2
    server = ServerThread(host, args.port)
    server.start()
    if not wait_until_ready(server, args.port):
        logging.error("Server did not start in time.")
        server.stop()
        server.join(timeout=3)
        return 3

    desktop_url = preferred_desktop_url(urls, args.port)
    if not args.no_browser:
        webbrowser.open(desktop_url)

    if args.no_tray:
        try:
            while server.is_alive():
                time.sleep(0.5)
        except KeyboardInterrupt:
            server.stop()
        return 0

    icon_path = resource_path("assets/app-icon.png")
    icon_image = Image.open(icon_path).convert("RGBA")

    def open_desktop(_: pystray.Icon, __: pystray.MenuItem) -> None:
        webbrowser.open(desktop_url)

    def copy_lan(_: pystray.Icon, __: pystray.MenuItem) -> None:
        pyperclip.copy(
            urls["lan"][0]
            if urls["lan"]
            else "LAN 접속 비활성화: Windows 네트워크를 '개인'으로 설정하세요."
        )

    def copy_tailscale(_: pystray.Icon, __: pystray.MenuItem) -> None:
        pyperclip.copy(
            urls["tailscale"][0]
            if urls["tailscale"]
            else "Tailscale을 연결한 뒤 NovelAI LAN Studio를 다시 실행하세요."
        )

    def quit_app(icon: pystray.Icon, _: pystray.MenuItem) -> None:
        server.stop()
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("PC 화면 열기", open_desktop, default=True),
        pystray.MenuItem("LAN 주소 복사", copy_lan, enabled=bool(urls["lan"])),
        pystray.MenuItem(
            "Tailscale 주소 복사",
            copy_tailscale,
            enabled=bool(urls["tailscale"]),
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("종료", quit_app),
    )
    tray = pystray.Icon("NovelAI-LAN-Studio", icon_image, "NovelAI LAN Studio", menu)
    try:
        tray.run()
    finally:
        server.stop()
        server.join(timeout=10)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
