from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_android_unreachable_pc_prefers_standalone_then_offline_gallery() -> None:
    source = (
        PROJECT_ROOT
        / "android"
        / "app"
        / "src"
        / "main"
        / "java"
        / "com"
        / "novelai"
        / "lanstudio"
        / "MainActivity.java"
    ).read_text(encoding="utf-8")

    transition = source.split(
        "private void showOfflineGalleryOrConnection", 1
    )[1].split("private void showOfflineGallery()", 1)[0]
    open_gallery = source.split("private void showOfflineGallery()", 1)[1].split(
        "private void refreshOfflineGalleryButton", 1
    )[0]
    refresh_button = source.split(
        "private void refreshOfflineGalleryButton", 1
    )[1].split("private void startOfflineGallerySync", 1)[0]

    assert "apiProfileStore.hasProfiles()" in transition
    assert "showStandaloneMode();" in transition
    assert "showOfflineGallery();" in transition
    assert "hasImages()" not in transition
    assert "hasImages()" not in open_gallery
    assert "setVisibility(View.VISIBLE)" in refresh_button
