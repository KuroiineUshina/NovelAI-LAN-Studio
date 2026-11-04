from __future__ import annotations

import gzip
import io
import json

from PIL import Image, PngImagePlugin

from backend.app.image_info import read_image_info

NAI_COMMENT = {
    "prompt": "1girl, santa costume",
    "uc": "lowres",
    "steps": 28,
    "scale": 5.0,
    "cfg_rescale": 0.2,
    "seed": 123456,
    "sampler": "k_euler_ancestral",
    "noise_schedule": "karras",
    "width": 832,
    "height": 1216,
    "v4_prompt": {
        "caption": {
            "base_caption": "1girl, santa costume, night",
            "char_captions": [{"char_caption": "girl, pink hair", "centers": [{"x": 0.5, "y": 0.5}]}],
        }
    },
    "v4_negative_prompt": {
        "caption": {"base_caption": "lowres, bad hands", "char_captions": [{"char_caption": "short hair"}]}
    },
}


def png_with_text(chunks: dict[str, str]) -> bytes:
    info = PngImagePlugin.PngInfo()
    for key, value in chunks.items():
        info.add_text(key, value)
    buffer = io.BytesIO()
    Image.new("RGB", (64, 64), (200, 200, 200)).save(buffer, format="PNG", pnginfo=info)
    return buffer.getvalue()


def stealth_png(payload: dict, compressed: bool) -> bytes:
    body = json.dumps(payload).encode()
    if compressed:
        body = gzip.compress(body)
    magic = b"stealth_pngcomp" if compressed else b"stealth_pnginfo"
    stream = magic + (len(body) * 8).to_bytes(4, "big") + body
    bits = [int(bit) for byte in stream for bit in f"{byte:08b}"]
    width, height = 64, 64
    image = Image.new("RGBA", (width, height), (120, 120, 120, 255))
    pixels = image.load()
    index = 0
    for x in range(width):
        for y in range(height):
            if index < len(bits):
                r, g, b, _ = pixels[x, y]
                pixels[x, y] = (r, g, b, 254 | bits[index])
                index += 1
    assert index == len(bits), "test image too small for payload"
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_novelai_png_text_chunks():
    data = png_with_text(
        {
            "Comment": json.dumps(NAI_COMMENT),
            "Source": "NovelAI Diffusion V4.5 4BDE2A90",
            "Software": "NovelAI",
        }
    )
    generation = read_image_info(data)["generation"]
    assert generation["source"] == "novelai"
    assert generation["prompt"] == "1girl, santa costume, night"
    assert generation["negative_prompt"] == "lowres, bad hands"
    assert generation["characters"] == [
        {"prompt": "girl, pink hair", "negative_prompt": "short hair", "center": {"x": 0.5, "y": 0.5}}
    ]
    assert generation["parameters"]["seed"] == 123456
    assert generation["parameters"]["guidance"] == 5.0
    assert generation["parameters"]["width"] == 832
    assert generation["model"] == "nai-diffusion-4-5-full"


def test_novelai_stealth_alpha_payload_compressed_and_plain():
    for compressed in (True, False):
        payload = {"Comment": json.dumps({**NAI_COMMENT, "v4_prompt": {}}), "Source": "NovelAI Diffusion V5 Curated"}
        generation = read_image_info(stealth_png(payload, compressed))["generation"]
        assert generation["prompt"] == "1girl, santa costume"
        assert generation["negative_prompt"] == "lowres, bad hands"
        assert generation["model"] == "nai-diffusion-5-curated"


def test_webui_parameters_text():
    text = (
        "masterpiece, 1girl\nwinter coat\n"
        "Negative prompt: lowres, blurry\n"
        "Steps: 30, Sampler: DPM++ 2M, CFG scale: 6.5, Seed: 42, Size: 832x1216, Model: anything"
    )
    generation = read_image_info(png_with_text({"parameters": text}))["generation"]
    assert generation["source"] == "webui"
    assert generation["prompt"] == "masterpiece, 1girl\nwinter coat"
    assert generation["negative_prompt"] == "lowres, blurry"
    assert generation["parameters"] == {
        "steps": 30,
        "sampler": "DPM++ 2M",
        "guidance": 6.5,
        "seed": 42,
        "width": 832,
        "height": 1216,
    }
    assert generation["model_label"] == "anything"


def test_camera_exif_from_jpeg():
    exif = Image.Exif()
    exif[0x010F] = "Samsung"
    exif[0x0110] = "Galaxy Z Fold7"
    exif[0x0132] = "2026:11:05 10:00:00"
    buffer = io.BytesIO()
    Image.new("RGB", (32, 32), (10, 20, 30)).save(buffer, format="JPEG", exif=exif)
    info = read_image_info(buffer.getvalue())
    assert info["generation"] is None
    assert info["camera"]["make"] == "Samsung"
    assert info["camera"]["model"] == "Galaxy Z Fold7"
    assert info["image"]["format"] == "JPEG"


def test_plain_image_has_no_info():
    buffer = io.BytesIO()
    Image.new("RGBA", (16, 16), (0, 0, 0, 255)).save(buffer, format="PNG")
    info = read_image_info(buffer.getvalue())
    assert info["generation"] is None and info["camera"] is None


def test_image_info_endpoint(client):
    data = png_with_text({"Comment": json.dumps(NAI_COMMENT), "Source": "NovelAI Diffusion V4.5"})
    response = client.post("/api/image-info", files={"file": ("nai.png", data, "image/png")})
    assert response.status_code == 200
    assert response.json()["generation"]["parameters"]["steps"] == 28
    assert client.get("/api/uploads").json()["items"] == []
    bad = client.post("/api/image-info", files={"file": ("x.png", b"not an image", "image/png")})
    assert bad.status_code == 400
