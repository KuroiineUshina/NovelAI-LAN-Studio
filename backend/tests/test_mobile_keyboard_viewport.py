from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_android_keyboard_overlays_without_resizing_webview() -> None:
    manifest = (
        PROJECT_ROOT / "android" / "app" / "src" / "main" / "AndroidManifest.xml"
    ).read_text(encoding="utf-8")

    assert 'android:windowSoftInputMode="adjustNothing"' in manifest
    assert 'android:windowSoftInputMode="adjustResize"' not in manifest


def test_mobile_web_viewport_requests_keyboard_overlay() -> None:
    document = (PROJECT_ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

    assert "interactive-widget=overlays-content" in document


def test_android_back_button_delegates_to_each_active_app_surface() -> None:
    app = (PROJECT_ROOT / "frontend" / "src" / "App.tsx").read_text(
        encoding="utf-8"
    )
    activity = (
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
    offline = (
        PROJECT_ROOT
        / "android"
        / "app"
        / "src"
        / "main"
        / "java"
        / "com"
        / "novelai"
        / "lanstudio"
        / "OfflineGalleryPage.java"
    ).read_text(encoding="utf-8")

    assert "NovelAIStudioBack" in app
    assert "tabHistoryRef.current.pop()" in app
    assert 'new Event("novelai-system-back", { cancelable: true })' in app

    assert "window.OfflineGalleryBack" in offline

    assert "requestWebBack(" in activity
    assert "window.NovelAIStudioBack" in activity
    assert "Standalone" not in activity.replace("LegacyStandaloneCleanup", "")
    assert "window.OfflineGalleryBack" in activity
