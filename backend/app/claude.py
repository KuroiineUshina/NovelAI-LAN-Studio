from __future__ import annotations

import json
import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit


logger = logging.getLogger(__name__)

CLAUDE_SKILL_NAME = "novelai-v5-scene-prompter"
CLAUDE_MCP_SERVER_NAME = "novelaiLANStudio"
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]"}


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def claude_home() -> Path:
    override = os.getenv("NOVELAI_STUDIO_CLAUDE_HOME")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".claude"


def claude_config_path() -> Path:
    override = os.getenv("NOVELAI_STUDIO_CLAUDE_CONFIG")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".claude.json"


def mcp_url(port: int) -> str:
    return f"http://127.0.0.1:{port}/mcp/"


def _points_to_studio(server: Any, port: int) -> bool:
    if not isinstance(server, dict):
        return False
    url = server.get("url")
    if not isinstance(url, str):
        return False
    try:
        parts = urlsplit(url)
        server_port = parts.port
    except ValueError:
        return False
    return (
        parts.scheme == "http"
        and (parts.hostname or "") in LOOPBACK_HOSTS
        and server_port == port
        and parts.path.rstrip("/") == "/mcp"
    )


def find_registered_mcp_server(config_path: Path, port: int) -> str | None:
    """Return the Claude Code MCP server name that targets this Studio, if any."""
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        logger.warning("Could not read the Claude Code configuration file.")
        return None
    if not isinstance(raw, dict):
        return None
    scopes: list[Any] = [raw.get("mcpServers")]
    projects = raw.get("projects")
    if isinstance(projects, dict):
        scopes.extend(
            project.get("mcpServers")
            for project in projects.values()
            if isinstance(project, dict)
        )
    for servers in scopes:
        if not isinstance(servers, dict):
            continue
        for name, server in servers.items():
            if _points_to_studio(server, port):
                return str(name)
    return None


class ClaudeIntegration:
    """Reports whether Claude Code can reach this Studio through MCP and the bundled skill."""

    def __init__(self, skill_root: Path, port_provider: Callable[[], int]):
        self.skill_root = skill_root.resolve()
        self.port_provider = port_provider
        self._last_mcp_activity_at: str | None = None

    @property
    def bundled_skill(self) -> Path:
        return self.skill_root / CLAUDE_SKILL_NAME

    @property
    def installed_skill(self) -> Path:
        return claude_home() / "skills" / CLAUDE_SKILL_NAME

    def record_mcp_activity(self) -> None:
        self._last_mcp_activity_at = _iso_now()

    def _skill_up_to_date(self) -> bool:
        source = self.bundled_skill
        destination = self.installed_skill
        for file in source.rglob("*"):
            if not file.is_file():
                continue
            target = destination / file.relative_to(source)
            try:
                if not target.is_file() or target.read_bytes() != file.read_bytes():
                    return False
            except OSError:
                return False
        return True

    def status(self) -> dict[str, Any]:
        port = self.port_provider()
        url = mcp_url(port)
        server_name = find_registered_mcp_server(claude_config_path(), port)
        skill_installed = (self.installed_skill / "SKILL.md").is_file()
        skill_up_to_date = skill_installed and self._skill_up_to_date()

        if not server_name:
            state = "mcp_missing"
            message = "Claude Code에 MCP를 등록해야 해요."
        elif not skill_installed:
            state = "skill_missing"
            message = "프롬프트 스킬을 설치해야 해요."
        elif not skill_up_to_date:
            state = "skill_outdated"
            message = "새 버전의 프롬프트 스킬이 있어요."
        else:
            state = "ready"
            message = "Claude에서 바로 쓸 수 있어요."

        return {
            "state": state,
            "message": message,
            "mcp_url": url,
            "mcp_registered": server_name is not None,
            "mcp_server_name": server_name,
            "register_command": (
                f"claude mcp add --transport http --scope user {CLAUDE_MCP_SERVER_NAME} {url}"
            ),
            "skill_name": CLAUDE_SKILL_NAME,
            "skill_installed": skill_installed,
            "skill_up_to_date": skill_up_to_date,
            "last_mcp_activity_at": self._last_mcp_activity_at,
            "last_checked_at": _iso_now(),
        }

    def install_skill(self) -> dict[str, Any]:
        source = self.bundled_skill
        if not (source / "SKILL.md").is_file():
            raise FileNotFoundError("앱에 포함된 프롬프트 스킬을 찾지 못했어요.")
        destination = self.installed_skill
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, destination, dirs_exist_ok=True)
        return self.status()


class McpActivityASGI:
    """Record the time of each MCP HTTP request without inspecting its contents."""

    def __init__(self, app, on_request: Callable[[], None]):
        self.app = app
        self.on_request = on_request

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http" and scope.get("method") == "POST":
            self.on_request()
        await self.app(scope, receive, send)
