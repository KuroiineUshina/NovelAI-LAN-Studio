from __future__ import annotations

import base64

import httpx
import pytest
import respx

from backend.app.novelai import NovelAIClient, NovelAIError


def request_data(mode: str = "txt2img") -> dict:
    return {
        "mode": mode,
        "model": "nai-diffusion-5-full",
        "quality_prompt": "masterpiece, best quality",
        "description_prompt": "night city",
        "quality_negative_prompt": "blurry, lowres",
        "description_negative_prompt": "empty street",
        "nsfw_enabled": False,
        "character_snapshot": [
            {
                "subject_type": "girl",
                "prompt": "girl, silver hair",
                "negative_prompt": "red hair",
                "tag_id": "tag-1",
            }
        ],
        "parameters": {
            "width": 1024,
            "height": 1024,
            "steps": 28,
            "guidance": 5,
            "guidance_rescale": 0.25,
            "sampler": "k_euler_ancestral",
            "count": 1,
            "quality": True,
            "seed": 123,
            "strength": 0.7,
            "noise": 0.2,
        },
    }


def test_native_character_payload_and_modes(icon_bytes: bytes):
    text_payload = NovelAIClient.build_generation_payload(request_data(), None, None)
    params = text_payload["parameters"]
    assert text_payload["action"] == "generate"
    assert text_payload["input"] == "1girl, masterpiece, best quality, night city"
    assert text_payload["use_new_shared_trial"] is True
    assert params["params_version"] == 4
    assert params["v4_prompt"]["caption"]["char_captions"][0]["char_caption"] == (
        "1girl, girl, silver hair"
    )
    assert params["v4_prompt"]["caption"]["base_caption"] == (
        "1girl, masterpiece, best quality, night city"
    )
    assert params["v4_prompt"]["caption"]["char_captions"][0]["centers"] == [{"x": 0.5, "y": 0.5}]
    assert params["v4_negative_prompt"]["caption"]["char_captions"][0]["char_caption"] == "red hair"
    assert params["v4_negative_prompt"]["caption"]["char_captions"][0]["centers"] == [{"x": 0.5, "y": 0.5}]
    assert params["v4_prompt"]["use_order"] is True
    assert params["v4_negative_prompt"]["use_order"] is False
    assert params["v4_negative_prompt"]["legacy_uc"] is False
    assert params["negative_prompt"] == "blurry, lowres, empty street"
    assert params["v4_negative_prompt"]["caption"]["base_caption"] == "blurry, lowres, empty street"
    assert params["deliberate_euler_ancestral_bug"] is False
    assert params["prefer_brownian"] is True
    assert params["noise_schedule"] == "karras"
    assert params["cfg_rescale"] == 0.25

    img_payload = NovelAIClient.build_generation_payload(request_data("img2img"), icon_bytes, None)
    assert img_payload["action"] == "img2img"
    assert base64.b64decode(img_payload["parameters"]["image"]) == icon_bytes

    inpaint_payload = NovelAIClient.build_generation_payload(request_data("inpaint"), icon_bytes, icon_bytes)
    assert inpaint_payload["action"] == "infill"
    assert inpaint_payload["model"] == "nai-diffusion-5-full-inpainting"
    assert base64.b64decode(inpaint_payload["parameters"]["mask"]) == icon_bytes


def test_nsfw_prefix_is_added_only_to_outbound_payload():
    data = request_data()
    data["nsfw_enabled"] = True

    payload = NovelAIClient.build_generation_payload(data, None, None)
    expected = "1girl, masterpiece, best quality, nsfw, uncensored, night city"
    assert payload["input"] == expected
    assert payload["parameters"]["v4_prompt"]["caption"]["base_caption"] == expected
    assert data["quality_prompt"] == "masterpiece, best quality"
    assert data["description_prompt"] == "night city"

    data["description_prompt"] = "NSFW, uncensored, night city"
    payload = NovelAIClient.build_generation_payload(data, None, None)
    assert payload["input"] == expected


def test_legacy_single_prompt_payload_still_works():
    data = request_data()
    data.pop("quality_prompt")
    data.pop("description_prompt")
    data["prompt"] = "legacy prompt"
    assert NovelAIClient.build_generation_payload(data, None, None)["input"] == (
        "1girl, legacy prompt"
    )


def test_subject_counts_are_derived_from_selected_character_types():
    data = request_data()
    data["character_snapshot"].append(
        {
            "subject_type": "boy",
            "prompt": "boy, blond hair",
            "negative_prompt": "",
            "tag_id": "tag-2",
        }
    )

    payload = NovelAIClient.build_generation_payload(data, None, None)

    assert payload["input"] == "1girl, 1boy, masterpiece, best quality, night city"
    assert data["quality_prompt"] == "masterpiece, best quality"
    assert data["description_prompt"] == "night city"


def test_character_caption_binds_each_subject_type_without_duplicate_tag():
    assert NovelAIClient.compose_character_prompt("검은 머리", "boy") == (
        "1boy, 검은 머리"
    )
    assert NovelAIClient.compose_character_prompt("1girl, 분홍 머리", "girl") == (
        "1girl, 분홍 머리"
    )
    assert NovelAIClient.compose_character_prompt("푸른 구체", "other") == "푸른 구체"


def test_character_centers_enable_coordinate_conditioning():
    data = request_data()
    data["character_snapshot"][0]["center"] = {"x": 0.333, "y": 0.5}
    data["character_snapshot"].append(
        {
            "subject_type": "boy",
            "prompt": "boy, blond hair",
            "negative_prompt": "black hair",
            "tag_id": "tag-2",
            "center": {"x": 0.667, "y": 0.5},
        }
    )

    payload = NovelAIClient.build_generation_payload(data, None, None)
    params = payload["parameters"]

    assert params["use_coords"] is True
    assert params["v4_prompt"]["use_coords"] is True
    assert params["v4_negative_prompt"]["use_coords"] is True
    assert params["v4_prompt"]["caption"]["char_captions"][0]["centers"] == [
        {"x": 0.333, "y": 0.5}
    ]
    assert params["v4_prompt"]["caption"]["char_captions"][1]["centers"] == [
        {"x": 0.667, "y": 0.5}
    ]


def test_subject_counts_pluralize_and_cap_at_six_plus():
    data = request_data()
    data["character_snapshot"] = [
        {
            "subject_type": "girl",
            "prompt": f"girl, hair color {index}",
            "negative_prompt": "",
            "tag_id": f"tag-{index}",
        }
        for index in range(6)
    ]

    payload = NovelAIClient.build_generation_payload(data, None, None)

    assert payload["input"].startswith("6+girls, ")


def test_manual_subject_count_overrides_automatic_count_for_that_type():
    data = request_data()
    data["description_prompt"] = "2girls, night city"
    data["character_snapshot"].append(
        {
            "subject_type": "boy",
            "prompt": "boy, blond hair",
            "negative_prompt": "",
            "tag_id": "tag-2",
        }
    )

    payload = NovelAIClient.build_generation_payload(data, None, None)

    assert payload["input"] == (
        "1boy, masterpiece, best quality, 2girls, night city"
    )
    assert payload["input"].count("2girls") == 1


def test_legacy_single_negative_prompt_payload_still_works():
    data = request_data()
    data.pop("quality_negative_prompt")
    data.pop("description_negative_prompt")
    data["negative_prompt"] = "legacy negative"
    payload = NovelAIClient.build_generation_payload(data, None, None)
    assert payload["parameters"]["negative_prompt"] == "legacy negative"


@pytest.mark.asyncio
@respx.mock
async def test_anlas_status_combines_subscription_and_paid_balance():
    route = respx.get("https://image.novelai.net/user/subscription").mock(
        return_value=httpx.Response(
            200,
            json={
                "active": True,
                "tier": 3,
                "expiresAt": 1_800_000_000,
                "trainingStepsLeft": {
                    "fixedTrainingStepsLeft": 5_780,
                    "purchasedTrainingSteps": 120,
                },
                "usage": {
                    "percent": 63,
                    "isNegative": False,
                    "timeUntilNextPercent": 7_888,
                },
            },
        )
    )
    result = await NovelAIClient("pst-test").get_anlas_status()
    assert route.call_count == 1
    assert result["tier_name"] == "Opus"
    assert result["subscription_anlas"] == 5_780
    assert result["paid_anlas"] == 120
    assert result["remaining_anlas"] == 5_900
    assert result["usage_percent"] == 63
    assert result["usage_is_negative"] is False
    assert "pst-test" not in str(result)


@pytest.mark.asyncio
@respx.mock
async def test_generate_decodes_json_once_without_retry(icon_bytes: bytes):
    route = respx.post("https://image.novelai.net/ai/generate-image").mock(
        return_value=httpx.Response(
            201,
            json={"images": [{"image": base64.b64encode(icon_bytes).decode(), "seed": 321}]},
        )
    )
    outputs = await NovelAIClient("pst-test").generate(request_data(), "ABC123")
    assert route.call_count == 1
    assert route.calls[0].request.headers["x-initiated-at"]
    assert outputs[0].data == icon_bytes
    assert outputs[0].seed == 321


@pytest.mark.asyncio
@respx.mock
async def test_server_failure_is_not_retried():
    route = respx.post("https://image.novelai.net/ai/generate-image").mock(
        return_value=httpx.Response(500, json={"message": "temporary"})
    )
    with pytest.raises(NovelAIError) as error:
        await NovelAIClient("pst-test").generate(request_data(), "ABC123")
    assert error.value.code == "NOVELAI_SERVER"
    assert route.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_upscale_uses_dedicated_endpoint(icon_bytes: bytes):
    route = respx.post("https://image.novelai.net/ai/upscale").mock(
        return_value=httpx.Response(
            200,
            json={"images": [{"image": base64.b64encode(icon_bytes).decode(), "seed": None}]},
        )
    )
    outputs = await NovelAIClient("pst-test").generate(
        request_data("upscale"), "UP1234", source=icon_bytes
    )
    assert route.call_count == 1
    sent = route.calls[0].request
    assert sent.headers["x-correlation-id"] == "UP1234"
    assert outputs[0].data == icon_bytes


def test_sampler_and_noise_schedule_reach_novelai_and_default_to_consistent_settings():
    from backend.app.schemas import GenerationParameters

    defaults = GenerationParameters()
    assert defaults.sampler == "k_dpmpp_2m"
    assert defaults.noise_schedule == "karras"

    data = request_data()
    data["parameters"].update({"sampler": "k_dpmpp_2m_sde", "noise_schedule": "exponential"})
    params = NovelAIClient.build_generation_payload(data, None, None)["parameters"]
    assert params["sampler"] == "k_dpmpp_2m_sde"
    assert params["noise_schedule"] == "exponential"

    with pytest.raises(ValueError):
        GenerationParameters(noise_schedule="linear")
