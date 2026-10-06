package com.novelai.lanstudio;

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
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;

public final class ApiProfileProvisioner {
    public interface Listener {
        void onEvent(JSONObject event);
    }

    private final ApiProfileStore profileStore;
    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private final AtomicBoolean running = new AtomicBoolean(false);

    public ApiProfileProvisioner(ApiProfileStore profileStore) {
        this.profileStore = profileStore;
    }

    public boolean request(
        String rawServerUrl,
        String cookie,
        String profileName,
        Listener listener
    ) {
        if (!running.compareAndSet(false, true)) return false;
        executor.execute(() -> {
            try {
                String server = ServerAddress.normalize(rawServerUrl);
                JSONObject body = new JSONObject()
                    .put("profile_name", normalizeName(profileName))
                    .put("key_id", ApiProfileStore.KEY_ID)
                    .put("public_key_b64", profileStore.publicKeyBase64());
                JSONObject requested = requestJson(
                    server + "/api/mobile/api-profiles/requests",
                    "POST",
                    cookie,
                    body
                );
                notify(listener, new JSONObject()
                    .put("state", "pending")
                    .put("request_id", requested.getString("id"))
                    .put("verification_code", requested.getString("verification_code"))
                    .put("profile_name", requested.optString("profile_name", "이 PC")));

                String requestId = requested.getString("id");
                long deadline = System.currentTimeMillis() + 10 * 60 * 1000L;
                while (!Thread.currentThread().isInterrupted() && System.currentTimeMillis() < deadline) {
                    Thread.sleep(2_000L);
                    JSONObject polled = requestJson(
                        server + "/api/mobile/api-profiles/requests/" + requestId,
                        "GET",
                        cookie,
                        null
                    );
                    String status = polled.optString("status", "pending");
                    if ("pending".equals(status)) continue;
                    if ("approved".equals(status)) {
                        JSONObject profile = profileStore.addApprovedProfile(polled, server);
                        notify(listener, new JSONObject()
                            .put("state", "approved")
                            .put("profile", profile));
                    } else {
                        notify(listener, new JSONObject().put("state", status));
                    }
                    return;
                }
                notify(listener, new JSONObject().put("state", "expired"));
            } catch (InterruptedException interrupted) {
                Thread.currentThread().interrupt();
            } catch (Exception error) {
                try {
                    notify(listener, new JSONObject()
                        .put("state", "error")
                        .put("error", safeMessage(error)));
                } catch (JSONException ignored) {
                    // No further delivery path is available.
                }
            } finally {
                running.set(false);
            }
        });
        return true;
    }

    public boolean isRunning() {
        return running.get();
    }

    public void shutdown() {
        executor.shutdownNow();
    }

    private static JSONObject requestJson(
        String url,
        String method,
        String cookie,
        JSONObject body
    ) throws IOException, JSONException {
        HttpURLConnection connection = (HttpURLConnection) new URL(url).openConnection();
        connection.setRequestMethod(method);
        connection.setConnectTimeout(6_000);
        connection.setReadTimeout(10_000);
        connection.setInstanceFollowRedirects(false);
        connection.setRequestProperty("Accept", "application/json");
        connection.setRequestProperty("User-Agent", "NovelAI-LAN-Studio-Android");
        if (cookie != null && !cookie.isEmpty()) connection.setRequestProperty("Cookie", cookie);
        if (body != null) {
            connection.setDoOutput(true);
            connection.setRequestProperty("Content-Type", "application/json; charset=UTF-8");
            try (OutputStream output = connection.getOutputStream()) {
                output.write(body.toString().getBytes(StandardCharsets.UTF_8));
            }
        }
        int status = connection.getResponseCode();
        byte[] response = readLimited(
            status >= 400 ? connection.getErrorStream() : connection.getInputStream(),
            1_048_576
        );
        connection.disconnect();
        JSONObject payload = response.length == 0
            ? new JSONObject()
            : new JSONObject(new String(response, StandardCharsets.UTF_8));
        if (status < 200 || status >= 300) {
            throw new IOException(payload.optString("detail", "PC 승인 요청 실패 (" + status + ")"));
        }
        return payload;
    }

    private static byte[] readLimited(InputStream raw, int limit) throws IOException {
        if (raw == null) return new byte[0];
        try (BufferedInputStream input = new BufferedInputStream(raw);
             ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[8192];
            int count;
            while ((count = input.read(buffer)) >= 0) {
                output.write(buffer, 0, count);
                if (output.size() > limit) throw new IOException("PC 응답이 너무 큽니다.");
            }
            return output.toByteArray();
        }
    }

    private static String normalizeName(String value) {
        String normalized = value == null ? "" : value.trim();
        return normalized.isEmpty() ? "이 PC" : normalized.substring(0, Math.min(80, normalized.length()));
    }

    private static void notify(Listener listener, JSONObject event) {
        if (listener != null) listener.onEvent(event);
    }

    private static String safeMessage(Exception error) {
        String message = error.getMessage();
        return message == null || message.trim().isEmpty()
            ? "API 프로필을 저장하지 못했습니다."
            : message;
    }
}
