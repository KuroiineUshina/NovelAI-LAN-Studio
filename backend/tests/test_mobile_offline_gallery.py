from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient

from backend.app.database import iso, utc_now


def create_cached_image(client: TestClient, icon_bytes: bytes) -> tuple[dict, dict]:
    services = client.app.state.services
    preset = services.database.create_preset(
        {
            "name": "하린",
            "tag_name": "harin",
            "subject_type": "girl",
            "prompt": "sensitive permanent character prompt",
            "negative_prompt": "sensitive negative prompt",
            "sort_order": 0,
        }
    )
    job = services.database.create_job(
        {"mode": "txt2img", "parameters": {}, "character_snapshot": []},
        "OFFLINE1",
    )
    image_id = f"offline-{job['id']}"
    saved = services.storage.save_generated(icon_bytes, image_id)
    created = utc_now()
    image = services.database.create_image(
        {
            "id": image_id,
            "job_id": job["id"],
            "parent_image_id": None,
            **saved,
            "mode": "txt2img",
            "model": "nai-diffusion-5-full",
            "prompt": "secret combined prompt",
            "quality_prompt": "secret quality prompt",
            "description_prompt": "secret scene prompt",
            "quality_negative_prompt": "secret quality negative",
            "description_negative_prompt": "secret scene negative",
            "negative_prompt": "secret combined negative",
            "settings": {"width": 1024, "height": 1024, "seed": 99},
            "character_snapshot": [
                {"name": "하린", "prompt": "secret character snapshot"}
            ],
            "seed": 99,
            "created_at": iso(created),
            "expires_at": iso(created + timedelta(hours=168)),
        },
        [preset["tag_id"]],
    )
    return image, preset


def test_mobile_offline_gallery_returns_only_cache_safe_metadata(
    client: TestClient, icon_bytes: bytes
):
    image, preset = create_cached_image(client, icon_bytes)

    response = client.get("/api/mobile/offline-gallery?favorite=false&page=1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["page"] == 1
    item = payload["items"][0]
    assert set(item) == {
        "id",
        "mime_type",
        "width",
        "height",
        "created_at",
        "favorite",
        "tags",
        "content_url",
    }
    assert item["id"] == image["id"]
    assert item["favorite"] is False
    assert item["tags"] == [{"id": preset["tag_id"], "name": "harin"}]
    assert item["content_url"] == f"/api/assets/{image['id']}/content"
    serialized = response.text.lower()
    for forbidden in (
        "prompt",
        "negative",
        "seed",
        "settings",
        "character_snapshot",
        "model",
        "expires_at",
    ):
        assert forbidden not in serialized


def test_mobile_offline_gallery_separates_temporary_and_favorites(
    client: TestClient, icon_bytes: bytes
):
    image, _ = create_cached_image(client, icon_bytes)
    assert client.patch(
        f"/api/images/{image['id']}/favorite", json={"favorite": True}
    ).status_code == 200

    temporary = client.get(
        "/api/mobile/offline-gallery?favorite=false&page=1"
    ).json()
    favorites = client.get(
        "/api/mobile/offline-gallery?favorite=true&page=1"
    ).json()

    assert temporary["items"] == []
    assert favorites["total"] == 1
    assert favorites["items"][0]["id"] == image["id"]
    assert favorites["items"][0]["favorite"] is True
    assert client.get(favorites["items"][0]["content_url"]).content == icon_bytes
