from __future__ import annotations

import json
import logging
import re
from datetime import timedelta

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from backend.app.database import iso, utc_now
from backend.app.discord_webhook import image_is_nsfw, validate_discord_webhook_url


WEBHOOK_URL = (
    "https://discord.com/api/webhooks/123456789012345678/"
    "abcdefghijklmnopqrstuvwxyzABCDEF1234567890"
)


# Made-up example characters.
EXAMPLE_LOOKS = {
    "harin": "short silver hair, green eyes, round glasses",
    "doyun": "black high ponytail, amber eyes, freckles",
    "sera": "wavy honey blonde hair, violet eyes, beauty mark",
}


def preset_payload(name: str, tag_name: str, order: int = 0) -> dict:
    return {
        "name": name,
        "tag_name": tag_name,
        "subject_type": "girl",
        "prompt": f"1girl, {EXAMPLE_LOOKS.get(tag_name, tag_name)}",
        "negative_prompt": "",
        "sort_order": order,
    }


def create_image(
    client: TestClient,
    icon_bytes: bytes,
    tag_id: str | None,
    *,
    nsfw_enabled: bool = False,
) -> dict:
    services = client.app.state.services
    job = services.database.create_job(
        {"mode": "txt2img", "parameters": {}, "character_snapshot": []},
        "DISCORD1",
    )
    image_id = f"discord-{job['id']}"
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
            "prompt": "masterpiece, night city",
            "quality_prompt": "masterpiece",
            "description_prompt": "night city",
            "negative_prompt": "blurry",
            "settings": {
                "width": 1024,
                "height": 1024,
                "guidance": 5,
                "nsfw_enabled": nsfw_enabled,
            },
            "character_snapshot": [{"name": "하린", "prompt": "1girl"}],
            "seed": 42,
            "created_at": iso(created),
            "expires_at": iso(created + timedelta(hours=168)),
        },
        [tag_id] if tag_id else [],
    )


def multipart_payload(request: httpx.Request) -> tuple[dict, str]:
    body = request.content.decode("utf-8", errors="ignore")
    match = re.search(
        r'name="payload_json"\r\n\r\n(.*?)\r\n--', body, flags=re.DOTALL
    )
    assert match is not None
    return json.loads(match.group(1)), body


def test_character_set_crud_preserves_order_and_validates_members(client: TestClient):
    first = client.post("/api/presets", json=preset_payload("하린", "harin", 0)).json()
    second = client.post("/api/presets", json=preset_payload("도윤", "doyun", 10)).json()
    third = client.post("/api/presets", json=preset_payload("세라", "sera", 20)).json()

    created = client.post(
        "/api/character-sets",
        json={"name": "기본 3인", "preset_ids": [third["id"], first["id"], second["id"]]},
    )
    assert created.status_code == 201
    character_set = created.json()
    assert character_set["preset_ids"] == [third["id"], first["id"], second["id"]]
    assert [member["name"] for member in character_set["members"]] == ["세라", "하린", "도윤"]

    duplicate_name = client.post(
        "/api/character-sets",
        json={"name": "기본 3인", "preset_ids": [first["id"], second["id"]]},
    )
    assert duplicate_name.status_code == 409
    assert client.post(
        "/api/character-sets",
        json={"name": "잘못된 세트", "preset_ids": [first["id"], "missing-preset"]},
    ).status_code == 400
    assert client.post(
        "/api/character-sets",
        json={"name": "중복", "preset_ids": [first["id"], first["id"]]},
    ).status_code == 422

    updated = client.put(
        f"/api/character-sets/{character_set['id']}",
        json={"name": "둘만", "preset_ids": [second["id"], third["id"]]},
    )
    assert updated.status_code == 200
    assert updated.json()["preset_ids"] == [second["id"], third["id"]]
    assert client.delete(f"/api/character-sets/{character_set['id']}").status_code == 204


def test_character_set_is_removed_when_preset_deletion_leaves_one_member(client: TestClient):
    first = client.post("/api/presets", json=preset_payload("A", "set-a")).json()
    second = client.post("/api/presets", json=preset_payload("B", "set-b")).json()
    character_set = client.post(
        "/api/character-sets",
        json={"name": "둘", "preset_ids": [first["id"], second["id"]]},
    ).json()
    assert client.delete(f"/api/presets/{first['id']}").status_code == 204
    assert client.get("/api/character-sets").json()["items"] == []
    assert client.delete(f"/api/character-sets/{character_set['id']}").status_code == 404


def test_discord_webhook_url_validation_blocks_non_discord_destinations():
    assert validate_discord_webhook_url(WEBHOOK_URL) == WEBHOOK_URL
    with pytest.raises(ValueError):
        validate_discord_webhook_url(
            WEBHOOK_URL.replace("discord.com", "example.com")
        )
    with pytest.raises(ValueError):
        validate_discord_webhook_url(f"{WEBHOOK_URL}?redirect=https://example.com")
    with pytest.raises(ValueError):
        validate_discord_webhook_url(WEBHOOK_URL.replace("https://", "http://"))


def test_discord_webhook_crud_never_returns_or_stores_url(client: TestClient):
    created = client.post(
        "/api/admin/webhooks", json={"name": "작업 채널", "url": WEBHOOK_URL}
    )
    assert created.status_code == 201
    webhook = created.json()
    assert webhook["configured"] is True
    assert WEBHOOK_URL not in created.text

    public = client.get("/api/webhooks")
    admin = client.get("/api/admin/webhooks")
    assert public.status_code == 200
    assert public.json()["items"][0]["name"] == "작업 채널"
    assert "url" not in public.json()["items"][0]
    assert "url" not in admin.json()["items"][0]
    assert WEBHOOK_URL not in public.text + admin.text

    with client.app.state.services.database.connect() as connection:
        dump = "\n".join(
            str(tuple(row))
            for row in connection.execute("SELECT * FROM discord_webhooks").fetchall()
        )
    assert WEBHOOK_URL not in dump

    renamed = client.put(
        f"/api/admin/webhooks/{webhook['id']}",
        json={"name": "공유 채널", "url": ""},
    )
    assert renamed.status_code == 200
    assert renamed.json()["configured"] is True
    assert client.delete(f"/api/admin/webhooks/{webhook['id']}").status_code == 204
    assert client.get("/api/webhooks").json()["items"] == []


@respx.mock
def test_discord_send_uses_multipart_safe_mentions_and_optional_metadata(
    client: TestClient, icon_bytes: bytes, caplog: pytest.LogCaptureFixture
):
    caplog.set_level(logging.INFO)
    preset = client.post("/api/presets", json=preset_payload("하린", "harin")).json()
    image = create_image(client, icon_bytes, preset["tag_id"])
    webhook = client.post(
        "/api/admin/webhooks", json={"name": "작업 채널", "url": WEBHOOK_URL}
    ).json()
    route = respx.post(
        url__regex=re.compile(r"^https://discord\.com/api/webhooks/.+")
    ).mock(return_value=httpx.Response(200, json={"id": "message-id"}))

    response = client.post(
        f"/api/images/{image['id']}/discord",
        json={
            "webhook_id": webhook["id"],
            "include_tags": True,
            "include_metadata": True,
        },
    )
    assert response.status_code == 200
    assert response.json()["webhook_name"] == "작업 채널"
    assert route.call_count == 1
    request = route.calls[0].request
    assert request.url.params["wait"] == "true"
    payload, body = multipart_payload(request)
    assert 'name="payload_json"' in body
    assert 'name="files[0]"' in body
    assert 'name="files[1]"' in body
    assert payload["allowed_mentions"]["parse"] == []
    assert payload["content"] == "#harin"
    assert "NovelAI LAN Studio에서 보낸 이미지" not in body
    assert "인물 태그:" not in body
    assert not payload["attachments"][0]["filename"].startswith("SPOILER_")
    assert all("description" not in attachment for attachment in payload["attachments"])
    assert "night city" in body
    assert WEBHOOK_URL not in response.text
    assert WEBHOOK_URL.split("/")[-1] not in caplog.text


@respx.mock
def test_discord_send_marks_nsfw_image_as_spoiler(
    client: TestClient, icon_bytes: bytes
):
    preset = client.post("/api/presets", json=preset_payload("NSFW", "adult")).json()
    image = create_image(
        client, icon_bytes, preset["tag_id"], nsfw_enabled=True
    )
    assert image_is_nsfw(image) is True
    webhook = client.post(
        "/api/admin/webhooks", json={"name": "스포일러 채널", "url": WEBHOOK_URL}
    ).json()
    route = respx.post(
        url__regex=re.compile(r"^https://discord\.com/api/webhooks/.+")
    ).mock(return_value=httpx.Response(200, json={"id": "message-id"}))

    response = client.post(
        f"/api/images/{image['id']}/discord",
        json={"webhook_id": webhook["id"], "include_tags": True},
    )
    assert response.status_code == 200
    payload, body = multipart_payload(route.calls[0].request)
    spoiler_name = f"SPOILER_novelai-{image['id']}.png"
    assert payload["attachments"][0]["filename"] == spoiler_name
    assert f'filename="{spoiler_name}"' in body
    assert payload["content"] == "#adult"


@respx.mock
def test_discord_send_without_tags_has_no_message_content(
    client: TestClient, icon_bytes: bytes
):
    image = create_image(client, icon_bytes, None)
    webhook = client.post(
        "/api/admin/webhooks", json={"name": "이미지만", "url": WEBHOOK_URL}
    ).json()
    route = respx.post(
        url__regex=re.compile(r"^https://discord\.com/api/webhooks/.+")
    ).mock(return_value=httpx.Response(200, json={"id": "message-id"}))

    response = client.post(
        f"/api/images/{image['id']}/discord",
        json={
            "webhook_id": webhook["id"],
            "include_tags": True,
            "include_metadata": False,
        },
    )
    assert response.status_code == 200
    payload, body = multipart_payload(route.calls[0].request)
    assert "content" not in payload
    assert "NovelAI LAN Studio에서 보낸 이미지" not in body
    assert len(payload["attachments"]) == 1


@pytest.mark.parametrize(
    ("discord_status", "expected_status"),
    [(401, 401), (404, 404), (429, 429), (500, 500)],
)
@respx.mock
def test_discord_send_errors_are_not_retried(
    client: TestClient,
    icon_bytes: bytes,
    discord_status: int,
    expected_status: int,
):
    preset = client.post("/api/presets", json=preset_payload("A", "error-a")).json()
    image = create_image(client, icon_bytes, preset["tag_id"])
    webhook = client.post(
        "/api/admin/webhooks", json={"name": "오류 채널", "url": WEBHOOK_URL}
    ).json()
    route = respx.post(
        url__regex=re.compile(r"^https://discord\.com/api/webhooks/.+")
    ).mock(return_value=httpx.Response(discord_status))
    response = client.post(
        f"/api/images/{image['id']}/discord",
        json={"webhook_id": webhook["id"]},
    )
    assert response.status_code == expected_status
    assert route.call_count == 1
    assert WEBHOOK_URL not in response.text


@respx.mock
def test_discord_connection_error_is_not_retried(client: TestClient, icon_bytes: bytes):
    preset = client.post("/api/presets", json=preset_payload("A", "network-a")).json()
    image = create_image(client, icon_bytes, preset["tag_id"])
    webhook = client.post(
        "/api/admin/webhooks", json={"name": "네트워크 채널", "url": WEBHOOK_URL}
    ).json()
    route = respx.post(
        url__regex=re.compile(r"^https://discord\.com/api/webhooks/.+")
    ).mock(side_effect=httpx.ConnectError("offline"))
    response = client.post(
        f"/api/images/{image['id']}/discord",
        json={"webhook_id": webhook["id"]},
    )
    assert response.status_code == 502
    assert route.call_count == 1
    assert "자동으로 다시 전송하지 않았습니다" in response.json()["detail"]


def test_discord_admin_is_local_machine_only_but_names_and_send_are_lan_visible(
    app, authorize_remote
):
    with TestClient(app, client=("192.168.1.20", 40000)) as remote:
        assert remote.get("/api/webhooks").status_code == 401
        authorize_remote(remote)
        assert remote.get("/api/webhooks").status_code == 200
        assert remote.get("/api/admin/webhooks").status_code == 403
        assert remote.post(
            "/api/admin/webhooks", json={"name": "차단", "url": WEBHOOK_URL}
        ).status_code == 403
