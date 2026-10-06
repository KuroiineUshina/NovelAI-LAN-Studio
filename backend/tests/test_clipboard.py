from __future__ import annotations

import io
import struct
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from backend.app import clipboard


def png_bytes(mode: str = "RGBA") -> bytes:
    buffer = io.BytesIO()
    Image.new(mode, (4, 3), (10, 20, 30, 255) if mode == "RGBA" else (10, 20, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_dropfiles_payload_lists_the_file_as_wide_text(tmp_path: Path):
    target = tmp_path / "copy.png"
    payload = clipboard.dropfiles_payload([target])
    p_files, _, _, _, wide = struct.unpack("<IiiII", payload[:20])
    assert (p_files, wide) == (20, 1)
    assert payload[20:].decode("utf-16-le") == str(target.resolve()) + "\0\0"


def test_dib_payload_is_a_bitmap_without_file_header():
    dib = clipboard.dib_payload(png_bytes())
    header_size, width, height = struct.unpack("<Iii", dib[:12])
    assert header_size >= 40
    assert (width, abs(height)) == (4, 3)


def test_copy_endpoint_writes_original_or_scrubbed_bytes(client: TestClient, monkeypatch):
    services = client.app.state.services
    calls: list[tuple[bytes, Path]] = []
    monkeypatch.setattr(clipboard, "copy_image_to_clipboard", lambda data, path: calls.append((data, path)))

    original = png_bytes()
    relative = "images/clip-test.png"
    absolute = services.storage.absolute(relative)
    absolute.parent.mkdir(parents=True, exist_ok=True)
    absolute.write_bytes(original)
    monkeypatch.setattr(services.database, "get_image", lambda image_id: {"id": image_id, "file_path": relative, "mime_type": "image/png"})

    preserved = client.post("/api/images/img-1/clipboard?metadata=preserve")
    assert preserved.status_code == 200
    assert calls[-1][0] == original
    assert calls[-1][1].name == "novelai-img-1.png"
    assert calls[-1][1].read_bytes() == original

    removed = client.post("/api/images/img-1/clipboard?metadata=remove")
    assert removed.status_code == 200
    assert calls[-1][1].name == "novelai-img-1-no-metadata.png"
    assert calls[-1][0].startswith(b"\x89PNG")

    monkeypatch.setattr(services.database, "get_image", lambda image_id: None)
    assert client.post("/api/images/missing/clipboard").status_code == 404


def test_copy_endpoint_is_pc_only(app, authorize_remote):
    with TestClient(app, client=("192.168.1.20", 40000)) as remote:
        authorize_remote(remote)
        assert remote.post("/api/images/img-1/clipboard").status_code == 403
