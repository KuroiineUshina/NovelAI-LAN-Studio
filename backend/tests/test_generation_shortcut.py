from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_ctrl_enter_requests_the_existing_generation_form_submit() -> None:
    source = (
        PROJECT_ROOT / "frontend" / "src" / "components" / "GenerateView.tsx"
    ).read_text(encoding="utf-8")

    assert "const handleGenerationShortcut" in source
    assert 'event.key !== "Enter"' in source
    assert "!event.ctrlKey" in source
    assert "event.repeat" in source
    assert "event.nativeEvent.isComposing" in source
    assert "submitInFlightRef.current" in source
    assert "event.currentTarget.requestSubmit()" in source
    assert "onKeyDown={handleGenerationShortcut}" in source
    assert 'title="Ctrl+Enter로 생성"' in source


def test_settings_ui_can_change_image_storage_directory() -> None:
    source = (
        PROJECT_ROOT / "frontend" / "src" / "components" / "SettingsView.tsx"
    ).read_text(encoding="utf-8")

    assert "image_storage_directory: string" in source
    assert "default_image_storage_directory: string" in source
    assert '"/api/admin/settings/image-storage"' in source
    assert "임시 이미지·즐겨찾기·썸네일·편집 파일도 함께 옮겨져요" in source
    assert "기본 폴더로" in source
    assert "폴더 변경" in source
