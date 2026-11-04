from __future__ import annotations

import io
import uuid
from datetime import timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from backend.app.database import iso, utc_now
from backend.app.main import create_app
from backend.app.mcp_generation import remove_flat_background
from backend.tests.test_mcp import MCP_HEADERS, mcp_call


def png(width: int, height: int, color=(200, 80, 120)) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (width, height), color).save(output, format="PNG")
    return output.getvalue()


def figure_on_white() -> bytes:
    image = Image.new("RGB", (64, 64), (255, 255, 255))
    for x in range(20, 44):
        for y in range(10, 54):
            image.putpixel((x, y), (40, 40, 160))
    # White patch inside the silhouette must stay opaque.
    for x in range(28, 36):
        for y in range(28, 36):
            image.putpixel((x, y), (255, 255, 255))
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def test_flat_background_removal_keeps_enclosed_white():
    with Image.open(io.BytesIO(remove_flat_background(figure_on_white()))) as result:
        alpha = result.getchannel("A")
        assert result.mode == "RGBA"
        assert alpha.getpixel((2, 2)) == 0
        assert alpha.getpixel((32, 32)) == 255
        assert alpha.getpixel((24, 20)) == 255


def test_generation_tools_are_listed_with_spending_hints(tmp_path: Path):
    app = create_app(data_dir=tmp_path / "data", start_workers=False, start_mcp=True)
    with TestClient(app, client=("127.0.0.1", 49100)) as client:
        response = client.post(
            "/mcp/",
            headers=MCP_HEADERS,
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        )
        tools = {tool["name"]: tool for tool in response.json()["result"]["tools"]}
        for name in ("generate_images", "remove_background", "collect_generation_outputs"):
            assert name in tools
        assert tools["generate_images"]["annotations"]["openWorldHint"] is True
        assert tools["generate_images"]["annotations"]["readOnlyHint"] is False


def test_generate_images_queues_job_without_touching_draft_and_collects_png(tmp_path: Path):
    app = create_app(data_dir=tmp_path / "data", start_workers=False, start_mcp=True)
    source = tmp_path / "front.png"
    source.write_bytes(png(1024, 1024))
    out = tmp_path / "out"
    with TestClient(app, client=("127.0.0.1", 49100)) as client:
        draft = client.get("/api/generation-draft").json()
        draft.update({"quality_prompt": "masterpiece", "description_prompt": "kept scene"})
        client.put("/api/generation-draft", json=draft)
        revision = mcp_call(client, 1, "get_prompt_context")["revision"]

        result = mcp_call(
            client,
            2,
            "generate_images",
            {
                "output_dir": str(out),
                "prompt": "1girl, t-pose, from side",
                "negative_prompt": "background",
                "source_image_path": str(source),
                "strength": 0.5,
                "seed": 42,
                "timeout_seconds": 1,
            },
        )
        assert result["status"] == "queued"
        assert result["mode"] == "img2img"
        services = app.state.services
        job = services.database.get_job(result["job_id"])
        request = job["request"]
        assert request["description_prompt"] == "1girl, t-pose, from side"
        assert request["quality_prompt"] == "masterpiece"
        assert request["parameters"]["strength"] == 0.5
        assert request["nsfw_enabled"] is False
        assert services.database.get_upload(request["source_asset_id"])
        assert mcp_call(client, 3, "get_prompt_context")["revision"] == revision

        image_id = str(uuid.uuid4())
        saved = services.storage.save_generated(png(1024, 1024, (10, 20, 30)), image_id)
        created = utc_now()
        services.database.create_image(
            {
                "id": image_id,
                "job_id": job["id"],
                **saved,
                "mode": "img2img",
                "model": request["model"],
                "prompt": "p",
                "negative_prompt": "",
                "settings": {"hidden_from_gallery": True},
                "character_snapshot": [],
                "seed": 42,
                "created_at": iso(created),
                "expires_at": iso(created + timedelta(hours=1)),
            },
            [],
        )
        services.database.finish_job(job["id"], "succeeded", 1)
        assert job["request"]["hidden_from_gallery"] is True
        assert client.get("/api/images").json()["total"] == 0

        collected = mcp_call(
            client,
            4,
            "collect_generation_outputs",
            {"job_id": job["id"], "output_dir": str(out), "filename_prefix": "side"},
        )
        assert collected["status"] == "succeeded"
        written = Path(collected["files"][0]["path"])
        assert written == out / "side_42.png"
        assert written.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
        assert services.database.get_image(image_id) is None
        assert services.database.get_upload(request["source_asset_id"]) is None


def test_remove_background_flat_color_is_local_and_free(tmp_path: Path):
    app = create_app(data_dir=tmp_path / "data", start_workers=False, start_mcp=True)
    source = tmp_path / "head.png"
    source.write_bytes(figure_on_white())
    with TestClient(app, client=("127.0.0.1", 49100)) as client:
        result = mcp_call(
            client,
            1,
            "remove_background",
            {"image_path": str(source), "output_dir": str(tmp_path / "out"), "method": "flat_color"},
        )
        assert result["anlas"]["spent"] == 0
        assert result["files"][0]["has_alpha"] is True
        assert Path(result["files"][0]["path"]).name == "head_nobg.png"
        assert app.state.services.database.list_jobs(10) == []


def test_generate_images_rejects_relative_output_dir(tmp_path: Path):
    app = create_app(data_dir=tmp_path / "data", start_workers=False, start_mcp=True)
    with TestClient(app, client=("127.0.0.1", 49100)) as client:
        response = client.post(
            "/mcp/",
            headers=MCP_HEADERS,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "generate_images",
                    "arguments": {"output_dir": "relative/out", "prompt": "1girl"},
                },
            },
        )
        assert response.json()["result"]["isError"] is True
        assert app.state.services.database.list_jobs(10) == []
