from __future__ import annotations

import re
from pathlib import Path

from backend.tests.frontend_sources import all_frontend_css


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_collapsed_gallery_keeps_icon_actions_and_two_downloads() -> None:
    source = (
        PROJECT_ROOT / "frontend" / "src" / "components" / "GalleryView.tsx"
    ).read_text(encoding="utf-8")
    summary = source.split('<div className="detail-summary-actions">', 1)[1].split(
        "</div>", 1
    )[0]

    assert 'aria-label="Discord 웹훅으로 전송"' in summary
    assert '<ImageDownloads url={detail.download_url} compact />' in summary
    downloads = (PROJECT_ROOT / "frontend/src/components/ImageDownloads.tsx").read_text(encoding="utf-8")
    assert 'aria-label="EXIF·생성정보 보존 다운로드"' in downloads
    assert 'aria-label="EXIF·생성정보 제거 다운로드"' in downloads
    assert 'imageDownloadUrl(url, "preserve")' in downloads
    assert 'imageDownloadUrl(url, "remove")' in downloads
    assert not re.search(r">\s*Discord 전송\s*<", summary)
    assert not re.search(r">\s*즐겨찾기(?: 해제)?\s*<", summary)


def test_collapsed_gallery_icon_actions_keep_touch_sized_buttons() -> None:
    styles = all_frontend_css()

    assert ".detail-summary-action" in styles
    assert "width: 42px" in styles
    assert "height: 42px" in styles


def test_gallery_grid_replaces_edit_action_with_direct_download() -> None:
    source = (
        PROJECT_ROOT / "frontend" / "src" / "components" / "GalleryView.tsx"
    ).read_text(encoding="utf-8")
    grid = source.split('<section className="image-grid"', 1)[1].split(
        "</section>", 1
    )[0]

    assert '<ImageDownloads url={image.download_url} compact />' in grid
    assert "onClick={() => onEdit(image)}" not in grid
    assert not re.search(r">\s*편집\s*<", grid)
