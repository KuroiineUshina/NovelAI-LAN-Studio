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


def test_standalone_gallery_offers_metadata_download_choices() -> None:
    standalone = (
        PROJECT_ROOT
        / "android"
        / "app"
        / "src"
        / "main"
        / "assets"
        / "standalone.html"
    ).read_text(encoding="utf-8")

    assert "다운로드" in standalone
    assert 'data-preserve="true"' in standalone
    assert 'data-preserve="false"' in standalone
    assert "Native.downloadImageWithMetadata" in standalone


def test_standalone_sync_is_manual_and_does_not_reload_the_app() -> None:
    standalone = (
        PROJECT_ROOT
        / "android"
        / "app"
        / "src"
        / "main"
        / "assets"
        / "standalone.html"
    ).read_text(encoding="utf-8")

    boot = standalone[
        standalone.index("function boot()") : standalone.index("function refreshSyncedState()")
    ]
    sync_result = standalone[
        standalone.index("onSyncResult:") : standalone.index("\n    boot();")
    ]

    assert "Native.syncNow()" not in boot
    assert "location.reload()" not in sync_result
    assert "refreshSyncedState()" in sync_result
    assert "$('sync').onclick=()=>{status('PC 동기화 확인 중');Native.syncNow()}" in standalone


def test_android_back_button_delegates_to_each_active_app_surface() -> None:
    app = (PROJECT_ROOT / "frontend" / "src" / "App.tsx").read_text(
        encoding="utf-8"
    )
    standalone = (
        PROJECT_ROOT
        / "android"
        / "app"
        / "src"
        / "main"
        / "assets"
        / "standalone.html"
    ).read_text(encoding="utf-8")
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

    assert "screenHistory=[]" in standalone
    assert "function handleSystemBack()" in standalone
    assert "window.Standalone={handleSystemBack" in standalone
    assert "window.OfflineGalleryBack" in offline

    assert "requestWebBack(" in activity
    assert "window.NovelAIStudioBack" in activity
    assert "window.Standalone.handleSystemBack" in activity
    assert "window.OfflineGalleryBack" in activity


def test_android_standalone_mode_uses_pc_approved_profiles_and_sync(client) -> None:
    android_main = PROJECT_ROOT / "android" / "app" / "src" / "main"
    required_files = (
        android_main / "assets" / "standalone.html",
        android_main / "java" / "com" / "novelai" / "lanstudio" / "ApiProfileStore.java",
        android_main / "java" / "com" / "novelai" / "lanstudio" / "ApiProfileProvisioner.java",
        android_main / "java" / "com" / "novelai" / "lanstudio" / "StandaloneBridge.java",
        android_main / "java" / "com" / "novelai" / "lanstudio" / "StandaloneNovelAIClient.java",
        android_main / "java" / "com" / "novelai" / "lanstudio" / "StandaloneSyncClient.java",
    )
    assert all(path.exists() for path in required_files)

    manifest = (android_main / "AndroidManifest.xml").read_text(encoding="utf-8")
    layout = (android_main / "res" / "layout" / "activity_main.xml").read_text(
        encoding="utf-8"
    )
    activity = (
        android_main
        / "java"
        / "com"
        / "novelai"
        / "lanstudio"
        / "MainActivity.java"
    ).read_text(encoding="utf-8")

    standalone = (android_main / "assets" / "standalone.html").read_text(encoding="utf-8")
    profile_store = required_files[1].read_text(encoding="utf-8")

    assert "standalone_button" in layout
    assert "showStandaloneMode" in activity
    assert "AndroidKeyStore" in profile_store
    assert "encrypted_token_b64" in profile_store
    assert 'id="token"' not in standalone
    assert "Persistent API Token" not in standalone
    assert "sendStoryMessage" not in standalone
    assert "storyScreen" not in standalone
    assert "--keyboard" in standalone
    assert "visualViewport" in standalone

    route_paths = {getattr(route, "path", None) for route in client.app.routes}
    assert "/api/mobile-sync/images" in route_paths
    assert not any(str(path or "").startswith("/api/story") for path in route_paths)
    assert "/api/mobile-sync/story-sessions" not in route_paths
    assert "/api/mobile/story-image-cache" not in route_paths
    assert "/api/mobile/standalone-snapshot" in route_paths
