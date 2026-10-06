from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.main import create_app


MCP_HEADERS = {
    "accept": "application/json, text/event-stream",
    "content-type": "application/json",
    "host": "127.0.0.1:8787",
    "mcp-protocol-version": "2025-06-18",
}


def mcp_call(
    client: TestClient,
    request_id: int,
    name: str,
    arguments: dict | None = None,
) -> dict:
    response = client.post(
        "/mcp/",
        headers=MCP_HEADERS,
        json={
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}},
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "error" not in payload
    assert payload["result"]["isError"] is False
    return payload["result"]["structuredContent"]


def test_mcp_reads_context_and_applies_description_prompts_and_nsfw(tmp_path: Path):
    app = create_app(
        data_dir=tmp_path / "mcp-data",
        start_workers=False,
        start_mcp=True,
    )
    with TestClient(app, client=("127.0.0.1", 49100)) as client:
        preset = client.post(
            "/api/presets",
            json={
                "name": "규나나",
                "tag_name": "gyunana",
                "subject_type": "girl",
                "prompt": "girl, pink hair, blue eyes, fox ears, shark tail",
                "negative_prompt": "short hair",
                "sort_order": 0,
            },
        ).json()
        draft = client.get("/api/generation-draft").json()
        draft.update(
            {
                "quality_prompt": "masterpiece, best quality",
                "description_prompt": "old scene",
                "quality_negative_prompt": "lowres, bad anatomy",
                "description_negative_prompt": "old scene negative",
                "nsfw_enabled": True,
                "character_preset_ids": [preset["id"]],
                "model": "nai-diffusion-5-full",
            }
        )
        assert client.put("/api/generation-draft", json=draft).status_code == 200

        context = mcp_call(client, 1, "get_prompt_context")
        assert context["model"]["label"] == "V5 Full"
        assert context["current_prompts"]["quality_prompt"] == "masterpiece, best quality"
        assert context["current_prompts"]["quality_negative_prompt"] == "lowres, bad anatomy"
        assert context["current_prompts"]["negative_description"] == "old scene negative"
        assert context["current_prompts"]["nsfw_enabled"] is True
        assert context["subject_counts"]["girl"] == 1
        assert context["active_characters"][0]["name"] == "규나나"
        assert context["active_characters"][0]["position"] == 1
        assert "pink hair" in context["active_characters"][0]["prompt"]
        assert "token" not in str(context).lower()
        assert "webhook" not in str(context).lower()

        applied = mcp_call(
            client,
            2,
            "apply_description_prompts",
            {
                "positive_description": "theme park, Viking ship ride, 안전바를 잡고 비명을 지르는 모습",
                "negative_description": "standing outside the ride, empty seats",
                "base_revision": context["revision"],
                "nsfw_enabled": False,
            },
        )
        assert applied["applied"] is True
        assert applied["nsfw_enabled"] is False

        saved = client.get("/api/generation-draft/sync").json()
        assert saved["source_client_id"] == "claude-mcp"
        assert saved["draft"]["description_prompt"].startswith("theme park")
        assert saved["draft"]["description_negative_prompt"] == "standing outside the ride, empty seats"
        assert saved["draft"]["quality_negative_prompt"] == "lowres, bad anatomy"
        assert saved["draft"]["quality_prompt"] == "masterpiece, best quality"
        assert saved["draft"]["nsfw_enabled"] is False
        assert saved["draft"]["character_preset_ids"] == [preset["id"]]


def test_mcp_applies_quality_prompts_without_touching_description_or_preset(tmp_path: Path):
    app = create_app(
        data_dir=tmp_path / "mcp-quality-data",
        start_workers=False,
        start_mcp=True,
    )
    with TestClient(app, client=("127.0.0.1", 49102)) as client:
        preset = client.post(
            "/api/quality-presets",
            json={"name": "기본 작가 조합", "prompt": "0.8::artist:a::, very aesthetic", "sort_order": 0},
        ).json()
        draft = client.get("/api/generation-draft").json()
        draft.update(
            {
                "quality_prompt": preset["prompt"],
                "quality_preset_id": preset["id"],
                "description_prompt": "park, walking",
                "quality_negative_prompt": "lowres",
                "description_negative_prompt": "full body",
            }
        )
        assert client.put("/api/generation-draft", json=draft).status_code == 200

        context = mcp_call(client, 1, "get_prompt_context")
        assert context["quality_preset"] == {"id": preset["id"], "name": "기본 작가 조합"}

        applied = mcp_call(
            client,
            2,
            "apply_quality_prompts",
            {
                "quality_prompt": "0.8::artist:a::, 0.5::artist:b::, very aesthetic",
                "base_revision": context["revision"],
            },
        )
        assert applied["applied"] is True
        assert applied["quality_negative_prompt"] == "lowres"
        assert applied["quality_preset_name"] == "기본 작가 조합"
        assert applied["differs_from_preset"] is True

        saved = client.get("/api/generation-draft/sync").json()
        assert saved["source_client_id"] == "claude-mcp"
        assert saved["draft"]["quality_prompt"] == "0.8::artist:a::, 0.5::artist:b::, very aesthetic"
        assert saved["draft"]["quality_negative_prompt"] == "lowres"
        assert saved["draft"]["description_prompt"] == "park, walking"
        assert saved["draft"]["description_negative_prompt"] == "full body"
        assert saved["draft"]["quality_preset_id"] == preset["id"]
        assert client.get("/api/quality-presets").json()["items"][0]["prompt"] == preset["prompt"]

        negative_only = mcp_call(
            client,
            3,
            "apply_quality_prompts",
            {"quality_negative_prompt": "lowres, bad hands", "base_revision": applied["revision"]},
        )
        assert negative_only["quality_prompt"] == "0.8::artist:a::, 0.5::artist:b::, very aesthetic"
        assert negative_only["quality_negative_prompt"] == "lowres, bad hands"

        stale = mcp_call(
            client,
            4,
            "apply_quality_prompts",
            {"quality_prompt": "stale", "base_revision": applied["revision"]},
        )
        assert stale["applied"] is False
        assert stale["reason"] == "revision_conflict"


def test_mcp_refuses_to_overwrite_a_newer_shared_draft(tmp_path: Path):
    app = create_app(
        data_dir=tmp_path / "mcp-conflict-data",
        start_workers=False,
        start_mcp=True,
    )
    with TestClient(app, client=("127.0.0.1", 49101)) as client:
        context = mcp_call(client, 1, "get_prompt_context")
        draft = client.get("/api/generation-draft").json()
        draft["description_prompt"] = "모바일에서 더 최신으로 저장한 장면"
        assert client.put("/api/generation-draft", json=draft).status_code == 200

        conflict = mcp_call(
            client,
            2,
            "apply_description_prompts",
            {
                "positive_description": "stale positive",
                "negative_description": "stale negative",
                "base_revision": context["revision"],
            },
        )
        assert conflict["applied"] is False
        assert conflict["reason"] == "revision_conflict"
        assert client.get("/api/generation-draft").json()["description_prompt"] == "모바일에서 더 최신으로 저장한 장면"


def test_mcp_lists_only_prompt_tools(tmp_path: Path):
    app = create_app(
        data_dir=tmp_path / "mcp-tools-data",
        start_workers=False,
        start_mcp=True,
    )
    with TestClient(app, client=("127.0.0.1", 49103)) as client:
        response = client.post(
            "/mcp/",
            headers=MCP_HEADERS,
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        )
        assert response.status_code == 200
        names = {tool["name"] for tool in response.json()["result"]["tools"]}
        assert names == {
            "get_prompt_context",
            "apply_description_prompts",
            "apply_quality_prompts",
        }


def test_mcp_is_blocked_for_lan_clients(tmp_path: Path):
    app = create_app(
        data_dir=tmp_path / "mcp-remote-data",
        start_workers=False,
        start_mcp=True,
    )
    with TestClient(app, client=("192.168.1.90", 49102)) as remote:
        response = remote.post(
            "/mcp/",
            headers=MCP_HEADERS,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
                "params": {},
            },
        )
        assert response.status_code == 403
        assert response.json()["detail"] == "PC에서만 사용할 수 있습니다."
