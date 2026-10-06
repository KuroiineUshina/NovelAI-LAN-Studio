package com.novelai.lanstudio;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;

public final class StandaloneNovelAIClientTest {
    @Test
    public void payloadMatchesDesktopPromptSeparationAndCharacterCounting() throws Exception {
        JSONObject request = new JSONObject()
            .put("model", "nai-diffusion-5-full")
            .put("quality_prompt", "best quality")
            .put("description_prompt", "rainy station")
            .put("quality_negative_prompt", "lowres")
            .put("description_negative_prompt", "daylight")
            .put("nsfw_enabled", true)
            .put("parameters", new JSONObject()
                .put("width", 832)
                .put("height", 1216)
                .put("steps", 28)
                .put("count", 1)
                .put("guidance", 5)
                .put("guidance_rescale", 0.2)
                .put("sampler", "k_euler_ancestral")
                .put("quality", true)
                .put("seed", 42))
            .put("characters", new JSONArray().put(new JSONObject()
                .put("subject_type", "girl")
                .put("prompt", "adult woman, black hair")
                .put("negative_prompt", "child")));

        JSONObject payload = StandaloneNovelAIClient.buildPayload(request);
        assertEquals("1girl, best quality, nsfw, uncensored, rainy station", payload.getString("input"));
        JSONObject parameters = payload.getJSONObject("parameters");
        assertEquals("lowres, daylight", parameters.getString("negative_prompt"));
        assertEquals(42L, parameters.getLong("seed"));
        assertEquals(1, parameters.getJSONObject("v4_prompt")
            .getJSONObject("caption").getJSONArray("char_captions").length());
        assertEquals("1girl, adult woman, black hair", parameters.getJSONObject("v4_prompt")
            .getJSONObject("caption").getJSONArray("char_captions")
            .getJSONObject(0).getString("char_caption"));
        assertTrue(parameters.getJSONObject("v4_negative_prompt")
            .getJSONObject("caption").getJSONArray("char_captions")
            .getJSONObject(0).getString("char_caption").contains("child"));
    }

    @Test
    public void explicitSubjectCountIsNotDuplicated() throws Exception {
        JSONArray characters = new JSONArray()
            .put(new JSONObject().put("subject_type", "girl"))
            .put(new JSONObject().put("subject_type", "girl"));
        assertEquals(
            "2girls, classroom",
            StandaloneNovelAIClient.composeSubjectCountPrompt("2girls, classroom", characters)
        );
    }

    @Test
    public void characterCaptionBindsSubjectTypeWithoutDuplicateTag() {
        assertEquals(
            "1boy, 검은 머리",
            StandaloneNovelAIClient.composeCharacterPrompt("검은 머리", "boy")
        );
        assertEquals(
            "1girl, 분홍 머리",
            StandaloneNovelAIClient.composeCharacterPrompt("1girl, 분홍 머리", "girl")
        );
        assertEquals(
            "푸른 구체",
            StandaloneNovelAIClient.composeCharacterPrompt("푸른 구체", "other")
        );
    }

    @Test
    public void characterCentersEnableCoordinateConditioning() throws Exception {
        JSONArray characters = new JSONArray()
            .put(new JSONObject()
                .put("subject_type", "girl")
                .put("prompt", "adult woman, black hair")
                .put("center", new JSONObject().put("x", 0.333).put("y", 0.5)))
            .put(new JSONObject()
                .put("subject_type", "boy")
                .put("prompt", "adult man, blond hair")
                .put("center", new JSONObject().put("x", 0.667).put("y", 0.5)));
        JSONObject request = new JSONObject()
            .put("model", "nai-diffusion-5-full")
            .put("description_prompt", "two people at a rainy station")
            .put("parameters", new JSONObject()
                .put("width", 832)
                .put("height", 1216)
                .put("steps", 28)
                .put("count", 1))
            .put("characters", characters);

        JSONObject parameters = StandaloneNovelAIClient.buildPayload(request)
            .getJSONObject("parameters");

        assertTrue(parameters.getBoolean("use_coords"));
        assertTrue(parameters.getJSONObject("v4_prompt").getBoolean("use_coords"));
        assertEquals(
            0.333,
            parameters.getJSONObject("v4_prompt").getJSONObject("caption")
                .getJSONArray("char_captions").getJSONObject(0)
                .getJSONArray("centers").getJSONObject(0).getDouble("x"),
            0.0001
        );
        assertEquals(
            0.667,
            parameters.getJSONObject("v4_prompt").getJSONObject("caption")
                .getJSONArray("char_captions").getJSONObject(1)
                .getJSONArray("centers").getJSONObject(0).getDouble("x"),
            0.0001
        );
    }
}
