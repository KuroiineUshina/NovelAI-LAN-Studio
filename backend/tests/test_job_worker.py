from __future__ import annotations

import asyncio
import base64
from pathlib import Path

import httpx
import pytest
import respx

from backend.app.config import AppPaths
from backend.app.database import Database
from backend.app.jobs import JobManager
from backend.app.storage import ImageStorage


class Credentials:
    def get_token(self) -> str:
        return "pst-test"


@pytest.mark.asyncio
@respx.mock
async def test_worker_persists_image_tags_and_statistics(tmp_path: Path, icon_bytes: bytes):
    paths = AppPaths(tmp_path / "app")
    paths.ensure()
    database = Database(paths.database)
    database.initialize()
    storage = ImageStorage(paths)
    preset = database.create_preset(
        {
            "name": "아리아",
            "tag_name": "aria",
            "subject_type": "girl",
            "prompt": "girl, silver hair",
            "negative_prompt": "red hair",
            "sort_order": 0,
        }
    )
    payload = {
        "mode": "txt2img",
        "model": "nai-diffusion-5-full",
        "quality_prompt": "masterpiece, best quality",
        "description_prompt": "night city",
        "quality_negative_prompt": "blurry, lowres",
        "description_negative_prompt": "empty street",
        "nsfw_enabled": True,
        "source_asset_id": None,
        "mask_asset_id": None,
        "parameters": {
            "width": 1024,
            "height": 1024,
            "steps": 28,
            "guidance": 5,
            "guidance_rescale": 0.3,
            "sampler": "k_euler_ancestral",
            "count": 1,
            "quality": True,
            "seed": None,
            "strength": 0.7,
            "noise": 0.2,
        },
        "character_snapshot": [
            {
                "preset_id": preset["id"],
                "name": preset["name"],
                "tag_id": preset["tag_id"],
                "tag_name": preset["tag_name"],
                "subject_type": "girl",
                "prompt": preset["prompt"],
                "negative_prompt": preset["negative_prompt"],
                "sort_order": 0,
            }
        ],
    }
    job = database.create_job(payload, "JOB123")
    route = respx.post("https://image.novelai.net/ai/generate-image").mock(
        return_value=httpx.Response(
            201,
            json={"images": [{"image": base64.b64encode(icon_bytes).decode(), "seed": 777}]},
        )
    )
    manager = JobManager(database, storage, Credentials())  # type: ignore[arg-type]
    await manager.start()
    try:
        await manager.enqueue(job["id"])
        for _ in range(100):
            current = database.get_job(job["id"])
            if current and current["status"] in {"succeeded", "failed"}:
                break
            await asyncio.sleep(0.02)
    finally:
        await manager.stop()

    current = database.get_job(job["id"])
    assert current and current["status"] == "succeeded"
    assert current["output_count"] == 1
    assert route.call_count == 1
    images = database.list_images(False, [], 1)
    assert images["total"] == 1
    assert images["items"][0]["seed"] == 777
    assert images["items"][0]["prompt"] == (
        "1girl, masterpiece, best quality, night city"
    )
    assert images["items"][0]["quality_prompt"] == "masterpiece, best quality"
    assert images["items"][0]["description_prompt"] == "night city"
    assert images["items"][0]["quality_negative_prompt"] == "blurry, lowres"
    assert images["items"][0]["description_negative_prompt"] == "empty street"
    assert images["items"][0]["negative_prompt"] == "blurry, lowres, empty street"
    assert images["items"][0]["settings"]["guidance_rescale"] == 0.3
    assert images["items"][0]["settings"]["nsfw_enabled"] is True
    assert images["items"][0]["tags"][0]["name"] == "aria"
    assert database.statistics()["lifetime"] == 1
