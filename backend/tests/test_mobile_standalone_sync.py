from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from fastapi.testclient import TestClient


def test_mobile_snapshot_and_image_upload_are_profile_scoped_and_idempotent(
    app, authorize_remote, icon_bytes: bytes
) -> None:
    services = app.state.services
    preset = services.database.create_preset(
        {
            "name": "동기화 인물",
            "tag_name": "sync-character",
            "subject_type": "girl",
            "prompt": "adult woman",
            "negative_prompt": "child",
            "sort_order": 0,
        }
    )
    server_id = services.database.get_or_create_server_id()

    with TestClient(app, client=("192.168.1.89", 43001)) as mobile:
        authorize_remote(mobile, display_name="Standalone Phone")
        snapshot = mobile.get("/api/mobile/standalone-snapshot")
        assert snapshot.status_code == 200
        payload = snapshot.json()
        assert payload["server_id"] == server_id
        assert payload["presets"][0]["prompt"] == "adult woman"
        assert "has_token" not in payload
        assert not any(key.startswith("story_") for key in payload)

        mobile_id = f"android-{uuid.uuid4()}"
        metadata = {
            "mobile_image_id": mobile_id,
            "mode": "txt2img",
            "model": "nai-diffusion-5-full",
            "quality_prompt": "best quality",
            "description_prompt": "rainy city",
            "quality_negative_prompt": "lowres",
            "description_negative_prompt": "daylight",
            "settings": {
                "width": 1024,
                "height": 1024,
                "steps": 28,
                "nsfw_enabled": True,
            },
            "character_snapshot": [
                {
                    "preset_id": preset["id"],
                    "name": preset["name"],
                    "tag_id": preset["tag_id"],
                    "tag_name": preset["tag_name"],
                    "subject_type": "girl",
                    "prompt": "adult woman",
                    "negative_prompt": "child",
                }
            ],
            "tags": [{"id": preset["tag_id"], "name": preset["tag_name"]}],
            "seed": 123,
            "favorite": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "api_profile_id": "mobile-profile-1",
            "origin_server_id": server_id,
        }
        first = mobile.post(
            "/api/mobile-sync/images",
            data={"metadata": json.dumps(metadata)},
            files={"file": (f"{mobile_id}.png", icon_bytes, "image/png")},
        )
        assert first.status_code == 201
        assert first.json()["duplicate"] is False
        assert first.json()["image"]["favorite_at"] is not None
        assert first.json()["image"]["settings"]["api_profile_id"] == "mobile-profile-1"
        sync_job = services.database.list_jobs(1)[0]
        assert sync_job["status"] == "succeeded"
        assert services.database.active_job_count() == 0

        duplicate = mobile.post(
            "/api/mobile-sync/images",
            data={"metadata": json.dumps(metadata)},
            files={"file": (f"{mobile_id}.png", icon_bytes, "image/png")},
        )
        assert duplicate.status_code == 201
        assert duplicate.json()["duplicate"] is True
        assert services.database.list_images(None, [], 1)["total"] == 1

        metadata["mobile_image_id"] = f"android-{uuid.uuid4()}"
        metadata["origin_server_id"] = str(uuid.uuid4())
        wrong_pc = mobile.post(
            "/api/mobile-sync/images",
            data={"metadata": json.dumps(metadata)},
            files={"file": ("wrong.png", icon_bytes, "image/png")},
        )
        assert wrong_pc.status_code == 409
