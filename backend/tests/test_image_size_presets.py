from __future__ import annotations

import re
from pathlib import Path

from backend.tests.frontend_sources import all_frontend_css


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _source() -> str:
    return (
        PROJECT_ROOT / "frontend" / "src" / "components" / "GenerateView.tsx"
    ).read_text(encoding="utf-8")


def test_image_size_presets_include_current_novelai_v5_sizes() -> None:
    source = _source()

    for width, height in (
        (640, 640),
        (1024, 1024),
        (1472, 1472),
        (512, 768),
        (832, 1216),
        (1024, 1536),
        (1088, 1920),
        (576, 1024),
        (768, 512),
        (1216, 832),
        (1536, 1024),
        (1920, 1088),
        (1024, 576),
    ):
        assert f"width: {width}, height: {height}" in source


def test_image_size_presets_are_grouped_by_actual_ratio() -> None:
    source = _source()

    assert "const SIZE_PRESET_GROUPS" in source
    assert 'label: "1:1"' in source
    assert 'label: "2:3 계열"' in source
    assert 'label: "9:16 계열"' in source
    assert 'label: "3:2 계열"' in source
    assert 'label: "16:9 계열"' in source
    assert "SIZE_PRESET_GROUPS.map" in source
    assert 'className="size-preset-group"' in source
    assert 'label: "정확한 9:16", ratio: "9:16", width: 576, height: 1024' in source
    assert 'label: "정확한 16:9", ratio: "16:9", width: 1024, height: 576' in source
    assert "width: 768, height: 1344" not in source
    assert "width: 1344, height: 768" not in source


def test_device_screen_presets_use_nearest_64_aligned_novelai_sizes() -> None:
    source = _source()

    assert 'description: "Galaxy Z Fold7 외부 디스플레이"' in source
    assert 'label: "Fold7 외부", ratio: "9:21", width: 768, height: 1792' in source
    assert 'description: "Galaxy Z Fold7 내부 · 원본 82:91 근사"' in source
    assert 'label: "Fold7 내부", ratio: "9:10 (≈82:91)", width: 1152, height: 1280' in source
    assert 'description: "iPad Air 4 · 원본 41:59 근사"' in source
    assert 'label: "iPad Air 4", ratio: "16:23 (≈41:59)", width: 1024, height: 1472' in source
    assert 'step="64"' in source

    for width, height, ratio_width, ratio_height, maximum_error_percent in (
        (768, 1792, 3, 7, 0.0),
        (1152, 1280, 82, 91, 0.122),
        (1024, 1472, 41, 59, 0.107),
    ):
        assert width % 64 == 0
        assert height % 64 == 0
        assert width <= 1536
        assert height <= 2048
        actual_ratio = width / height
        original_ratio = ratio_width / ratio_height
        error_percent = abs((actual_ratio / original_ratio) - 1) * 100
        assert error_percent <= maximum_error_percent

    assert "width: 864, height: 2016" not in source
    assert "width: 1312, height: 1456" not in source
    assert "width: 1312, height: 1888" not in source


def test_every_image_size_preset_is_aligned_to_64_pixels() -> None:
    source = _source()
    preset_sizes = [
        (int(width), int(height))
        for width, height in re.findall(r"width: (\d+), height: (\d+)", source)
    ]

    assert preset_sizes
    assert all(width % 64 == 0 and height % 64 == 0 for width, height in preset_sizes)


def test_sizes_above_normal_pixel_limit_receive_paid_gold_style() -> None:
    source = _source()
    styles = all_frontend_css()
    anlas = (PROJECT_ROOT / "frontend" / "src" / "anlas.ts").read_text(
        encoding="utf-8"
    )

    assert "export const NORMAL_PIXEL_LIMIT = 1024 * 1024" in anlas
    assert "preset.width * preset.height > NORMAL_PIXEL_LIMIT" in source
    assert 'paidBySize ? " paid-size" : ""' in source
    assert "해상도 기준 Anlas 사용" in source
    assert ".size-preset.paid-size" in styles
    assert ".size-preset.paid-size.selected" in styles
