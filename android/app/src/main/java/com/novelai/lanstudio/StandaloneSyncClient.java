package com.novelai.lanstudio;

import android.content.Context;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.BufferedInputStream;
import java.io.BufferedOutputStream;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.UUID;

public final class StandaloneSyncClient implements AutoCloseable {
    public static final String COOKIE_PREFIX = "pc_device_cookie:";

    private final SecureSecretStore secrets;
    private final ApiProfileStore profiles;
    private final StandaloneDatabase database;
    private final StandaloneImageStore imageStore;

    public StandaloneSyncClient(Context context, ApiProfileStore profiles) {
        Context app = context.getApplicationContext();
        this.secrets = new SecureSecretStore(app);
        this.profiles = profiles;
        this.database = new StandaloneDatabase(app);
        this.imageStore = new StandaloneImageStore(app);
    }

    public SyncResult syncAll() {
        cleanupExpired();
        JSONArray savedProfiles = profiles.listSafe();
        Set<String> visitedServers = new HashSet<>();
        int images = 0;
        int online = 0;
        String lastMessage = "저장된 PC 연결 정보가 없습니다.";
        for (int index = 0; index < savedProfiles.length(); index++) {
            JSONObject profile = savedProfiles.optJSONObject(index);
            if (profile == null) continue;
            String serverUrl = profile.optString("server_url", "");
            String serverId = profile.optString("server_id", "");
            if (serverUrl.isEmpty() || serverId.isEmpty() || !visitedServers.add(serverId)) continue;
            String cookie = secrets.get(COOKIE_PREFIX + serverUrl);
            if (cookie == null || cookie.isEmpty()) {
                lastMessage = "PC 연결 승인이 만료되어 다시 연결해야 합니다.";
                continue;
            }
            try {
                JSONObject status = getJson(serverUrl + "/api/status", cookie);
                if (!status.optBoolean("device_authorized", false)) {
                    lastMessage = "PC에서 이 기기를 다시 승인해야 합니다.";
                    continue;
                }
                online++;
                JSONObject snapshot = getJson(serverUrl + "/api/mobile/standalone-snapshot", cookie);
                if (!serverId.equals(snapshot.optString("server_id"))) {
                    lastMessage = "API 프로필의 원본 PC와 현재 PC가 일치하지 않습니다.";
                    continue;
                }
                mergeSnapshot(serverId, snapshot);
                boolean pendingChanges = false;
                boolean failed = false;

                for (StandaloneDatabase.StoredImage image : database.unsyncedImages(serverId, 100)) {
                    int response = uploadImage(serverUrl, cookie, image);
                    if (response >= 200 && response < 300) {
                        if (database.markSynced(image)) images++;
                        else pendingChanges = true;
                    } else {
                        String message = "PC 이미지 동기화 실패 (" + response + ")";
                        database.markSyncError(image.id, message);
                        lastMessage = message;
                        failed = true;
                        break;
                    }
                }
                if (!failed) lastMessage = pendingChanges
                    ? "동기화 중 추가된 변경은 다음 동기화에 전송됩니다."
                    : "동기화 완료";
            } catch (IOException | JSONException error) {
                lastMessage = safeMessage(error);
            }
        }
        return new SyncResult(online, images, lastMessage);
    }

    private void mergeSnapshot(String serverId, JSONObject snapshot) {
        database.saveSnapshot(serverId, snapshot);
    }

    public void cleanupExpired() {
        long now = System.currentTimeMillis();
        for (StandaloneDatabase.StoredImage image : database.expiredImages(now)) {
            imageStore.delete(image);
            database.deleteImage(image.id);
        }
    }

    private JSONObject getJson(String url, String cookie) throws IOException, JSONException {
        HttpURLConnection connection = open(url, "GET", cookie, null);
        int status = connection.getResponseCode();
        byte[] body = readLimited(
            status >= 400 ? connection.getErrorStream() : connection.getInputStream(),
            32 * 1024 * 1024
        );
        connection.disconnect();
        if (status < 200 || status >= 300) throw new IOException(errorFor(status, body));
        return new JSONObject(new String(body, StandardCharsets.UTF_8));
    }

    private int uploadImage(
        String server,
        String cookie,
        StandaloneDatabase.StoredImage image
    ) throws IOException, JSONException {
        String boundary = "----NovelAILANStudio" + UUID.randomUUID().toString().replace("-", "");
        HttpURLConnection connection = open(
            server + "/api/mobile-sync/images",
            "POST",
            cookie,
            "multipart/form-data; boundary=" + boundary
        );
        connection.setChunkedStreamingMode(65_536);
        JSONObject metadata = image.toJson()
            .put("mobile_image_id", image.id)
            .put("favorite", image.favoriteAt != null);
        metadata.remove("width");
        metadata.remove("height");
        metadata.remove("expires_at");
        metadata.remove("favorite_at");
        metadata.remove("synced");
        metadata.remove("sync_error");
        byte[] metadataBytes = metadata.toString().getBytes(StandardCharsets.UTF_8);
        try (BufferedOutputStream output = new BufferedOutputStream(connection.getOutputStream())) {
            write(output, "--" + boundary + "\r\n");
            write(output, "Content-Disposition: form-data; name=\"metadata\"\r\n");
            write(output, "Content-Type: application/json; charset=UTF-8\r\n\r\n");
            output.write(metadataBytes);
            write(output, "\r\n--" + boundary + "\r\n");
            write(output, "Content-Disposition: form-data; name=\"file\"; filename=\"" + image.id + ".png\"\r\n");
            write(output, "Content-Type: " + image.mimeType + "\r\n\r\n");
            try (BufferedInputStream file = new BufferedInputStream(new FileInputStream(new File(image.filePath)))) {
                byte[] buffer = new byte[65_536];
                int count;
                while ((count = file.read(buffer)) >= 0) output.write(buffer, 0, count);
            }
            write(output, "\r\n--" + boundary + "--\r\n");
            output.flush();
        }
        int status = connection.getResponseCode();
        readLimited(status >= 400 ? connection.getErrorStream() : connection.getInputStream(), 1_048_576);
        connection.disconnect();
        return status;
    }

    private static HttpURLConnection open(
        String url,
        String method,
        String cookie,
        String contentType
    ) throws IOException {
        HttpURLConnection connection = (HttpURLConnection) new URL(url).openConnection();
        connection.setRequestMethod(method);
        connection.setConnectTimeout(6_000);
        connection.setReadTimeout("GET".equals(method) ? 15_000 : 90_000);
        connection.setInstanceFollowRedirects(false);
        connection.setRequestProperty("Accept", "application/json");
        connection.setRequestProperty("User-Agent", "NovelAI-LAN-Studio-Android");
        if (cookie != null && !cookie.isEmpty()) connection.setRequestProperty("Cookie", cookie);
        if (contentType != null) {
            connection.setDoOutput(true);
            connection.setRequestProperty("Content-Type", contentType);
        }
        return connection;
    }

    private static void write(OutputStream output, String value) throws IOException {
        output.write(value.getBytes(StandardCharsets.UTF_8));
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

    private static String errorFor(int status, byte[] body) {
        try {
            JSONObject payload = new JSONObject(new String(body, StandardCharsets.UTF_8));
            String detail = payload.optString("detail", "");
            if (!detail.isEmpty()) return detail;
        } catch (JSONException ignored) { }
        return status == 401
            ? "PC에서 이 기기를 다시 승인해야 합니다."
            : "PC 서버 응답 오류 (" + status + ")";
    }

    private static String safeMessage(Exception error) {
        String message = error.getMessage();
        return message == null || message.trim().isEmpty() ? "동기화하지 못했습니다." : message;
    }

    @Override
    public void close() {
        database.close();
    }

    public static final class SyncResult {
        public final int onlineServers;
        public final int synchronizedImages;
        public final String message;

        SyncResult(int onlineServers, int synchronizedImages, String message) {
            this.onlineServers = onlineServers;
            this.synchronizedImages = synchronizedImages;
            this.message = message;
        }

        public JSONObject toJson() throws JSONException {
            return new JSONObject()
                .put("online_servers", onlineServers)
                .put("synchronized_images", synchronizedImages)
                .put("message", message);
        }
    }
}
