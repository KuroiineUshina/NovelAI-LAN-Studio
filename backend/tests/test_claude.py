from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.claude import (
    CLAUDE_SKILL_NAME,
    ClaudeIntegration,
    find_registered_mcp_server,
)


def bundled_skill(root: Path, body: str = "skill v1") -> Path:
    skill = root / CLAUDE_SKILL_NAME
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(
        f"---\nname: {CLAUDE_SKILL_NAME}\ndescription: test\n---\n{body}\n",
        encoding="utf-8",
    )
    return root


def write_claude_config(servers: dict, projects: dict | None = None) -> None:
    payload: dict = {"mcpServers": servers}
    if projects is not None:
        payload["projects"] = projects
    Path(os.environ["NOVELAI_STUDIO_CLAUDE_CONFIG"]).write_text(
        json.dumps(payload), encoding="utf-8"
    )


def test_registered_server_is_found_in_user_or_project_scope(tmp_path: Path):
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "mcpServers": {"other": {"type": "http", "url": "http://127.0.0.1:9999/mcp/"}},
                "projects": {
                    "C:/work": {
                        "mcpServers": {
                            "studio": {"type": "http", "url": "http://localhost:8787/mcp"}
                        }
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    assert find_registered_mcp_server(config, 8787) == "studio"
    assert find_registered_mcp_server(config, 8788) is None
    assert find_registered_mcp_server(tmp_path / "missing.json", 8787) is None


def test_status_walks_from_missing_mcp_to_ready(tmp_path: Path):
    integration = ClaudeIntegration(bundled_skill(tmp_path / "bundled"), lambda: 8787)

    status = integration.status()
    assert status["state"] == "mcp_missing"
    assert status["mcp_url"] == "http://127.0.0.1:8787/mcp/"
    assert "claude mcp add --transport http" in status["register_command"]

    write_claude_config({"novelaiLANStudio": {"type": "http", "url": "http://127.0.0.1:8787/mcp/"}})
    status = integration.status()
    assert status["state"] == "skill_missing"
    assert status["mcp_server_name"] == "novelaiLANStudio"

    installed = integration.install_skill()
    assert installed["state"] == "ready"
    assert installed["skill_up_to_date"] is True

    bundled_skill(tmp_path / "bundled", "skill v2")
    assert integration.status()["state"] == "skill_outdated"
    assert integration.install_skill()["state"] == "ready"


def test_admin_claude_endpoints_and_mcp_activity(tmp_path: Path):
    from backend.app.main import create_app

    app = create_app(data_dir=tmp_path / "data", start_workers=False, start_mcp=True)
    services = app.state.services
    services.claude = ClaudeIntegration(bundled_skill(tmp_path / "bundled"), lambda: 8787)
    write_claude_config({"novelaiLANStudio": {"type": "http", "url": "http://127.0.0.1:8787/mcp/"}})

    with TestClient(app, client=("127.0.0.1", 49200)) as client:
        settings = client.get("/api/admin/settings")
        assert settings.status_code == 200
        assert settings.json()["claude"]["state"] == "skill_missing"

        installed = client.post("/api/admin/claude/skill")
        assert installed.status_code == 200
        assert installed.json()["state"] == "ready"
        assert (
            Path(os.environ["NOVELAI_STUDIO_CLAUDE_HOME"])
            / "skills"
            / CLAUDE_SKILL_NAME
            / "SKILL.md"
        ).is_file()

        assert client.get("/api/admin/claude/status").json()["last_mcp_activity_at"] is None
        client.post(
            "/mcp/",
            headers={
                "accept": "application/json, text/event-stream",
                "content-type": "application/json",
                "host": "127.0.0.1:8787",
                "mcp-protocol-version": "2025-06-18",
            },
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        )
        assert client.get("/api/admin/claude/status").json()["last_mcp_activity_at"]


def test_bundled_skill_ships_with_the_app():
    root = Path(__file__).resolve().parents[2]
    skill = root / "claude-skills" / CLAUDE_SKILL_NAME / "SKILL.md"
    text = skill.read_text(encoding="utf-8")
    assert f"name: {CLAUDE_SKILL_NAME}" in text
    assert "apply_quality_prompts" in text
    assert "codex" not in text.lower()
