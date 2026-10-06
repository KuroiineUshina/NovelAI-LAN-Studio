from __future__ import annotations

import httpx
import respx
from fastapi.testclient import TestClient


def preset_payload(name: str = "아리아", tag: str = "aria") -> dict:
    return {
        "name": name,
        "tag_name": tag,
        "subject_type": "girl",
        "prompt": "girl, silver hair, blue eyes",
        "negative_prompt": "red hair",
        "sort_order": 0,
    }


def test_status_and_preset_crud(client: TestClient):
    status = client.get("/api/status")
    assert status.status_code == 200
    assert status.json()["admin_available"] is True
    assert len(status.json()["models"]) == 4

    created = client.post("/api/presets", json=preset_payload())
    assert created.status_code == 201
    preset_id = created.json()["id"]
    assert created.json()["tag_name"] == "aria"

    updated_payload = preset_payload("아리아 수정", "aria-main")
    updated = client.put(f"/api/presets/{preset_id}", json=updated_payload)
    assert updated.status_code == 200
    assert updated.json()["name"] == "아리아 수정"

    listing = client.get("/api/presets").json()["items"]
    assert [item["id"] for item in listing] == [preset_id]

    deleted = client.delete(f"/api/presets/{preset_id}")
    assert deleted.status_code == 204
    assert client.get("/api/presets").json()["items"] == []


def test_quality_prompt_preset_crud(client: TestClient):
    payload = {
        "name": "애니 고품질",
        "prompt": "masterpiece, best quality, amazing quality",
        "sort_order": 10,
    }
    created = client.post("/api/quality-presets", json=payload)
    assert created.status_code == 201
    preset_id = created.json()["id"]
    assert created.json()["prompt"] == payload["prompt"]

    duplicate = client.post("/api/quality-presets", json=payload)
    assert duplicate.status_code == 409

    updated = client.put(
        f"/api/quality-presets/{preset_id}",
        json={**payload, "prompt": "masterpiece, absurdres"},
    )
    assert updated.status_code == 200
    assert updated.json()["prompt"] == "masterpiece, absurdres"
    assert [item["id"] for item in client.get("/api/quality-presets").json()["items"]] == [preset_id]
    assert client.delete(f"/api/quality-presets/{preset_id}").status_code == 204
    assert client.get("/api/quality-presets").json()["items"] == []


def test_anlas_status_without_token_is_safe(client: TestClient):
    response = client.get("/api/anlas")
    assert response.status_code == 200
    assert response.json()["available"] is False
    assert response.json()["remaining_anlas"] is None


@respx.mock
def test_anlas_status_is_cached_and_never_returns_token(client: TestClient):
    client.app.state.services.credentials.token = "pst-secret-test-token"
    route = respx.get("https://image.novelai.net/user/subscription").mock(
        return_value=httpx.Response(
            200,
            json={
                "active": True,
                "tier": 3,
                "expiresAt": 1_800_000_000,
                "trainingStepsLeft": {
                    "fixedTrainingStepsLeft": 900,
                    "purchasedTrainingSteps": 100,
                },
                "usage": {"percent": 80, "isNegative": False, "timeUntilNextPercent": 60},
            },
        )
    )
    first = client.get("/api/anlas")
    second = client.get("/api/anlas")
    assert first.status_code == 200
    assert first.json()["remaining_anlas"] == 1_000
    assert first.json()["subscription_anlas"] == 900
    assert first.json()["paid_anlas"] == 100
    assert "pst-secret-test-token" not in first.text
    assert second.json() == first.json()
    assert route.call_count == 1


def test_generation_draft_persists(client: TestClient):
    initial = client.get("/api/generation-draft").json()
    assert initial["schema_version"] == 4
    assert initial["quality_prompt"] == ""
    assert initial["description_prompt"] == ""
    assert initial["quality_preset_id"] is None
    assert initial["quality_negative_prompt"] == ""
    assert initial["description_negative_prompt"] == ""
    assert initial["nsfw_enabled"] is False
    assert initial["character_preset_ids"] == []
    assert initial["model"] == "nai-diffusion-5-full"
    draft = {
        "schema_version": 4,
        "quality_prompt": "masterpiece, best quality",
        "description_prompt": "night city",
        "quality_preset_id": None,
        "quality_negative_prompt": "blurry, low quality",
        "description_negative_prompt": "empty street",
        "nsfw_enabled": False,
        "character_preset_ids": ["preset-a", "preset-b"],
        "model": "nai-diffusion-5-curated",
        "parameters": {
            "width": 832,
            "height": 1216,
            "steps": 23,
            "guidance": 7,
            "guidance_rescale": 0.35,
            "sampler": "k_euler_ancestral",
            "noise_schedule": "polyexponential",
            "quality": True,
            "count": 1,
            "seed": 123,
            "strength": 0.7,
            "noise": 0.2,
        },
    }
    saved = client.put("/api/generation-draft", json=draft)
    assert saved.status_code == 200
    assert saved.json() == draft
    assert client.get("/api/generation-draft").json() == draft


def test_generation_draft_sync_tracks_cross_device_revisions(client: TestClient):
    initial = client.get("/api/generation-draft/sync")
    assert initial.status_code == 200
    first_revision = initial.json()["revision"]
    draft = initial.json()["draft"]
    draft["quality_prompt"] = "PC에서 입력한 품질 프롬프트"
    draft["description_prompt"] = "PC에서 입력한 묘사 프롬프트"

    pc_save = client.put(
        "/api/generation-draft/sync",
        json={"client_id": "pc-client-1234", "draft": draft},
    )
    assert pc_save.status_code == 200
    assert pc_save.json()["revision"] == first_revision + 1
    assert pc_save.json()["source_client_id"] == "pc-client-1234"

    mobile_read = client.get("/api/generation-draft/sync").json()
    assert mobile_read["revision"] == pc_save.json()["revision"]
    assert mobile_read["draft"]["quality_prompt"] == "PC에서 입력한 품질 프롬프트"
    assert mobile_read["draft"]["description_prompt"] == "PC에서 입력한 묘사 프롬프트"

    mobile_read["draft"]["description_negative_prompt"] = "모바일에서 입력한 묘사 네거티브"
    mobile_save = client.post(
        "/api/generation-draft/sync",
        json={"client_id": "mobile-client-1234", "draft": mobile_read["draft"]},
    )
    assert mobile_save.status_code == 200
    assert mobile_save.json()["revision"] == pc_save.json()["revision"] + 1
    saved_draft = client.get("/api/generation-draft").json()
    assert saved_draft["description_negative_prompt"] == "모바일에서 입력한 묘사 네거티브"
    assert saved_draft["quality_negative_prompt"] == ""


def test_generation_draft_migrates_from_latest_job(client: TestClient):
    services = client.app.state.services
    services.database.create_job(
        {
            "mode": "txt2img",
            "quality_prompt": "last quality prompt",
            "description_prompt": "last submitted prompt",
            "negative_prompt": "last submitted negative",
            "character_preset_ids": ["last-preset"],
            "model": "nai-diffusion-4-5-full",
            "parameters": {"width": 832, "height": 1216, "guidance_rescale": 0.42},
            "character_snapshot": [],
        },
        "MIG123",
    )
    migrated = client.get("/api/generation-draft").json()
    assert migrated["quality_prompt"] == "last quality prompt"
    assert migrated["description_prompt"] == "last submitted prompt"
    assert migrated["quality_negative_prompt"] == "last submitted negative"
    assert migrated["description_negative_prompt"] == ""
    assert migrated["character_preset_ids"] == ["last-preset"]
    assert migrated["model"] == "nai-diffusion-4-5-full"
    assert migrated["parameters"]["width"] == 832
    assert migrated["parameters"]["height"] == 1216
    assert migrated["parameters"]["guidance_rescale"] == 0.42


def test_old_prompt_only_draft_keeps_text_and_migrates_selection(client: TestClient):
    services = client.app.state.services
    services.database.create_job(
        {
            "mode": "txt2img",
            "prompt": "job prompt",
            "negative_prompt": "job negative",
            "character_preset_ids": ["selected-preset"],
            "model": "nai-diffusion-5-curated",
            "parameters": {"width": 832, "height": 1216},
            "character_snapshot": [],
        },
        "OLD123",
    )
    services.database.set_app_setting(
        "generation_draft",
        '{"prompt":"saved prompt","negative_prompt":"saved negative"}',
    )
    migrated = client.get("/api/generation-draft").json()
    assert migrated["schema_version"] == 4
    assert migrated["quality_prompt"] == ""
    assert migrated["description_prompt"] == "saved prompt"
    assert migrated["quality_negative_prompt"] == "saved negative"
    assert migrated["description_negative_prompt"] == ""
    assert migrated["character_preset_ids"] == ["selected-preset"]
    assert migrated["model"] == "nai-diffusion-5-curated"


def test_migration_recovers_latest_nonempty_selection(client: TestClient):
    services = client.app.state.services
    services.database.create_job(
        {
            "mode": "txt2img",
            "prompt": "selected job",
            "negative_prompt": "",
            "character_preset_ids": ["wanted-preset"],
            "model": "nai-diffusion-5-full",
            "parameters": {},
            "character_snapshot": [],
        },
        "SEL123",
    )
    services.database.create_job(
        {
            "mode": "txt2img",
            "prompt": "latest job after accidental clear",
            "negative_prompt": "",
            "character_preset_ids": [],
            "model": "nai-diffusion-5-full",
            "parameters": {},
            "character_snapshot": [],
        },
        "CLR123",
    )
    services.database.set_app_setting(
        "generation_draft",
        '{"prompt":"kept text","negative_prompt":"","character_preset_ids":[],"model":"nai-diffusion-5-full","parameters":{}}',
    )
    migrated = client.get("/api/generation-draft").json()
    assert migrated["schema_version"] == 4
    assert migrated["description_prompt"] == "kept text"
    assert migrated["character_preset_ids"] == ["wanted-preset"]


def test_upload_validation_and_listing(client: TestClient, icon_bytes: bytes):
    response = client.post(
        "/api/uploads",
        files={"file": ("source.png", icon_bytes, "image/png")},
    )
    assert response.status_code == 201
    upload = response.json()
    assert upload["kind"] == "upload"
    assert upload["content_url"].endswith("/content")

    content = client.get(upload["content_url"])
    assert content.status_code == 200
    assert content.content == icon_bytes

    listing = client.get("/api/uploads").json()["items"]
    assert len(listing) == 1
    assert client.delete(f"/api/uploads/{upload['id']}").status_code == 204


def test_inpaint_mask_must_match_source_dimensions(client: TestClient, icon_bytes: bytes):
    upload = client.post(
        "/api/uploads",
        files={"file": ("source.png", icon_bytes, "image/png")},
    ).json()
    matching = client.post(
        "/api/masks",
        data={"source_asset_id": upload["id"]},
        files={"file": ("mask.png", icon_bytes, "image/png")},
    )
    assert matching.status_code == 201
    assert matching.json()["source_asset_id"] == upload["id"]


def test_job_request_expands_character_snapshot(client: TestClient):
    services = client.app.state.services
    services.credentials.token = "pst-test-token"
    preset = client.post("/api/presets", json=preset_payload()).json()
    request = {
        "mode": "txt2img",
        "model": "nai-diffusion-5-full",
        "quality_prompt": "masterpiece, best quality",
        "description_prompt": "night city",
        "quality_negative_prompt": "blurry",
        "description_negative_prompt": "empty street",
        "character_preset_ids": [preset["id"]],
        "source_asset_id": None,
        "mask_asset_id": None,
        "parameters": {
            "width": 1024,
            "height": 1024,
            "steps": 28,
            "guidance": 5,
            "guidance_rescale": 0.25,
            "sampler": "k_euler_ancestral",
            "quality": True,
            "count": 1,
            "seed": None,
            "strength": 0.7,
            "noise": 0.2,
        },
    }
    response = client.post("/api/jobs", json=request)
    assert response.status_code == 202
    snapshot = response.json()["request"]["character_snapshot"]
    assert snapshot[0]["tag_name"] == "aria"
    assert snapshot[0]["prompt"] == preset_payload()["prompt"]
    assert isinstance(response.json()["request"]["parameters"]["seed"], int)
    assert response.json()["request"]["quality_prompt"] == "masterpiece, best quality"
    assert response.json()["request"]["description_prompt"] == "night city"
    assert response.json()["request"]["quality_negative_prompt"] == "blurry"
    assert response.json()["request"]["description_negative_prompt"] == "empty street"
    assert response.json()["request"]["parameters"]["guidance_rescale"] == 0.25


def test_generation_validation(client: TestClient):
    body = {
        "mode": "inpaint",
        "model": "nai-diffusion-5-full",
        "description_prompt": "change coat",
        "parameters": {},
    }
    response = client.post("/api/jobs", json=body)
    assert response.status_code == 422

    too_many = []
    for index in range(7):
        too_many.append(client.post("/api/presets", json=preset_payload(f"인물 {index}", f"tag-{index}")).json()["id"])
    body = {
        "mode": "txt2img",
        "model": "nai-diffusion-4-5-full",
        "description_prompt": "group",
        "character_preset_ids": too_many,
        "parameters": {},
    }
    assert client.post("/api/jobs", json=body).status_code == 422

    invalid_rescale = {
        "mode": "txt2img",
        "model": "nai-diffusion-5-full",
        "description_prompt": "group",
        "parameters": {"guidance_rescale": 1.01},
    }
    assert client.post("/api/jobs", json=invalid_rescale).status_code == 422


def test_admin_settings_are_unavailable_to_remote_devices(app, authorize_remote):
    with TestClient(app, client=("192.168.1.20", 40000)) as remote:
        assert remote.get("/api/status").status_code == 200
        assert remote.get("/api/status").json()["admin_available"] is False
        assert remote.get("/api/admin/settings").status_code == 401
        assert remote.put("/api/admin/settings/autostart", json={"enabled": True}).status_code == 401
        assert remote.put("/api/admin/settings/image-storage", json={"directory": "C:\\Images"}).status_code == 401
        assert remote.get("/api/admin/claude/status").status_code == 401
        assert remote.post("/api/admin/claude/skill").status_code == 401
        authorize_remote(remote)
        assert remote.get("/api/admin/settings").status_code == 403
        assert remote.put("/api/admin/settings/autostart", json={"enabled": True}).status_code == 403
        assert remote.put("/api/admin/settings/image-storage", json={"directory": "C:\\Images"}).status_code == 403
        assert remote.get("/api/admin/claude/status").status_code == 403
        assert remote.post("/api/admin/claude/skill").status_code == 403
        assert remote.get("/api/presets").status_code == 200
        assert remote.get("/api/quality-presets").status_code == 200


def test_public_remote_is_rejected(app):
    with TestClient(app, client=("8.8.8.8", 40000)) as remote:
        response = remote.get("/api/status")
        assert response.status_code == 403


def test_built_ui_index_is_revalidated_and_hashed_assets_are_cached(client):
    import pytest

    index = client.get("/")
    if index.status_code != 200 or "text/html" not in index.headers.get("content-type", ""):
        pytest.skip("frontend/dist is not built")
    assert index.headers["cache-control"] == "no-cache"
    asset = next(
        part.split('"')[0]
        for part in index.text.split('src="/')[1:] + index.text.split('href="/')[1:]
        if part.startswith("assets/")
    )
    response = client.get(f"/{asset}")
    assert response.status_code == 200
    assert "immutable" in response.headers["cache-control"]


def test_quality_presets_store_an_optional_negative(client):
    created = client.post(
        "/api/quality-presets",
        json={"name": "with negative", "prompt": "very aesthetic", "negative_prompt": " lowres, blurry ", "sort_order": 0},
    )
    assert created.status_code == 201
    assert created.json()["negative_prompt"] == "lowres, blurry"

    legacy = client.post("/api/quality-presets", json={"name": "positive only", "prompt": "masterpiece"})
    assert legacy.status_code == 201
    assert legacy.json()["negative_prompt"] == ""

    updated = client.put(
        f"/api/quality-presets/{legacy.json()['id']}",
        json={"name": "positive only", "prompt": "masterpiece", "negative_prompt": "bad hands", "sort_order": 0},
    )
    assert updated.json()["negative_prompt"] == "bad hands"
    names = {item["name"]: item["negative_prompt"] for item in client.get("/api/quality-presets").json()["items"]}
    assert names == {"with negative": "lowres, blurry", "positive only": "bad hands"}


def test_quality_preset_negative_column_is_added_to_existing_databases(tmp_path):
    import sqlite3

    from backend.app.database import Database

    path = tmp_path / "legacy.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE quality_prompt_presets (id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE,"
        " prompt TEXT NOT NULL, sort_order INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    connection.execute(
        "INSERT INTO quality_prompt_presets VALUES ('p1','old','masterpiece',0,'2026-01-01','2026-01-01')"
    )
    connection.commit()
    connection.close()

    database = Database(path)
    database.initialize()
    preset = database.get_quality_prompt_preset("p1")
    assert preset["prompt"] == "masterpiece"
    assert preset["negative_prompt"] == ""
