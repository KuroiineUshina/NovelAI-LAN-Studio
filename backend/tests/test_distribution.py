from __future__ import annotations

import json
import re
from pathlib import Path

import httpx
import pytest
import respx

from backend.app.distribution import (
    DistributionPublishError,
    publish_distribution_files,
    split_file_for_discord,
)


WEBHOOK_URL = (
    "https://discord.com/api/webhooks/123456789012345678/"
    "abcdefghijklmnopqrstuvwxyzABCDEF1234567890"
)


def payload_from_request(request: httpx.Request) -> dict:
    body = request.content.decode("utf-8", errors="ignore")
    match = re.search(
        r'name="payload_json"\r\n\r\n(.*?)\r\n--', body, flags=re.DOTALL
    )
    assert match is not None
    return json.loads(match.group(1))


@pytest.mark.asyncio
@respx.mock
async def test_distribution_publishes_only_files_without_message_text(tmp_path: Path):
    artifacts = [
        tmp_path / "release.zip",
        tmp_path / "release.apk",
        tmp_path / "SHA256SUMS.txt",
    ]
    for index, artifact in enumerate(artifacts):
        artifact.write_bytes(f"artifact-{index}".encode())
    route = respx.post(
        url__regex=re.compile(r"^https://discord\.com/api/webhooks/.+")
    ).mock(return_value=httpx.Response(200, json={"id": "message"}))

    published = await publish_distribution_files(WEBHOOK_URL, artifacts)

    assert published == [artifact.name for artifact in artifacts]
    assert route.call_count == 1
    payload = payload_from_request(route.calls[0].request)
    assert "content" not in payload
    assert payload["attachments"] == [
        {"id": index, "filename": artifact.name}
        for index, artifact in enumerate(artifacts)
    ]
    assert payload["allowed_mentions"]["parse"] == []


def test_large_zip_is_split_and_can_be_reassembled(tmp_path: Path):
    source = tmp_path / "release.exe"
    original = bytes(range(251)) * 5
    source.write_bytes(original)

    parts, join_script = split_file_for_discord(
        source, tmp_path / "parts", chunk_bytes=400
    )

    assert len(parts) == 4
    assert b"".join(part.read_bytes() for part in parts) == original
    script = join_script.read_text(encoding="utf-8")
    assert join_script.name.endswith("-EXE.cmd")
    assert source.name in script
    assert all(part.name in script for part in parts)


@pytest.mark.asyncio
@respx.mock
async def test_distribution_failure_is_not_retried(tmp_path: Path):
    artifact = tmp_path / "release.zip"
    artifact.write_bytes(b"release")
    route = respx.post(
        url__regex=re.compile(r"^https://discord\.com/api/webhooks/.+")
    ).mock(return_value=httpx.Response(413))

    with pytest.raises(DistributionPublishError, match="업로드 제한"):
        await publish_distribution_files(WEBHOOK_URL, [artifact])
    assert route.call_count == 1
