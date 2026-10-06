from __future__ import annotations

import ipaddress
import hashlib
import hmac
import os
import socket
import time
from collections import defaultdict
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from fastapi import HTTPException, Request, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from .config import is_tailscale_ipv4

if TYPE_CHECKING:
    from .database import Database


DEVICE_COOKIE_NAME = "novelai_studio_device"
DEVICE_AUTH_PUBLIC_API_PATHS = {
    "/api/status",
    "/api/device-auth/request",
    "/api/device-auth/poll",
}


def _is_allowed_address(value: str | None) -> bool:
    if not value:
        return False
    if value == "testclient" and os.getenv("NOVELAI_STUDIO_TESTING") == "1":
        return True
    try:
        address = ipaddress.ip_address(value.split("%", 1)[0])
    except ValueError:
        return False
    return (
        address.is_loopback
        or address.is_private
        or address.is_link_local
        or is_tailscale_ipv4(address)
    )


def is_loopback_client(value: str | None) -> bool:
    if value == "testclient" and os.getenv("NOVELAI_STUDIO_TESTING") == "1":
        return True
    try:
        address = ipaddress.ip_address((value or "").split("%", 1)[0])
    except ValueError:
        return False
    return address.is_loopback


def is_local_machine_client(
    value: str | None, local_addresses: set[str] | None = None
) -> bool:
    if is_loopback_client(value):
        return True
    normalized = (value or "").split("%", 1)[0]
    return bool(normalized and local_addresses and normalized in local_addresses)


def device_credential_hash(device_id: str, secret: str) -> str:
    return hashlib.sha256(f"{device_id}:{secret}".encode("utf-8")).hexdigest()


def device_cookie_value(device_id: str, secret: str) -> str:
    return f"{device_id}.{secret}"


def parse_device_cookie(value: str | None) -> tuple[str, str] | None:
    if not value or "." not in value:
        return None
    device_id, secret = value.rsplit(".", 1)
    if not device_id or len(secret) != 64:
        return None
    if any(character not in "0123456789abcdef" for character in secret):
        return None
    return device_id, secret


def _network_access_enabled(value: str | None) -> bool:
    if value == "testclient" and os.getenv("NOVELAI_STUDIO_TESTING") == "1":
        return True
    try:
        address = ipaddress.ip_address((value or "").split("%", 1)[0])
    except ValueError:
        return False
    if address.is_loopback:
        return True
    if is_tailscale_ipv4(address):
        return os.getenv("NOVELAI_STUDIO_TAILSCALE_ENABLED", "0") == "1"
    return (
        (address.is_private or address.is_link_local)
        and os.getenv("NOVELAI_STUDIO_LAN_ENABLED", "1") == "1"
    )


def _is_allowed_host(host_header: str) -> bool:
    value = host_header.strip().lower()
    if value.startswith("["):
        host = value[1:].split("]", 1)[0]
    else:
        host = value.rsplit(":", 1)[0] if value.count(":") <= 1 else value
    if host in {"localhost", socket.gethostname().lower(), f"{socket.gethostname().lower()}.local", "testserver"}:
        return True
    return _is_allowed_address(host)


class LocalNetworkOnlyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        remote = request.client.host if request.client else None
        if (
            not _is_allowed_address(remote)
            or not _network_access_enabled(remote)
            or not _is_allowed_host(request.headers.get("host", ""))
        ):
            return JSONResponse(
                status_code=403,
                content={
                    "detail": "이 앱은 로컬 PC, 같은 사설 네트워크 또는 연결된 Tailscale 기기에서만 사용할 수 있습니다."
                },
            )
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if origin:
                try:
                    source = urlsplit(origin)
                    target = urlsplit(str(request.url))
                    same_origin = (
                        source.scheme in {"http", "https"}
                        and source.hostname is not None
                        and source.username is None and source.password is None
                        and source.path in {"", "/"}
                        and not source.query and not source.fragment
                        and (source.scheme, source.hostname, source.port if source.port is not None else (443 if source.scheme == "https" else 80))
                        == (target.scheme, target.hostname, target.port if target.port is not None else (443 if target.scheme == "https" else 80))
                    )
                except ValueError:
                    same_origin = False
                if not same_origin:
                    return JSONResponse(status_code=403, content={"detail": "허용되지 않은 요청 출처입니다."})
            elif request.headers.get("sec-fetch-site") in {"cross-site", "same-site"}:
                return JSONResponse(status_code=403, content={"detail": "허용되지 않은 요청 출처입니다."})
        return await call_next(request)


class LoopbackOnlyASGI:
    """Restrict a mounted ASGI application to requests from this PC."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http":
            client = scope.get("client")
            remote = client[0] if client else None
            if not is_loopback_client(remote):
                response = JSONResponse(
                    status_code=403,
                    content={"detail": "PC에서만 사용할 수 있습니다."},
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


class DeviceAuthorizationMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        database: "Database",
        local_addresses: set[str] | None = None,
    ):
        super().__init__(app)
        self.database = database
        self.local_addresses = set(local_addresses or ())
        self._last_seen_updates: dict[str, float] = {}

    async def dispatch(self, request: Request, call_next):
        remote = request.client.host if request.client else None
        request.state.device_approval_required = not is_local_machine_client(
            remote, self.local_addresses
        )
        request.state.device_authorized = not request.state.device_approval_required
        request.state.device_id = None
        request.state.device_name = None

        if request.state.device_approval_required:
            parsed = parse_device_cookie(request.cookies.get(DEVICE_COOKIE_NAME))
            if parsed:
                device_id, secret = parsed
                record = self.database.get_device_approval(device_id)
                if (
                    record
                    and record["status"] == "approved"
                    and hmac.compare_digest(
                        record["credential_hash"],
                        device_credential_hash(device_id, secret),
                    )
                ):
                    request.state.device_authorized = True
                    request.state.device_id = device_id
                    request.state.device_name = record["display_name"]
                    now = time.monotonic()
                    if now - self._last_seen_updates.get(device_id, 0.0) >= 60:
                        self.database.touch_device_approval(
                            device_id,
                            remote or "",
                            request.headers.get("user-agent", ""),
                        )
                        self._last_seen_updates[device_id] = now

            if (
                request.url.path.startswith("/api/")
                and request.url.path not in DEVICE_AUTH_PUBLIC_API_PATHS
                and not request.state.device_authorized
            ):
                return JSONResponse(
                    status_code=401,
                    content={
                        "detail": "이 모바일 기기는 데스크탑에서 연결 승인을 받아야 합니다.",
                        "code": "DEVICE_APPROVAL_REQUIRED",
                    },
                )

        return await call_next(request)


def require_local_machine(request: Request) -> None:
    remote = request.client.host if request.client else None
    services = getattr(request.app.state, "services", None)
    local_addresses = getattr(services, "local_client_addresses", set())
    if not is_local_machine_client(remote, local_addresses):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="PC에서만 사용할 수 있습니다.")


class SubmissionRateLimiter:
    def __init__(
        self,
        minimum_interval: float = 1.0,
        message: str = "생성 버튼을 너무 빠르게 눌렀습니다.",
    ):
        self.minimum_interval = minimum_interval
        self.message = message
        self._last: defaultdict[str, float] = defaultdict(float)

    def check(self, request: Request) -> None:
        key = request.client.host if request.client else "unknown"
        now = time.monotonic()
        if now - self._last[key] < self.minimum_interval:
            raise HTTPException(status_code=429, detail=self.message)
        self._last[key] = now
