from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.tests.test_storage_directory import _create_image


def test_unavailable_storage_never_switches_root_or_cleans_records(client, tmp_path, icon_bytes):
    state = client.app.state.services
    image = _create_image(client, icon_bytes)
    target = tmp_path / "external"
    state.change_image_storage_directory(str(target))
    disconnected = tmp_path / "disconnected"
    target.rename(disconnected)
    restarted = create_app(data_dir=state.paths.root, start_workers=False)
    recovered = restarted.state.services
    assert recovered.storage.root == target
    assert recovered.image_storage_settings()["storage_warning"]
    assert recovered.jobs.cleanup_once() == {"images": 0, "uploads": 0, "masks": 0}
    assert recovered.database.get_image(image["id"])
    with TestClient(restarted) as browser:
        assert browser.post("/api/uploads", files={"file": ("icon.png", icon_bytes, "image/png")}).status_code == 503
    assert not target.exists()
    disconnected.rename(target)
    assert recovered.storage.read(image["file_path"]) == icon_bytes
    assert recovered.image_storage_settings()["storage_warning"] is None


def test_migration_blocks_uploads_until_root_switch(client, tmp_path, icon_bytes, monkeypatch):
    state = client.app.state.services
    ready, release = threading.Event(), threading.Event()
    prepare = state.storage.prepare_migration
    def paused(directory):
        migration = prepare(directory)
        ready.set()
        assert release.wait(10)
        return migration
    monkeypatch.setattr(state.storage, "prepare_migration", paused)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(state.change_image_storage_directory, str(tmp_path / "new-storage"))
        try:
            assert ready.wait(10)
            assert client.post("/api/uploads", files={"file": ("icon.png", icon_bytes, "image/png")}).status_code == 409
        finally:
            release.set()
        future.result(timeout=10)
    response = client.post("/api/uploads", files={"file": ("icon.png", icon_bytes, "image/png")})
    assert response.status_code == 201
    saved = state.database.get_upload(response.json()["id"])
    assert state.storage.read(saved["file_path"]) == icon_bytes


def test_migration_rejected_while_mutation_or_cleanup_is_active(client, tmp_path):
    state = client.app.state.services
    with state.storage_gate.activity():
        response = client.put("/api/admin/settings/image-storage", json={"directory": str(tmp_path / "blocked")})
        assert response.status_code == 409
    assert not (tmp_path / "blocked").exists()
