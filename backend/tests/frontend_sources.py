from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def all_frontend_css() -> str:
    """Return every stylesheet under frontend/src, foundation first."""
    source = PROJECT_ROOT / "frontend" / "src"
    foundation = source / "styles.css"
    others = sorted(path for path in source.rglob("*.css") if path != foundation)
    return "\n".join(path.read_text(encoding="utf-8") for path in [foundation, *others])
