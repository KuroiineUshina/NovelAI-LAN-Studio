import json
from pathlib import Path

from backend.app import __version__


def test_release_version_matches_backend_and_frontend():
    root = Path(__file__).resolve().parents[2]
    version = (root / "VERSION").read_text().strip()
    assert __version__ == version
    assert json.loads((root / "frontend/package.json").read_text())["version"] == version
    lock = json.loads((root / "frontend/package-lock.json").read_text())
    assert lock["version"] == lock["packages"][""]["version"] == version
