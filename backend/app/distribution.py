from __future__ import annotations

import json
import mimetypes
from pathlib import Path
from typing import Sequence

import httpx

from .discord_webhook import validate_discord_webhook_url


DISCORD_SAFE_BATCH_BYTES = 9 * 1024 * 1024


class DistributionPublishError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def split_file_for_discord(
    source: Path,
    output_directory: Path,
    *,
    chunk_bytes: int = DISCORD_SAFE_BATCH_BYTES,
) -> tuple[list[Path], Path]:
    output_directory.mkdir(parents=True, exist_ok=True)
    parts: list[Path] = []
    try:
        with source.open("rb") as stream:
            index = 1
            while chunk := stream.read(chunk_bytes):
                part = output_directory / f"{source.name}.{index:03d}"
                part.write_bytes(chunk)
                parts.append(part)
                index += 1
    except OSError as exc:
        raise DistributionPublishError(
            f"배포 파일 분할에 실패했습니다: {source.name}"
        ) from exc
    if not parts:
        raise DistributionPublishError(f"빈 배포 파일은 전송할 수 없습니다: {source.name}")

    artifact_kind = source.suffix.lstrip(".").upper() or "FILE"
    join_script = output_directory / f"NovelAI-LAN-Studio-Join-Windows-{artifact_kind}.cmd"
    joined_parts = "+".join(f'"{part.name}"' for part in parts)
    script = (
        "@echo off\r\n"
        "setlocal\r\n"
        "cd /d \"%~dp0\"\r\n"
        f"copy /b {joined_parts} \"{source.name}\" >nul\r\n"
        "if errorlevel 1 exit /b 1\r\n"
    )
    join_script.write_text(script, encoding="utf-8", newline="")
    return parts, join_script


def _file_batches(
    files: Sequence[Path], max_bytes: int
) -> list[list[tuple[Path, bytes]]]:
    batches: list[list[tuple[Path, bytes]]] = []
    current: list[tuple[Path, bytes]] = []
    current_size = 0
    for path in files:
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise DistributionPublishError(
                f"배포 파일을 읽지 못했습니다: {path.name}"
            ) from exc
        if len(data) > max_bytes:
            raise DistributionPublishError(
                f"Discord 전송용 분할이 필요합니다: {path.name}"
            )
        if current and current_size + len(data) > max_bytes:
            batches.append(current)
            current = []
            current_size = 0
        current.append((path, data))
        current_size += len(data)
    if current:
        batches.append(current)
    return batches


async def publish_distribution_files(
    webhook_url: str,
    files: Sequence[Path],
    *,
    timeout: float = 120.0,
    max_batch_bytes: int = DISCORD_SAFE_BATCH_BYTES,
) -> list[str]:
    normalized_url = validate_discord_webhook_url(webhook_url)
    published: list[str] = []
    headers = {"User-Agent": "NovelAI-LAN-Studio/1.0 (+local-release)"}

    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=False,
        headers=headers,
    ) as client:
        for batch in _file_batches(files, max_batch_bytes):
            attachments: list[dict[str, object]] = []
            multipart_files: list[tuple[str, tuple[str, bytes, str]]] = []
            for index, (path, data) in enumerate(batch):
                mime_type = (
                    "application/vnd.android.package-archive"
                    if path.suffix.lower() == ".apk"
                    else mimetypes.guess_type(path.name)[0]
                    or "application/octet-stream"
                )
                attachments.append({"id": index, "filename": path.name})
                multipart_files.append(
                    (f"files[{index}]", (path.name, data, mime_type))
                )
            payload = {
                "allowed_mentions": {"parse": [], "replied_user": False},
                "attachments": attachments,
            }
            try:
                response = await client.post(
                    normalized_url,
                    params={"wait": "true"},
                    data={"payload_json": json.dumps(payload)},
                    files=multipart_files,
                )
            except httpx.RequestError as exc:
                raise DistributionPublishError(
                    "Discord에 배포 파일을 보내지 못했습니다."
                ) from exc
            if not response.is_success:
                batch_names = ", ".join(path.name for path, _ in batch)
                if response.status_code == 413:
                    message = f"Discord 업로드 제한을 초과했습니다: {batch_names}"
                elif response.status_code == 429:
                    message = f"Discord 전송 제한에 도달했습니다: {batch_names}"
                else:
                    message = (
                        f"Discord 배포 파일 전송에 실패했습니다: "
                        f"{batch_names} ({response.status_code})"
                    )
                raise DistributionPublishError(message, response.status_code)
            published.extend(path.name for path, _ in batch)
    return published
