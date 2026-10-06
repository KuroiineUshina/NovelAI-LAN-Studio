import io
import uuid

import pytest
from PIL import Image, ImageOps, PngImagePlugin
from fastapi.testclient import TestClient

from backend.app.database import iso, utc_now
from backend.app.image_export import metadata_free_png, _stealth_header


def png_bytes(image=None):
    image = image or Image.new("RGBA", (32, 64), (101, 151, 201, 255))
    info = PngImagePlugin.PngInfo()
    info.add_text("Comment", '{"prompt":"private prompt","seed":12345}')
    info.add_text("parameters", "secret compressed prompt", zip=True)
    info.add_itxt("XML:com.adobe.xmp", "private xmp")
    exif = Image.Exif()
    exif[315] = "private author"
    output = io.BytesIO()
    image.save(output, "PNG", pnginfo=info, exif=exif, icc_profile=b"private profile")
    return output.getvalue()


def seed_image(client, data):
    services = client.app.state.services
    job = services.database.create_job({"mode":"txt2img", "model":"nai-diffusion-5-full", "parameters":{}}, "EXPORT")
    services.database.finish_job(job["id"], "succeeded")
    image_id = str(uuid.uuid4())
    saved = services.storage.save_generated(data, image_id)
    item = services.database.create_image({
        **saved, "id":image_id, "job_id":job["id"], "parent_image_id":None,
        "mode":"txt2img", "model":"nai-diffusion-5-full", "prompt":"private",
        "negative_prompt":"", "settings":{}, "character_snapshot":[], "seed":12345,
        "created_at":iso(utc_now()), "expires_at":None,
    }, [])
    return item, services.storage.absolute(item["file_path"])


def test_download_modes_are_non_destructive_and_default_is_exact_original(client):
    original = png_bytes()
    item, path = seed_image(client, original)
    before = client.app.state.services.database.get_image(item["id"])
    for suffix in ("", "?metadata=preserve"):
        response = client.get(f'/api/images/{item["id"]}/download{suffix}')
        assert response.status_code == 200
        assert response.content == original
        assert response.headers["content-type"] == "image/png"
    response = client.get(f'/api/images/{item["id"]}/download?metadata=remove')
    assert response.status_code == 200
    assert "-no-metadata.png" in response.headers["content-disposition"]
    assert response.headers["cache-control"] == "private, no-store"
    clean = Image.open(io.BytesIO(response.content))
    assert clean.info == {}
    assert not clean.getexif()
    assert clean.tobytes() == Image.open(io.BytesIO(original)).tobytes()
    assert path.read_bytes() == original
    assert client.app.state.services.database.get_image(item["id"]) == before


@pytest.mark.parametrize("magic,channels", [
    (b"stealth_pngcomp", (3,)), (b"stealth_pnginfo", (3,)),
    (b"stealth_rgbcomp", (0,1,2)), (b"stealth_rgbinfo", (0,1,2)),
])
def test_entire_stealth_payload_is_erased_not_just_header(tmp_path, magic, channels):
    image = Image.new("RGBA", (32,64), (101,151,201,255))
    payload = magic + b"\x00\x00\x00\x80private payload!"
    bits = [(byte >> bit) & 1 for byte in payload for bit in range(7,-1,-1)]
    index = 0
    for x in range(image.width):
        for y in range(image.height):
            pixel = list(image.getpixel((x,y)))
            for channel in channels:
                if index < len(bits):
                    pixel[channel] = (pixel[channel] & 254) | bits[index]
                    index += 1
            image.putpixel((x,y), tuple(pixel))
    assert _stealth_header(image, channels) == magic
    path = tmp_path / "stealth.png"
    path.write_bytes(png_bytes(image))
    before = path.read_bytes()
    clean = Image.open(io.BytesIO(metadata_free_png(path)))
    assert clean.info == {}
    assert _stealth_header(clean, channels) != magic
    if channels == (3,):
        assert clean.getchannel("A").getextrema() == (255,255)
        assert clean.convert("RGB").tobytes() == image.convert("RGB").tobytes()
    else:
        assert all((v & 1) == 0 for v in clean.convert("RGB").tobytes())
    assert path.read_bytes() == before


def test_plain_transparency_and_pixels_are_preserved(tmp_path):
    image = Image.new("RGBA", (3,2))
    image.putdata([(1,2,3,0),(4,5,6,1),(7,8,9,127),(10,11,12,128),(13,14,15,254),(16,17,18,255)])
    path = tmp_path / "alpha.png"
    path.write_bytes(png_bytes(image))
    clean = Image.open(io.BytesIO(metadata_free_png(path)))
    assert clean.tobytes() == image.tobytes()
    assert not clean.info


@pytest.mark.parametrize("orientation", range(1,9))
def test_exif_orientation_is_applied_before_metadata_removal(tmp_path, orientation):
    image = Image.new("RGB", (3,2))
    image.putdata([(x*30,0,0) for x in range(6)])
    exif = Image.Exif()
    exif[274] = orientation
    exif[315] = "private author"
    path = tmp_path / "oriented.jpg"
    image.save(path, "JPEG", exif=exif)
    clean = Image.open(io.BytesIO(metadata_free_png(path)))
    with Image.open(path) as source:
        expected = ImageOps.exif_transpose(source).convert("RGBA")
        assert clean.size == expected.size
        assert clean.tobytes() == expected.tobytes()
    assert not clean.info


def test_webp_exports_pixel_only_png(tmp_path):
    path = tmp_path / "image.webp"
    image = Image.new("RGBA", (8,8), (120,90,40,128))
    image.save(path, "WEBP", lossless=True, xmp=b"private metadata")
    clean = Image.open(io.BytesIO(metadata_free_png(path)))
    assert clean.format == "PNG"
    assert clean.tobytes() == Image.open(path).convert("RGBA").tobytes()
    assert not clean.info


def test_download_errors_never_fall_back_to_metadata_original(client):
    item, path = seed_image(client, png_bytes())
    url = f'/api/images/{item["id"]}/download'
    assert client.get(url + "?metadata=unknown").status_code == 422
    path.write_bytes(b"invalid private image")
    assert client.get(url + "?metadata=remove").status_code == 422
    path.unlink()
    assert client.get(url).status_code == 410
    assert client.get(url + "?metadata=remove").status_code == 410
    assert client.get("/api/images/nonexistent/download?metadata=remove").status_code == 404


def test_unapproved_remote_cannot_download_either_version(client, app):
    item, _ = seed_image(client, png_bytes())
    with TestClient(app, client=("192.168.0.99", 50000)) as remote:
        for mode in ("preserve", "remove"):
            response = remote.get(f'/api/images/{item["id"]}/download?metadata={mode}', headers={"host":"192.168.0.2:8787"})
            assert response.status_code in (401,403)
