from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def test_gallery_api_forwards_nsfw_filter(client: TestClient, monkeypatch) -> None:
    database = client.app.state.services.database
    image_calls: list[tuple[bool | None, list[str], int, bool | None]] = []
    tag_calls: list[bool | None] = []

    def list_images(favorite, tags, page, nsfw=None):
        image_calls.append((favorite, tags, page, nsfw))
        return {"items": [], "total": 0, "page": page, "page_size": 50}

    def favorite_tag_counts(nsfw=None):
        tag_calls.append(nsfw)
        return []

    monkeypatch.setattr(database, "list_images", list_images)
    monkeypatch.setattr(database, "favorite_tag_counts", favorite_tag_counts)

    assert client.get(
        "/api/images?favorite=true&tag=one&tag=two&nsfw=true&page=3"
    ).status_code == 200
    assert client.get("/api/images/favorite-tags?nsfw=false").status_code == 200

    assert image_calls == [(True, ["one", "two"], 3, True)]
    assert tag_calls == [False]


def test_gallery_frontend_offers_server_backed_nsfw_filters() -> None:
    source = (
        Path(__file__).resolve().parents[2]
        / "frontend"
        / "src"
        / "components"
        / "GalleryView.tsx"
    ).read_text(encoding="utf-8")

    assert 'role="switch"' in source
    assert 'aria-checked={nsfwOnly}' in source
    assert 'aria-label="NSFW만 보기"' in source
    assert "<ShieldAlert" in source
    assert 'params.set("nsfw", "true")' in source
    assert "일반만" not in source
