from __future__ import annotations

import asyncio
import base64
import io
import json
import zipfile
from pathlib import Path

import httpx
import pytest
import respx
from PIL import Image
from pydantic import ValidationError

from backend.app.config import AppPaths
from backend.app.database import Database
from backend.app.jobs import JobManager
from backend.app.novelai import NovelAIClient, letterbox_reference
from backend.app.schemas import GenerationRequest
from backend.app.storage import ImageStorage
from backend.tests.test_novelai import request_data


class Credentials:
    def get_token(self) -> str:
        return "pst-test"


def png(width: int, height: int) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (width, height), (200, 80, 120)).save(output, format="PNG")
    return output.getvalue()


def test_reference_payload_fields_follow_novelai_contract():
    data = {**request_data(), "model": "nai-diffusion-4-5-full"}
    payload = NovelAIClient.build_generation_payload(
        data, None, None, vibes=[(b"vibe-a", 0.6), (b"vibe-b", 0.3)]
    )
    params = payload["parameters"]
    assert params["reference_image_multiple"] == [
        base64.b64encode(b"vibe-a").decode(),
        base64.b64encode(b"vibe-b").decode(),
    ]
    assert params["reference_strength_multiple"] == [0.6, 0.3]
    assert "director_reference_images" not in params

    payload = NovelAIClient.build_generation_payload(
        data,
        None,
        None,
        character_references=[
            {"image": b"ref", "kind": "character", "strength": 0.8, "fidelity": 0.75}
        ],
    )
    params = payload["parameters"]
    assert params["director_reference_images"] == [base64.b64encode(b"ref").decode()]
    assert params["director_reference_descriptions"] == [
        {"caption": {"base_caption": "character", "char_captions": []}, "legacy_uc": False}
    ]
    assert params["director_reference_information_extracted"] == [1]
    assert params["director_reference_strength_values"] == [0.8]
    # Fidelity is sent inverted.
    assert params["director_reference_secondary_strength_values"] == [0.25]
    assert "reference_image_multiple" not in params


@pytest.mark.parametrize(
    ("size", "canvas"),
    [((832, 1216), (1024, 1536)), ((1216, 832), (1536, 1024)), ((1000, 1000), (1472, 1472))],
)
def test_character_reference_is_letterboxed_to_a_supported_canvas(size, canvas):
    with Image.open(io.BytesIO(letterbox_reference(png(*size)))) as result:
        assert result.size == canvas
        assert result.getpixel((0, 0)) in {(0, 0, 0), (200, 80, 120)}


def base_request(**overrides) -> dict:
    body = {
        "mode": "txt2img",
        "model": "nai-diffusion-4-5-full",
        "description_prompt": "1girl",
    }
    body.update(overrides)
    return body


def test_references_are_limited_to_supported_models_and_not_combined():
    GenerationRequest(**base_request(vibe_references=[{"asset_id": "a"}]))
    GenerationRequest(**base_request(character_references=[{"asset_id": "a"}]))
    with pytest.raises(ValidationError, match="바이브"):
        GenerationRequest(**base_request(model="nai-diffusion-5-full", vibe_references=[{"asset_id": "a"}]))
    with pytest.raises(ValidationError, match="캐릭터 레퍼런스"):
        GenerationRequest(
            **base_request(model="nai-diffusion-5-full", character_references=[{"asset_id": "a"}])
        )
    with pytest.raises(ValidationError, match="함께"):
        GenerationRequest(
            **base_request(
                vibe_references=[{"asset_id": "a"}], character_references=[{"asset_id": "b"}]
            )
        )


def test_director_needs_a_source_and_tool_but_no_prompt():
    request = GenerationRequest(
        mode="director",
        model="nai-diffusion-5-full",
        source_asset_id="img",
        director={"tool": "emotion", "emotion": "Smug", "level": 2},
    )
    assert request.director and request.director.emotion == "smug"
    with pytest.raises(ValidationError):
        GenerationRequest(mode="director", source_asset_id="img")
    with pytest.raises(ValidationError):
        GenerationRequest(mode="director", director={"tool": "lineart"})
    with pytest.raises(ValidationError):
        GenerationRequest(
            mode="director", source_asset_id="img", director={"tool": "emotion", "emotion": "rage"}
        )


@pytest.mark.asyncio
@respx.mock
async def test_director_emotion_request_and_zip_response():
    source = png(832, 1216)
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("image_0.png", source)
    route = respx.post("https://image.novelai.net/ai/augment-image").mock(
        return_value=httpx.Response(
            201, content=archive.getvalue(), headers={"content-type": "application/zip"}
        )
    )
    data = {
        "mode": "director",
        "model": "nai-diffusion-5-full",
        "director": {"tool": "emotion", "emotion": "smug", "prompt": "blush", "level": 2},
    }
    outputs = await NovelAIClient("pst-test").generate(data, "DIR123", source=source)
    body = json.loads(route.calls[0].request.content)
    assert body == {
        "req_type": "emotion",
        "width": 832,
        "height": 1216,
        "image": base64.b64encode(source).decode(),
        "prompt": "smug;;blush",
        "defry": 2,
    }
    assert [item.data for item in outputs] == [source]


async def run_job(manager: JobManager, database: Database, job_id: str) -> dict:
    await manager.enqueue(job_id)
    for _ in range(150):
        current = database.get_job(job_id)
        if current and current["status"] in {"succeeded", "failed"}:
            return current
        await asyncio.sleep(0.02)
    raise AssertionError("job did not finish")


@pytest.mark.asyncio
@respx.mock
async def test_worker_encodes_each_vibe_once_and_reuses_the_cache(tmp_path: Path, icon_bytes: bytes):
    paths = AppPaths(tmp_path / "app")
    paths.ensure()
    database = Database(paths.database)
    database.initialize()
    storage = ImageStorage(paths)
    saved = storage.save_upload(icon_bytes, "vibe.png")
    database.create_upload(
        upload_id=saved["id"],
        file_path=saved["file_path"],
        thumbnail_path=saved["thumbnail_path"],
        original_name=saved["original_name"],
        mime_type=saved["mime_type"],
        width=saved["width"],
        height=saved["height"],
    )
    encode = respx.post("https://image.novelai.net/ai/encode-vibe").mock(
        return_value=httpx.Response(201, content=b"encoded-vibe")
    )
    generate = respx.post("https://image.novelai.net/ai/generate-image").mock(
        return_value=httpx.Response(
            201, json={"images": [{"image": base64.b64encode(icon_bytes).decode(), "seed": 1}]}
        )
    )
    body = GenerationRequest(
        **base_request(
            vibe_references=[{"asset_id": saved["id"], "strength": 0.5, "information_extracted": 0.7}]
        )
    ).model_dump()
    body["character_snapshot"] = []
    manager = JobManager(database, storage, Credentials())  # type: ignore[arg-type]
    await manager.start()
    try:
        first = await run_job(manager, database, database.create_job(body, "VIBE01")["id"])
        second = await run_job(manager, database, database.create_job(body, "VIBE02")["id"])
    finally:
        await manager.stop()

    assert first["status"] == second["status"] == "succeeded"
    assert encode.call_count == 1
    encoded_request = json.loads(encode.calls[0].request.content)
    assert encoded_request["model"] == "nai-diffusion-4-5-full"
    assert encoded_request["information_extracted"] == 0.7
    sent = json.loads(generate.calls[1].request.content)["parameters"]
    assert sent["reference_image_multiple"] == [base64.b64encode(b"encoded-vibe").decode()]
    assert sent["reference_strength_multiple"] == [0.5]
    image = database.list_images(False, [], 1)["items"][0]
    assert image["settings"]["vibe_references"][0]["asset_id"] == saved["id"]


def test_nsfw_prompt_is_sent_only_while_nsfw_is_enabled():
    data = {**request_data(), "nsfw_prompt": "lying on bed"}
    off = NovelAIClient.build_generation_payload(data, None, None)
    assert "lying on bed" not in off["input"]
    on = NovelAIClient.build_generation_payload({**data, "nsfw_enabled": True}, None, None)
    assert on["input"] == "1girl, masterpiece, best quality, nsfw, uncensored, night city, lying on bed"


def test_draft_keeps_nsfw_prompt_when_an_older_client_omits_it(client):
    draft = client.get("/api/generation-draft/sync").json()["draft"]
    draft["nsfw_prompt"] = "saved nsfw text"
    client.put("/api/generation-draft/sync", json={"client_id": "pc-client-1234", "draft": draft})
    legacy = {key: value for key, value in draft.items() if key != "nsfw_prompt"}
    legacy["description_prompt"] = "from android"
    client.post("/api/generation-draft/sync", json={"client_id": "android-1234", "draft": legacy})
    saved = client.get("/api/generation-draft").json()
    assert saved["description_prompt"] == "from android"
    assert saved["nsfw_prompt"] == "saved nsfw text"
