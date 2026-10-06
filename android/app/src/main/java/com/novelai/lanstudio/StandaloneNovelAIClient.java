package com.novelai.lanstudio;

import android.util.Base64;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.BufferedInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.security.SecureRandom;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.UUID;
import java.util.regex.Pattern;

public final class StandaloneNovelAIClient {
    private static final String BASE_URL = "https://image.novelai.net";
    private static final Pattern NSFW_PREFIX = Pattern.compile(
        "^\\s*nsfw\\s*,\\s*uncensored\\s*,?\\s*",
        Pattern.CASE_INSENSITIVE
    );

    public List<GeneratedImage> generate(String token, JSONObject request)
        throws IOException, JSONException {
        JSONObject payload = buildPayload(request);
        HttpURLConnection connection = open("/ai/generate-image", token, "POST");
        byte[] body = payload.toString().getBytes(StandardCharsets.UTF_8);
        connection.setFixedLengthStreamingMode(body.length);
        try (OutputStream stream = connection.getOutputStream()) {
            stream.write(body);
        }
        int status = connection.getResponseCode();
        byte[] response = readResponse(connection, status);
        connection.disconnect();
        if (status < 200 || status >= 300) throw new IOException(errorMessage(status, response));
        JSONObject decoded = new JSONObject(new String(response, StandardCharsets.UTF_8));
        JSONArray images = decoded.optJSONArray("images");
        if (images == null || images.length() == 0) {
            throw new IOException("NovelAI가 이미지 없이 응답했습니다.");
        }
        List<GeneratedImage> results = new ArrayList<>();
        for (int index = 0; index < images.length(); index++) {
            JSONObject item = images.getJSONObject(index);
            String encoded = item.optString("image", "");
            int comma = encoded.indexOf(',');
            if (encoded.startsWith("data:") && comma >= 0) encoded = encoded.substring(comma + 1);
            byte[] imageBytes;
            try {
                imageBytes = Base64.decode(encoded, Base64.DEFAULT);
            } catch (IllegalArgumentException error) {
                throw new IOException("NovelAI 이미지 응답을 해석하지 못했습니다.", error);
            }
            Long seed = item.has("seed") && !item.isNull("seed") ? item.getLong("seed") : null;
            results.add(new GeneratedImage(imageBytes, seed));
        }
        return results;
    }

    public JSONObject subscription(String token) throws IOException, JSONException {
        HttpURLConnection connection = open("/user/subscription", token, "GET");
        int status = connection.getResponseCode();
        byte[] response = readResponse(connection, status);
        connection.disconnect();
        if (status < 200 || status >= 300) throw new IOException(errorMessage(status, response));
        JSONObject payload = new JSONObject(new String(response, StandardCharsets.UTF_8));
        JSONObject result = new JSONObject()
            .put("active", payload.optBoolean("active", false))
            .put("tier", payload.optInt("tier", 0));
        JSONObject balance = payload.optJSONObject("trainingStepsLeft");
        if (balance != null) {
            result.put("remaining_anlas",
                balance.optLong("fixedTrainingStepsLeft", 0L)
                    + balance.optLong("purchasedTrainingSteps", 0L));
        } else if (payload.has("trainingStepsLeft")) {
            result.put("remaining_anlas", payload.optLong("trainingStepsLeft", 0L));
        } else {
            result.put("remaining_anlas", JSONObject.NULL);
        }
        return result;
    }

    static JSONObject buildPayload(JSONObject request) throws JSONException {
        String model = request.optString("model", "nai-diffusion-5-full");
        if (!(model.equals("nai-diffusion-5-full")
            || model.equals("nai-diffusion-5-curated")
            || model.equals("nai-diffusion-4-5-full")
            || model.equals("nai-diffusion-4-5-curated"))) {
            throw new JSONException("지원하지 않는 모델입니다.");
        }
        JSONObject input = request.optJSONObject("parameters");
        if (input == null) input = new JSONObject();
        int width = input.optInt("width", 1024);
        int height = input.optInt("height", 1024);
        int steps = input.optInt("steps", 28);
        int count = input.optInt("count", 1);
        if (width < 64 || height < 64 || width > 2048 || height > 2048
            || width % 64 != 0 || height % 64 != 0
            || (long) width * (long) height > 3_145_728L) {
            throw new JSONException("이미지 크기는 64 배수이며 최대 약 3.1MP까지 가능합니다.");
        }
        if (steps < 1 || steps > 50 || count < 1 || count > 4) {
            throw new JSONException("단계 또는 생성 수가 지원 범위를 벗어났습니다.");
        }
        boolean nsfw = request.optBoolean("nsfw_enabled", false);
        String prompt = composePrompt(
            request.optString("quality_prompt", ""),
            request.optString("description_prompt", ""),
            nsfw
        );
        if (prompt.isEmpty()) throw new JSONException("묘사 프롬프트를 입력해 주세요.");
        String negativePrompt = composeNegativePrompt(
            request.optString("quality_negative_prompt", request.optString("negative_prompt", "")),
            request.optString("description_negative_prompt", "")
        );
        JSONArray characters = request.optJSONArray("characters");
        if (characters == null) characters = new JSONArray();
        int maximumCharacters = model.startsWith("nai-diffusion-5-") ? 22 : 6;
        if (characters.length() > maximumCharacters) {
            throw new JSONException("선택한 모델의 인물 수 제한을 초과했습니다.");
        }
        prompt = composeSubjectCountPrompt(prompt, characters);

        JSONArray characterPrompts = new JSONArray();
        JSONArray negativeCharacterPrompts = new JSONArray();
        boolean useCharacterCoords = false;
        for (int index = 0; index < characters.length(); index++) {
            JSONObject character = characters.getJSONObject(index);
            JSONObject requestedCenter = character.optJSONObject("center");
            double x = 0.5;
            double y = 0.5;
            if (requestedCenter != null && requestedCenter.has("x")) {
                x = Math.max(0.0, Math.min(1.0, requestedCenter.optDouble("x", 0.5)));
                y = Math.max(0.0, Math.min(1.0, requestedCenter.optDouble("y", 0.5)));
                useCharacterCoords = true;
            }
            JSONArray center = new JSONArray().put(new JSONObject().put("x", x).put("y", y));
            characterPrompts.put(new JSONObject()
                .put(
                    "char_caption",
                    composeCharacterPrompt(
                        character.optString("prompt", ""),
                        character.optString("subject_type", "other")
                    )
                )
                .put("centers", center));
            negativeCharacterPrompts.put(new JSONObject()
                .put("char_caption", character.optString("negative_prompt", ""))
                .put("centers", center));
        }
        long seed = input.has("seed") && !input.isNull("seed")
            ? input.optLong("seed")
            : Integer.toUnsignedLong(new SecureRandom().nextInt());
        boolean quality = input.optBoolean("quality", true);
        JSONObject parameters = new JSONObject()
            .put("params_version", 4)
            .put("width", width)
            .put("height", height)
            .put("steps", steps)
            .put("scale", input.optDouble("guidance", 5.0))
            .put("sampler", input.optString("sampler", "k_euler_ancestral"))
            .put("n_samples", count)
            .put("qualityToggle", quality)
            .put("negative_prompt", negativePrompt)
            .put("ucPreset", 0)
            .put("cfg_rescale", input.optDouble("guidance_rescale", 0.0))
            .put("controlnet_strength", 1.0)
            .put("dynamic_thresholding", false)
            .put("noise_schedule", "karras")
            .put("legacy", false)
            .put("legacy_v3_extend", false)
            .put("use_coords", useCharacterCoords)
            .put("deliberate_euler_ancestral_bug", false)
            .put("prefer_brownian", true)
            .put("tag_hint_qt", quality ? 1 : 0)
            .put("tag_hint_uc_preset", 0)
            .put("image_format", "png")
            .put("seed", seed)
            .put("v4_prompt", new JSONObject()
                .put("caption", new JSONObject()
                    .put("base_caption", prompt)
                    .put("char_captions", characterPrompts))
                .put("use_coords", useCharacterCoords)
                .put("use_order", true)
                .put("legacy_uc", false))
            .put("v4_negative_prompt", new JSONObject()
                .put("caption", new JSONObject()
                    .put("base_caption", negativePrompt)
                    .put("char_captions", negativeCharacterPrompts))
                .put("use_coords", useCharacterCoords)
                .put("use_order", false)
                .put("legacy_uc", false));
        return new JSONObject()
            .put("input", prompt)
            .put("model", model)
            .put("action", "generate")
            .put("parameters", parameters)
            .put("use_new_shared_trial", true);
    }

    public static String composePrompt(String quality, String description, boolean nsfw) {
        String cleanQuality = trimCommas(quality);
        String cleanDescription = description == null ? "" : description.trim();
        if (nsfw) cleanDescription = NSFW_PREFIX.matcher(cleanDescription).replaceFirst("");
        cleanDescription = trimCommas(cleanDescription);
        List<String> parts = new ArrayList<>();
        if (!cleanQuality.isEmpty()) parts.add(cleanQuality);
        if (nsfw) parts.add("nsfw, uncensored");
        if (!cleanDescription.isEmpty()) parts.add(cleanDescription);
        return String.join(", ", parts);
    }

    public static String composeNegativePrompt(String quality, String description) {
        List<String> parts = new ArrayList<>();
        String cleanQuality = trimCommas(quality);
        String cleanDescription = trimCommas(description);
        if (!cleanQuality.isEmpty()) parts.add(cleanQuality);
        if (!cleanDescription.isEmpty()) parts.add(cleanDescription);
        return String.join(", ", parts);
    }

    static String composeSubjectCountPrompt(String prompt, JSONArray characters) {
        String[] subjects = {"girl", "boy", "other"};
        List<String> automatic = new ArrayList<>();
        for (String subject : subjects) {
            int count = 0;
            for (int index = 0; index < characters.length(); index++) {
                JSONObject character = characters.optJSONObject(index);
                if (character != null && subject.equals(character.optString("subject_type"))) count++;
            }
            if (count == 0) continue;
            Pattern existing = Pattern.compile(
                "(?<![\\w])(?:\\d+\\+?\\s*" + subject + "s?|multiple\\s+" + subject + "s)(?![\\w])",
                Pattern.CASE_INSENSITIVE
            );
            if (existing.matcher(prompt).find()) continue;
            automatic.add(count == 1 ? "1" + subject : (count >= 6 ? "6+" + subject + "s" : count + subject + "s"));
        }
        if (prompt != null && !prompt.trim().isEmpty()) automatic.add(prompt.trim());
        return String.join(", ", automatic);
    }

    static String composeCharacterPrompt(String prompt, String subjectType) {
        String normalizedPrompt = trimCommas(prompt);
        if (!("girl".equals(subjectType) || "boy".equals(subjectType))) {
            return normalizedPrompt;
        }
        Pattern existingTag = Pattern.compile(
            "(?<![\\w])1\\s*" + Pattern.quote(subjectType) + "(?![\\w])",
            Pattern.CASE_INSENSITIVE
        );
        if (existingTag.matcher(normalizedPrompt).find()) return normalizedPrompt;
        if (normalizedPrompt.isEmpty()) return "1" + subjectType;
        return "1" + subjectType + ", " + normalizedPrompt;
    }

    private static String trimCommas(String value) {
        return value == null ? "" : value.trim().replaceAll("^,+|,+$", "").trim();
    }

    private static HttpURLConnection open(String path, String token, String method) throws IOException {
        HttpURLConnection connection = (HttpURLConnection) new URL(BASE_URL + path).openConnection();
        connection.setRequestMethod(method);
        connection.setConnectTimeout(20_000);
        connection.setReadTimeout("POST".equals(method) ? 240_000 : 20_000);
        connection.setInstanceFollowRedirects(false);
        connection.setRequestProperty("Authorization", "Bearer " + token);
        connection.setRequestProperty("Accept", "application/json");
        connection.setRequestProperty("X-Correlation-ID", UUID.randomUUID().toString().substring(0, 8));
        connection.setRequestProperty("X-Initiated-At", Instant.now().toString());
        if ("POST".equals(method)) {
            connection.setDoOutput(true);
            connection.setRequestProperty("Content-Type", "application/json");
        }
        return connection;
    }

    private static byte[] readResponse(HttpURLConnection connection, int status) throws IOException {
        InputStream raw = status >= 400 ? connection.getErrorStream() : connection.getInputStream();
        if (raw == null) return new byte[0];
        try (BufferedInputStream stream = new BufferedInputStream(raw);
             ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[16_384];
            int count;
            while ((count = stream.read(buffer)) >= 0) {
                output.write(buffer, 0, count);
                if (output.size() > 80 * 1024 * 1024) {
                    throw new IOException("NovelAI 응답이 모바일 처리 한도를 초과했습니다.");
                }
            }
            return output.toByteArray();
        }
    }

    private static String errorMessage(int status, byte[] response) {
        String base = switch (status) {
            case 400 -> "NovelAI가 생성 설정을 거부했습니다.";
            case 401 -> "저장된 NovelAI API 프로필이 올바르지 않거나 만료되었습니다.";
            case 402 -> "이미지 생성에 필요한 ANLAS가 부족합니다.";
            case 403 -> "현재 계정 또는 구독으로 이 요청을 사용할 수 없습니다.";
            case 429 -> "NovelAI 요청 제한에 도달했습니다. 자동 재시도하지 않습니다.";
            default -> status >= 500
                ? "NovelAI 서버 오류가 발생했습니다. 자동 재시도하지 않습니다."
                : String.format(Locale.ROOT, "NovelAI 요청이 실패했습니다. (%d)", status);
        };
        try {
            JSONObject body = new JSONObject(new String(response, StandardCharsets.UTF_8));
            String detail = body.optString("message", body.optString("error", ""));
            if (!detail.isEmpty()) base += " " + detail.substring(0, Math.min(180, detail.length()));
        } catch (JSONException ignored) { }
        return base;
    }

    public static final class GeneratedImage {
        public final byte[] data;
        public final Long seed;

        GeneratedImage(byte[] data, Long seed) {
            this.data = data;
            this.seed = seed;
        }
    }
}
