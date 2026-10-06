from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .config import MAX_IMAGE_DIMENSION, MODELS


SubjectType = Literal["girl", "boy", "other"]
GenerationMode = Literal["txt2img", "img2img", "inpaint", "upscale"]
NoiseSchedule = Literal["karras", "exponential", "polyexponential"]


class CharacterPresetInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    tag_name: str = Field(min_length=1, max_length=80)
    subject_type: SubjectType = "girl"
    prompt: str = Field(min_length=1, max_length=8_000)
    negative_prompt: str = Field(default="", max_length=8_000)
    sort_order: int = Field(default=0, ge=-10_000, le=10_000)

    @field_validator("name", "tag_name", "prompt", "negative_prompt")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()


class StorageDirectoryInput(BaseModel):
    directory: str = Field(min_length=1, max_length=2_048)

    @field_validator("directory")
    @classmethod
    def strip_directory(cls, value: str) -> str:
        return value.strip()


class QualityPromptPresetInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    prompt: str = Field(min_length=1, max_length=32_000)
    # Empty means "this preset does not manage the quality negative".
    negative_prompt: str = Field(default="", max_length=32_000)
    sort_order: int = Field(default=0, ge=-10_000, le=10_000)

    @field_validator("name", "prompt", "negative_prompt")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()


class CharacterSetInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    preset_ids: list[str] = Field(min_length=2, max_length=22)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        return value.strip()

    @field_validator("preset_ids")
    @classmethod
    def validate_preset_ids(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value]
        if any(not item for item in normalized):
            raise ValueError("비어 있는 인물 프리셋 ID가 있습니다.")
        if len(set(normalized)) != len(normalized):
            raise ValueError("인물 세트에 같은 인물을 중복으로 넣을 수 없습니다.")
        return normalized


class DiscordWebhookInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    url: str = Field(min_length=1, max_length=2_048)

    @field_validator("name", "url")
    @classmethod
    def strip_webhook_text(cls, value: str) -> str:
        return value.strip()


class DiscordWebhookUpdateInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    url: str | None = Field(default=None, max_length=2_048)

    @field_validator("name")
    @classmethod
    def strip_webhook_name(cls, value: str) -> str:
        return value.strip()

    @field_validator("url", mode="before")
    @classmethod
    def empty_webhook_url_is_none(cls, value: Any) -> Any:
        if value is None:
            return None
        stripped = str(value).strip()
        return stripped or None


class DiscordSendInput(BaseModel):
    webhook_id: str = Field(min_length=1, max_length=80)
    include_tags: bool = True
    include_metadata: bool = False

    @field_validator("webhook_id")
    @classmethod
    def strip_webhook_id(cls, value: str) -> str:
        return value.strip()


class GenerationParameters(BaseModel):
    width: int = Field(default=1024, ge=64, le=MAX_IMAGE_DIMENSION)
    height: int = Field(default=1024, ge=64, le=MAX_IMAGE_DIMENSION)
    steps: int = Field(default=28, ge=1, le=50)
    guidance: float = Field(default=5.0, ge=0.1, le=20)
    guidance_rescale: float = Field(default=0.0, ge=0, le=1)
    # DPM++ 2M + karras is deterministic for a given seed, so results stay consistent.
    sampler: str = Field(default="k_dpmpp_2m", min_length=1, max_length=80)
    noise_schedule: NoiseSchedule = "karras"
    quality: bool = True
    count: int = Field(default=1, ge=1, le=4)
    seed: int | None = Field(default=None, ge=0, le=4_294_967_295)
    strength: float = Field(default=0.7, ge=0, le=1)
    noise: float = Field(default=0.2, ge=0, le=1)


class GenerationRequest(BaseModel):
    mode: GenerationMode
    repeat_count: int = Field(default=1, ge=1, le=100, strict=True)
    model: str = "nai-diffusion-5-full"
    quality_prompt: str = Field(default="", max_length=32_000)
    description_prompt: str = Field(default="", max_length=32_000)
    quality_negative_prompt: str = Field(default="", max_length=32_000)
    description_negative_prompt: str = Field(default="", max_length=32_000)
    nsfw_enabled: bool = False
    character_preset_ids: list[str] = Field(default_factory=list)
    source_asset_id: str | None = None
    mask_asset_id: str | None = None
    parameters: GenerationParameters = Field(default_factory=GenerationParameters)

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_prompt(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        migrated = dict(value)
        if "description_prompt" not in migrated:
            migrated["description_prompt"] = migrated.get("prompt", "")
        if (
            "quality_negative_prompt" not in migrated
            and "description_negative_prompt" not in migrated
        ):
            migrated["quality_negative_prompt"] = migrated.get("negative_prompt", "")
            migrated["description_negative_prompt"] = ""
        migrated.pop("negative_prompt", None)
        return migrated

    @field_validator(
        "quality_prompt",
        "description_prompt",
        "quality_negative_prompt",
        "description_negative_prompt",
    )
    @classmethod
    def strip_prompt(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_mode(self) -> "GenerationRequest":
        if self.model not in MODELS:
            raise ValueError("지원하지 않는 모델입니다.")
        if self.mode != "upscale" and not self.description_prompt:
            raise ValueError("묘사 프롬프트를 입력해 주세요.")
        if self.mode in {"img2img", "inpaint", "upscale"} and not self.source_asset_id:
            raise ValueError("원본 이미지가 필요합니다.")
        if self.mode == "inpaint" and not self.mask_asset_id:
            raise ValueError("인페인트 마스크가 필요합니다.")
        if self.mode == "txt2img" and (self.source_asset_id or self.mask_asset_id):
            raise ValueError("텍스트 생성에는 원본 또는 마스크를 사용할 수 없습니다.")
        if self.mode == "upscale" and self.parameters.count != 1:
            raise ValueError("업스케일은 한 번에 한 장만 처리할 수 있습니다.")
        model = MODELS[self.model]
        if len(self.character_preset_ids) > model.max_characters:
            raise ValueError(f"{model.label}은 인물을 최대 {model.max_characters}명까지 지원합니다.")
        return self


class TokenInput(BaseModel):
    token: str = Field(min_length=8, max_length=4_096)

    @field_validator("token")
    @classmethod
    def strip_token(cls, value: str) -> str:
        return value.strip()


class AutostartInput(BaseModel):
    enabled: bool


class GenerationDraft(BaseModel):
    schema_version: int = 4
    quality_prompt: str = Field(default="", max_length=32_000)
    description_prompt: str = Field(default="", max_length=32_000)
    quality_preset_id: str | None = Field(default=None, max_length=80)
    quality_negative_prompt: str = Field(default="", max_length=32_000)
    description_negative_prompt: str = Field(default="", max_length=32_000)
    nsfw_enabled: bool = False
    character_preset_ids: list[str] = Field(default_factory=list, max_length=22)
    model: str = "nai-diffusion-5-full"
    parameters: GenerationParameters = Field(default_factory=GenerationParameters)

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_prompt(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        migrated = dict(value)
        if "description_prompt" not in migrated:
            migrated["description_prompt"] = migrated.get("prompt", "")
        if (
            "quality_negative_prompt" not in migrated
            and "description_negative_prompt" not in migrated
        ):
            migrated["quality_negative_prompt"] = migrated.get("negative_prompt", "")
            migrated["description_negative_prompt"] = ""
        migrated.pop("prompt", None)
        migrated.pop("negative_prompt", None)
        migrated["schema_version"] = 4
        return migrated

    @field_validator("model")
    @classmethod
    def validate_model(cls, value: str) -> str:
        if value not in MODELS:
            return "nai-diffusion-5-full"
        return value


class GenerationDraftSyncInput(BaseModel):
    client_id: str = Field(min_length=8, max_length=80, pattern=r"^[A-Za-z0-9._:-]+$")
    draft: GenerationDraft


class DeviceApprovalRequestInput(BaseModel):
    device_id: str = Field(
        min_length=16,
        max_length=80,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )
    display_name: str = Field(min_length=1, max_length=80)
    pairing_secret: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[a-f0-9]{64}$",
    )

    @field_validator("display_name")
    @classmethod
    def strip_display_name(cls, value: str) -> str:
        return value.strip()


class DeviceApprovalPollInput(BaseModel):
    device_id: str = Field(
        min_length=16,
        max_length=80,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )
    pairing_secret: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[a-f0-9]{64}$",
    )


class ApiProfileTransferRequestInput(BaseModel):
    profile_name: str = Field(default="이 PC", min_length=1, max_length=80)
    key_id: str = Field(min_length=8, max_length=120, pattern=r"^[A-Za-z0-9._:-]+$")
    public_key_b64: str = Field(min_length=256, max_length=8_192)

    @field_validator("profile_name")
    @classmethod
    def strip_profile_name(cls, value: str) -> str:
        return value.strip()


class MobileImageSyncMetadata(BaseModel):
    mobile_image_id: str = Field(
        min_length=12,
        max_length=100,
        pattern=r"^android-[A-Za-z0-9-]+$",
    )
    mode: Literal["txt2img"] = "txt2img"
    model: str = Field(min_length=1, max_length=80)
    quality_prompt: str = Field(default="", max_length=32_000)
    description_prompt: str = Field(default="", max_length=32_000)
    quality_negative_prompt: str = Field(default="", max_length=32_000)
    description_negative_prompt: str = Field(default="", max_length=32_000)
    settings: dict[str, Any] = Field(default_factory=dict)
    character_snapshot: list[dict[str, Any]] = Field(default_factory=list, max_length=22)
    tags: list[dict[str, Any]] = Field(default_factory=list, max_length=50)
    seed: int | None = Field(default=None, ge=0, le=4_294_967_295)
    favorite: bool = False
    created_at: str = Field(min_length=10, max_length=80)
    api_profile_id: str | None = Field(default=None, max_length=80)
    origin_server_id: str | None = Field(default=None, max_length=80)
