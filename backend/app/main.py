from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import os
import secrets
import time
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel
from starlette.background import BackgroundTask

from . import __version__

from .autostart import AutostartError, get_autostart_status, set_autostart_enabled

from .config import (
    DEFAULT_PORT,
    DEVICE_APPROVAL_TTL_MINUTES,
    DEVICE_COOKIE_MAX_AGE_SECONDS,
    MAX_UPLOAD_BYTES,
    MODELS,
    AppPaths,
    local_machine_ipv4_addresses,
    network_urls,
    resource_path,
)
from . import clipboard
from .claude import ClaudeIntegration, McpActivityASGI
from .credentials import CredentialStore, CredentialStoreError
from .database import Database, iso, utc_now
from .discord_webhook import (
    DiscordWebhookClient,
    DiscordWebhookError,
    validate_discord_webhook_url,
)
from .jobs import JobManager, correlation_id
from .image_export import metadata_free_png
from .mobile_profiles import (
    MobileProfileKeyError,
    encrypt_profile_token,
    public_key_verification_code,
)
from .novelai import NovelAIClient, NovelAIError
from .schemas import (
    AutostartInput,
    ApiProfileTransferRequestInput,
    CharacterPresetInput,
    CharacterSetInput,
    DiscordSendInput,
    DiscordWebhookInput,
    DiscordWebhookUpdateInput,
    DeviceApprovalPollInput,
    DeviceApprovalRequestInput,
    GenerationDraft,
    GenerationDraftSyncInput,
    GenerationRequest,
    QualityPromptPresetInput,
    StorageDirectoryInput,
    MobileImageSyncMetadata,
    TokenInput,
)
from .security import (
    DEVICE_COOKIE_NAME,
    DeviceAuthorizationMiddleware,
    LocalNetworkOnlyMiddleware,
    LoopbackOnlyASGI,
    SubmissionRateLimiter,
    device_cookie_value,
    device_credential_hash,
    is_loopback_client,
    is_local_machine_client,
    require_local_machine,
)
from .storage import (
    ImageStorage, ImageValidationError, StorageLocationError,
    StorageActivityGate, StorageBusyError, StorageUnavailableError,
)


logger = logging.getLogger(__name__)


class FavoriteInput(BaseModel):
    favorite: bool


class Services:
    def __init__(
        self,
        paths: AppPaths,
        novelai_base_url: str | None = None,
        local_client_addresses: set[str] | None = None,
    ):
        self.paths = paths
        self.local_client_addresses = (
            set(local_client_addresses)
            if local_client_addresses is not None
            else local_machine_ipv4_addresses()
        )
        self.paths.ensure()
        self.database = Database(paths.database)
        self.database.initialize()
        self.storage_warning: str | None = None
        configured_storage = self.database.get_app_setting("image_storage_directory")
        if configured_storage:
            configured_root = ImageStorage.normalize_root(configured_storage)
            try:
                if not configured_root.is_dir():
                    raise StorageLocationError("설정된 이미지 저장 폴더에 접근할 수 없습니다.")
                self.storage = ImageStorage(paths, configured_root)
            except (OSError, StorageLocationError) as exc:
                logger.error("Unable to open configured image storage: %s", exc)
                self.storage = ImageStorage(paths, configured_root, initialize=False)
                self.storage_warning = (
                    "지정된 이미지 저장 폴더에 접근할 수 없습니다. 드라이브 연결과 폴더 접근 권한을 확인해 주세요."
                ) if configured_root.is_dir() else None
        else:
            self.storage = ImageStorage(paths)
        self.credentials = CredentialStore()
        self.storage_gate = StorageActivityGate()
        self.jobs = JobManager(
            self.database,
            self.storage,
            self.credentials,
            novelai_base_url=novelai_base_url,
            storage_gate=self.storage_gate,
        )
        self.rate_limiter = SubmissionRateLimiter()
        self.webhook_rate_limiter = SubmissionRateLimiter(
            message="Discord 전송 버튼을 너무 빠르게 눌렀습니다."
        )
        self.device_approval_rate_limiter = SubmissionRateLimiter(
            minimum_interval=2.0,
            message="연결 승인 요청을 너무 빠르게 보냈습니다.",
        )
        self.profile_transfer_rate_limiter = SubmissionRateLimiter(
            minimum_interval=2.0,
            message="API 프로필 전송 요청을 너무 빠르게 보냈습니다.",
        )
        self.discord = DiscordWebhookClient()
        self.claude = ClaudeIntegration(
            resource_path("claude-skills"),
            lambda: int(os.getenv("NOVELAI_STUDIO_PORT", str(DEFAULT_PORT))),
        )
        self._anlas_cache: dict[str, Any] | None = None
        self._anlas_cache_at = 0.0
        self._anlas_lock = asyncio.Lock()
        self._draft_sync_lock = asyncio.Lock()

    def clear_anlas_cache(self) -> None:
        self._anlas_cache = None
        self._anlas_cache_at = 0.0

    def image_storage_settings(self) -> dict[str, Any]:
        warning = self.storage_warning if self.storage.available else (
            "지정된 이미지 저장 폴더에 접근할 수 없습니다. 드라이브 연결과 폴더 접근 권한을 확인해 주세요."
        )
        return {
            "image_storage_directory": str(self.storage.root),
            "default_image_storage_directory": str(self.paths.assets.resolve()),
            "storage_warning": warning,
        }

    def change_image_storage_directory(self, directory: str) -> dict[str, Any]:
        with self.storage_gate.migration():
            if self.database.active_job_count() > 0:
                raise RuntimeError(
                    "생성 대기 또는 실행 중인 작업이 끝난 뒤 저장 폴더를 변경해 주세요."
                )
            current_storage = self.storage
            migration = current_storage.prepare_migration(directory)
            if migration is None:
                self.database.set_app_setting(
                    "image_storage_directory", str(current_storage.root)
                )
                self.storage_warning = None
                return {**self.image_storage_settings(), "moved": False}
            try:
                next_storage = ImageStorage(self.paths, migration.target_root)
                self.database.set_app_setting(
                    "image_storage_directory", str(migration.target_root)
                )
            except Exception:
                ImageStorage.rollback_migration(migration)
                raise
            self.storage = next_storage
            self.jobs.storage = next_storage
            self.storage_warning = ImageStorage.finalize_migration(migration)
            return {**self.image_storage_settings(), "moved": True}

    async def get_anlas_status(self, force: bool = False) -> dict[str, Any] | None:
        token = self.credentials.get_token()
        if not token:
            return None
        now = time.monotonic()
        if not force and self._anlas_cache and now - self._anlas_cache_at < 15:
            return self._anlas_cache
        async with self._anlas_lock:
            now = time.monotonic()
            if not force and self._anlas_cache and now - self._anlas_cache_at < 15:
                return self._anlas_cache
            client = (
                NovelAIClient(token, self.jobs.novelai_base_url)
                if self.jobs.novelai_base_url
                else NovelAIClient(token)
            )
            result = await client.get_anlas_status()
            self._anlas_cache = result
            self._anlas_cache_at = time.monotonic()
            return result


def _public_image(item: dict[str, Any]) -> dict[str, Any]:
    result = {key: value for key, value in item.items() if key not in {"file_path", "thumbnail_path", "cleanup_error"}}
    result["content_url"] = f"/api/assets/{item['id']}/content"
    result["thumbnail_url"] = f"/api/assets/{item['id']}/thumbnail"
    result["download_url"] = f"/api/images/{item['id']}/download"
    return result


def _offline_gallery_image(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item["id"],
        "mime_type": item["mime_type"],
        "width": item["width"],
        "height": item["height"],
        "created_at": item["created_at"],
        "favorite": item.get("favorite_at") is not None,
        "tags": item.get("tags", []),
        "content_url": f"/api/assets/{item['id']}/content",
    }


def _public_upload(item: dict[str, Any]) -> dict[str, Any]:
    result = {key: value for key, value in item.items() if key not in {"file_path", "thumbnail_path", "cleanup_error"}}
    result["content_url"] = f"/api/assets/{item['id']}/content"
    result["thumbnail_url"] = f"/api/assets/{item['id']}/thumbnail"
    result["kind"] = "upload"
    return result


class FrontendStaticFiles(StaticFiles):
    """Serve the built UI so a new build shows up without clearing the WebView cache."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if response.media_type == "text/html":
            # index.html points at hashed bundles; always revalidate it.
            response.headers["Cache-Control"] = "no-cache"
        elif path.replace("\\", "/").startswith("assets/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


def create_app(
    data_dir: Path | None = None,
    novelai_base_url: str | None = None,
    start_workers: bool = True,
    start_mcp: bool | None = None,
    local_client_addresses: set[str] | None = None,
) -> FastAPI:
    paths = AppPaths(data_dir) if data_dir else AppPaths.from_environment()
    services = Services(paths, novelai_base_url, local_client_addresses)
    mcp_enabled = start_workers if start_mcp is None else start_mcp
    mcp_server = FastMCP(
        "NovelAI LAN Studio",
        instructions=(
            "Read and update the shared image-description draft, and update the quality "
            "prompt only when the user explicitly asks. Pass the revision from "
            "get_prompt_context so another device's edits are never overwritten. Never "
            "request or expose tokens, webhooks, deletion tools, or unrelated settings."
        ),
        streamable_http_path="/",
        stateless_http=True,
        json_response=True,
        log_level="WARNING",
    )
    mcp_http_app = mcp_server.streamable_http_app()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        async with AsyncExitStack() as stack:
            if mcp_enabled:
                await stack.enter_async_context(mcp_server.session_manager.run())
            if start_workers:
                await services.jobs.start()
            try:
                yield
            finally:
                if start_workers:
                    await services.jobs.stop()

    app = FastAPI(
        title="NovelAI LAN Studio",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    app.state.services = services

    @app.middleware("http")
    async def storage_mutation_boundary(request: Request, call_next):
        if (request.method not in {"GET", "HEAD", "OPTIONS"}
                and request.url.path.startswith("/api/")
                and request.url.path != "/api/admin/settings/image-storage"):
            try:
                with services.storage_gate.activity():
                    return await call_next(request)
            except StorageBusyError as exc:
                return JSONResponse(status_code=409, content={"detail": str(exc)})
        return await call_next(request)

    app.add_middleware(
        DeviceAuthorizationMiddleware,
        database=services.database,
        local_addresses=services.local_client_addresses,
    )
    app.add_middleware(LocalNetworkOnlyMiddleware)

    def svc() -> Services:
        return services

    @app.exception_handler(ImageValidationError)
    async def image_validation_handler(_: Request, exc: ImageValidationError):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(StorageUnavailableError)
    async def storage_unavailable_handler(_: Request, exc: StorageUnavailableError):
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    @app.get("/api/status")
    async def status_endpoint(request: Request, state: Services = Depends(svc)):
        lan_enabled = os.getenv("NOVELAI_STUDIO_LAN_ENABLED", "1") == "1"
        tailscale_enabled = os.getenv("NOVELAI_STUDIO_TAILSCALE_ENABLED", "0") == "1"
        runtime_port = int(os.getenv("NOVELAI_STUDIO_PORT", str(DEFAULT_PORT)))
        detected_urls = network_urls(runtime_port)
        lan_urls = detected_urls["lan"] if lan_enabled else []
        tailscale_urls = detected_urls["tailscale"] if tailscale_enabled else []
        remote = request.client.host if request.client else None
        local_machine_client = is_local_machine_client(
            remote, state.local_client_addresses
        )
        device_approval_required = not is_local_machine_client(
            remote, state.local_client_addresses
        )
        device_authorized = bool(
            getattr(request.state, "device_authorized", not device_approval_required)
        )
        pending_cutoff = iso(
            utc_now() - timedelta(minutes=DEVICE_APPROVAL_TTL_MINUTES)
        )
        return {
            "name": "NovelAI LAN Studio",
            "version": __version__,
            "server": "online",
            "lan_enabled": lan_enabled,
            "tailscale_enabled": tailscale_enabled,
            "remote_access_supported": True,
            "lan_urls": lan_urls,
            "tailscale_urls": tailscale_urls,
            "mobile_urls": [*lan_urls, *tailscale_urls],
            "admin_available": local_machine_client,
            "device_approval_required": device_approval_required,
            "device_authorized": device_authorized,
            "device_name": getattr(request.state, "device_name", None),
            "pending_device_count": (
                state.database.count_pending_device_approvals(pending_cutoff)
                if local_machine_client
                else 0
            ),
            "pending_api_profile_transfer_count": (
                state.database.count_pending_api_profile_transfers(pending_cutoff)
                if local_machine_client
                else 0
            ),
            "has_token": bool(state.credentials.get_token()),
            "models": [
                {
                    "id": model.api_id,
                    "label": model.label,
                    "family": model.family,
                    "max_characters": model.max_characters,
                }
                for model in MODELS.values()
            ],
            "security_notice": "PC에서 승인한 기기만 접속할 수 있어요. 인터넷에는 공개되지 않아요.",
        }

    @app.post("/api/device-auth/request", status_code=202)
    async def request_device_approval(
        body: DeviceApprovalRequestInput,
        request: Request,
        state: Services = Depends(svc),
    ):
        if is_local_machine_client(
            request.client.host if request.client else None,
            state.local_client_addresses,
        ):
            raise HTTPException(status_code=400, detail="PC 화면은 연결 승인이 필요하지 않습니다.")
        state.device_approval_rate_limiter.check(request)
        remote = request.client.host if request.client else ""
        item = state.database.request_device_approval(
            body.device_id,
            body.display_name,
            device_credential_hash(body.device_id, body.pairing_secret),
            remote,
            request.headers.get("user-agent", ""),
        )
        return {
            "device_id": item["device_id"],
            "display_name": item["display_name"],
            "status": item["status"],
            "expires_in_seconds": DEVICE_APPROVAL_TTL_MINUTES * 60,
        }

    @app.post("/api/device-auth/poll")
    async def poll_device_approval(
        body: DeviceApprovalPollInput,
        request: Request,
        state: Services = Depends(svc),
    ):
        record = state.database.get_device_approval(body.device_id)
        expected_hash = device_credential_hash(body.device_id, body.pairing_secret)
        if not record or not secrets.compare_digest(
            record["credential_hash"], expected_hash
        ):
            raise HTTPException(status_code=404, detail="연결 승인 요청을 찾을 수 없습니다.")
        requested_at = record["requested_at"]
        cutoff = iso(utc_now() - timedelta(minutes=DEVICE_APPROVAL_TTL_MINUTES))
        if record["status"] == "pending" and requested_at < cutoff:
            return {"status": "expired", "device_id": body.device_id}
        if record["status"] != "approved":
            return {"status": record["status"], "device_id": body.device_id}

        remote = request.client.host if request.client else ""
        state.database.touch_device_approval(
            body.device_id,
            remote,
            request.headers.get("user-agent", ""),
        )
        response = JSONResponse(
            {
                "status": "approved",
                "device_id": body.device_id,
                "display_name": record["display_name"],
            }
        )
        response.set_cookie(
            key=DEVICE_COOKIE_NAME,
            value=device_cookie_value(body.device_id, body.pairing_secret),
            max_age=DEVICE_COOKIE_MAX_AGE_SECONDS,
            httponly=True,
            secure=False,
            samesite="strict",
            path="/",
        )
        return response

    @app.get("/api/admin/devices", dependencies=[Depends(require_local_machine)])
    async def list_device_approvals(state: Services = Depends(svc)):
        cutoff = iso(utc_now() - timedelta(minutes=DEVICE_APPROVAL_TTL_MINUTES))
        items = state.database.list_device_approvals()
        for item in items:
            if item["status"] == "pending" and item["requested_at"] < cutoff:
                item["status"] = "expired"
        return {"items": items}

    @app.post(
        "/api/admin/devices/{device_id}/approve",
        dependencies=[Depends(require_local_machine)],
    )
    async def approve_device(device_id: str, state: Services = Depends(svc)):
        cutoff = iso(utc_now() - timedelta(minutes=DEVICE_APPROVAL_TTL_MINUTES))
        item = state.database.decide_device_approval(
            device_id, "approved", requested_after=cutoff
        )
        if not item:
            raise HTTPException(
                status_code=409,
                detail="승인 요청이 없거나 만료되었습니다. 모바일에서 다시 요청해 주세요.",
            )
        return item

    @app.post(
        "/api/admin/devices/{device_id}/deny",
        dependencies=[Depends(require_local_machine)],
    )
    async def deny_device(device_id: str, state: Services = Depends(svc)):
        item = state.database.decide_device_approval(device_id, "denied")
        if not item:
            raise HTTPException(status_code=404, detail="대기 중인 승인 요청을 찾을 수 없습니다.")
        return item

    @app.delete(
        "/api/admin/devices/{device_id}",
        status_code=204,
        dependencies=[Depends(require_local_machine)],
    )
    async def revoke_device(device_id: str, state: Services = Depends(svc)):
        if not state.database.revoke_device_approval(device_id):
            raise HTTPException(status_code=404, detail="승인된 기기를 찾을 수 없습니다.")

    @app.post("/api/mobile/api-profiles/requests", status_code=202)
    async def request_mobile_api_profile(
        body: ApiProfileTransferRequestInput,
        request: Request,
        state: Services = Depends(svc),
    ):
        device_id = getattr(request.state, "device_id", None)
        if not device_id or not getattr(request.state, "device_authorized", False):
            raise HTTPException(
                status_code=403,
                detail="승인된 모바일 기기에서만 API 프로필을 요청할 수 있습니다.",
            )
        if not state.credentials.get_token():
            raise HTTPException(
                status_code=409,
                detail="PC에 저장된 NovelAI API 토큰이 없습니다.",
            )
        state.profile_transfer_rate_limiter.check(request)
        try:
            verification_code = public_key_verification_code(body.public_key_b64)
        except MobileProfileKeyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        item = state.database.request_api_profile_transfer(
            device_id,
            body.profile_name,
            body.key_id,
            body.public_key_b64,
            verification_code,
        )
        return {
            "id": item["id"],
            "status": item["status"],
            "profile_name": item["profile_name"],
            "verification_code": item["verification_code"],
            "expires_in_seconds": DEVICE_APPROVAL_TTL_MINUTES * 60,
        }

    @app.get("/api/mobile/api-profiles/requests/{request_id}")
    async def poll_mobile_api_profile(
        request_id: str,
        request: Request,
        state: Services = Depends(svc),
    ):
        device_id = getattr(request.state, "device_id", None)
        item = state.database.get_api_profile_transfer(request_id)
        if not item or not device_id or item["device_id"] != device_id:
            raise HTTPException(status_code=404, detail="API 프로필 요청을 찾을 수 없습니다.")
        cutoff = iso(utc_now() - timedelta(minutes=DEVICE_APPROVAL_TTL_MINUTES))
        if item["status"] == "pending" and item["requested_at"] < cutoff:
            return {"id": request_id, "status": "expired"}
        response = {
            "id": item["id"],
            "status": item["status"],
            "profile_name": item["profile_name"],
            "key_id": item["key_id"],
            "verification_code": item["verification_code"],
            "server_id": item.get("server_id"),
        }
        if item["status"] == "approved":
            response["encrypted_token_b64"] = item["encrypted_token_b64"]
            state.database.mark_api_profile_transfer_delivered(request_id)
        return response

    @app.get(
        "/api/admin/api-profile-transfers",
        dependencies=[Depends(require_local_machine)],
    )
    async def list_api_profile_transfers(state: Services = Depends(svc)):
        cutoff = iso(utc_now() - timedelta(minutes=DEVICE_APPROVAL_TTL_MINUTES))
        items = state.database.list_api_profile_transfers()
        for item in items:
            if item["requested_at"] < cutoff:
                item["status"] = "expired"
        return {"items": items}

    @app.post(
        "/api/admin/api-profile-transfers/{request_id}/approve",
        dependencies=[Depends(require_local_machine)],
    )
    async def approve_api_profile_transfer(
        request_id: str, state: Services = Depends(svc)
    ):
        item = state.database.get_api_profile_transfer(request_id, include_key=True)
        cutoff = iso(utc_now() - timedelta(minutes=DEVICE_APPROVAL_TTL_MINUTES))
        if (
            not item
            or item["status"] != "pending"
            or item["requested_at"] < cutoff
        ):
            raise HTTPException(
                status_code=409,
                detail="API 프로필 요청이 없거나 만료되었습니다.",
            )
        token = state.credentials.get_token()
        if not token:
            raise HTTPException(status_code=409, detail="PC에 저장된 API 토큰이 없습니다.")
        try:
            encrypted = encrypt_profile_token(item["public_key_b64"], token)
        except MobileProfileKeyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        approved = state.database.approve_api_profile_transfer(
            request_id,
            encrypted,
            state.database.get_or_create_server_id(),
            cutoff,
        )
        if not approved:
            raise HTTPException(status_code=409, detail="API 프로필 요청을 승인하지 못했습니다.")
        return approved

    @app.post(
        "/api/admin/api-profile-transfers/{request_id}/deny",
        dependencies=[Depends(require_local_machine)],
    )
    async def deny_api_profile_transfer(
        request_id: str, state: Services = Depends(svc)
    ):
        item = state.database.deny_api_profile_transfer(request_id)
        if not item:
            raise HTTPException(status_code=404, detail="대기 중인 API 프로필 요청이 없습니다.")
        return item

    @app.get("/api/admin/settings", dependencies=[Depends(require_local_machine)])
    async def admin_settings(state: Services = Depends(svc)):
        runtime_port = int(os.getenv("NOVELAI_STUDIO_PORT", str(DEFAULT_PORT)))
        lan_enabled = os.getenv("NOVELAI_STUDIO_LAN_ENABLED", "1") == "1"
        tailscale_enabled = os.getenv("NOVELAI_STUDIO_TAILSCALE_ENABLED", "0") == "1"
        detected_urls = network_urls(runtime_port)
        lan_urls = detected_urls["lan"] if lan_enabled else []
        tailscale_urls = detected_urls["tailscale"] if tailscale_enabled else []
        return {
            "has_token": bool(state.credentials.get_token()),
            "data_directory": str(state.paths.root),
            **state.image_storage_settings(),
            "port": runtime_port,
            "retention_hours": 168,
            "lan_urls": lan_urls,
            "tailscale_urls": tailscale_urls,
            "mobile_urls": [*lan_urls, *tailscale_urls],
            "autostart": get_autostart_status(),
            "claude": state.claude.status(),
        }

    @app.put(
        "/api/admin/settings/image-storage",
        dependencies=[Depends(require_local_machine)],
    )
    async def update_image_storage_directory(
        body: StorageDirectoryInput, state: Services = Depends(svc)
    ):
        try:
            return await asyncio.to_thread(
                state.change_image_storage_directory, body.directory
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (OSError, StorageLocationError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.put(
        "/api/admin/settings/autostart",
        dependencies=[Depends(require_local_machine)],
    )
    async def update_autostart(body: AutostartInput):
        try:
            return set_autostart_enabled(body.enabled)
        except AutostartError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/admin/claude/status", dependencies=[Depends(require_local_machine)])
    async def claude_status(state: Services = Depends(svc)):
        return await asyncio.to_thread(state.claude.status)

    @app.post("/api/admin/claude/skill", dependencies=[Depends(require_local_machine)])
    async def install_claude_skill(state: Services = Depends(svc)):
        try:
            return await asyncio.to_thread(state.claude.install_skill)
        except OSError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.put("/api/admin/settings/token", dependencies=[Depends(require_local_machine)])
    async def save_token(body: TokenInput, state: Services = Depends(svc)):
        try:
            state.credentials.set_token(body.token)
        except CredentialStoreError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        state.clear_anlas_cache()
        return {"saved": True, "has_token": True}

    @app.delete("/api/admin/settings/token", dependencies=[Depends(require_local_machine)])
    async def delete_token(state: Services = Depends(svc)):
        try:
            state.credentials.delete_token()
        except CredentialStoreError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        state.clear_anlas_cache()
        return {"saved": True, "has_token": False}

    @app.post("/api/admin/settings/token/test", dependencies=[Depends(require_local_machine)])
    async def test_token(state: Services = Depends(svc)):
        try:
            result = await state.get_anlas_status(force=True)
        except CredentialStoreError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        except NovelAIError as exc:
            raise HTTPException(status_code=exc.status_code or 502, detail=str(exc)) from exc
        if result is None:
            raise HTTPException(status_code=400, detail="저장된 API 토큰이 없습니다.")
        return {"connected": True, **result}

    @app.get("/api/anlas")
    async def anlas_status(
        refresh: bool = Query(default=False), state: Services = Depends(svc)
    ):
        try:
            result = await state.get_anlas_status(force=refresh)
        except CredentialStoreError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        except NovelAIError as exc:
            raise HTTPException(status_code=exc.status_code or 502, detail=str(exc)) from exc
        if result is None:
            return {
                "available": False,
                "active": False,
                "tier": 0,
                "tier_name": "미연결",
                "subscription_anlas": None,
                "paid_anlas": None,
                "remaining_anlas": None,
                "usage_percent": None,
                "usage_is_negative": None,
                "usage_time_until_next_percent": None,
                "refreshed_at": None,
            }
        return {"available": True, **result}

    @app.post("/api/admin/cleanup", dependencies=[Depends(require_local_machine)])
    async def run_cleanup(state: Services = Depends(svc)):
        return await __import__("asyncio").to_thread(state.jobs.cleanup_once)

    @app.get("/api/webhooks")
    async def list_discord_webhook_targets(state: Services = Depends(svc)):
        return {"items": state.database.list_discord_webhooks()}

    @app.get("/api/admin/webhooks", dependencies=[Depends(require_local_machine)])
    async def list_admin_discord_webhooks(state: Services = Depends(svc)):
        try:
            items = [
                {
                    **item,
                    "configured": bool(
                        state.credentials.get_discord_webhook_url(item["id"])
                    ),
                }
                for item in state.database.list_discord_webhooks()
            ]
        except CredentialStoreError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return {"items": items}

    @app.post(
        "/api/admin/webhooks",
        status_code=201,
        dependencies=[Depends(require_local_machine)],
    )
    async def create_discord_webhook(
        body: DiscordWebhookInput, state: Services = Depends(svc)
    ):
        try:
            normalized_url = validate_discord_webhook_url(body.url)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            item = state.database.create_discord_webhook(body.name)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        try:
            state.credentials.set_discord_webhook_url(item["id"], normalized_url)
        except CredentialStoreError as exc:
            state.database.delete_discord_webhook(item["id"])
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return {**item, "configured": True}

    @app.put(
        "/api/admin/webhooks/{webhook_id}",
        dependencies=[Depends(require_local_machine)],
    )
    async def update_discord_webhook(
        webhook_id: str,
        body: DiscordWebhookUpdateInput,
        state: Services = Depends(svc),
    ):
        current = state.database.get_discord_webhook(webhook_id)
        if not current:
            raise HTTPException(status_code=404, detail="Discord 웹훅을 찾을 수 없습니다.")
        normalized_url: str | None = None
        previous_url: str | None = None
        if body.url:
            try:
                normalized_url = validate_discord_webhook_url(body.url)
                previous_url = state.credentials.get_discord_webhook_url(webhook_id)
                state.credentials.set_discord_webhook_url(webhook_id, normalized_url)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            except CredentialStoreError as exc:
                raise HTTPException(status_code=500, detail=str(exc)) from exc
        try:
            item = state.database.update_discord_webhook(webhook_id, body.name)
        except ValueError as exc:
            if normalized_url:
                try:
                    if previous_url:
                        state.credentials.set_discord_webhook_url(webhook_id, previous_url)
                    else:
                        state.credentials.delete_discord_webhook_url(webhook_id)
                except CredentialStoreError:
                    logger.exception("Failed to restore Discord webhook credential after metadata conflict")
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if not item:
            raise HTTPException(status_code=404, detail="Discord 웹훅을 찾을 수 없습니다.")
        try:
            configured = bool(state.credentials.get_discord_webhook_url(webhook_id))
        except CredentialStoreError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return {**item, "configured": configured}

    @app.delete(
        "/api/admin/webhooks/{webhook_id}",
        status_code=204,
        dependencies=[Depends(require_local_machine)],
    )
    async def delete_discord_webhook(
        webhook_id: str, state: Services = Depends(svc)
    ):
        if not state.database.get_discord_webhook(webhook_id):
            raise HTTPException(status_code=404, detail="Discord 웹훅을 찾을 수 없습니다.")
        try:
            state.credentials.delete_discord_webhook_url(webhook_id)
        except CredentialStoreError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        state.database.delete_discord_webhook(webhook_id)

    @app.get("/api/presets")
    async def list_presets(state: Services = Depends(svc)):
        return {"items": state.database.list_presets()}

    @app.get("/api/quality-presets")
    async def list_quality_prompt_presets(state: Services = Depends(svc)):
        return {"items": state.database.list_quality_prompt_presets()}

    @app.get("/api/character-sets")
    async def list_character_sets(state: Services = Depends(svc)):
        return {"items": state.database.list_character_sets()}

    def load_generation_draft(state: Services) -> GenerationDraft:
        saved = state.database.get_app_setting("generation_draft")
        if not saved:
            migrated = state.database.latest_generation_draft()
            draft = GenerationDraft.model_validate(migrated or {})
            state.database.set_app_settings(
                {
                    "generation_draft": draft.model_dump_json(),
                    "generation_draft_revision": "1",
                    "generation_draft_client_id": "migration",
                }
            )
            return draft
        try:
            raw = json.loads(saved)
            saved_version = int(raw.get("schema_version") or 0)
            migrated_draft = saved_version < 4
            if saved_version < 2:
                migrated = state.database.latest_generation_draft() or {}
                raw = {**migrated, **raw}
                if not raw.get("character_preset_ids"):
                    raw["character_preset_ids"] = state.database.latest_nonempty_character_preset_ids()
            if saved_version < 3:
                raw["description_prompt"] = str(
                    raw.get("prompt") or raw.get("description_prompt") or ""
                )
                raw.setdefault("quality_prompt", "")
                raw.setdefault("quality_preset_id", None)
                raw["schema_version"] = 3
            if saved_version < 4:
                if "negative_prompt" in raw:
                    raw["quality_negative_prompt"] = str(
                        raw.get("negative_prompt") or ""
                    )
                else:
                    raw.setdefault("quality_negative_prompt", "")
                raw.setdefault("description_negative_prompt", "")
                raw.pop("negative_prompt", None)
                raw["schema_version"] = 4
            draft = GenerationDraft.model_validate(raw)
            if draft.quality_preset_id and not state.database.get_quality_prompt_preset(
                draft.quality_preset_id
            ):
                draft = draft.model_copy(update={"quality_preset_id": None})
                migrated_draft = True
            if migrated_draft:
                state.database.set_app_setting("generation_draft", draft.model_dump_json())
            return draft
        except (TypeError, ValueError, json.JSONDecodeError):
            logger.warning("Invalid saved generation draft; returning an empty draft.")
            return GenerationDraft()

    def generation_draft_revision(state: Services) -> int:
        try:
            return max(0, int(state.database.get_app_setting("generation_draft_revision") or 0))
        except ValueError:
            return 0

    def generation_draft_envelope(state: Services) -> dict[str, Any]:
        draft = load_generation_draft(state)
        return {
            "revision": generation_draft_revision(state),
            "source_client_id": state.database.get_app_setting("generation_draft_client_id"),
            "draft": draft.model_dump(),
        }

    @app.get("/api/generation-draft")
    async def get_generation_draft(state: Services = Depends(svc)):
        return load_generation_draft(state).model_dump()

    async def persist_generation_draft(
        body: GenerationDraft, state: Services, client_id: str = "legacy-client"
    ) -> dict[str, Any]:
        async with state._draft_sync_lock:
            revision = generation_draft_revision(state) + 1
            state.database.set_app_settings(
                {
                    "generation_draft": body.model_dump_json(),
                    "generation_draft_revision": str(revision),
                    "generation_draft_client_id": client_id,
                }
            )
            return {
                "revision": revision,
                "source_client_id": client_id,
                "draft": body.model_dump(),
            }

    @mcp_server.tool(
        name="get_prompt_context",
        title="현재 NovelAI 프롬프트 문맥 읽기",
        description=(
            "현재 공유 생성 초안, 모델, 선택된 인물 순서와 인물 프롬프트를 읽습니다. "
            "프롬프트를 작성하기 전에 먼저 호출하세요."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
        structured_output=True,
    )
    async def mcp_get_prompt_context() -> dict[str, Any]:
        async with services._draft_sync_lock:
            envelope = generation_draft_envelope(services)
        draft = envelope["draft"]
        selected = services.database.get_presets(draft["character_preset_ids"])
        model_spec = MODELS[draft["model"]]
        characters = [
            {
                "position": index + 1,
                "id": preset["id"],
                "name": preset["name"],
                "subject_type": preset["subject_type"],
                "prompt": preset["prompt"],
                "negative_prompt": preset["negative_prompt"],
            }
            for index, preset in enumerate(selected)
        ]
        subject_counts = {
            subject: sum(1 for item in characters if item["subject_type"] == subject)
            for subject in ("girl", "boy", "other")
        }
        quality_preset = (
            services.database.get_quality_prompt_preset(draft["quality_preset_id"])
            if draft["quality_preset_id"]
            else None
        )
        return {
            "revision": envelope["revision"],
            "model": {
                "id": draft["model"],
                "label": model_spec.label,
                "family": model_spec.family,
            },
            "current_prompts": {
                "quality_prompt": draft["quality_prompt"],
                "positive_description": draft["description_prompt"],
                "quality_negative_prompt": draft["quality_negative_prompt"],
                "negative_description": draft["description_negative_prompt"],
                "nsfw_enabled": draft["nsfw_enabled"],
            },
            "quality_preset": (
                {"id": quality_preset["id"], "name": quality_preset["name"]}
                if quality_preset
                else None
            ),
            "subject_counts": subject_counts,
            "active_characters": characters,
        }

    @mcp_server.tool(
        name="apply_description_prompts",
        title="NovelAI 묘사 P·N·NSFW 초안 적용",
        description=(
            "현재 공유 생성 초안의 묘사 포지티브와 네거티브를 교체하고, "
            "사용자가 명시한 경우에만 NSFW 상태도 함께 변경합니다. "
            "get_prompt_context에서 받은 revision을 base_revision으로 전달하세요."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
        structured_output=True,
    )
    async def mcp_apply_description_prompts(
        positive_description: str,
        negative_description: str,
        base_revision: int,
        nsfw_enabled: bool | None = None,
    ) -> dict[str, Any]:
        positive = positive_description.strip()
        negative = negative_description.strip()
        if not positive:
            raise ValueError("positive_description은 비워 둘 수 없습니다.")
        if len(positive) > 32_000 or len(negative) > 32_000:
            raise ValueError("프롬프트는 각각 32,000자를 넘을 수 없습니다.")
        async with services._draft_sync_lock:
            current_revision = generation_draft_revision(services)
            if base_revision != current_revision:
                return {
                    "applied": False,
                    "reason": "revision_conflict",
                    "current_revision": current_revision,
                    "message": "다른 기기에서 초안이 변경되었습니다. 문맥을 다시 읽어 주세요.",
                }
            current = load_generation_draft(services)
            updates: dict[str, Any] = {
                "description_prompt": positive,
                "description_negative_prompt": negative,
            }
            if nsfw_enabled is not None:
                updates["nsfw_enabled"] = nsfw_enabled
            updated = current.model_copy(update=updates)
            next_revision = current_revision + 1
            services.database.set_app_settings(
                {
                    "generation_draft": updated.model_dump_json(),
                    "generation_draft_revision": str(next_revision),
                    "generation_draft_client_id": "claude-mcp",
                }
            )
        return {
            "applied": True,
            "revision": next_revision,
            "positive_description": positive,
            "negative_description": negative,
            "nsfw_enabled": updated.nsfw_enabled,
        }

    @mcp_server.tool(
        name="apply_quality_prompts",
        title="NovelAI 품질 P·N 초안 적용",
        description=(
            "현재 공유 생성 초안의 품질 포지티브(작가 조합·화풍·품질 태그)와 품질 네거티브를 "
            "교체합니다. 사용자가 품질 프롬프트 수정을 명시적으로 요청한 경우에만 호출하고, "
            "바꾸지 않을 쪽은 생략하세요. 저장된 품질 프리셋 자체는 바꾸지 않습니다. "
            "get_prompt_context에서 받은 revision을 base_revision으로 전달하세요."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
        structured_output=True,
    )
    async def mcp_apply_quality_prompts(
        base_revision: int,
        quality_prompt: str | None = None,
        quality_negative_prompt: str | None = None,
    ) -> dict[str, Any]:
        if quality_prompt is None and quality_negative_prompt is None:
            raise ValueError("quality_prompt와 quality_negative_prompt 중 하나는 전달해야 합니다.")
        updates: dict[str, Any] = {}
        if quality_prompt is not None:
            positive = quality_prompt.strip()
            if not positive:
                raise ValueError("quality_prompt는 비워 둘 수 없습니다.")
            updates["quality_prompt"] = positive
        if quality_negative_prompt is not None:
            updates["quality_negative_prompt"] = quality_negative_prompt.strip()
        if any(len(value) > 32_000 for value in updates.values()):
            raise ValueError("프롬프트는 각각 32,000자를 넘을 수 없습니다.")
        async with services._draft_sync_lock:
            current_revision = generation_draft_revision(services)
            if base_revision != current_revision:
                return {
                    "applied": False,
                    "reason": "revision_conflict",
                    "current_revision": current_revision,
                    "message": "다른 기기에서 초안이 변경되었습니다. 문맥을 다시 읽어 주세요.",
                }
            current = load_generation_draft(services)
            updated = current.model_copy(update=updates)
            next_revision = current_revision + 1
            services.database.set_app_settings(
                {
                    "generation_draft": updated.model_dump_json(),
                    "generation_draft_revision": str(next_revision),
                    "generation_draft_client_id": "claude-mcp",
                }
            )
        preset = (
            services.database.get_quality_prompt_preset(updated.quality_preset_id)
            if updated.quality_preset_id
            else None
        )
        differs = bool(
            preset
            and (
                preset["prompt"] != updated.quality_prompt
                or (
                    bool(preset.get("negative_prompt"))
                    and preset["negative_prompt"] != updated.quality_negative_prompt
                )
            )
        )
        return {
            "applied": True,
            "revision": next_revision,
            "quality_prompt": updated.quality_prompt,
            "quality_negative_prompt": updated.quality_negative_prompt,
            "quality_preset_name": preset["name"] if preset else None,
            "differs_from_preset": differs,
        }

    @app.put("/api/generation-draft")
    async def save_generation_draft(body: GenerationDraft, state: Services = Depends(svc)):
        result = await persist_generation_draft(body, state)
        return result["draft"]

    @app.post("/api/generation-draft")
    async def flush_generation_draft(body: GenerationDraft, state: Services = Depends(svc)):
        result = await persist_generation_draft(body, state)
        return result["draft"]

    @app.get("/api/generation-draft/sync")
    async def sync_generation_draft(state: Services = Depends(svc)):
        async with state._draft_sync_lock:
            return generation_draft_envelope(state)

    @app.put("/api/generation-draft/sync")
    @app.post("/api/generation-draft/sync")
    async def save_generation_draft_sync(
        body: GenerationDraftSyncInput, state: Services = Depends(svc)
    ):
        return await persist_generation_draft(body.draft, state, body.client_id)

    @app.post("/api/presets", status_code=201)
    async def create_preset(body: CharacterPresetInput, state: Services = Depends(svc)):
        try:
            return state.database.create_preset(body.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.put("/api/presets/{preset_id}")
    async def update_preset(preset_id: str, body: CharacterPresetInput, state: Services = Depends(svc)):
        try:
            result = state.database.update_preset(preset_id, body.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if not result:
            raise HTTPException(status_code=404, detail="인물 프리셋을 찾을 수 없습니다.")
        return result

    @app.delete("/api/presets/{preset_id}", status_code=204)
    async def delete_preset(preset_id: str, state: Services = Depends(svc)):
        if not state.database.delete_preset(preset_id):
            raise HTTPException(status_code=404, detail="인물 프리셋을 찾을 수 없습니다.")

    @app.post("/api/character-sets", status_code=201)
    async def create_character_set(
        body: CharacterSetInput, state: Services = Depends(svc)
    ):
        try:
            return state.database.create_character_set(body.model_dump())
        except ValueError as exc:
            status_code = 409 if "같은 이름" in str(exc) else 400
            raise HTTPException(status_code=status_code, detail=str(exc)) from exc

    @app.put("/api/character-sets/{set_id}")
    async def update_character_set(
        set_id: str, body: CharacterSetInput, state: Services = Depends(svc)
    ):
        try:
            result = state.database.update_character_set(set_id, body.model_dump())
        except ValueError as exc:
            status_code = 409 if "같은 이름" in str(exc) else 400
            raise HTTPException(status_code=status_code, detail=str(exc)) from exc
        if not result:
            raise HTTPException(status_code=404, detail="인물 세트를 찾을 수 없습니다.")
        return result

    @app.delete("/api/character-sets/{set_id}", status_code=204)
    async def delete_character_set(set_id: str, state: Services = Depends(svc)):
        if not state.database.delete_character_set(set_id):
            raise HTTPException(status_code=404, detail="인물 세트를 찾을 수 없습니다.")

    @app.post("/api/quality-presets", status_code=201)
    async def create_quality_prompt_preset(
        body: QualityPromptPresetInput, state: Services = Depends(svc)
    ):
        try:
            return state.database.create_quality_prompt_preset(body.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.put("/api/quality-presets/{preset_id}")
    async def update_quality_prompt_preset(
        preset_id: str,
        body: QualityPromptPresetInput,
        state: Services = Depends(svc),
    ):
        try:
            result = state.database.update_quality_prompt_preset(
                preset_id, body.model_dump()
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if not result:
            raise HTTPException(
                status_code=404, detail="품질 프롬프트 프리셋을 찾을 수 없습니다."
            )
        return result

    @app.delete("/api/quality-presets/{preset_id}", status_code=204)
    async def delete_quality_prompt_preset(
        preset_id: str, state: Services = Depends(svc)
    ):
        if not state.database.delete_quality_prompt_preset(preset_id):
            raise HTTPException(
                status_code=404, detail="품질 프롬프트 프리셋을 찾을 수 없습니다."
            )

    @app.get("/api/mobile/standalone-snapshot")
    async def mobile_standalone_snapshot(state: Services = Depends(svc)):
        return {
            "schema_version": 1,
            "server_id": state.database.get_or_create_server_id(),
            "generated_at": iso(),
            "models": [
                {
                    "id": model.api_id,
                    "label": model.label,
                    "family": model.family,
                    "max_characters": model.max_characters,
                }
                for model in MODELS.values()
            ],
            "presets": state.database.list_presets(),
            "character_sets": state.database.list_character_sets(),
            "quality_presets": state.database.list_quality_prompt_presets(),
            "generation_draft": generation_draft_envelope(state),
        }

    @app.post("/api/mobile-sync/images", status_code=201)
    async def sync_mobile_image(
        request: Request,
        metadata: Annotated[str, Form(...)],
        file: UploadFile = File(...),
        state: Services = Depends(svc),
    ):
        device_id = getattr(request.state, "device_id", None)
        if not device_id:
            raise HTTPException(status_code=403, detail="모바일 기기에서만 동기화할 수 있습니다.")
        try:
            parsed = MobileImageSyncMetadata.model_validate_json(metadata)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="모바일 이미지 메타데이터가 올바르지 않습니다.") from exc
        server_id = state.database.get_or_create_server_id()
        if parsed.origin_server_id and parsed.origin_server_id != server_id:
            raise HTTPException(
                status_code=409,
                detail="이 이미지는 다른 PC의 API 프로필에서 생성되어 현재 PC와 동기화할 수 없습니다.",
            )
        existing = state.database.get_image(parsed.mobile_image_id)
        if existing:
            updated = await set_favorite(existing["id"], FavoriteInput(favorite=parsed.favorite), state)
            return {"image": updated, "duplicate": True}
        data = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="동기화 이미지는 최대 20MB까지 가능합니다.")
        try:
            created = datetime.fromisoformat(parsed.created_at)
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            created = created.astimezone(timezone.utc)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="이미지 생성 시각이 올바르지 않습니다.") from exc
        now = utc_now()
        if created > now + timedelta(minutes=10):
            created = now
        try:
            saved = state.storage.save_generated(data, parsed.mobile_image_id)
        except ImageValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        settings = dict(parsed.settings)
        settings["api_profile_id"] = parsed.api_profile_id
        settings["origin_server_id"] = server_id
        settings["synced_from_device_id"] = device_id
        request_data = {
            "mode": "txt2img",
            "model": parsed.model,
            "quality_prompt": parsed.quality_prompt,
            "description_prompt": parsed.description_prompt,
            "quality_negative_prompt": parsed.quality_negative_prompt,
            "description_negative_prompt": parsed.description_negative_prompt,
            "nsfw_enabled": bool(settings.get("nsfw_enabled")),
            "character_snapshot": parsed.character_snapshot,
            "parameters": settings,
            "mobile_sync": True,
        }
        job: dict[str, Any] | None = None
        try:
            job = state.database.create_job(request_data, correlation_id())
            state.database.set_job_running(job["id"])
            tag_ids = state.database.existing_tag_ids(
                [str(item.get("id") or "") for item in parsed.tags]
            )
            image = state.database.create_image(
                {
                    "id": parsed.mobile_image_id,
                    "job_id": job["id"],
                    "parent_image_id": None,
                    **saved,
                    "mode": "txt2img",
                    "model": parsed.model,
                    "prompt": NovelAIClient.compose_prompt(
                        parsed.quality_prompt,
                        parsed.description_prompt,
                        bool(settings.get("nsfw_enabled")),
                    ),
                    "quality_prompt": parsed.quality_prompt,
                    "description_prompt": parsed.description_prompt,
                    "quality_negative_prompt": parsed.quality_negative_prompt,
                    "description_negative_prompt": parsed.description_negative_prompt,
                    "negative_prompt": NovelAIClient.compose_negative_prompt(
                        parsed.quality_negative_prompt,
                        parsed.description_negative_prompt,
                    ),
                    "settings": settings,
                    "character_snapshot": parsed.character_snapshot,
                    "seed": parsed.seed,
                    "created_at": iso(created),
                    "expires_at": iso(created + timedelta(hours=168)),
                },
                tag_ids,
            )
            if parsed.favorite:
                new_file, new_thumb = state.storage.move_favorite(image, True)
                image = state.database.set_favorite_paths(
                    image["id"], True, new_file, new_thumb
                ) or image
            state.database.finish_job(job["id"], "succeeded", 1)
        except Exception as exc:
            if job:
                state.database.finish_job(
                    job["id"], "failed", 0, "MOBILE_SYNC", str(exc)[:1_000]
                )
            state.storage.delete_paths(saved["file_path"], saved["thumbnail_path"])
            raise
        return {"image": _public_image(image), "duplicate": False}

    @app.post("/api/uploads", status_code=201)
    async def upload_image(file: UploadFile = File(...), state: Services = Depends(svc)):
        data = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="업로드 파일은 최대 20MB까지 가능합니다.")
        saved = state.storage.save_upload(data, file.filename or "upload")
        record = state.database.create_upload(
            upload_id=saved["id"],
            file_path=saved["file_path"],
            thumbnail_path=saved["thumbnail_path"],
            original_name=saved["original_name"],
            mime_type=saved["mime_type"],
            width=saved["width"],
            height=saved["height"],
        )
        return _public_upload(record)

    @app.get("/api/uploads")
    async def list_uploads(state: Services = Depends(svc)):
        return {"items": [_public_upload(item) for item in state.database.list_uploads()]}

    @app.delete("/api/uploads/{upload_id}", status_code=204)
    async def delete_upload(upload_id: str, state: Services = Depends(svc)):
        item = state.database.get_upload(upload_id)
        if not item:
            raise HTTPException(status_code=404, detail="업로드 원본을 찾을 수 없습니다.")
        state.storage.delete_paths(item["file_path"], item.get("thumbnail_path"))
        state.database.delete_upload_record(upload_id)

    @app.post("/api/masks", status_code=201)
    async def upload_mask(
        source_asset_id: Annotated[str, Form()],
        file: UploadFile = File(...),
        state: Services = Depends(svc),
    ):
        source = state.database.get_image(source_asset_id) or state.database.get_upload(source_asset_id)
        if not source:
            raise HTTPException(status_code=404, detail="마스크의 원본 이미지를 찾을 수 없습니다.")
        data = await file.read(MAX_UPLOAD_BYTES + 1)
        saved = state.storage.save_mask(data, source_asset_id)
        if saved["width"] != source["width"] or saved["height"] != source["height"]:
            state.storage.delete_paths(saved["file_path"])
            raise HTTPException(status_code=400, detail="마스크 크기가 원본 이미지와 일치하지 않습니다.")
        state.database.create_mask(
            mask_id=saved["id"],
            file_path=saved["file_path"],
            source_asset_id=saved["source_asset_id"],
        )
        return {"id": saved["id"], "source_asset_id": source_asset_id}

    @app.post("/api/jobs", status_code=202)
    async def create_job(
        body: GenerationRequest,
        request: Request,
        state: Services = Depends(svc),
    ):
        state.storage.ensure_available()
        state.rate_limiter.check(request)
        presets = state.database.get_presets(body.character_preset_ids)
        if len(presets) != len(body.character_preset_ids):
            raise HTTPException(status_code=400, detail="선택한 인물 프리셋 중 일부가 없습니다.")
        payload = body.model_dump()
        if payload["parameters"]["seed"] is None:
            payload["random_seed_each_request"] = True
            payload["parameters"]["seed"] = secrets.randbits(32)
        payload["character_snapshot"] = [
            {
                "preset_id": preset["id"],
                "name": preset["name"],
                "tag_id": preset["tag_id"],
                "tag_name": preset["tag_name"],
                "subject_type": preset["subject_type"],
                "prompt": preset["prompt"],
                "negative_prompt": preset["negative_prompt"],
                "sort_order": preset["sort_order"],
            }
            for preset in presets
        ]
        try:
            job = state.database.create_job(payload, correlation_id())
        except OverflowError as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        await state.jobs.enqueue(job["id"])
        return job

    @app.get("/api/jobs")
    async def list_jobs(limit: int = Query(default=30, ge=1, le=100), state: Services = Depends(svc)):
        return {"items": state.database.list_jobs(limit)}

    @app.get("/api/jobs/{job_id}")
    async def get_job(job_id: str, state: Services = Depends(svc)):
        job = state.database.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다.")
        return job

    @app.post("/api/jobs/{job_id}/cancel")
    async def cancel_job(job_id: str, state: Services = Depends(svc)):
        if not state.database.request_job_stop(job_id):
            raise HTTPException(status_code=409, detail="대기 중인 작업이나 진행 중인 연속 생성만 중단할 수 있습니다.")
        job = state.database.get_job(job_id)
        return {"cancelled": job["status"] == "cancelled", "cancel_requested": True}

    @app.get("/api/images")
    async def list_images(
        favorite: bool | None = None,
        tag: list[str] = Query(default=[]),
        nsfw: bool | None = None,
        page: int = Query(default=1, ge=1),
        state: Services = Depends(svc),
    ):
        result = state.database.list_images(favorite, tag, page, nsfw=nsfw)
        result["items"] = [_public_image(item) for item in result["items"]]
        return result

    @app.get("/api/mobile/offline-gallery")
    async def mobile_offline_gallery(
        favorite: bool = False,
        page: int = Query(default=1, ge=1),
        state: Services = Depends(svc),
    ):
        result = state.database.list_images(favorite, [], page)
        result["items"] = [
            _offline_gallery_image(item) for item in result["items"]
        ]
        return result

    @app.get("/api/images/favorite-tags")
    async def favorite_tags(
        nsfw: bool | None = None,
        state: Services = Depends(svc),
    ):
        return {"items": state.database.favorite_tag_counts(nsfw=nsfw)}

    @app.patch("/api/images/{image_id}/favorite")
    async def set_favorite(image_id: str, body: FavoriteInput, state: Services = Depends(svc)):
        image = state.database.get_image(image_id)
        if not image:
            raise HTTPException(status_code=404, detail="이미지를 찾을 수 없습니다.")
        currently_favorite = image["favorite_at"] is not None
        if currently_favorite == body.favorite:
            return _public_image(image)
        new_file, new_thumb = state.storage.move_favorite(image, body.favorite)
        try:
            result = state.database.set_favorite_paths(image_id, body.favorite, new_file, new_thumb)
        except Exception:
            rollback = {**image, "file_path": new_file, "thumbnail_path": new_thumb}
            state.storage.move_favorite(rollback, not body.favorite)
            raise
        return _public_image(result) if result else None

    @app.post("/api/images/{image_id}/discord")
    async def send_image_to_discord(
        image_id: str,
        body: DiscordSendInput,
        request: Request,
        state: Services = Depends(svc),
    ):
        state.webhook_rate_limiter.check(request)
        image = state.database.get_image(image_id)
        if not image:
            raise HTTPException(status_code=404, detail="이미지를 찾을 수 없습니다.")
        webhook = state.database.get_discord_webhook(body.webhook_id)
        if not webhook:
            raise HTTPException(status_code=404, detail="Discord 웹훅을 찾을 수 없습니다.")
        try:
            webhook_url = state.credentials.get_discord_webhook_url(body.webhook_id)
        except CredentialStoreError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        if not webhook_url:
            raise HTTPException(
                status_code=409,
                detail="PC 설정에서 이 Discord 웹훅 주소를 다시 저장해 주세요.",
            )
        image_path = state.storage.absolute(image["file_path"])
        if not image_path.exists():
            raise HTTPException(status_code=410, detail="전송할 원본 이미지 파일이 없습니다.")
        try:
            await state.discord.send_image(
                webhook_url,
                image,
                image_path,
                include_tags=body.include_tags,
                include_metadata=body.include_metadata,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=409,
                detail="PC 설정에서 이 Discord 웹훅 주소를 다시 저장해 주세요.",
            ) from exc
        except DiscordWebhookError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        return {
            "sent": True,
            "webhook_id": webhook["id"],
            "webhook_name": webhook["name"],
        }

    @app.delete("/api/images/{image_id}", status_code=204)
    async def delete_image(image_id: str, state: Services = Depends(svc)):
        image = state.database.get_image(image_id)
        if not image:
            raise HTTPException(status_code=404, detail="이미지를 찾을 수 없습니다.")
        state.storage.delete_paths(image["file_path"], image.get("thumbnail_path"))
        state.database.delete_image_record(image_id)

    def _resolve_asset(asset_id: str, state: Services) -> dict[str, Any]:
        image = state.database.get_image(asset_id)
        if image:
            return image
        upload = state.database.get_upload(asset_id)
        if upload:
            return upload
        raise HTTPException(status_code=404, detail="이미지를 찾을 수 없습니다.")

    @app.get("/api/assets/{asset_id}/content")
    async def asset_content(asset_id: str, state: Services = Depends(svc)):
        item = _resolve_asset(asset_id, state)
        path = state.storage.absolute(item["file_path"])
        if not path.exists():
            raise HTTPException(status_code=410, detail="이미지 파일이 없습니다.")
        return FileResponse(path, media_type=item["mime_type"])

    @app.get("/api/assets/{asset_id}/thumbnail")
    async def asset_thumbnail(asset_id: str, state: Services = Depends(svc)):
        item = _resolve_asset(asset_id, state)
        relative = item.get("thumbnail_path") or item["file_path"]
        path = state.storage.absolute(relative)
        if not path.exists():
            raise HTTPException(status_code=410, detail="썸네일 파일이 없습니다.")
        return FileResponse(path, media_type=mimetypes.guess_type(path.name)[0] or "image/webp")

    @app.get("/api/images/{image_id}/download")
    def download_image(
        image_id: str,
        metadata: Literal["preserve", "remove"] = "preserve",
        state: Services = Depends(svc),
    ):
        item = state.database.get_image(image_id)
        if not item:
            raise HTTPException(status_code=404, detail="이미지를 찾을 수 없습니다.")
        path = state.storage.absolute(item["file_path"])
        if not path.is_file():
            raise HTTPException(status_code=410, detail="이미지 파일이 없습니다.")
        if metadata == "remove":
            try:
                data = metadata_free_png(path)
            except (ValueError, OSError) as exc:
                raise HTTPException(status_code=422, detail="이미지 정보를 제거하지 못했습니다. 원본은 변경되지 않았습니다.") from exc
            return Response(data, media_type="image/png", headers={
                "Content-Disposition": f'attachment; filename="novelai-{image_id}-no-metadata.png"',
                "Cache-Control": "private, no-store",
            })
        return FileResponse(path, media_type=item["mime_type"], filename=f"novelai-{image_id}{path.suffix}", headers={"Cache-Control": "private, no-store"})

    @app.post("/api/images/{image_id}/clipboard", dependencies=[Depends(require_local_machine)])
    def copy_image_to_clipboard(
        image_id: str,
        metadata: Literal["preserve", "remove"] = "preserve",
        state: Services = Depends(svc),
    ):
        item = state.database.get_image(image_id)
        if not item:
            raise HTTPException(status_code=404, detail="이미지를 찾을 수 없습니다.")
        path = state.storage.absolute(item["file_path"])
        if not path.is_file():
            raise HTTPException(status_code=410, detail="이미지 파일이 없습니다.")
        try:
            data = metadata_free_png(path) if metadata == "remove" else path.read_bytes()
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail="이미지 정보를 제거하지 못했어요") from exc
        # The clipboard file list points at a real file, so keep a copy that outlives this request.
        folder = state.paths.root / "clipboard"
        folder.mkdir(parents=True, exist_ok=True)
        cutoff = time.time() - 24 * 3600
        for old in folder.glob("*.png"):
            try:
                if old.stat().st_mtime < cutoff:
                    old.unlink()
            except OSError:
                pass
        suffix = "-no-metadata" if metadata == "remove" else ""
        target = folder / f"novelai-{image_id}{suffix}.png"
        target.write_bytes(data)
        try:
            clipboard.copy_image_to_clipboard(data, target)
        except clipboard.ClipboardError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"copied": True, "metadata": metadata}

    @app.get("/api/favorites/export")
    async def export_favorites(state: Services = Depends(svc)):
        favorites = state.database.all_favorites()
        if not favorites:
            raise HTTPException(status_code=404, detail="내보낼 즐겨찾기 이미지가 없습니다.")
        archive = state.storage.build_favorites_zip(favorites)
        return FileResponse(
            archive,
            media_type="application/zip",
            filename="novelai-favorites.zip",
            background=BackgroundTask(archive.unlink, missing_ok=True),
        )

    @app.get("/api/stats")
    async def statistics(state: Services = Depends(svc)):
        return state.database.statistics()

    app.mount(
        "/mcp",
        LoopbackOnlyASGI(McpActivityASGI(mcp_http_app, lambda: services.claude.record_mcp_activity())),
        name="novelai-mcp",
    )

    frontend_dist = resource_path("frontend/dist")
    if frontend_dist.exists():
        app.mount("/", FrontendStaticFiles(directory=frontend_dist, html=True), name="frontend")
    else:
        @app.get("/")
        async def development_root():
            return {
                "message": "Frontend is not built. Run npm install and npm run build in frontend/.",
                "api": "/api/status",
            }

    return app
