package com.novelai.lanstudio;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertThrows;
import static org.junit.Assert.assertTrue;

import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.InetAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.atomic.AtomicReference;

public final class OfflineGalleryCacheTest {
    @Rule
    public TemporaryFolder temporaryFolder = new TemporaryFolder();

    @Test
    public void syncCachesBothFoldersAndNeverPersistsPromptMetadata() throws Exception {
        byte[] temporaryImage = "temporary-image".getBytes(StandardCharsets.UTF_8);
        byte[] favoriteImage = "favorite-image".getBytes(StandardCharsets.UTF_8);
        try (MiniHttpServer server = new MiniHttpServer(temporaryImage, favoriteImage, false)) {
            OfflineGalleryCache cache = new OfflineGalleryCache(temporaryFolder.newFolder("app"));
            String baseUrl = "http://127.0.0.1:" + server.getPort();

            OfflineGalleryCache.SyncResult first = cache.sync(
                baseUrl,
                "device=approved",
                "test-agent"
            );

            assertEquals(2, first.downloaded);
            assertEquals(2, first.total);
            assertEquals(2, cache.getImageCount());
            assertTrue(cache.hasImages());
            assertNotNull(cache.getImageFile("temporary-1"));
            assertNotNull(cache.getImageFile("favorite-1"));
            String metadata = cache.metadataJson();
            assertTrue(metadata.contains("하린"));
            assertTrue(metadata.contains("\"favorite\":true"));
            assertTrue(metadata.contains("\"favorite\":false"));
            assertFalse(metadata.contains("prompt"));
            assertFalse(metadata.contains("seed"));
            assertFalse(metadata.contains("settings"));

            OfflineGalleryCache.SyncResult second = cache.sync(
                baseUrl,
                "device=approved",
                "test-agent"
            );
            assertEquals(0, second.downloaded);
            assertEquals(2, second.total);
            server.assertHealthy();
        }
    }

    @Test
    public void interruptedInitialSyncKeepsAlreadyDownloadedImagesAvailable() throws Exception {
        byte[] temporaryImage = "temporary-image".getBytes(StandardCharsets.UTF_8);
        byte[] favoriteImage = "favorite-image".getBytes(StandardCharsets.UTF_8);
        try (MiniHttpServer server = new MiniHttpServer(temporaryImage, favoriteImage, true)) {
            OfflineGalleryCache cache = new OfflineGalleryCache(
                temporaryFolder.newFolder("partial-app")
            );
            String baseUrl = "http://127.0.0.1:" + server.getPort();

            assertThrows(
                IOException.class,
                () -> cache.sync(baseUrl, "device=approved", "test-agent")
            );

            assertTrue(cache.hasImages());
            assertEquals(1, cache.getImageCount());
            assertNotNull(cache.getImageFile("temporary-1"));
            assertFalse(cache.metadataJson().contains("favorite-1"));
            assertEquals(0, cache.getLastSyncedAt());
            server.assertHealthy();
        }
    }

    @Test
    public void sanitizerKeepsOnlyOfflineGalleryFields() throws Exception {
        JSONObject source = new JSONObject();
        source.put("id", "image-safe-1");
        source.put("mime_type", "image/webp");
        source.put("width", 768);
        source.put("height", 1344);
        source.put("created_at", "2026-09-01T00:00:00Z");
        source.put("prompt", "secret");
        source.put("negative_prompt", "secret negative");
        source.put("seed", 44);
        source.put("tags", new JSONArray().put(new JSONObject().put("name", "규나나")));

        JSONObject sanitized = OfflineGalleryCache.sanitizeServerItem(source, true);

        assertEquals("image-safe-1", sanitized.getString("id"));
        assertEquals("image/webp", sanitized.getString("mime_type"));
        assertTrue(sanitized.getBoolean("favorite"));
        assertEquals("규나나", sanitized.getJSONArray("tags").getString(0));
        assertFalse(sanitized.has("prompt"));
        assertFalse(sanitized.has("negative_prompt"));
        assertFalse(sanitized.has("seed"));
    }

    private static final class MiniHttpServer implements AutoCloseable {
        private final byte[] temporaryImage;
        private final byte[] favoriteImage;
        private final boolean failFavoriteImage;
        private final ServerSocket serverSocket;
        private final AtomicReference<Throwable> failure = new AtomicReference<>();
        private final Thread thread;
        private volatile boolean closed;

        private MiniHttpServer(
            byte[] temporaryImage,
            byte[] favoriteImage,
            boolean failFavoriteImage
        ) throws IOException {
            this.temporaryImage = temporaryImage;
            this.favoriteImage = favoriteImage;
            this.failFavoriteImage = failFavoriteImage;
            serverSocket = new ServerSocket(0, 50, InetAddress.getByName("127.0.0.1"));
            thread = new Thread(this::serve, "offline-gallery-test-server");
            thread.setDaemon(true);
            thread.start();
        }

        private int getPort() {
            return serverSocket.getLocalPort();
        }

        private void serve() {
            while (!closed) {
                try (Socket socket = serverSocket.accept()) {
                    handle(socket);
                } catch (IOException error) {
                    if (!closed) {
                        failure.compareAndSet(null, error);
                    }
                } catch (Throwable error) {
                    failure.compareAndSet(null, error);
                }
            }
        }

        private void handle(Socket socket) throws Exception {
            BufferedReader reader = new BufferedReader(
                new InputStreamReader(socket.getInputStream(), StandardCharsets.US_ASCII)
            );
            String requestLine = reader.readLine();
            if (requestLine == null) {
                return;
            }
            String cookie = null;
            String header;
            while ((header = reader.readLine()) != null && !header.isEmpty()) {
                if (header.regionMatches(true, 0, "Cookie:", 0, "Cookie:".length())) {
                    cookie = header.substring("Cookie:".length()).trim();
                }
            }
            assertEquals("device=approved", cookie);
            String target = requestLine.split(" ")[1];
            if (target.startsWith("/api/mobile/offline-gallery")) {
                boolean favorite = target.contains("favorite=true");
                String id = favorite ? "favorite-1" : "temporary-1";
                JSONObject item = new JSONObject();
                item.put("id", id);
                item.put("mime_type", "image/png");
                item.put("width", 1024);
                item.put("height", 1024);
                item.put(
                    "created_at",
                    favorite ? "2026-09-01T02:00:00Z" : "2026-09-01T01:00:00Z"
                );
                item.put("content_url", "/api/assets/" + id + "/content");
                item.put("prompt", "must never be cached");
                item.put("seed", 12345);
                item.put("settings", new JSONObject().put("guidance", 7));
                item.put(
                    "tags",
                    new JSONArray().put(
                        new JSONObject().put("id", "tag-1").put("name", "하린")
                    )
                );
                JSONObject body = new JSONObject();
                body.put("items", new JSONArray().put(item));
                body.put("total", 1);
                body.put("page", 1);
                body.put("page_size", 50);
                respond(
                    socket.getOutputStream(),
                    "application/json; charset=utf-8",
                    body.toString().getBytes(StandardCharsets.UTF_8)
                );
                return;
            }
            if ("/api/assets/temporary-1/content".equals(target)) {
                respond(socket.getOutputStream(), "image/png", temporaryImage);
                return;
            }
            if ("/api/assets/favorite-1/content".equals(target)) {
                respond(
                    socket.getOutputStream(),
                    "image/png",
                    favoriteImage,
                    failFavoriteImage ? 500 : 200
                );
                return;
            }
            respond(socket.getOutputStream(), "text/plain", new byte[0], 404);
        }

        private static void respond(OutputStream output, String contentType, byte[] body)
            throws IOException {
            respond(output, contentType, body, 200);
        }

        private static void respond(
            OutputStream output,
            String contentType,
            byte[] body,
            int status
        ) throws IOException {
            String reason = status == 200 ? "OK" : status == 500 ? "Error" : "Not Found";
            String headers = "HTTP/1.1 "
                + status
                + " "
                + reason
                + "\r\nContent-Type: "
                + contentType
                + "\r\nContent-Length: "
                + body.length
                + "\r\nConnection: close\r\n\r\n";
            output.write(headers.getBytes(StandardCharsets.US_ASCII));
            output.write(body);
            output.flush();
        }

        private void assertHealthy() {
            Throwable error = failure.get();
            if (error != null) {
                throw new AssertionError(error);
            }
        }

        @Override
        public void close() throws Exception {
            closed = true;
            serverSocket.close();
            thread.join(2_000);
            assertHealthy();
        }
    }
}
