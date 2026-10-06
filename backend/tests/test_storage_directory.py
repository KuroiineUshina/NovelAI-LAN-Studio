from __future__ import annotations

import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.database import iso, utc_now
from backend.app.main import create_app


def _create_image(client: TestClient, icon_bytes: bytes) -> dict:
    services = client.app.state.services
    job = services.database.create_job(
        {
            "mode": "txt2img",
            "model": "nai-diffusion-5-full",
            "parameters": {},
            "character_snapshot": [],
        },
        "STORE1",
    )
    services.database.finish_job(job["id"], "succeeded")
    image_id = str(uuid.uuid4())
    saved = services.storage.save_generated(icon_bytes, image_id)
    created = utc_now()
    return services.database.create_image(
        {
            "id": image_id,
            "job_id": job["id"],
            "parent_image_id": None,
            **saved,
            "mode": "txt2img",
            "model": "nai-diffusion-5-full",
            "prompt": "test",
            "quality_prompt": "",
            "description_prompt": "test",
            "quality_negative_prompt": "",
            "description_negative_prompt": "",
            "negative_prompt": "",
            "settings": {},
            "character_snapshot": [],
            "seed": 1,
            "created_at": iso(created),
            "expires_at": iso(created),
        },
        [],
    )


def test_image_storage_directory_moves_files_and_survives_restart(
    client: TestClient, icon_bytes: bytes, tmp_path: Path
) -> None:
    services = client.app.state.services
    image = _create_image(client, icon_bytes)
    original_root = services.storage.root
    original_relative = image["file_path"]
    target = tmp_path / "chosen-image-storage"

    response = client.put(
        "/api/admin/settings/image-storage", json={"directory": str(target)}
    )

    assert response.status_code == 200
    assert response.json()["moved"] is True
    assert Path(response.json()["image_storage_directory"]) == target.resolve()
    assert services.storage.root == target.resolve()
    assert services.jobs.storage is services.storage
    assert services.database.get_image(image["id"])["file_path"] == original_relative
    assert services.storage.read(original_relative) == icon_bytes
    assert services.storage.read(image["thumbnail_path"])
    assert not (original_root / "temporary" / Path(original_relative).name).exists()

    restarted = create_app(data_dir=services.paths.root, start_workers=False)
    assert restarted.state.services.storage.root == target.resolve()
    assert restarted.state.services.storage.read(original_relative) == icon_bytes


def test_image_storage_directory_rejects_nonempty_target(
    client: TestClient, icon_bytes: bytes, tmp_path: Path
) -> None:
    services = client.app.state.services
    image = _create_image(client, icon_bytes)
    original_root = services.storage.root
    target = tmp_path / "not-empty"
    target.mkdir()
    unrelated = target / "keep.txt"
    unrelated.write_text("do not overwrite", encoding="utf-8")

    response = client.put(
        "/api/admin/settings/image-storage", json={"directory": str(target)}
    )

    assert response.status_code == 400
    assert services.storage.root == original_root
    assert unrelated.read_text(encoding="utf-8") == "do not overwrite"
    assert services.storage.read(image["file_path"]) == icon_bytes


def test_image_storage_directory_rejects_change_while_job_is_active(
    client: TestClient, tmp_path: Path
) -> None:
    services = client.app.state.services
    services.database.create_job(
        {
            "mode": "txt2img",
            "model": "nai-diffusion-5-full",
            "parameters": {},
            "character_snapshot": [],
        },
        "ACTIVE",
    )

    response = client.put(
        "/api/admin/settings/image-storage",
        json={"directory": str(tmp_path / "blocked")},
    )

    assert response.status_code == 409
    assert not (tmp_path / "blocked").exists()


def test_admin_settings_exposes_current_and_default_image_storage(
    client: TestClient,
) -> None:
    response = client.get("/api/admin/settings")

    assert response.status_code == 200
    assert response.json()["image_storage_directory"]
    assert response.json()["default_image_storage_directory"]
    assert "storage_warning" in response.json()
