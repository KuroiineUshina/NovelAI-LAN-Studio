from __future__ import annotations

import ipaddress
import os
import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


APP_NAME = "NovelAI-LAN-Studio"
DEFAULT_PORT = 8787
RETENTION_HOURS = 168
MAX_QUEUE_SIZE = 10
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_IMAGE_DIMENSION = 8192
DEVICE_APPROVAL_TTL_MINUTES = 10
DEVICE_COOKIE_MAX_AGE_SECONDS = 365 * 24 * 60 * 60
TAILSCALE_IPV4_NETWORK = ipaddress.ip_network("100.64.0.0/10")


@dataclass(frozen=True)
class ModelSpec:
    api_id: str
    label: str
    family: str
    max_characters: int

    @property
    def supports_vibe_transfer(self) -> bool:
        # NovelAI has not shipped Vibe Transfer or Precise Reference for V5 yet.
        return self.family in {"v4", "v4.5"}

    @property
    def supports_character_reference(self) -> bool:
        return self.family == "v4.5"

    @property
    def inpaint_id(self) -> str:
        return f"{self.api_id}-inpainting"


MODELS: dict[str, ModelSpec] = {
    "nai-diffusion-5-full": ModelSpec(
        "nai-diffusion-5-full", "V5 Full", "v5", 22
    ),
    "nai-diffusion-5-curated": ModelSpec(
        "nai-diffusion-5-curated", "V5 Curated", "v5", 22
    ),
    "nai-diffusion-4-5-full": ModelSpec(
        "nai-diffusion-4-5-full", "V4.5 Full", "v4.5", 6
    ),
    "nai-diffusion-4-5-curated": ModelSpec(
        "nai-diffusion-4-5-curated", "V4.5 Curated", "v4.5", 6
    ),
}


def resource_path(relative: str) -> Path:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return root / relative


@dataclass
class AppPaths:
    root: Path

    @classmethod
    def from_environment(cls) -> "AppPaths":
        override = os.getenv("NOVELAI_STUDIO_DATA_DIR")
        if override:
            return cls(Path(override).expanduser().resolve())
        local_app_data = os.getenv("LOCALAPPDATA")
        if not local_app_data:
            local_app_data = str(Path.home() / "AppData" / "Local")
        return cls(Path(local_app_data) / APP_NAME)

    @property
    def database(self) -> Path:
        return self.root / "data" / "app.db"

    @property
    def assets(self) -> Path:
        return self.root / "data" / "assets"

    @property
    def temporary(self) -> Path:
        return self.assets / "temporary"

    @property
    def favorites(self) -> Path:
        return self.assets / "favorites"

    @property
    def uploads(self) -> Path:
        return self.assets / "uploads"

    @property
    def thumbnails(self) -> Path:
        return self.assets / "thumbnails"

    @property
    def masks(self) -> Path:
        return self.assets / "masks"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    def ensure(self) -> None:
        for path in (
            self.database.parent,
            self.temporary,
            self.favorites,
            self.uploads,
            self.thumbnails,
            self.masks,
            self.logs,
        ):
            path.mkdir(parents=True, exist_ok=True)


def is_tailscale_ipv4(value: str | ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    try:
        address = value if isinstance(value, (ipaddress.IPv4Address, ipaddress.IPv6Address)) else ipaddress.ip_address(value)
    except ValueError:
        return False
    return isinstance(address, ipaddress.IPv4Address) and address in TAILSCALE_IPV4_NETWORK


def _tailscale_cli_addresses() -> set[str]:
    candidates: list[str] = []
    discovered = shutil.which("tailscale")
    if discovered:
        candidates.append(discovered)
    if sys.platform == "win32":
        for root_name in ("ProgramFiles", "ProgramFiles(x86)"):
            root = os.getenv(root_name)
            if root:
                candidates.append(str(Path(root) / "Tailscale" / "tailscale.exe"))

    seen: set[str] = set()
    for executable in candidates:
        normalized = str(Path(executable))
        if normalized.lower() in seen or not Path(normalized).exists():
            continue
        seen.add(normalized.lower())
        try:
            result = subprocess.run(
                [normalized, "ip", "-4"],
                capture_output=True,
                text=True,
                timeout=3,
                creationflags=(
                    subprocess.CREATE_NO_WINDOW
                    if sys.platform == "win32"
                    else 0
                ),
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if result.returncode != 0:
            continue
        addresses = {
            line.strip()
            for line in result.stdout.splitlines()
            if is_tailscale_ipv4(line.strip())
        }
        if addresses:
            return addresses
    return set()


def _detected_ipv4_addresses() -> set[str]:
    addresses: set[str] = set()
    try:
        for result in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            addresses.add(result[4][0])
    except OSError:
        pass
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("1.1.1.1", 80))
        addresses.add(sock.getsockname()[0])
        sock.close()
    except OSError:
        pass
    addresses.update(_tailscale_cli_addresses())
    return addresses


def local_machine_ipv4_addresses() -> set[str]:
    """IPv4 addresses currently owned by this PC, used to recognize local clients."""

    return set(_detected_ipv4_addresses())


def lan_ipv4_addresses() -> list[str]:
    private: set[str] = set()
    for address in _detected_ipv4_addresses():
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            continue
        if (
            ip.version == 4
            and ip.is_private
            and not ip.is_loopback
            and not ip.is_link_local
            and not is_tailscale_ipv4(ip)
        ):
            private.add(address)
    return sorted(private)


def tailscale_ipv4_addresses() -> list[str]:
    return sorted(
        address
        for address in _detected_ipv4_addresses()
        if is_tailscale_ipv4(address)
    )


def network_urls(port: int = DEFAULT_PORT) -> dict[str, list[str]]:
    lan_addresses: list[str] = []
    tailscale_addresses: list[str] = []
    for value in _detected_ipv4_addresses():
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            continue
        if is_tailscale_ipv4(address):
            tailscale_addresses.append(value)
        elif (
            address.version == 4
            and address.is_private
            and not address.is_loopback
            and not address.is_link_local
        ):
            lan_addresses.append(value)
    lan = [f"http://{address}:{port}" for address in sorted(set(lan_addresses))]
    tailscale = [
        f"http://{address}:{port}" for address in sorted(set(tailscale_addresses))
    ]
    return {"lan": lan, "tailscale": tailscale, "all": [*lan, *tailscale]}


def mobile_urls(port: int = DEFAULT_PORT) -> list[str]:
    return network_urls(port)["all"]
