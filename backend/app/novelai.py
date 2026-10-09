from __future__ import annotations

import base64
import io
import json
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

from .config import MODELS


IMAGE_API_BASE = "https://image.novelai.net"
# Precise Reference images must be letterboxed (black) onto one of these canvases.
CHARACTER_REFERENCE_CANVASES = ((1024, 1536), (1536, 1024), (1472, 1472))


def letterbox_reference(image_bytes: bytes) -> bytes:
    from PIL import Image

    with Image.open(io.BytesIO(image_bytes)) as source:
        image = source.convert("RGB")
    ratio = image.width / image.height
    if ratio > 1.2:
        canvas_size = CHARACTER_REFERENCE_CANVASES[1]
    elif ratio < 1 / 1.2:
        canvas_size = CHARACTER_REFERENCE_CANVASES[0]
    else:
        canvas_size = CHARACTER_REFERENCE_CANVASES[2]
    scale = min(canvas_size[0] / image.width, canvas_size[1] / image.height)
    fitted = image.resize(
        (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
        Image.LANCZOS,
    )
    canvas = Image.new("RGB", canvas_size, (0, 0, 0))
    canvas.paste(fitted, ((canvas_size[0] - fitted.width) // 2, (canvas_size[1] - fitted.height) // 2))
    output = io.BytesIO()
    canvas.save(output, format="PNG")
    return output.getvalue()


@dataclass
class GeneratedImage:
    data: bytes
    seed: int | None


class NovelAIError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int | None = None):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class NovelAIClient:
    def __init__(self, token: str, base_url: str = IMAGE_API_BASE):
        self.token = token
        self.base_url = base_url.rstrip("/")

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def _subscription_payload(self) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.get(
                    f"{self.base_url}/user/subscription", headers=self.headers
                )
        except httpx.RequestError as exc:
            raise NovelAIError("NETWORK", "NovelAI 서버에 연결하지 못했습니다.") from exc
        self._raise_for_status(response)
        try:
            return response.json()
        except ValueError as exc:
            raise NovelAIError(
                "INVALID_RESPONSE", "NovelAI 구독 응답을 해석하지 못했습니다."
            ) from exc

    async def get_anlas_status(self) -> dict[str, Any]:
        payload = await self._subscription_payload()
        raw_balance = payload.get("trainingStepsLeft")
        subscription_anlas: int | None
        paid_anlas: int | None

        if isinstance(raw_balance, dict):
            subscription_anlas = int(raw_balance.get("fixedTrainingStepsLeft") or 0)
            paid_anlas = int(raw_balance.get("purchasedTrainingSteps") or 0)
        elif isinstance(raw_balance, (int, float)):
            subscription_anlas = int(raw_balance)
            paid_anlas = 0
        else:
            subscription_anlas = None
            paid_anlas = None

        remaining_anlas = (
            subscription_anlas + paid_anlas
            if subscription_anlas is not None and paid_anlas is not None
            else None
        )
        tier = int(payload.get("tier") or 0)
        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
        tier_names = {0: "Free", 1: "Tablet", 2: "Scroll", 3: "Opus"}

        return {
            "active": bool(payload.get("active")),
            "tier": tier,
            "tier_name": tier_names.get(tier, f"Tier {tier}"),
            "expires_at": payload.get("expiresAt"),
            "subscription_anlas": subscription_anlas,
            "paid_anlas": paid_anlas,
            "remaining_anlas": remaining_anlas,
            "usage_percent": usage.get("percent"),
            "usage_is_negative": usage.get("isNegative"),
            "usage_time_until_next_percent": usage.get("timeUntilNextPercent"),
            "refreshed_at": datetime.now(timezone.utc).isoformat(),
        }

    async def test_connection(self) -> dict[str, Any]:
        return await self.get_anlas_status()

    @staticmethod
    def _decode_images(payload: dict[str, Any]) -> list[GeneratedImage]:
        results: list[GeneratedImage] = []
        for item in payload.get("images") or []:
            encoded = item.get("image") or ""
            if "," in encoded and encoded.startswith("data:"):
                encoded = encoded.split(",", 1)[1]
            try:
                data = base64.b64decode(encoded, validate=True)
            except (ValueError, TypeError) as exc:
                raise NovelAIError("INVALID_RESPONSE", "NovelAI 이미지 응답을 해석하지 못했습니다.") from exc
            results.append(GeneratedImage(data=data, seed=item.get("seed")))
        if not results:
            raise NovelAIError("EMPTY_RESPONSE", "NovelAI가 이미지 없이 응답했습니다.")
        return results

    @staticmethod
    def _decode_zip(content: bytes) -> list[GeneratedImage]:
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                names = sorted(name for name in archive.namelist() if not name.endswith("/"))
                results = [GeneratedImage(data=archive.read(name), seed=None) for name in names]
        except zipfile.BadZipFile as exc:
            raise NovelAIError("INVALID_RESPONSE", "NovelAI 응답을 해석하지 못했습니다.") from exc
        if not results:
            raise NovelAIError("EMPTY_RESPONSE", "NovelAI가 이미지 없이 응답했습니다.")
        return results

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if response.is_success:
            return
        messages = {
            400: ("BAD_REQUEST", "NovelAI가 생성 설정을 거부했습니다."),
            401: ("UNAUTHORIZED", "NovelAI API 토큰이 올바르지 않거나 만료되었습니다."),
            402: ("INSUFFICIENT_ANLAS", "이미지 생성에 필요한 Anlas가 부족합니다."),
            403: ("FORBIDDEN", "현재 계정 또는 구독으로 이 요청을 사용할 수 없습니다."),
            409: ("CONFLICT", "NovelAI가 현재 요청을 처리할 수 없습니다."),
            429: ("RATE_LIMITED", "NovelAI 요청 제한에 도달했습니다. 잠시 후 직접 다시 시도해 주세요."),
            500: ("NOVELAI_SERVER", "NovelAI 서버 내부 오류가 발생했습니다."),
            502: ("NOVELAI_GATEWAY", "NovelAI 게이트웨이 오류가 발생했습니다."),
            503: ("NOVELAI_UNAVAILABLE", "NovelAI 서비스를 일시적으로 사용할 수 없습니다."),
            504: ("NOVELAI_TIMEOUT", "NovelAI 서버의 처리 시간이 초과되었습니다."),
        }
        code, message = messages.get(
            response.status_code,
            ("NOVELAI_ERROR", f"NovelAI 요청이 실패했습니다. ({response.status_code})"),
        )
        try:
            body = response.json()
            detail = body.get("message") or body.get("error")
            if isinstance(detail, str) and detail:
                message = f"{message} {detail[:240]}"
        except (ValueError, json.JSONDecodeError):
            pass
        raise NovelAIError(code, message, response.status_code)

    @staticmethod
    def compose_prompt(
        quality_prompt: str, description_prompt: str, nsfw_enabled: bool, nsfw_prompt: str = ""
    ) -> str:
        quality = quality_prompt.strip().strip(",").strip()
        description = description_prompt.strip()
        if nsfw_enabled:
            description = re.sub(
                r"^\s*nsfw\s*,\s*uncensored\s*,?\s*",
                "",
                description,
                count=1,
                flags=re.IGNORECASE,
            )
        description = description.strip().strip(",").strip()
        parts = [quality]
        if nsfw_enabled:
            parts.append("nsfw, uncensored")
        parts.append(description)
        if nsfw_enabled:
            parts.append(nsfw_prompt.strip().strip(",").strip())
        return ", ".join(part for part in parts if part)

    @staticmethod
    def compose_negative_prompt(
        quality_negative_prompt: str, description_negative_prompt: str
    ) -> str:
        quality = quality_negative_prompt.strip().strip(",").strip()
        description = description_negative_prompt.strip().strip(",").strip()
        return ", ".join(part for part in (quality, description) if part)

    @staticmethod
    def compose_subject_count_prompt(
        base_prompt: str, characters: list[dict[str, Any]]
    ) -> str:
        counts = {"girl": 0, "boy": 0, "other": 0}
        for character in characters:
            subject_type = character.get("subject_type")
            if subject_type in counts:
                counts[subject_type] += 1

        automatic_tags: list[str] = []
        for subject_type in ("girl", "boy", "other"):
            count = counts[subject_type]
            if count == 0:
                continue
            existing_count = re.search(
                rf"(?<![\w])(?:\d+\+?\s*{subject_type}s?|multiple\s+{subject_type}s)(?![\w])",
                base_prompt,
                flags=re.IGNORECASE,
            )
            if existing_count:
                continue
            if count == 1:
                automatic_tags.append(f"1{subject_type}")
            elif count >= 6:
                automatic_tags.append(f"6+{subject_type}s")
            else:
                automatic_tags.append(f"{count}{subject_type}s")

        prompt = base_prompt.strip().strip(",").strip()
        return ", ".join([*automatic_tags, prompt] if prompt else automatic_tags)

    @staticmethod
    def compose_character_prompt(prompt: str, subject_type: str) -> str:
        character_prompt = prompt.strip().strip(",").strip()
        if subject_type not in {"girl", "boy"}:
            return character_prompt
        subject_tag = f"1{subject_type}"
        if re.search(
            rf"(?<![\w])1\s*{subject_type}(?![\w])",
            character_prompt,
            flags=re.IGNORECASE,
        ):
            return character_prompt
        return ", ".join(part for part in (subject_tag, character_prompt) if part)

    @staticmethod
    def build_generation_payload(
        request_data: dict[str, Any],
        source: bytes | None,
        mask: bytes | None,
        vibes: list[tuple[bytes, float]] | None = None,
        character_references: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        parameters = request_data["parameters"]
        characters = request_data.get("character_snapshot") or []
        base_prompt = NovelAIClient.compose_prompt(
            request_data.get("quality_prompt", ""),
            request_data.get("description_prompt", request_data.get("prompt", "")),
            bool(request_data.get("nsfw_enabled")),
            request_data.get("nsfw_prompt", ""),
        )
        base_prompt = NovelAIClient.compose_subject_count_prompt(base_prompt, characters)
        negative_prompt = NovelAIClient.compose_negative_prompt(
            request_data.get(
                "quality_negative_prompt", request_data.get("negative_prompt", "")
            ),
            request_data.get("description_negative_prompt", ""),
        )

        character_prompts: list[dict[str, Any]] = []
        negative_character_prompts: list[dict[str, Any]] = []
        use_character_coords = False
        for character in characters:
            center = character.get("center")
            if isinstance(center, dict) and isinstance(center.get("x"), (int, float)):
                x = min(1.0, max(0.0, float(center["x"])))
                y = min(1.0, max(0.0, float(center.get("y", 0.5))))
                use_character_coords = True
            else:
                x, y = 0.5, 0.5
            centers = [{"x": x, "y": y}]
            character_prompts.append(
                {
                    "char_caption": NovelAIClient.compose_character_prompt(
                        character["prompt"], str(character.get("subject_type") or "other")
                    ),
                    "centers": centers,
                }
            )
            negative_character_prompts.append(
                {
                    "char_caption": character.get("negative_prompt", ""),
                    "centers": centers,
                }
            )

        seed = parameters.get("seed")
        request_parameters: dict[str, Any] = {
            "params_version": 4,
            "width": parameters["width"],
            "height": parameters["height"],
            "steps": parameters["steps"],
            "scale": parameters["guidance"],
            "sampler": parameters["sampler"],
            "n_samples": parameters["count"],
            "qualityToggle": parameters["quality"],
            "negative_prompt": negative_prompt,
            "ucPreset": 0,
            "cfg_rescale": parameters.get("guidance_rescale", 0.0),
            "controlnet_strength": 1.0,
            "dynamic_thresholding": False,
            "noise_schedule": parameters.get("noise_schedule") or "karras",
            "legacy": False,
            "legacy_v3_extend": False,
            "use_coords": use_character_coords,
            "deliberate_euler_ancestral_bug": False,
            "prefer_brownian": True,
            "tag_hint_qt": 1 if parameters["quality"] else 0,
            "tag_hint_uc_preset": 0,
            "image_format": "png",
            "v4_prompt": {
                "caption": {
                    "base_caption": base_prompt,
                    "char_captions": character_prompts,
                },
                "use_coords": use_character_coords,
                "use_order": True,
                "legacy_uc": False,
            },
            "v4_negative_prompt": {
                "caption": {
                    "base_caption": negative_prompt,
                    "char_captions": negative_character_prompts,
                },
                "use_coords": use_character_coords,
                "use_order": False,
                "legacy_uc": False,
            },
        }
        if seed is not None:
            request_parameters["seed"] = seed
        if vibes:
            # V4+ vibes are pre-encoded per model; Information Extracted is baked into the encoding.
            request_parameters.update(
                {
                    "reference_image_multiple": [
                        base64.b64encode(encoding).decode("ascii") for encoding, _ in vibes
                    ],
                    "reference_strength_multiple": [strength for _, strength in vibes],
                    "normalize_reference_strength_multiple": False,
                }
            )
        if character_references:
            request_parameters.update(
                {
                    "director_reference_images": [
                        base64.b64encode(item["image"]).decode("ascii")
                        for item in character_references
                    ],
                    "director_reference_descriptions": [
                        {
                            "caption": {"base_caption": item["kind"], "char_captions": []},
                            "legacy_uc": False,
                        }
                        for item in character_references
                    ],
                    "director_reference_information_extracted": [1 for _ in character_references],
                    "director_reference_strength_values": [
                        item["strength"] for item in character_references
                    ],
                    # NovelAI's UI "Fidelity" is sent inverted.
                    "director_reference_secondary_strength_values": [
                        round(1 - item["fidelity"], 4) for item in character_references
                    ],
                }
            )

        mode = request_data["mode"]
        action = "generate"
        model = request_data["model"]
        if mode == "img2img":
            action = "img2img"
            request_parameters.update(
                {
                    "image": base64.b64encode(source or b"").decode("ascii"),
                    "strength": parameters["strength"],
                    "noise": parameters["noise"],
                    "extra_noise_seed": seed if seed is not None else 0,
                }
            )
        elif mode == "inpaint":
            action = "infill"
            model = MODELS[model].inpaint_id
            request_parameters.update(
                {
                    "image": base64.b64encode(source or b"").decode("ascii"),
                    "mask": base64.b64encode(mask or b"").decode("ascii"),
                    "strength": parameters["strength"],
                    "noise": parameters["noise"],
                    "add_original_image": False,
                }
            )
        return {
            "input": base_prompt,
            "model": model,
            "action": action,
            "parameters": request_parameters,
            "use_new_shared_trial": True,
        }

    async def _post(
        self, endpoint: str, body: dict[str, Any], correlation_id: str, accept: str = "application/json"
    ) -> httpx.Response:
        headers = {
            **self.headers,
            "Accept": accept,
            "X-Correlation-ID": correlation_id,
            "X-Initiated-At": datetime.now(timezone.utc).isoformat(),
        }
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(240, connect=20)) as client:
                response = await client.post(f"{self.base_url}{endpoint}", headers=headers, json=body)
        except httpx.TimeoutException as exc:
            raise NovelAIError(
                "NETWORK_UNCERTAIN",
                "연결이 끝나기 전에 응답이 끊겼습니다. 중복 과금을 막기 위해 자동 재시도하지 않습니다.",
            ) from exc
        except httpx.RequestError as exc:
            raise NovelAIError("NETWORK", "NovelAI 서버에 연결하지 못했습니다.") from exc
        self._raise_for_status(response)
        return response

    async def encode_vibe(
        self, image: bytes, information_extracted: float, model: str, correlation_id: str
    ) -> bytes:
        response = await self._post(
            "/ai/encode-vibe",
            {
                "image": base64.b64encode(image).decode("ascii"),
                "information_extracted": information_extracted,
                "model": model,
            },
            correlation_id,
            accept="*/*",
        )
        if not response.content:
            raise NovelAIError("EMPTY_RESPONSE", "NovelAI가 바이브 인코딩 없이 응답했습니다.")
        return response.content

    async def augment(
        self, director: dict[str, Any], image: bytes, correlation_id: str
    ) -> list[GeneratedImage]:
        from PIL import Image

        with Image.open(io.BytesIO(image)) as source_image:
            width, height = source_image.size
        tool = director["tool"]
        body: dict[str, Any] = {
            "req_type": tool,
            "width": width,
            "height": height,
            "image": base64.b64encode(image).decode("ascii"),
        }
        if tool == "emotion":
            mood = director.get("emotion") or "neutral"
            body["prompt"] = f"{mood};;{director.get('prompt') or ''}"
            body["defry"] = int(director.get("level") or 0)
        elif tool == "colorize":
            body["prompt"] = director.get("prompt") or ""
            body["defry"] = int(director.get("level") or 0)
        response = await self._post("/ai/augment-image", body, correlation_id, accept="*/*")
        if "json" in response.headers.get("content-type", ""):
            try:
                return self._decode_images(response.json())
            except ValueError as exc:
                raise NovelAIError("INVALID_RESPONSE", "NovelAI 응답을 해석하지 못했습니다.") from exc
        return self._decode_zip(response.content)

    async def generate(
        self,
        request_data: dict[str, Any],
        correlation_id: str,
        source: bytes | None = None,
        mask: bytes | None = None,
        vibes: list[tuple[bytes, float]] | None = None,
        character_references: list[dict[str, Any]] | None = None,
    ) -> list[GeneratedImage]:
        if request_data["mode"] == "director":
            return await self.augment(request_data["director"], source or b"", correlation_id)
        if request_data["mode"] == "upscale":
            endpoint = "/ai/upscale"
            body = {
                "image": base64.b64encode(source or b"").decode("ascii"),
                "model": request_data["model"],
            }
        else:
            endpoint = "/ai/generate-image"
            body = self.build_generation_payload(
                request_data, source, mask, vibes=vibes, character_references=character_references
            )
        headers = {
            **self.headers,
            "X-Correlation-ID": correlation_id,
            "X-Initiated-At": datetime.now(timezone.utc).isoformat(),
        }
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(240, connect=20)) as client:
                response = await client.post(f"{self.base_url}{endpoint}", headers=headers, json=body)
        except httpx.TimeoutException as exc:
            raise NovelAIError(
                "NETWORK_UNCERTAIN",
                "연결이 끝나기 전에 응답이 끊겼습니다. 중복 과금을 막기 위해 자동 재시도하지 않습니다.",
            ) from exc
        except httpx.RequestError as exc:
            raise NovelAIError("NETWORK", "NovelAI 서버에 연결하지 못했습니다.") from exc
        self._raise_for_status(response)
        try:
            payload = response.json()
        except ValueError as exc:
            raise NovelAIError("INVALID_RESPONSE", "NovelAI 응답이 JSON 형식이 아닙니다.") from exc
        return self._decode_images(payload)
