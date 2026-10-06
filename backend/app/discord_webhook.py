from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx


# HTTPX logs full request URLs at INFO. Discord webhook URLs contain a secret token,
# so request logging must stay below the application's log threshold.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


DISCORD_UPLOAD_LIMIT = 10 * 1024 * 1024
_ALLOWED_HOSTS = {
    "discord.com",
    "canary.discord.com",
    "ptb.discord.com",
    "discordapp.com",
}
_WEBHOOK_PATH = re.compile(
    r"^/api(?:/v\d+)?/webhooks/(?P<webhook_id>\d{17,20})/(?P<token>[A-Za-z0-9._-]{20,})/?$"
)


class DiscordWebhookError(RuntimeError):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def validate_discord_webhook_url(value: str) -> str:
    """Accept only Discord-owned incoming webhook endpoints to prevent SSRF."""

    raw = value.strip()
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("올바른 Discord 웹훅 주소가 아닙니다.") from exc
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "https"
        or host not in _ALLOWED_HOSTS
        or port not in {None, 443}
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or not _WEBHOOK_PATH.fullmatch(parsed.path)
    ):
        raise ValueError(
            "Discord에서 복사한 https://discord.com/api/webhooks/... 주소를 입력해 주세요."
        )
    path = parsed.path.rstrip("/")
    return urlunsplit(("https", host, path, "", ""))


def image_manifest(image: dict[str, Any]) -> bytes:
    payload = {
        "schema_version": 1,
        "image_id": image["id"],
        "job_id": image["job_id"],
        "parent_image_id": image.get("parent_image_id"),
        "created_at": image["created_at"],
        "mode": image["mode"],
        "model": image["model"],
        "width": image["width"],
        "height": image["height"],
        "seed": image.get("seed"),
        "quality_prompt": image.get("quality_prompt", ""),
        "description_prompt": image.get("description_prompt", image.get("prompt", "")),
        "prompt": image.get("prompt", ""),
        "negative_prompt": image.get("negative_prompt", ""),
        "settings": image.get("settings", {}),
        "characters": image.get("character_snapshot", []),
        "tags": image.get("tags", []),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def image_is_nsfw(image: dict[str, Any]) -> bool:
    settings = image.get("settings")
    return isinstance(settings, dict) and settings.get("nsfw_enabled") is True


class DiscordWebhookClient:
    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout

    async def send_image(
        self,
        webhook_url: str,
        image: dict[str, Any],
        image_path: Path,
        *,
        include_tags: bool,
        include_metadata: bool,
    ) -> None:
        normalized_url = validate_discord_webhook_url(webhook_url)
        try:
            image_size = image_path.stat().st_size
        except OSError as exc:
            raise DiscordWebhookError("전송할 원본 이미지 파일을 읽지 못했습니다.", 410) from exc
        if image_size > DISCORD_UPLOAD_LIMIT:
            raise DiscordWebhookError(
                "이미지가 Discord 웹훅의 파일당 10MB 제한을 초과합니다.", 413
            )

        extension = image_path.suffix.lower() or ".png"
        base_filename = f"novelai-{image['id']}{extension}"
        filename = (
            f"SPOILER_{base_filename}" if image_is_nsfw(image) else base_filename
        )
        tag_line = ""
        if include_tags and image.get("tags"):
            tag_line = " ".join(f"#{item['name']}" for item in image["tags"])[
                :2_000
            ]

        attachments: list[dict[str, Any]] = [{"id": 0, "filename": filename}]
        try:
            image_bytes = image_path.read_bytes()
        except OSError as exc:
            raise DiscordWebhookError("전송할 원본 이미지 파일을 읽지 못했습니다.", 410) from exc
        files: list[tuple[str, tuple[str, bytes, str]]] = [
            (
                "files[0]",
                (filename, image_bytes, image.get("mime_type") or "application/octet-stream"),
            )
        ]
        if include_metadata:
            metadata = image_manifest(image)
            metadata_name = f"novelai-{image['id']}-metadata.json"
            attachments.append({"id": 1, "filename": metadata_name})
            files.append(
                (
                    "files[1]",
                    (metadata_name, metadata, "application/json; charset=utf-8"),
                )
            )

        payload: dict[str, Any] = {
            "allowed_mentions": {"parse": [], "replied_user": False},
            "attachments": attachments,
        }
        if tag_line:
            payload["content"] = tag_line
        headers = {"User-Agent": "NovelAI-LAN-Studio/1.0 (+local-app)"}
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout, follow_redirects=False, headers=headers
            ) as client:
                response = await client.post(
                    normalized_url,
                    params={"wait": "true"},
                    data={"payload_json": json.dumps(payload, ensure_ascii=False)},
                    files=files,
                )
        except httpx.RequestError as exc:
            raise DiscordWebhookError(
                "Discord 서버에 연결하지 못했습니다. 자동으로 다시 전송하지 않았습니다."
            ) from exc

        if response.is_success:
            return
        messages = {
            400: "Discord가 메시지 또는 첨부 파일을 거부했습니다.",
            401: "Discord 웹훅 인증 정보가 올바르지 않습니다.",
            403: "Discord 채널에 파일을 보낼 권한이 없습니다.",
            404: "Discord 웹훅이 삭제되었거나 주소가 올바르지 않습니다.",
            413: "이미지가 Discord의 업로드 제한을 초과합니다.",
            429: "Discord 웹훅 전송 제한에 도달했습니다. 잠시 후 직접 다시 시도해 주세요.",
        }
        if response.status_code >= 500:
            message = "Discord 서버 오류로 전송하지 못했습니다. 자동으로 다시 전송하지 않았습니다."
        else:
            message = messages.get(
                response.status_code,
                f"Discord 전송에 실패했습니다. ({response.status_code})",
            )
        raise DiscordWebhookError(message, response.status_code)
