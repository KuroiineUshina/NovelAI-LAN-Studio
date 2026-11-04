"""Read generation info and camera EXIF out of an attached image.

Covers NovelAI PNG text chunks, NovelAI/WebUI stealth pnginfo hidden in the
alpha or RGB low bits, Stable Diffusion WebUI "parameters" text, and EXIF
(including a NovelAI JSON stored in UserComment by some converters).
"""
from __future__ import annotations

import gzip
import io
import json
import re
from typing import Any

from PIL import ExifTags, Image

from .config import MAX_IMAGE_DIMENSION, MODELS

_ALPHA_MAGIC = {b"stealth_pnginfo": False, b"stealth_pngcomp": True}
_RGB_MAGIC = {b"stealth_rgbinfo": False, b"stealth_rgbcomp": True}
_MAX_TEXT = 64_000


_LOW_BIT = bytes(0x31 if value & 1 else 0x30 for value in range(256))


def _bits(text: bytes, start: int, count: int) -> bytes:
    return int(text[start:start + count], 2).to_bytes(count // 8, "big")


def _stealth_payload(image: Image.Image) -> dict[str, Any] | None:
    # Stealth pnginfo walks columns first, then rows, most-significant bit first.
    # Transposing turns that column walk into PIL's ordinary row-major bytes.
    rgba = image.convert("RGBA").transpose(Image.Transpose.TRANSPOSE)
    for raw, magics in (
        (rgba.getchannel("A").tobytes(), _ALPHA_MAGIC),
        (rgba.convert("RGB").tobytes(), _RGB_MAGIC),
    ):
        bits = raw.translate(_LOW_BIT)
        if len(bits) < 152:
            continue
        head = _bits(bits, 0, 120)
        if head not in magics:
            continue
        length = int(bits[120:152], 2)
        if length <= 0 or length % 8 or 152 + length > len(bits):
            continue
        payload = _bits(bits, 152, length)
        try:
            if magics[head]:
                payload = gzip.decompress(payload)
            text = payload.decode("utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return {"parameters": text}
        return data if isinstance(data, dict) else None
    return None


def _model_id(source: str) -> str | None:
    label = source.lower()
    family = "5" if re.search(r"\bv5\b", label) else "4-5" if "v4.5" in label else None
    if not family:
        return None
    candidate = f"nai-diffusion-{family}-{'curated' if 'curated' in label else 'full'}"
    return candidate if candidate in MODELS else None


def _from_novelai(comment: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    caption = (comment.get("v4_prompt") or {}).get("caption") or {}
    negative = (comment.get("v4_negative_prompt") or {}).get("caption") or {}
    negative_chars = negative.get("char_captions") or []
    characters = []
    for index, item in enumerate(caption.get("char_captions") or []):
        centers = item.get("centers") or []
        characters.append(
            {
                "prompt": str(item.get("char_caption") or ""),
                "negative_prompt": str(
                    (negative_chars[index].get("char_caption") if index < len(negative_chars) else "") or ""
                ),
                "center": centers[0] if centers else None,
            }
        )
    source_label = str(extra.get("Source") or "")
    parameters = {
        "width": comment.get("width"),
        "height": comment.get("height"),
        "steps": comment.get("steps"),
        "guidance": comment.get("scale"),
        "guidance_rescale": comment.get("cfg_rescale"),
        "sampler": comment.get("sampler"),
        "noise_schedule": comment.get("noise_schedule"),
        "seed": comment.get("seed"),
        "strength": comment.get("strength"),
        "noise": comment.get("noise"),
    }
    return {
        "source": "novelai",
        "prompt": str(caption.get("base_caption") or comment.get("prompt") or extra.get("Description") or ""),
        "negative_prompt": str(negative.get("base_caption") or comment.get("uc") or ""),
        "characters": characters,
        "parameters": {key: value for key, value in parameters.items() if value is not None},
        "model": _model_id(source_label),
        "model_label": source_label or None,
        "request_type": comment.get("request_type"),
    }


_WEBUI_KEYS = {
    "Steps": ("steps", int),
    "CFG scale": ("guidance", float),
    "Seed": ("seed", int),
    "Sampler": ("sampler", str),
    "Denoising strength": ("strength", float),
}


def _from_webui(text: str) -> dict[str, Any]:
    lines = text.strip().split("\n")
    settings_line = lines.pop() if lines and re.match(r"^\s*Steps:", lines[-1]) else ""
    prompt_lines, negative_lines, target = [], [], None
    for line in lines:
        if line.startswith("Negative prompt:"):
            target = negative_lines
            line = line[len("Negative prompt:"):].strip()
        (target if target is not None else prompt_lines).append(line)
    parameters: dict[str, Any] = {}
    model_label = None
    for key, value in re.findall(r"([A-Za-z][A-Za-z0-9 ]*):\s*(\"[^\"]*\"|[^,]+)", settings_line):
        key, value = key.strip(), value.strip().strip('"')
        if key in _WEBUI_KEYS:
            name, cast = _WEBUI_KEYS[key]
            try:
                parameters[name] = cast(value)
            except ValueError:
                pass
        elif key == "Size" and "x" in value:
            width, _, height = value.partition("x")
            if width.isdigit() and height.isdigit():
                parameters["width"], parameters["height"] = int(width), int(height)
        elif key == "Model":
            model_label = value
    return {
        "source": "webui",
        "prompt": "\n".join(prompt_lines).strip(),
        "negative_prompt": "\n".join(negative_lines).strip(),
        "characters": [],
        "parameters": parameters,
        "model": None,
        "model_label": model_label,
        "request_type": None,
    }


def _camera(image: Image.Image) -> tuple[dict[str, Any] | None, str | None]:
    exif = image.getexif()
    if not exif:
        return None, None
    merged: dict[int, Any] = dict(exif)
    try:
        merged.update(exif.get_ifd(ExifTags.IFD.Exif))
    except (KeyError, AttributeError):
        pass
    user_comment = merged.get(0x9286)
    comment_text = None
    if isinstance(user_comment, bytes):
        for prefix, codec in ((b"UNICODE\x00", "utf-16-be"), (b"ASCII\x00\x00\x00", "ascii"), (b"", "utf-8")):
            if user_comment.startswith(prefix):
                try:
                    comment_text = user_comment[len(prefix):].decode(codec).strip("\x00 ")
                    break
                except UnicodeDecodeError:
                    continue
    elif isinstance(user_comment, str):
        comment_text = user_comment
    names = {
        0x010F: "make",
        0x0110: "model",
        0x9003: "taken_at",
        0x0132: "modified_at",
        0xA434: "lens",
        0x829A: "exposure_time",
        0x829D: "f_number",
        0x8827: "iso",
        0x920A: "focal_length",
        0x0131: "software",
    }
    camera: dict[str, Any] = {}
    for tag, name in names.items():
        value = merged.get(tag)
        if value in (None, "", b""):
            continue
        if isinstance(value, bytes):
            value = value.decode("utf-8", "replace").strip("\x00 ")
        elif not isinstance(value, (int, str)):
            try:
                value = float(value)
            except (TypeError, ValueError):
                value = str(value)
        camera[name] = value.strip() if isinstance(value, str) else value
    if 0x8825 in exif:
        camera["has_location"] = True
    return (camera or None), comment_text


def read_image_info(data: bytes) -> dict[str, Any]:
    with Image.open(io.BytesIO(data)) as image:
        if max(image.size) > MAX_IMAGE_DIMENSION:
            raise ValueError("이미지 크기는 최대 8192×8192까지 읽을 수 있어요.")
        image.load()
        text = {
            key: value
            for key, value in (getattr(image, "text", None) or image.info).items()
            if isinstance(value, str) and len(value) <= _MAX_TEXT
        }
        camera, comment_text = _camera(image)
        stealth = None if "Comment" in text or "parameters" in text else _stealth_payload(image)
        size = {"width": image.width, "height": image.height, "format": image.format}

    generation = None
    for candidate in (text, stealth or {}):
        comment = candidate.get("Comment")
        if isinstance(comment, str):
            try:
                comment = json.loads(comment)
            except json.JSONDecodeError:
                comment = None
        if isinstance(comment, dict):
            generation = _from_novelai(comment, candidate)
            break
        if isinstance(candidate.get("parameters"), str):
            generation = _from_webui(candidate["parameters"])
            break
    if generation is None and comment_text:
        try:
            parsed = json.loads(comment_text)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict) and ("prompt" in parsed or "v4_prompt" in parsed):
            generation = _from_novelai(parsed, {})
        elif re.search(r"\bSteps:", comment_text):
            generation = _from_webui(comment_text)
    if camera and generation and camera.get("software") == "NovelAI":
        camera = None
    return {"image": size, "generation": generation, "camera": camera}
