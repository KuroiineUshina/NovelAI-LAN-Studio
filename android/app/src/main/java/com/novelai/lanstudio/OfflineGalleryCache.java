package com.novelai.lanstudio;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.BufferedInputStream;
import java.io.BufferedOutputStream;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.nio.file.AtomicMoveNotSupportedException;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Pattern;

public final class OfflineGalleryCache {
    private static final int MAX_METADATA_BYTES = 8 * 1024 * 1024;
    private static final int MAX_IMAGE_BYTES = 64 * 1024 * 1024;
    private static final Pattern SAFE_ID = Pattern.compile("[A-Za-z0-9_-]{1,128}");

    private final File rootDirectory;
    private final File imagesDirectory;
    private final File metadataFile;
    private final Object stateLock = new Object();

    private Map<String, CachedEntry> entries = new LinkedHashMap<>();
    private long lastSyncedAt;

    public OfflineGalleryCache(File applicationFilesDirectory) {
        rootDirectory = new File(applicationFilesDirectory, "offline-gallery");
        imagesDirectory = new File(rootDirectory, "images");
        metadataFile = new File(rootDirectory, "metadata.json");
        ensureDirectory(imagesDirectory);
        loadMetadata();
    }

    public boolean hasImages() {
        synchronized (stateLock) {
            return !entries.isEmpty();
        }
    }

    public int getImageCount() {
        synchronized (stateLock) {
            return entries.size();
        }
    }

    public long getLastSyncedAt() {
        synchronized (stateLock) {
            return lastSyncedAt;
        }
    }

    public File getImageFile(String id) {
        if (!isSafeId(id)) {
            return null;
        }
        synchronized (stateLock) {
            if (!entries.containsKey(id)) {
                return null;
            }
        }
        File file = fileForId(id);
        return file.isFile() && file.length() > 0 ? file : null;
    }

    public String getMimeType(String id) {
        synchronized (stateLock) {
            CachedEntry entry = entries.get(id);
            return entry == null ? "application/octet-stream" : entry.mimeType;
        }
    }

    public String getDownloadFileName(String id) {
        return "NovelAI-LAN-Studio-" + id + extensionForMimeType(getMimeType(id));
    }

    public String metadataJson() {
        synchronized (stateLock) {
            return buildMetadata(entries, lastSyncedAt).toString();
        }
    }

    public synchronized SyncResult sync(String baseUrl, String cookie, String userAgent)
        throws IOException, JSONException {
        LinkedHashMap<String, RemoteEntry> remoteEntries = new LinkedHashMap<>();
        collectRemoteEntries(baseUrl, cookie, userAgent, false, remoteEntries);
        collectRemoteEntries(baseUrl, cookie, userAgent, true, remoteEntries);

        long previousSync;
        LinkedHashMap<String, CachedEntry> progressEntries;
        synchronized (stateLock) {
            previousSync = lastSyncedAt;
            progressEntries = new LinkedHashMap<>(entries);
        }
        for (RemoteEntry remote : remoteEntries.values()) {
            File destination = fileForId(remote.cached.id);
            if (destination.isFile() && destination.length() > 0) {
                progressEntries.put(remote.cached.id, remote.cached);
            }
        }
        persistProgress(progressEntries, previousSync);

        int downloaded = 0;
        for (RemoteEntry remote : remoteEntries.values()) {
            File destination = fileForId(remote.cached.id);
            if (!destination.isFile() || destination.length() == 0) {
                downloadImage(baseUrl, remote.contentUrl, cookie, userAgent, destination);
                downloaded += 1;
                progressEntries.put(remote.cached.id, remote.cached);
                if (downloaded == 1 || downloaded % 10 == 0) {
                    persistProgress(progressEntries, previousSync);
                }
            }
        }

        LinkedHashMap<String, CachedEntry> nextEntries = new LinkedHashMap<>();
        for (RemoteEntry remote : remoteEntries.values()) {
            nextEntries.put(remote.cached.id, remote.cached);
        }
        long syncedAt = System.currentTimeMillis();
        writeMetadata(nextEntries, syncedAt);

        int removed = removeStaleImages(nextEntries);
        synchronized (stateLock) {
            entries = nextEntries;
            lastSyncedAt = syncedAt;
        }
        return new SyncResult(downloaded, removed, nextEntries.size());
    }

    private void persistProgress(
        LinkedHashMap<String, CachedEntry> progressEntries,
        long completedSyncAt
    ) throws IOException {
        writeMetadata(progressEntries, completedSyncAt);
        synchronized (stateLock) {
            entries = new LinkedHashMap<>(progressEntries);
            lastSyncedAt = completedSyncAt;
        }
    }

    static JSONObject sanitizeServerItem(JSONObject source, boolean favorite)
        throws JSONException {
        String id = source.getString("id");
        if (!isSafeId(id)) {
            throw new JSONException("unsafe image id");
        }
        JSONObject cached = new JSONObject();
        cached.put("id", id);
        cached.put("mime_type", normalizeMimeType(source.optString("mime_type")));
        cached.put("width", Math.max(1, source.optInt("width", 1)));
        cached.put("height", Math.max(1, source.optInt("height", 1)));
        cached.put("created_at", source.optString("created_at", ""));
        cached.put("favorite", favorite);
        JSONArray tagNames = new JSONArray();
        JSONArray tags = source.optJSONArray("tags");
        if (tags != null) {
            for (int index = 0; index < tags.length(); index++) {
                JSONObject tag = tags.optJSONObject(index);
                if (tag == null) {
                    continue;
                }
                String name = tag.optString("name", "").trim();
                if (!name.isEmpty()) {
                    tagNames.put(name);
                }
            }
        }
        cached.put("tags", tagNames);
        return cached;
    }

    private void collectRemoteEntries(
        String baseUrl,
        String cookie,
        String userAgent,
        boolean favorite,
        LinkedHashMap<String, RemoteEntry> output
    ) throws IOException, JSONException {
        for (int page = 1; page <= 10_000; page++) {
            String endpoint = baseUrl + "/api/mobile/offline-gallery?favorite=" + favorite + "&page=" + page;
            JSONObject response = requestJson(endpoint, cookie, userAgent);
            JSONArray items = response.optJSONArray("items");
            if (items == null || items.length() == 0) {
                return;
            }
            for (int index = 0; index < items.length(); index++) {
                JSONObject source = items.getJSONObject(index);
                CachedEntry cached = CachedEntry.fromJson(sanitizeServerItem(source, favorite));
                output.put(cached.id, new RemoteEntry(cached, source.getString("content_url")));
            }
            int total = Math.max(items.length(), response.optInt("total", items.length()));
            int pageSize = Math.max(1, response.optInt("page_size", items.length()));
            if (page * pageSize >= total) {
                return;
            }
        }
        throw new IOException("offline gallery pagination exceeded safety limit");
    }

    private static JSONObject requestJson(String url, String cookie, String userAgent)
        throws IOException, JSONException {
        HttpURLConnection connection = openConnection(url, cookie, userAgent);
        try {
            int status = connection.getResponseCode();
            if (status != HttpURLConnection.HTTP_OK) {
                throw new IOException("offline gallery metadata request failed: " + status);
            }
            try (InputStream input = new BufferedInputStream(connection.getInputStream())) {
                return new JSONObject(readUtf8(input, MAX_METADATA_BYTES));
            }
        } finally {
            connection.disconnect();
        }
    }

    private static void downloadImage(
        String baseUrl,
        String relativeUrl,
        String cookie,
        String userAgent,
        File destination
    ) throws IOException {
        URL base = new URL(baseUrl + "/");
        URL resolved = new URL(base, relativeUrl);
        if (!base.getProtocol().equalsIgnoreCase(resolved.getProtocol())
            || !base.getHost().equalsIgnoreCase(resolved.getHost())
            || effectivePort(base) != effectivePort(resolved)) {
            throw new IOException("offline image URL escaped the connected server");
        }

        HttpURLConnection connection = openConnection(resolved.toString(), cookie, userAgent);
        File temporary = new File(destination.getParentFile(), destination.getName() + ".part");
        if (temporary.exists()) {
            temporary.delete();
        }
        try {
            int status = connection.getResponseCode();
            if (status != HttpURLConnection.HTTP_OK) {
                throw new IOException("offline image request failed: " + status);
            }
            long declaredLength = connection.getContentLengthLong();
            if (declaredLength > MAX_IMAGE_BYTES) {
                throw new IOException("offline image exceeded the cache size limit");
            }
            long written = 0;
            try (
                InputStream input = new BufferedInputStream(connection.getInputStream());
                FileOutputStream fileOutput = new FileOutputStream(temporary);
                BufferedOutputStream output = new BufferedOutputStream(fileOutput)
            ) {
                byte[] buffer = new byte[64 * 1024];
                int read;
                while ((read = input.read(buffer)) != -1) {
                    written += read;
                    if (written > MAX_IMAGE_BYTES) {
                        throw new IOException("offline image exceeded the cache size limit");
                    }
                    output.write(buffer, 0, read);
                }
                output.flush();
                fileOutput.getFD().sync();
            }
            if (written == 0) {
                throw new IOException("offline image response was empty");
            }
            moveReplacing(temporary, destination);
        } finally {
            connection.disconnect();
            if (temporary.exists()) {
                temporary.delete();
            }
        }
    }

    private static HttpURLConnection openConnection(
        String url,
        String cookie,
        String userAgent
    ) throws IOException {
        HttpURLConnection connection = (HttpURLConnection) new URL(url).openConnection();
        connection.setRequestMethod("GET");
        connection.setConnectTimeout(5_000);
        connection.setReadTimeout(30_000);
        connection.setInstanceFollowRedirects(false);
        connection.setRequestProperty("Accept", "application/json, image/*");
        if (cookie != null && !cookie.isEmpty()) {
            connection.setRequestProperty("Cookie", cookie);
        }
        if (userAgent != null && !userAgent.isEmpty()) {
            connection.setRequestProperty("User-Agent", userAgent);
        }
        return connection;
    }

    private void loadMetadata() {
        if (!metadataFile.isFile()) {
            return;
        }
        try (InputStream input = new FileInputStream(metadataFile)) {
            JSONObject root = new JSONObject(readUtf8(input, MAX_METADATA_BYTES));
            JSONArray items = root.optJSONArray("items");
            LinkedHashMap<String, CachedEntry> loaded = new LinkedHashMap<>();
            if (items != null) {
                for (int index = 0; index < items.length(); index++) {
                    CachedEntry entry = CachedEntry.fromJson(items.getJSONObject(index));
                    File file = fileForId(entry.id);
                    if (file.isFile() && file.length() > 0) {
                        loaded.put(entry.id, entry);
                    }
                }
            }
            synchronized (stateLock) {
                entries = loaded;
                lastSyncedAt = root.optLong("last_synced_at", 0);
            }
        } catch (Exception ignored) {
            synchronized (stateLock) {
                entries = new LinkedHashMap<>();
                lastSyncedAt = 0;
            }
        }
    }

    private void writeMetadata(Map<String, CachedEntry> nextEntries, long syncedAt)
        throws IOException {
        ensureDirectory(rootDirectory);
        File temporary = new File(rootDirectory, "metadata.json.part");
        byte[] data = buildMetadata(nextEntries, syncedAt)
            .toString()
            .getBytes(StandardCharsets.UTF_8);
        try (FileOutputStream output = new FileOutputStream(temporary)) {
            output.write(data);
            output.flush();
            output.getFD().sync();
        }
        moveReplacing(temporary, metadataFile);
    }

    private static JSONObject buildMetadata(
        Map<String, CachedEntry> source,
        long syncedAt
    ) {
        JSONObject root = new JSONObject();
        JSONArray items = new JSONArray();
        List<CachedEntry> sorted = new ArrayList<>(source.values());
        sorted.sort(Comparator.comparing((CachedEntry item) -> item.createdAt).reversed());
        try {
            root.put("schema_version", 1);
            root.put("last_synced_at", syncedAt);
            for (CachedEntry entry : sorted) {
                items.put(entry.toJson());
            }
            root.put("items", items);
        } catch (JSONException error) {
            throw new IllegalStateException(error);
        }
        return root;
    }

    private int removeStaleImages(Map<String, CachedEntry> retained) {
        File[] files = imagesDirectory.listFiles();
        if (files == null) {
            return 0;
        }
        int removed = 0;
        for (File file : files) {
            String name = file.getName();
            if (!name.endsWith(".image")) {
                continue;
            }
            String id = name.substring(0, name.length() - ".image".length());
            if (!retained.containsKey(id) && file.delete()) {
                removed += 1;
            }
        }
        return removed;
    }

    private File fileForId(String id) {
        return new File(imagesDirectory, id + ".image");
    }

    private static String readUtf8(InputStream input, int limit) throws IOException {
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        byte[] buffer = new byte[16 * 1024];
        int total = 0;
        int read;
        while ((read = input.read(buffer)) != -1) {
            total += read;
            if (total > limit) {
                throw new IOException("response exceeded safety limit");
            }
            output.write(buffer, 0, read);
        }
        return output.toString(StandardCharsets.UTF_8.name());
    }

    private static void ensureDirectory(File directory) {
        if (!directory.isDirectory() && !directory.mkdirs() && !directory.isDirectory()) {
            throw new IllegalStateException("failed to create offline gallery directory");
        }
    }

    private static void moveReplacing(File source, File destination) throws IOException {
        try {
            Files.move(
                source.toPath(),
                destination.toPath(),
                StandardCopyOption.ATOMIC_MOVE,
                StandardCopyOption.REPLACE_EXISTING
            );
        } catch (AtomicMoveNotSupportedException error) {
            Files.move(
                source.toPath(),
                destination.toPath(),
                StandardCopyOption.REPLACE_EXISTING
            );
        }
    }

    private static boolean isSafeId(String value) {
        return value != null && SAFE_ID.matcher(value).matches();
    }

    private static String normalizeMimeType(String value) {
        if ("image/jpeg".equalsIgnoreCase(value)) {
            return "image/jpeg";
        }
        if ("image/webp".equalsIgnoreCase(value)) {
            return "image/webp";
        }
        return "image/png";
    }

    private static String extensionForMimeType(String mimeType) {
        if ("image/jpeg".equalsIgnoreCase(mimeType)) {
            return ".jpg";
        }
        if ("image/webp".equalsIgnoreCase(mimeType)) {
            return ".webp";
        }
        return ".png";
    }

    private static int effectivePort(URL url) {
        if (url.getPort() != -1) {
            return url.getPort();
        }
        return url.getDefaultPort();
    }

    public static final class SyncResult {
        public final int downloaded;
        public final int removed;
        public final int total;

        private SyncResult(int downloaded, int removed, int total) {
            this.downloaded = downloaded;
            this.removed = removed;
            this.total = total;
        }
    }

    private static final class RemoteEntry {
        private final CachedEntry cached;
        private final String contentUrl;

        private RemoteEntry(CachedEntry cached, String contentUrl) {
            this.cached = cached;
            this.contentUrl = contentUrl;
        }
    }

    private static final class CachedEntry {
        private final String id;
        private final String mimeType;
        private final int width;
        private final int height;
        private final String createdAt;
        private final boolean favorite;
        private final List<String> tags;

        private CachedEntry(
            String id,
            String mimeType,
            int width,
            int height,
            String createdAt,
            boolean favorite,
            List<String> tags
        ) {
            this.id = id;
            this.mimeType = mimeType;
            this.width = width;
            this.height = height;
            this.createdAt = createdAt;
            this.favorite = favorite;
            this.tags = tags;
        }

        private static CachedEntry fromJson(JSONObject source) throws JSONException {
            String id = source.getString("id");
            if (!isSafeId(id)) {
                throw new JSONException("unsafe cached image id");
            }
            JSONArray rawTags = source.optJSONArray("tags");
            ArrayList<String> tags = new ArrayList<>();
            if (rawTags != null) {
                for (int index = 0; index < rawTags.length(); index++) {
                    String tag = rawTags.optString(index, "").trim();
                    if (!tag.isEmpty()) {
                        tags.add(tag);
                    }
                }
            }
            return new CachedEntry(
                id,
                normalizeMimeType(source.optString("mime_type")),
                Math.max(1, source.optInt("width", 1)),
                Math.max(1, source.optInt("height", 1)),
                source.optString("created_at", ""),
                source.optBoolean("favorite", false),
                tags
            );
        }

        private JSONObject toJson() throws JSONException {
            JSONObject value = new JSONObject();
            value.put("id", id);
            value.put("mime_type", mimeType);
            value.put("width", width);
            value.put("height", height);
            value.put("created_at", createdAt);
            value.put("favorite", favorite);
            JSONArray tagValues = new JSONArray();
            for (String tag : tags) {
                tagValues.put(tag);
            }
            value.put("tags", tagValues);
            return value;
        }
    }
}
