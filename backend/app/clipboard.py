"""Put an image on the Windows clipboard exactly as stored, so metadata survives.

Browsers re-encode images written through the web Clipboard API, which drops PNG
text chunks. The PC app runs on the same machine as the user, so it writes the
clipboard itself with three formats:

- CF_HDROP: the file itself. Discord, Explorer and messengers paste the original bytes.
- "PNG": the raw PNG bytes for apps that read the registered PNG format.
- CF_DIB: a plain bitmap for everything else.
"""
from __future__ import annotations

import ctypes
import io
import struct
import sys
import time
from pathlib import Path

from PIL import Image

CF_DIB = 8
CF_HDROP = 15
GMEM_MOVEABLE = 0x0002
HWND_MESSAGE = -3


class ClipboardError(RuntimeError):
    pass


def dropfiles_payload(paths: list[Path]) -> bytes:
    """DROPFILES header followed by a double-null-terminated UTF-16 path list."""
    header = struct.pack("<IiiII", 20, 0, 0, 0, 1)  # pFiles, pt.x, pt.y, fNC, fWide
    names = "".join(str(path.resolve()) + "\0" for path in paths) + "\0"
    return header + names.encode("utf-16-le")


def dib_payload(png_bytes: bytes) -> bytes:
    """BMP bytes without the 14-byte file header, i.e. a packed DIB."""
    with Image.open(io.BytesIO(png_bytes)) as image:
        converted = image.convert("RGBA" if "A" in image.getbands() else "RGB")
        buffer = io.BytesIO()
        converted.save(buffer, format="BMP")
    return buffer.getvalue()[14:]


def copy_image_to_clipboard(png_bytes: bytes, file_path: Path) -> None:
    if sys.platform != "win32":
        raise ClipboardError("클립보드 복사는 Windows PC 앱에서만 쓸 수 있어요")
    _set_clipboard(
        [
            (CF_HDROP, dropfiles_payload([file_path])),
            ("PNG", png_bytes),
            (CF_DIB, dib_payload(png_bytes)),
        ]
    )


def _set_clipboard(items: list[tuple[int | str, bytes]]) -> None:  # pragma: no cover - Windows only
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.CreateWindowExW.argtypes = [
        wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
    ]
    user32.DestroyWindow.argtypes = [wintypes.HWND]
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
    user32.RegisterClipboardFormatW.restype = wintypes.UINT
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = wintypes.LPVOID
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]

    # EmptyClipboard with a NULL owner makes SetClipboardData fail, so own it with a hidden window.
    hwnd = user32.CreateWindowExW(0, "STATIC", None, 0, 0, 0, 0, 0, HWND_MESSAGE, None, None, None)
    if not hwnd:
        raise ClipboardError("클립보드를 준비하지 못했어요")
    try:
        for _ in range(20):
            if user32.OpenClipboard(hwnd):
                break
            time.sleep(0.05)
        else:
            raise ClipboardError("다른 프로그램이 클립보드를 쓰고 있어요. 잠시 뒤 다시 시도해 주세요")
        try:
            user32.EmptyClipboard()
            for fmt, data in items:
                code = user32.RegisterClipboardFormatW(fmt) if isinstance(fmt, str) else fmt
                handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
                if not handle:
                    raise ClipboardError("클립보드 메모리를 확보하지 못했어요")
                pointer = kernel32.GlobalLock(handle)
                ctypes.memmove(pointer, data, len(data))
                kernel32.GlobalUnlock(handle)
                if not user32.SetClipboardData(code, handle):
                    kernel32.GlobalFree(handle)
                    raise ClipboardError("클립보드에 넣지 못했어요")
        finally:
            user32.CloseClipboard()
    finally:
        user32.DestroyWindow(hwnd)
