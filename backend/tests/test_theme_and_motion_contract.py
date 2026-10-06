from __future__ import annotations

from pathlib import Path

from backend.tests.frontend_sources import all_frontend_css


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_web_theme_is_applied_before_react_and_has_one_tap_toggle() -> None:
    index = (PROJECT_ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    app = (PROJECT_ROOT / "frontend" / "src" / "App.tsx").read_text(
        encoding="utf-8"
    )
    header = (
        PROJECT_ROOT / "frontend" / "src" / "components" / "StudioHeader.tsx"
    ).read_text(encoding="utf-8")
    styles = all_frontend_css()

    assert index.index("novelai-lan-studio-theme-v1") < index.index("/src/main.tsx")
    assert "<StudioHeader" in app
    assert "onToggleTheme={() => setTheme" in app
    assert "라이트 모드로 전환" in header
    assert "다크 모드로 전환" in header
    assert "onClick={onToggleTheme}" in header
    assert 'data-theme="light"' in styles
    assert "prefers-reduced-motion" in styles


def test_primary_navigation_has_one_header_for_desktop_and_mobile() -> None:
    app = (PROJECT_ROOT / "frontend/src/App.tsx").read_text(encoding="utf-8")
    header = (PROJECT_ROOT / "frontend/src/components/StudioHeader.tsx").read_text(
        encoding="utf-8"
    )
    assert app.count("<StudioHeader") == 1
    assert 'className="sidebar"' not in app
    assert 'className="bottom-nav"' not in app
    for item in ("generate", "gallery", "presets", "stats", "settings"):
        assert header.count(f'id: "{item}"') == 1
    assert 'id: "story"' not in header
    assert 'aria-label="주 메뉴"' in header
    assert 'aria-current={tab === id ? "page" : undefined}' in header
    assert "status.lan_urls" in header
    assert "status.tailscale_urls" in header
    assert "status.security_notice" in header
    assert "novelai-system-back" in header


def test_workbench_has_no_result_preview_but_keeps_source_editing() -> None:
    generate = (PROJECT_ROOT / "frontend/src/components/GenerateView.tsx").read_text(
        encoding="utf-8"
    )
    assert "WorkbenchResults" not in generate
    assert "workbench-mobile-switch" not in generate
    assert 'aria-label="장면 설정"' in generate
    assert "<InpaintCanvas" in generate
    assert "원본 선택" in generate
    assert "generation-submit-controls" in generate
    assert "parseRepeatCount" in generate


def test_image_results_have_motion_with_reduced_motion_fallback() -> None:
    gallery = (
        PROJECT_ROOT / "frontend" / "src" / "components" / "GalleryView.tsx"
    ).read_text(encoding="utf-8")
    styles = all_frontend_css()

    assert "enteringImageIds" in gallery
    assert "image-card-enter" in gallery
    assert "@keyframes result-card-enter" in styles
    assert "prefers-reduced-motion: reduce" in styles


def test_android_offline_and_standalone_surfaces_share_theme_and_motion() -> None:
    standalone = (
        PROJECT_ROOT
        / "android"
        / "app"
        / "src"
        / "main"
        / "assets"
        / "standalone.html"
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

    assert 'id="themeToggle"' in standalone
    assert "card-enter" in standalone
    assert "prefers-reduced-motion:reduce" in standalone
    assert "novelai-lan-studio-theme-v1" in offline
    assert 'id=\"themeToggle\"' in offline


def test_borderless_ui_and_warm_light_theme_cover_web_and_android() -> None:
    styles = all_frontend_css()
    index = (PROJECT_ROOT / "frontend" / "index.html").read_text(
        encoding="utf-8"
    )
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
    input_background = (
        PROJECT_ROOT
        / "android"
        / "app"
        / "src"
        / "main"
        / "res"
        / "drawable"
        / "input_background.xml"
    ).read_text(encoding="utf-8")
    secondary_button = (
        PROJECT_ROOT
        / "android"
        / "app"
        / "src"
        / "main"
        / "res"
        / "drawable"
        / "secondary_button_background.xml"
    ).read_text(encoding="utf-8")

    assert "body *:not(.spinner) { border-color: transparent !important; }" in styles
    assert "body *:not(.spinner){border-color:transparent!important}" in standalone
    assert "body *{border-color:transparent!important}" in offline
    assert "<stroke" not in input_background
    assert "<stroke" not in secondary_button

    for source in (styles, standalone, offline, index, app):
        assert "#f3eee4" in source
    assert "#fffaf2" in styles
    assert "#fffaf2" in standalone
    assert "#fffaf2" in offline
    assert "transition: background-color .2s" not in styles


def test_eight_bundled_korean_fonts_have_local_switches_and_ofl_notices() -> None:
    styles = all_frontend_css()
    index = (PROJECT_ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    app = (PROJECT_ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
    settings = (
        PROJECT_ROOT / "frontend" / "src" / "components" / "SettingsView.tsx"
    ).read_text(encoding="utf-8")
    standalone = (
        PROJECT_ROOT / "android" / "app" / "src" / "main" / "assets" / "standalone.html"
    ).read_text(encoding="utf-8")
    canonical_fonts = sorted((PROJECT_ROOT / "assets" / "fonts").glob("*.woff2"))
    licenses = sorted((PROJECT_ROOT / "assets" / "fonts" / "licenses").glob("*.txt"))

    assert len(canonical_fonts) == 8
    assert len(licenses) == 8
    assert all(path.stat().st_size > 100_000 for path in canonical_fonts)
    assert all("Open Font License" in path.read_text(encoding="utf-8") for path in licenses)
    assert styles.count("@font-face") == 8
    assert "novelai-lan-studio-font-v1" in index
    assert "getInitialAppFont" in app
    assert "고딕 4종과 명조 4종" in settings
    assert 'id="appFont"' in standalone
    assert "APP_FONTS" in standalone
