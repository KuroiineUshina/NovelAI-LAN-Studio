"""Non-destructive exports: remove file metadata and recognized stealth payloads."""
from __future__ import annotations

import io
import threading
from pathlib import Path

from PIL import Image, ImageOps

from .config import MAX_IMAGE_DIMENSION


_EXPORT_LOCK = threading.Lock()
_ALPHA_MAGIC = (b"stealth_pngcomp", b"stealth_pnginfo")
_RGB_MAGIC = (b"stealth_rgbcomp", b"stealth_rgbinfo")


def _stealth_header(image: Image.Image, channels: tuple[int, ...]) -> bytes:
    """Stealth pnginfo traverses columns first, most-significant bit first."""
    pixels = image.load()
    result = bytearray()
    value = bits = 0
    for x in range(image.width):
        for y in range(image.height):
            for channel in channels:
                value = (value << 1) | (pixels[x, y][channel] & 1)
                bits += 1
                if bits == 8:
                    result.append(value)
                    value = bits = 0
                    if len(result) == 15:
                        return bytes(result)
    return bytes(result)


def metadata_free_png(path: Path) -> bytes:
    # Limit simultaneous full-resolution decoding; the API runs in a worker thread.
    with _EXPORT_LOCK, Image.open(path) as source:
        if max(source.size) > MAX_IMAGE_DIMENSION:
            raise ValueError("정보 제거 다운로드의 최대 크기는 8192×8192입니다.")
        if getattr(source, "is_animated", False):
            raise ValueError("움직이는 이미지는 원본 보존 다운로드를 사용해 주세요.")
        rgba = source.convert("RGBA")
        alpha_hidden = _stealth_header(rgba, (3,)) in _ALPHA_MAGIC
        rgb_hidden = _stealth_header(rgba, (0, 1, 2)) in _RGB_MAGIC
        if alpha_hidden or rgb_hidden:
            channels = list(rgba.split())
            if alpha_hidden:
                # Erase the WHOLE payload, not only its signature. NovelAI uses
                # 254/255 on otherwise opaque images; restore those to opaque.
                original_alpha = channels[3]
                channels[3] = original_alpha.point([255 if a >= 254 else a & 254 for a in range(256)])
                original_alpha.close()
            if rgb_hidden:
                for index in range(3):
                    original_channel = channels[index]
                    channels[index] = original_channel.point([v & 254 for v in range(256)])
                    original_channel.close()
            scrubbed = Image.merge("RGBA", channels)
            scrubbed.info = rgba.info.copy()  # Orientation is consumed below.
            rgba.close()
            rgba = scrubbed
            for channel in channels:
                channel.close()
        oriented = ImageOps.exif_transpose(rgba)
        # A new pixel-only image prevents EXIF/XMP/ICC/text from being inherited.
        clean = Image.frombytes("RGBA", oriented.size, oriented.tobytes())
        try:
            output = io.BytesIO()
            clean.save(output, "PNG")
            return output.getvalue()
        finally:
            clean.close()
            oriented.close()
            rgba.close()
