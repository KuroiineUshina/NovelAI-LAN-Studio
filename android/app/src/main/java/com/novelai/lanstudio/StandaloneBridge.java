package com.novelai.lanstudio;

import android.net.Uri;
import android.webkit.JavascriptInterface;
import android.webkit.WebResourceResponse;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.ByteArrayInputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.util.Collections;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;

public final class StandaloneBridge {
    private static final String DRAFT_PREFIX = "standalone_draft:";
    private final MainActivity activity;
    private final ApiProfileStore profiles;
    private final SecureSecretStore secrets;
    private final StandaloneDatabase database;
    private final StandaloneImageStore imageStore;
    private final StandaloneNovelAIClient imageClient = new StandaloneNovelAIClient();
    private final ExecutorService generationExecutor = Executors.newSingleThreadExecutor();
    private final ExecutorService syncExecutor = Executors.newSingleThreadExecutor();
    private final AtomicBoolean syncRunning = new AtomicBoolean(false);

    public StandaloneBridge(MainActivity activity, ApiProfileStore profiles) {
        this.activity = activity;
        this.profiles = profiles;
        this.secrets = new SecureSecretStore(activity.getApplicationContext());
        this.database = new StandaloneDatabase(activity.getApplicationContext());
        this.imageStore = new StandaloneImageStore(activity.getApplicationContext());
    }

    @JavascriptInterface
    public String bootstrap() {
        try (StandaloneSyncClient client = new StandaloneSyncClient(
            activity.getApplicationContext(), profiles
        )) {
            client.cleanupExpired();
        }
        JSONObject active = profiles.activeProfileSafe();
        String serverId = active == null ? "" : active.optString("server_id", "");
        JSONObject snapshot = database.getSnapshot(serverId);
        JSONObject draft = parseObject(
            secrets.get(DRAFT_PREFIX + profiles.activeId()),
            snapshot.optJSONObject("generation_draft") == null
                ? defaultDraft()
                : snapshot.optJSONObject("generation_draft").optJSONObject("draft")
        );
        JSONObject result = new JSONObject();
        try {
            result.put("profiles", profiles.listSafe());
            result.put("active_profile", active == null ? JSONObject.NULL : active);
            result.put("snapshot", snapshot);
            result.put("draft", draft);
            result.put("pending_images", database.unsyncedImageCount());
        } catch (JSONException ignored) { }
        return result.toString();
    }

    @JavascriptInterface
    public String listProfiles() {
        return profiles.listSafe().toString();
    }

    @JavascriptInterface
    public boolean setActiveProfile(String profileId) {
        return profiles.setActive(profileId);
    }

    @JavascriptInterface
    public boolean renameProfile(String profileId, String name) {
        return profiles.rename(profileId, name);
    }

    @JavascriptInterface
    public boolean deleteProfile(String profileId) {
        return profiles.delete(profileId);
    }

    @JavascriptInterface
    public void saveDraft(String rawDraft) {
        try {
            JSONObject draft = new JSONObject(rawDraft);
            secrets.put(DRAFT_PREFIX + profiles.activeId(), draft.toString());
        } catch (JSONException ignored) { }
    }

    @JavascriptInterface
    public void generate(String rawRequest) {
        generationExecutor.execute(() -> {
            JSONObject callback = new JSONObject();
            try {
                String token = profiles.activeToken();
                JSONObject profile = requireActiveProfile(token);
                JSONObject request = new JSONObject(rawRequest);
                List<StandaloneNovelAIClient.GeneratedImage> outputs = imageClient.generate(token, request);
                JSONArray created = new JSONArray();
                long now = System.currentTimeMillis();
                for (StandaloneNovelAIClient.GeneratedImage output : outputs) {
                    String id = "android-" + UUID.randomUUID();
                    StandaloneImageStore.SavedImage saved = imageStore.saveGenerated(output.data, id);
                    StandaloneDatabase.StoredImage image = new StandaloneDatabase.StoredImage();
                    image.id = id;
                    image.filePath = saved.filePath;
                    image.thumbnailPath = saved.thumbnailPath;
                    image.mimeType = saved.mimeType;
                    image.width = saved.width;
                    image.height = saved.height;
                    image.model = request.optString("model", "nai-diffusion-5-full");
                    image.qualityPrompt = request.optString("quality_prompt", "");
                    image.descriptionPrompt = request.optString("description_prompt", "");
                    image.qualityNegativePrompt = request.optString("quality_negative_prompt", "");
                    image.descriptionNegativePrompt = request.optString("description_negative_prompt", "");
                    JSONObject settings = request.optJSONObject("parameters") == null
                        ? new JSONObject()
                        : new JSONObject(request.getJSONObject("parameters").toString());
                    settings.put("nsfw_enabled", request.optBoolean("nsfw_enabled", false));
                    if (output.seed != null) settings.put("seed", output.seed);
                    image.settingsJson = settings.toString();
                    JSONArray characters = request.optJSONArray("characters");
                    image.characterSnapshotJson = characters == null ? "[]" : characters.toString();
                    image.tagsJson = tagsFromCharacters(characters).toString();
                    image.seed = output.seed;
                    image.apiProfileId = profile.optString("id", "");
                    image.originServerId = profile.optString("server_id", "");
                    image.createdAt = now;
                    image.expiresAt = now + StandaloneDatabase.RETENTION_MILLIS;
                    image.favoriteAt = null;
                    image.synced = false;
                    try {
                        database.insertImage(image);
                    } catch (RuntimeException error) {
                        imageStore.delete(image);
                        throw error;
                    }
                    created.put(decorateImage(image));
                }
                secrets.put(DRAFT_PREFIX + profiles.activeId(), request.toString());
                callback.put("ok", true).put("images", created);
            } catch (Exception error) {
                putError(callback, error);
            }
            activity.runStandaloneScript("window.Standalone.onGenerationResult(" + callback + ")");
            if (callback.optBoolean("ok")) queueSync(false);
        });
    }

    @JavascriptInterface
    public String listImages(String folder, boolean nsfwOnly) {
        JSONArray result = new JSONArray();
        boolean favorites = "favorites".equals(folder);
        for (StandaloneDatabase.StoredImage image : database.listImages(favorites, 500)) {
            try {
                if (nsfwOnly && !new JSONObject(image.settingsJson).optBoolean("nsfw_enabled")) continue;
                result.put(decorateImage(image));
            } catch (JSONException ignored) { }
        }
        return result.toString();
    }

    @JavascriptInterface
    public String toggleFavorite(String imageId) {
        JSONObject result = new JSONObject();
        StandaloneDatabase.StoredImage image = database.getImage(imageId);
        try {
            if (image == null) throw new IOException("이미지를 찾을 수 없습니다.");
            boolean favorite = image.favoriteAt == null;
            StandaloneImageStore.SavedPaths paths = imageStore.moveFavorite(image, favorite);
            if (!database.updateFavorite(
                image.id, paths.filePath, paths.thumbnailPath, favorite,
                System.currentTimeMillis()
            )) throw new IOException("이미지 상태를 저장하지 못했습니다.");
            result.put("ok", true).put("favorite", favorite);
            queueSync(false);
        } catch (Exception error) {
            putError(result, error);
        }
        return result.toString();
    }

    @JavascriptInterface
    public void downloadImage(String imageId) {
        downloadImageWithMetadata(imageId, true);
    }

    @JavascriptInterface
    public void downloadImageWithMetadata(String imageId, boolean preserveMetadata) {
        StandaloneDatabase.StoredImage image = database.getImage(imageId);
        if (image != null) {
            activity.downloadStandaloneImage(
                new File(image.filePath),
                "novelai-" + image.id + (preserveMetadata
                    ? ("image/jpeg".equals(image.mimeType) ? ".jpg" : "image/webp".equals(image.mimeType) ? ".webp" : ".png")
                    : "-no-metadata.png"),
                preserveMetadata ? image.mimeType : "image/png",
                !preserveMetadata
            );
        }
    }

    @JavascriptInterface
    public void refreshAccount() {
        generationExecutor.execute(() -> {
            JSONObject result = new JSONObject();
            try {
                String token = profiles.activeToken();
                requireActiveProfile(token);
                result.put("ok", true).put("account", imageClient.subscription(token));
            } catch (Exception error) {
                putError(result, error);
            }
            activity.runStandaloneScript("window.Standalone.onAccountResult(" + result + ")");
        });
    }

    @JavascriptInterface
    public void syncNow() {
        queueSync(true);
    }

    void foregroundSync() {
        queueSync(false);
    }

    @JavascriptInterface
    public void exitStandalone() {
        activity.leaveStandaloneMode();
    }

    WebResourceResponse imageResponse(String rawUrl) {
        try {
            Uri uri = Uri.parse(rawUrl);
            List<String> segments = uri.getPathSegments();
            if (segments.size() != 2 || !"local-image".equals(segments.get(0))) return missingImage();
            StandaloneDatabase.StoredImage image = database.getImage(segments.get(1));
            if (image == null) return missingImage();
            boolean full = "1".equals(uri.getQueryParameter("full"));
            File file = new File(full ? image.filePath : image.thumbnailPath);
            if (!file.isFile()) return missingImage();
            return new WebResourceResponse(
                full ? image.mimeType : "image/jpeg",
                null,
                200,
                "OK",
                Collections.singletonMap("Cache-Control", "private, max-age=60"),
                new FileInputStream(file)
            );
        } catch (Exception error) {
            return missingImage();
        }
    }

    void shutdown() {
        generationExecutor.shutdownNow();
        syncExecutor.shutdownNow();
        database.close();
    }

    private void queueSync(boolean notifyWeb) {
        if (!syncRunning.compareAndSet(false, true)) return;
        syncExecutor.execute(() -> {
            try (StandaloneSyncClient client = new StandaloneSyncClient(
                activity.getApplicationContext(), profiles
            )) {
                StandaloneSyncClient.SyncResult sync = client.syncAll();
                if (notifyWeb) {
                    activity.runStandaloneScript("window.Standalone.onSyncResult(" + sync.toJson() + ")");
                }
            } catch (Exception ignored) {
                // A later explicit or foreground sync will retry idempotent PC transfers.
            } finally {
                syncRunning.set(false);
            }
        });
    }

    private JSONObject requireActiveProfile(String token) throws IOException {
        JSONObject profile = profiles.activeProfileSafe();
        if (profile == null || token == null || token.isEmpty()) {
            throw new IOException("PC에서 승인받은 API 프로필을 선택해 주세요.");
        }
        return profile;
    }

    private static JSONArray tagsFromCharacters(JSONArray characters) throws JSONException {
        JSONArray tags = new JSONArray();
        if (characters == null) return tags;
        for (int index = 0; index < characters.length(); index++) {
            JSONObject character = characters.optJSONObject(index);
            if (character == null) continue;
            String id = character.optString("tag_id", "");
            String name = character.optString("tag_name", "");
            if (!id.isEmpty() && !name.isEmpty()) {
                tags.put(new JSONObject().put("id", id).put("name", name));
            }
        }
        return tags;
    }

    private static JSONObject decorateImage(StandaloneDatabase.StoredImage image) throws JSONException {
        return image.toJson()
            .put("content_url", "https://standalone.novelai-lan-studio.invalid/local-image/" + image.id + "?full=1")
            .put("thumbnail_url", "https://standalone.novelai-lan-studio.invalid/local-image/" + image.id);
    }

    private static JSONObject defaultDraft() {
        try {
            return new JSONObject()
                .put("schema_version", 4)
                .put("quality_prompt", "")
                .put("description_prompt", "")
                .put("quality_negative_prompt", "")
                .put("description_negative_prompt", "")
                .put("nsfw_enabled", false)
                .put("character_preset_ids", new JSONArray())
                .put("model", "nai-diffusion-5-full")
                .put("parameters", new JSONObject()
                    .put("width", 1024).put("height", 1024).put("steps", 28)
                    .put("guidance", 5).put("guidance_rescale", 0)
                    .put("sampler", "k_euler_ancestral").put("quality", true)
                    .put("count", 1).put("seed", JSONObject.NULL));
        } catch (JSONException impossible) {
            return new JSONObject();
        }
    }

    private static JSONObject parseObject(String value, JSONObject fallback) {
        if (fallback == null) fallback = defaultDraft();
        try { return value == null ? fallback : new JSONObject(value); }
        catch (JSONException error) { return fallback; }
    }

    private static void putError(JSONObject target, Exception error) {
        try {
            String message = error.getMessage();
            target.put("ok", false).put(
                "error",
                message == null || message.trim().isEmpty() ? "요청을 처리하지 못했습니다." : message
            );
        } catch (JSONException ignored) { }
    }

    private static WebResourceResponse missingImage() {
        return new WebResourceResponse(
            "text/plain", "UTF-8", 404, "Not Found",
            Collections.emptyMap(),
            new ByteArrayInputStream(new byte[0])
        );
    }
}
