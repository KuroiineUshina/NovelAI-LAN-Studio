package com.novelai.lanstudio;

import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.database.sqlite.SQLiteOpenHelper;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.time.Instant;
import java.util.ArrayList;
import java.util.List;

public final class StandaloneDatabase extends SQLiteOpenHelper {
    private static final String DATABASE_NAME = "standalone.db";
    private static final int DATABASE_VERSION = 4;
    public static final long RETENTION_MILLIS = 7L * 24L * 60L * 60L * 1000L;
    static final String IMAGE_ACK_SELECTION = "id=? AND file_path=? AND favorite_at IS ? AND expires_at IS ?";

    public StandaloneDatabase(Context context) {
        super(context, DATABASE_NAME, null, DATABASE_VERSION);
    }

    @Override
    public void onCreate(SQLiteDatabase database) {
        database.execSQL("CREATE TABLE images ("
            + "id TEXT PRIMARY KEY,file_path TEXT NOT NULL,thumbnail_path TEXT NOT NULL,"
            + "mime_type TEXT NOT NULL,width INTEGER NOT NULL,height INTEGER NOT NULL,"
            + "mode TEXT NOT NULL,model TEXT NOT NULL,quality_prompt TEXT NOT NULL,"
            + "description_prompt TEXT NOT NULL,quality_negative_prompt TEXT NOT NULL DEFAULT '',"
            + "description_negative_prompt TEXT NOT NULL DEFAULT '',settings_json TEXT NOT NULL,"
            + "character_snapshot_json TEXT NOT NULL,tags_json TEXT NOT NULL,seed INTEGER,"
            + "api_profile_id TEXT,origin_server_id TEXT,created_at INTEGER NOT NULL,"
            + "expires_at INTEGER,favorite_at INTEGER,synced INTEGER NOT NULL DEFAULT 0,"
            + "sync_error TEXT)");
        database.execSQL("CREATE INDEX idx_mobile_images_created ON images(created_at DESC)");
        database.execSQL("CREATE INDEX idx_mobile_images_expiry ON images(expires_at)");
        database.execSQL("CREATE INDEX idx_mobile_images_sync ON images(synced,created_at)");
        database.execSQL("CREATE TABLE snapshots (server_id TEXT PRIMARY KEY,payload_json TEXT NOT NULL,updated_at INTEGER NOT NULL)");
    }

    @Override
    public void onUpgrade(SQLiteDatabase database, int oldVersion, int newVersion) {
        if (oldVersion < 2) {
            addColumn(database, "images", "quality_negative_prompt", "TEXT NOT NULL DEFAULT ''");
            addColumn(database, "images", "description_negative_prompt", "TEXT NOT NULL DEFAULT ''");
            addColumn(database, "images", "api_profile_id", "TEXT");
            addColumn(database, "images", "origin_server_id", "TEXT");
            database.execSQL("CREATE TABLE IF NOT EXISTS snapshots (server_id TEXT PRIMARY KEY,payload_json TEXT NOT NULL,updated_at INTEGER NOT NULL)");
        }
        if (oldVersion < 4) {
            // Storyteller was removed; generated images stay in the images table.
            database.execSQL("DROP INDEX IF EXISTS idx_mobile_story_server_updated");
            database.execSQL("DROP INDEX IF EXISTS idx_mobile_story_sync");
            database.execSQL("DROP TABLE IF EXISTS story_documents");
        }
    }

    private static void addColumn(SQLiteDatabase database, String table, String name, String type) {
        try {
            database.execSQL("ALTER TABLE " + table + " ADD COLUMN " + name + " " + type);
        } catch (RuntimeException ignored) {
            // The column may already exist after a partially completed migration.
        }
    }

    public synchronized void insertImage(StoredImage image) {
        getWritableDatabase().insertOrThrow("images", null, values(image));
    }

    public synchronized StoredImage getImage(String id) {
        try (Cursor cursor = getReadableDatabase().query(
            "images", null, "id=?", new String[]{id}, null, null, null
        )) {
            return cursor.moveToFirst() ? fromCursor(cursor) : null;
        }
    }

    public synchronized List<StoredImage> listImages(boolean favoritesOnly, int limit) {
        String selection = favoritesOnly ? "favorite_at IS NOT NULL" : "favorite_at IS NULL";
        List<StoredImage> images = new ArrayList<>();
        try (Cursor cursor = getReadableDatabase().query(
            "images", null, selection, null, null, null,
            "created_at DESC", null
        )) {
            int maximum = Math.max(1, Math.min(limit, 500));
            while (cursor.moveToNext() && images.size() < maximum) {
                images.add(fromCursor(cursor));
            }
        }
        return images;
    }

    public synchronized List<StoredImage> unsyncedImages(String serverId, int limit) {
        List<StoredImage> images = new ArrayList<>();
        try (Cursor cursor = getReadableDatabase().query(
            "images", null,
            "synced=0 AND origin_server_id=?",
            new String[]{serverId}, null, null, "created_at ASC",
            Integer.toString(Math.max(1, Math.min(limit, 100)))
        )) {
            while (cursor.moveToNext()) images.add(fromCursor(cursor));
        }
        return images;
    }

    public synchronized int unsyncedImageCount() {
        try (Cursor cursor = getReadableDatabase().rawQuery(
            "SELECT COUNT(*) FROM images WHERE synced=0", null
        )) {
            return cursor.moveToFirst() ? cursor.getInt(0) : 0;
        }
    }

    public synchronized boolean updateFavorite(
        String id,
        String filePath,
        String thumbnailPath,
        boolean favorite,
        long now
    ) {
        ContentValues values = new ContentValues();
        values.put("file_path", filePath);
        values.put("thumbnail_path", thumbnailPath);
        if (favorite) {
            values.put("favorite_at", now);
            values.putNull("expires_at");
        } else {
            values.putNull("favorite_at");
            values.put("expires_at", now + RETENTION_MILLIS);
        }
        values.put("synced", 0);
        values.putNull("sync_error");
        return getWritableDatabase().update("images", values, "id=?", new String[]{id}) > 0;
    }

    public synchronized boolean markSynced(StoredImage uploaded) {
        ContentValues values = new ContentValues();
        values.put("synced", 1);
        values.putNull("sync_error");
        return getWritableDatabase().update("images", values, IMAGE_ACK_SELECTION,
            new String[]{uploaded.id, uploaded.filePath,
                uploaded.favoriteAt == null ? null : uploaded.favoriteAt.toString(),
                uploaded.expiresAt == null ? null : uploaded.expiresAt.toString()}) > 0;
    }

    public synchronized void markSyncError(String id, String message) {
        ContentValues values = new ContentValues();
        String normalized = message == null ? "동기화 실패" : message;
        values.put("sync_error", normalized.substring(0, Math.min(300, normalized.length())));
        getWritableDatabase().update("images", values, "id=?", new String[]{id});
    }

    public synchronized boolean deleteImage(String id) {
        return getWritableDatabase().delete("images", "id=?", new String[]{id}) > 0;
    }

    public synchronized List<StoredImage> expiredImages(long now) {
        List<StoredImage> images = new ArrayList<>();
        try (Cursor cursor = getReadableDatabase().query(
            "images", null,
            "favorite_at IS NULL AND expires_at IS NOT NULL AND expires_at<=?",
            new String[]{Long.toString(now)}, null, null, "expires_at ASC"
        )) {
            while (cursor.moveToNext()) images.add(fromCursor(cursor));
        }
        return images;
    }

    public synchronized void saveSnapshot(String serverId, JSONObject payload) {
        ContentValues values = new ContentValues();
        values.put("server_id", serverId);
        values.put("payload_json", payload.toString());
        values.put("updated_at", System.currentTimeMillis());
        getWritableDatabase().insertWithOnConflict(
            "snapshots", null, values, SQLiteDatabase.CONFLICT_REPLACE
        );
    }

    public synchronized JSONObject getSnapshot(String serverId) {
        if (serverId == null || serverId.isEmpty()) return new JSONObject();
        try (Cursor cursor = getReadableDatabase().query(
            "snapshots", new String[]{"payload_json"}, "server_id=?",
            new String[]{serverId}, null, null, null
        )) {
            if (!cursor.moveToFirst()) return new JSONObject();
            return new JSONObject(cursor.getString(0));
        } catch (JSONException error) {
            return new JSONObject();
        }
    }

    private static ContentValues values(StoredImage image) {
        ContentValues values = new ContentValues();
        values.put("id", image.id);
        values.put("file_path", image.filePath);
        values.put("thumbnail_path", image.thumbnailPath);
        values.put("mime_type", image.mimeType);
        values.put("width", image.width);
        values.put("height", image.height);
        values.put("mode", image.mode);
        values.put("model", image.model);
        values.put("quality_prompt", image.qualityPrompt);
        values.put("description_prompt", image.descriptionPrompt);
        values.put("quality_negative_prompt", image.qualityNegativePrompt);
        values.put("description_negative_prompt", image.descriptionNegativePrompt);
        values.put("settings_json", image.settingsJson);
        values.put("character_snapshot_json", image.characterSnapshotJson);
        values.put("tags_json", image.tagsJson);
        if (image.seed == null) values.putNull("seed"); else values.put("seed", image.seed);
        values.put("api_profile_id", image.apiProfileId);
        values.put("origin_server_id", image.originServerId);
        values.put("created_at", image.createdAt);
        if (image.expiresAt == null) values.putNull("expires_at"); else values.put("expires_at", image.expiresAt);
        if (image.favoriteAt == null) values.putNull("favorite_at"); else values.put("favorite_at", image.favoriteAt);
        values.put("synced", image.synced ? 1 : 0);
        if (image.syncError == null) values.putNull("sync_error"); else values.put("sync_error", image.syncError);
        return values;
    }

    private static StoredImage fromCursor(Cursor cursor) {
        StoredImage image = new StoredImage();
        image.id = cursor.getString(cursor.getColumnIndexOrThrow("id"));
        image.filePath = cursor.getString(cursor.getColumnIndexOrThrow("file_path"));
        image.thumbnailPath = cursor.getString(cursor.getColumnIndexOrThrow("thumbnail_path"));
        image.mimeType = cursor.getString(cursor.getColumnIndexOrThrow("mime_type"));
        image.width = cursor.getInt(cursor.getColumnIndexOrThrow("width"));
        image.height = cursor.getInt(cursor.getColumnIndexOrThrow("height"));
        image.mode = cursor.getString(cursor.getColumnIndexOrThrow("mode"));
        image.model = cursor.getString(cursor.getColumnIndexOrThrow("model"));
        image.qualityPrompt = cursor.getString(cursor.getColumnIndexOrThrow("quality_prompt"));
        image.descriptionPrompt = cursor.getString(cursor.getColumnIndexOrThrow("description_prompt"));
        image.qualityNegativePrompt = cursor.getString(cursor.getColumnIndexOrThrow("quality_negative_prompt"));
        image.descriptionNegativePrompt = cursor.getString(cursor.getColumnIndexOrThrow("description_negative_prompt"));
        image.settingsJson = cursor.getString(cursor.getColumnIndexOrThrow("settings_json"));
        image.characterSnapshotJson = cursor.getString(cursor.getColumnIndexOrThrow("character_snapshot_json"));
        image.tagsJson = cursor.getString(cursor.getColumnIndexOrThrow("tags_json"));
        image.seed = nullableLong(cursor, "seed");
        image.apiProfileId = cursor.getString(cursor.getColumnIndexOrThrow("api_profile_id"));
        image.originServerId = cursor.getString(cursor.getColumnIndexOrThrow("origin_server_id"));
        image.createdAt = cursor.getLong(cursor.getColumnIndexOrThrow("created_at"));
        image.expiresAt = nullableLong(cursor, "expires_at");
        image.favoriteAt = nullableLong(cursor, "favorite_at");
        image.synced = cursor.getInt(cursor.getColumnIndexOrThrow("synced")) == 1;
        image.syncError = cursor.getString(cursor.getColumnIndexOrThrow("sync_error"));
        return image;
    }

    private static Long nullableLong(Cursor cursor, String name) {
        int index = cursor.getColumnIndexOrThrow(name);
        return cursor.isNull(index) ? null : cursor.getLong(index);
    }

    public static final class StoredImage {
        public String id;
        public String filePath;
        public String thumbnailPath;
        public String mimeType = "image/png";
        public int width;
        public int height;
        public String mode = "txt2img";
        public String model = "nai-diffusion-5-full";
        public String qualityPrompt = "";
        public String descriptionPrompt = "";
        public String qualityNegativePrompt = "";
        public String descriptionNegativePrompt = "";
        public String settingsJson = "{}";
        public String characterSnapshotJson = "[]";
        public String tagsJson = "[]";
        public Long seed;
        public String apiProfileId;
        public String originServerId;
        public long createdAt;
        public Long expiresAt;
        public Long favoriteAt;
        public boolean synced;
        public String syncError;

        public JSONObject toJson() throws JSONException {
            return new JSONObject()
                .put("id", id)
                .put("mime_type", mimeType)
                .put("width", width)
                .put("height", height)
                .put("mode", mode)
                .put("model", model)
                .put("quality_prompt", qualityPrompt)
                .put("description_prompt", descriptionPrompt)
                .put("quality_negative_prompt", qualityNegativePrompt)
                .put("description_negative_prompt", descriptionNegativePrompt)
                .put("settings", new JSONObject(settingsJson))
                .put("character_snapshot", new JSONArray(characterSnapshotJson))
                .put("tags", new JSONArray(tagsJson))
                .put("seed", seed == null ? JSONObject.NULL : seed)
                .put("api_profile_id", apiProfileId == null ? JSONObject.NULL : apiProfileId)
                .put("origin_server_id", originServerId == null ? JSONObject.NULL : originServerId)
                .put("created_at", Instant.ofEpochMilli(createdAt).toString())
                .put("expires_at", expiresAt == null ? JSONObject.NULL : Instant.ofEpochMilli(expiresAt).toString())
                .put("favorite_at", favoriteAt == null ? JSONObject.NULL : Instant.ofEpochMilli(favoriteAt).toString())
                .put("synced", synced)
                .put("sync_error", syncError == null ? JSONObject.NULL : syncError);
        }
    }
}
