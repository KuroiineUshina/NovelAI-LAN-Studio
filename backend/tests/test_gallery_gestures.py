from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_fullscreen_gallery_supports_fit_gated_swipe_and_pinch_zoom() -> None:
    source = (
        PROJECT_ROOT
        / "frontend"
        / "src"
        / "components"
        / "ZoomableGalleryImage.tsx"
    ).read_text(encoding="utf-8")

    assert "FIT_SCALE_EPSILON" in source
    assert "onPointerDown" in source
    assert "onPointerMove" in source
    assert "distance(points[0], points[1])" in source
    assert "current.scale <= FIT_SCALE_EPSILON" in source
    assert "onNavigate(deltaX < 0 ? 1 : -1)" in source
    assert "deltaY > 110" in source
    assert "onSwipeClose()" in source
    assert "transform.scale.toFixed(1)" in source


def test_regular_detail_swipe_down_closes_the_viewer() -> None:
    source = (
        PROJECT_ROOT / "frontend" / "src" / "components" / "GalleryView.tsx"
    ).read_text(encoding="utf-8")

    assert "deltaY > 95" in source
    assert "closeDetail();" in source
    assert "onSwipeClose={closeDetail}" in source
