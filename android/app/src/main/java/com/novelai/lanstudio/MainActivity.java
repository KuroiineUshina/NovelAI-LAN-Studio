package com.novelai.lanstudio;

import android.annotation.SuppressLint;
import android.Manifest;
import android.app.Activity;
import android.app.DownloadManager;
import android.content.ContentResolver;
import android.content.ContentValues;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.os.Handler;
import android.os.Looper;
import android.provider.MediaStore;
import android.view.KeyEvent;
import android.view.View;
import android.view.inputmethod.EditorInfo;
import android.webkit.CookieManager;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.Toast;
import android.window.OnBackInvokedDispatcher;

import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.ByteArrayInputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.Collections;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;

public final class MainActivity extends Activity {
    private static final String PREFERENCES = "lan_studio_android";
    private static final String SERVER_URL_KEY = "server_url";
    private static final int FILE_CHOOSER_REQUEST = 1401;
    private static final int STORAGE_PERMISSION_REQUEST = 1402;
    private static final String OFFLINE_HOST = "offline.novelai-lan-studio.invalid";
    private static final String OFFLINE_INDEX_URL = "https://" + OFFLINE_HOST + "/offline/index.html";
    private static final String STANDALONE_HOST = "standalone.novelai-lan-studio.invalid";
    private static final String STANDALONE_INDEX_URL = "https://" + STANDALONE_HOST + "/index.html";
    private static final long OFFLINE_SYNC_INTERVAL_MS = 5 * 60 * 1000L;
    private static final long OFFLINE_SYNC_DEBOUNCE_MS = 30 * 1000L;

    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private final ExecutorService cacheExecutor = Executors.newSingleThreadExecutor();
    private final ExecutorService downloadExecutor = Executors.newSingleThreadExecutor();
    private final AtomicBoolean offlineSyncRunning = new AtomicBoolean(false);
    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private final Runnable offlineSyncRunnable = this::handlePeriodicOfflineSync;

    private WebView webView;
    private View connectionPanel;
    private EditText serverAddress;
    private Button connectButton;
    private Button restoreButton;
    private Button offlineGalleryButton;
    private Button standaloneButton;
    private ProgressBar connectProgress;
    private TextView connectStatus;
    private TextView connectError;
    private SharedPreferences preferences;
    private ValueCallback<Uri[]> fileChooserCallback;
    private PendingDownload pendingDownload;
    private String pendingCachedDownloadId;
    private boolean pendingCachedDownloadRemoveMetadata;
    private volatile String connectedBaseUrl;
    private OfflineGalleryCache offlineGalleryCache;
    private boolean offlineGalleryVisible;
    private boolean standaloneVisible;
    private ApiProfileStore apiProfileStore;
    private ApiProfileProvisioner apiProfileProvisioner;
    private OnlineAndroidBridge onlineAndroidBridge;
    private StandaloneBridge standaloneBridge;
    private SecureSecretStore secureSecretStore;
    private boolean destroyed;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);
        getWindow().setStatusBarColor(Color.rgb(11, 12, 23));
        getWindow().setNavigationBarColor(Color.rgb(11, 12, 23));

        preferences = getSharedPreferences(PREFERENCES, MODE_PRIVATE);
        offlineGalleryCache = new OfflineGalleryCache(getFilesDir());
        apiProfileStore = new ApiProfileStore(this);
        secureSecretStore = new SecureSecretStore(this);
        apiProfileProvisioner = new ApiProfileProvisioner(apiProfileStore);
        onlineAndroidBridge = new OnlineAndroidBridge(this);
        standaloneBridge = new StandaloneBridge(this, apiProfileStore);
        webView = findViewById(R.id.studio_webview);
        connectionPanel = findViewById(R.id.connection_panel);
        serverAddress = findViewById(R.id.server_address);
        connectButton = findViewById(R.id.connect_button);
        restoreButton = findViewById(R.id.restore_button);
        offlineGalleryButton = findViewById(R.id.offline_gallery_button);
        standaloneButton = findViewById(R.id.standalone_button);
        connectProgress = findViewById(R.id.connect_progress);
        connectStatus = findViewById(R.id.connect_status);
        connectError = findViewById(R.id.connect_error);
        String defaultUrl = getString(R.string.default_server_url);
        serverAddress.setText(preferences.getString(SERVER_URL_KEY, defaultUrl));
        configureWebView();

        connectButton.setOnClickListener(view -> connectToServer());
        offlineGalleryButton.setOnClickListener(view -> showOfflineGallery());
        standaloneButton.setOnClickListener(view -> showStandaloneMode());
        restoreButton.setOnClickListener(view -> {
            serverAddress.setText(defaultUrl);
            serverAddress.setSelection(serverAddress.length());
            clearConnectionError();
        });
        serverAddress.setOnEditorActionListener((view, actionId, event) -> {
            boolean keyboardGo = actionId == EditorInfo.IME_ACTION_GO;
            boolean enter = event != null && event.getAction() == KeyEvent.ACTION_UP && event.getKeyCode() == KeyEvent.KEYCODE_ENTER;
            if (keyboardGo || enter) {
                connectToServer();
                return true;
            }
            return false;
        });
        refreshOfflineGalleryButton();
        refreshStandaloneButton();

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            getOnBackInvokedDispatcher().registerOnBackInvokedCallback(
                OnBackInvokedDispatcher.PRIORITY_DEFAULT,
                this::handleBack
            );
        }

        if (savedInstanceState != null && webView.restoreState(savedInstanceState) != null) {
            String restoredUrl = webView.getUrl();
            String savedBase = preferences.getString(SERVER_URL_KEY, defaultUrl);
            if (isOfflineUrl(restoredUrl) && offlineGalleryCache.hasImages()) {
                offlineGalleryVisible = true;
                showWebView();
                return;
            }
            if (isStandaloneUrl(restoredUrl) && apiProfileStore.hasProfiles()) {
                standaloneVisible = true;
                showWebView();
                return;
            }
            if (ServerAddress.isAllowedUrl(savedBase, restoredUrl)) {
                connectedBaseUrl = savedBase;
                showWebView();
                return;
            }
        }
        connectToServer();
    }

    @SuppressLint("SetJavaScriptEnabled")
    private void configureWebView() {
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(true);
        settings.setGeolocationEnabled(false);
        settings.setSaveFormData(false);
        settings.setMediaPlaybackRequiresUserGesture(true);
        settings.setSupportMultipleWindows(true);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setUserAgentString(
            settings.getUserAgentString() + " NovelAI-LAN-Studio-Android/" + BuildConfig.VERSION_NAME
        );
        CookieManager cookieManager = CookieManager.getInstance();
        cookieManager.setAcceptCookie(true);
        cookieManager.setAcceptThirdPartyCookies(webView, false);
        settings.setSafeBrowsingEnabled(true);
        boolean debuggable = (getApplicationInfo().flags & android.content.pm.ApplicationInfo.FLAG_DEBUGGABLE) != 0;
        WebView.setWebContentsDebuggingEnabled(debuggable);
        webView.addJavascriptInterface(onlineAndroidBridge, "NovelAIAndroid");

        webView.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                return handleNavigation(request.getUrl().toString());
            }

            @Override
            @SuppressWarnings("deprecation")
            public boolean shouldOverrideUrlLoading(WebView view, String url) {
                return handleNavigation(url);
            }

            @Override
            public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
                return interceptResource(request.getUrl().toString());
            }

            @Override
            @SuppressWarnings("deprecation")
            public WebResourceResponse shouldInterceptRequest(WebView view, String url) {
                return interceptResource(url);
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                if (isStandaloneUrl(url)) {
                    standaloneVisible = true;
                    offlineGalleryVisible = false;
                    showWebView();
                    view.clearHistory();
                    return;
                }
                if (isOfflineUrl(url)) {
                    offlineGalleryVisible = true;
                    showWebView();
                    view.clearHistory();
                    return;
                }
                if (ServerAddress.isAllowedUrl(connectedBaseUrl, url)) {
                    standaloneVisible = false;
                    offlineGalleryVisible = false;
                    CookieManager cookieManager = CookieManager.getInstance();
                    cookieManager.flush();
                    String cookie = cookieManager.getCookie(connectedBaseUrl);
                    if (cookie != null && cookie.contains("novelai_studio_device=")) {
                        secureSecretStore.put(
                            StandaloneSyncClient.COOKIE_PREFIX + connectedBaseUrl,
                            cookie
                        );
                    }
                    showWebView();
                    view.clearHistory();
                    startOfflineGallerySync();
                    scheduleOfflineGallerySync();
                    standaloneBridge.foregroundSync();
                    dispatchApiProfiles();
                }
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                if (request.isForMainFrame()) {
                    showOfflineGalleryOrConnection(getString(R.string.server_unreachable));
                }
            }

            @Override
            public void onReceivedHttpError(WebView view, WebResourceRequest request, android.webkit.WebResourceResponse errorResponse) {
                if (request.isForMainFrame() && errorResponse.getStatusCode() >= 400) {
                    showOfflineGalleryOrConnection(getString(R.string.server_unreachable));
                }
            }
        });

        webView.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback, FileChooserParams params) {
                if (fileChooserCallback != null) {
                    fileChooserCallback.onReceiveValue(null);
                }
                fileChooserCallback = callback;
                Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
                intent.addCategory(Intent.CATEGORY_OPENABLE);
                intent.setType("image/*");
                intent.putExtra(Intent.EXTRA_MIME_TYPES, new String[]{"image/png", "image/jpeg", "image/webp"});
                try {
                    startActivityForResult(Intent.createChooser(intent, getString(R.string.choose_image)), FILE_CHOOSER_REQUEST);
                    return true;
                } catch (RuntimeException error) {
                    fileChooserCallback = null;
                    callback.onReceiveValue(null);
                    return false;
                }
            }
        });

        webView.setDownloadListener((url, userAgent, contentDisposition, mimeType, contentLength) -> {
            if (!ServerAddress.isAllowedUrl(connectedBaseUrl, url)) {
                Toast.makeText(this, R.string.download_blocked, Toast.LENGTH_LONG).show();
                return;
            }
            PendingDownload download = new PendingDownload(url, userAgent, contentDisposition, mimeType);
            if (Build.VERSION.SDK_INT <= Build.VERSION_CODES.P
                && checkSelfPermission(Manifest.permission.WRITE_EXTERNAL_STORAGE) != PackageManager.PERMISSION_GRANTED) {
                pendingDownload = download;
                requestPermissions(new String[]{Manifest.permission.WRITE_EXTERNAL_STORAGE}, STORAGE_PERMISSION_REQUEST);
                return;
            }
            startDownload(download);
        });
    }

    private boolean handleNavigation(String url) {
        if (handleOfflineDownloadUrl(url)) {
            return true;
        }
        if (isOfflineUrl(url)) {
            return false;
        }
        if (isStandaloneUrl(url)) {
            return false;
        }
        return blockUnexpectedNavigation(url);
    }

    private WebResourceResponse interceptResource(String url) {
        WebResourceResponse standalone = interceptStandaloneResource(url);
        if (standalone != null) return standalone;
        WebResourceResponse offline = interceptOfflineResource(url);
        return offline == null ? interceptUnexpectedResource(url) : offline;
    }

    private WebResourceResponse interceptStandaloneResource(String url) {
        if (!isStandaloneUrl(url)) return null;
        Uri uri = Uri.parse(url);
        String path = uri.getPath();
        if (path != null && path.startsWith("/local-image/")) {
            return standaloneBridge.imageResponse(url);
        }
        if ("/index.html".equals(path) || "/".equals(path) || path == null || path.isEmpty()) {
            try (InputStream input = getAssets().open("standalone.html")) {
                return offlineResponse("text/html", readAll(input, 2 * 1024 * 1024));
            } catch (IOException error) {
                return offlineNotFound();
            }
        }
        return offlineNotFound();
    }

    private static byte[] readAll(InputStream input, int limit) throws IOException {
        java.io.ByteArrayOutputStream output = new java.io.ByteArrayOutputStream();
        byte[] buffer = new byte[8192];
        int count;
        while ((count = input.read(buffer)) >= 0) {
            output.write(buffer, 0, count);
            if (output.size() > limit) throw new IOException("asset too large");
        }
        return output.toByteArray();
    }

    private boolean blockUnexpectedNavigation(String url) {
        if (isStandaloneUrl(url)) return false;
        if (ServerAddress.isAllowedUrl(connectedBaseUrl, url)) {
            return false;
        }
        Toast.makeText(this, R.string.download_blocked, Toast.LENGTH_SHORT).show();
        return true;
    }

    private WebResourceResponse interceptUnexpectedResource(String url) {
        if (url != null && (url.startsWith("data:image/") || url.startsWith("blob:"))) {
            return null;
        }
        if (ServerAddress.isAllowedUrl(connectedBaseUrl, url)) {
            return null;
        }
        return new WebResourceResponse(
            "text/plain",
            "UTF-8",
            403,
            "Blocked by NovelAI LAN Studio",
            Collections.emptyMap(),
            new ByteArrayInputStream(new byte[0])
        );
    }

    private WebResourceResponse interceptOfflineResource(String url) {
        if (!isOfflineUrl(url)) {
            return null;
        }
        Uri uri = Uri.parse(url);
        String path = uri.getPath();
        if ("/offline/index.html".equals(path) || "/offline/".equals(path)) {
            return offlineResponse(
                "text/html",
                OfflineGalleryPage.html().getBytes(StandardCharsets.UTF_8)
            );
        }
        if ("/offline/metadata.json".equals(path)) {
            return offlineResponse(
                "application/json",
                offlineGalleryCache.metadataJson().getBytes(StandardCharsets.UTF_8)
            );
        }
        if (path != null && path.startsWith("/offline/image/")) {
            String id = uri.getLastPathSegment();
            File file = offlineGalleryCache.getImageFile(id);
            if (file == null) {
                return offlineNotFound();
            }
            try {
                return new WebResourceResponse(
                    offlineGalleryCache.getMimeType(id),
                    null,
                    200,
                    "OK",
                    Collections.singletonMap("Cache-Control", "private, max-age=31536000"),
                    new FileInputStream(file)
                );
            } catch (IOException error) {
                return offlineNotFound();
            }
        }
        return offlineNotFound();
    }

    private static WebResourceResponse offlineResponse(String mimeType, byte[] data) {
        return new WebResourceResponse(
            mimeType,
            "UTF-8",
            200,
            "OK",
            Collections.singletonMap("Cache-Control", "no-store"),
            new ByteArrayInputStream(data)
        );
    }

    private static WebResourceResponse offlineNotFound() {
        return new WebResourceResponse(
            "text/plain",
            "UTF-8",
            404,
            "Not Found",
            Collections.emptyMap(),
            new ByteArrayInputStream(new byte[0])
        );
    }

    private static boolean isOfflineUrl(String url) {
        if (url == null) {
            return false;
        }
        Uri uri = Uri.parse(url);
        return "https".equalsIgnoreCase(uri.getScheme())
            && OFFLINE_HOST.equalsIgnoreCase(uri.getHost());
    }

    private static boolean isStandaloneUrl(String url) {
        if (url == null) return false;
        Uri uri = Uri.parse(url);
        return "https".equalsIgnoreCase(uri.getScheme())
            && STANDALONE_HOST.equalsIgnoreCase(uri.getHost());
    }

    private void connectToServer() {
        final String normalized;
        try {
            normalized = ServerAddress.normalize(serverAddress.getText().toString());
        } catch (IllegalArgumentException error) {
            showConnection(getString(R.string.invalid_address));
            return;
        }

        serverAddress.setText(normalized);
        serverAddress.setSelection(serverAddress.length());
        setConnecting(true);
        executor.execute(() -> {
            ProbeResult result = probeServer(normalized);
            runOnUiThread(() -> {
                if (destroyed) {
                    return;
                }
                setConnecting(false);
                if (result == ProbeResult.OK) {
                    standaloneVisible = false;
                    connectedBaseUrl = normalized;
                    offlineGalleryVisible = false;
                    preferences.edit().putString(SERVER_URL_KEY, normalized).apply();
                    connectError.setVisibility(View.GONE);
                    webView.setVisibility(View.VISIBLE);
                    connectionPanel.setVisibility(View.GONE);
                    webView.loadUrl(normalized);
                } else if (result == ProbeResult.WRONG_SERVER) {
                    showConnection(getString(R.string.wrong_server));
                } else {
                    showOfflineGalleryOrConnection(getString(R.string.server_unreachable));
                }
            });
        });
    }

    private ProbeResult probeServer(String baseUrl) {
        HttpURLConnection connection = null;
        try {
            connection = (HttpURLConnection) new URL(baseUrl + "/api/status").openConnection();
            connection.setRequestMethod("GET");
            connection.setConnectTimeout(2500);
            connection.setReadTimeout(3500);
            connection.setInstanceFollowRedirects(false);
            connection.setRequestProperty("Accept", "application/json");
            if (connection.getResponseCode() != HttpURLConnection.HTTP_OK) {
                return ProbeResult.UNREACHABLE;
            }
            StringBuilder body = new StringBuilder();
            try (BufferedReader reader = new BufferedReader(new InputStreamReader(connection.getInputStream(), StandardCharsets.UTF_8))) {
                String line;
                while ((line = reader.readLine()) != null && body.length() < 65536) {
                    body.append(line);
                }
            }
            JSONObject status = new JSONObject(body.toString());
            return "NovelAI LAN Studio".equals(status.optString("name"))
                && "online".equals(status.optString("server"))
                ? ProbeResult.OK
                : ProbeResult.WRONG_SERVER;
        } catch (Exception error) {
            return ProbeResult.UNREACHABLE;
        } finally {
            if (connection != null) {
                connection.disconnect();
            }
        }
    }

    private void setConnecting(boolean connecting) {
        connectButton.setEnabled(!connecting);
        restoreButton.setEnabled(!connecting);
        standaloneButton.setEnabled(!connecting && apiProfileStore.hasProfiles());
        serverAddress.setEnabled(!connecting);
        connectProgress.setVisibility(connecting ? View.VISIBLE : View.GONE);
        connectStatus.setVisibility(connecting ? View.VISIBLE : View.GONE);
        if (connecting) {
            connectError.setVisibility(View.GONE);
        }
    }

    private void clearConnectionError() {
        connectError.setText("");
        connectError.setVisibility(View.GONE);
    }

    private void showWebView() {
        setConnecting(false);
        connectionPanel.setVisibility(View.GONE);
        webView.setVisibility(View.VISIBLE);
    }

    private void showConnection(String message) {
        offlineGalleryVisible = false;
        standaloneVisible = false;
        setConnecting(false);
        webView.stopLoading();
        webView.setVisibility(View.GONE);
        connectionPanel.setVisibility(View.VISIBLE);
        refreshOfflineGalleryButton();
        refreshStandaloneButton();
        if (message == null || message.isEmpty()) {
            clearConnectionError();
        } else {
            connectError.setText(message);
            connectError.setVisibility(View.VISIBLE);
        }
    }

    private void showOfflineGalleryOrConnection(String message) {
        if (apiProfileStore.hasProfiles()) {
            showStandaloneMode();
        } else {
            showOfflineGallery();
        }
    }

    private void showOfflineGallery() {
        setConnecting(false);
        offlineGalleryVisible = true;
        standaloneVisible = false;
        connectionPanel.setVisibility(View.GONE);
        webView.setVisibility(View.VISIBLE);
        webView.loadUrl(OFFLINE_INDEX_URL);
    }

    private void refreshOfflineGalleryButton() {
        if (offlineGalleryButton == null) {
            return;
        }
        offlineGalleryButton.setVisibility(View.VISIBLE);
    }

    private void refreshStandaloneButton() {
        if (standaloneButton == null) return;
        standaloneButton.setVisibility(apiProfileStore.hasProfiles() ? View.VISIBLE : View.GONE);
        standaloneButton.setEnabled(apiProfileStore.hasProfiles());
    }

    private void showStandaloneMode() {
        if (!apiProfileStore.hasProfiles()) {
            Toast.makeText(this, R.string.api_profile_required, Toast.LENGTH_LONG).show();
            return;
        }
        standaloneVisible = true;
        offlineGalleryVisible = false;
        connectedBaseUrl = null;
        clearConnectionError();
        webView.removeJavascriptInterface("AndroidStudio");
        webView.addJavascriptInterface(standaloneBridge, "AndroidStudio");
        webView.setVisibility(View.VISIBLE);
        connectionPanel.setVisibility(View.GONE);
        webView.loadUrl(STANDALONE_INDEX_URL);
    }

    void leaveStandaloneMode() {
        runOnUiThread(() -> {
            standaloneVisible = false;
            webView.removeJavascriptInterface("AndroidStudio");
            webView.addJavascriptInterface(onlineAndroidBridge, "NovelAIAndroid");
            webView.stopLoading();
            webView.loadUrl("about:blank");
            showConnection("");
        });
    }

    void runStandaloneScript(String script) {
        runOnUiThread(() -> {
            if (!destroyed && standaloneVisible) webView.evaluateJavascript(script, null);
        });
    }

    String getApiProfilesJson() {
        return apiProfileStore.listSafe().toString();
    }

    boolean requestApiProfile(String profileName) {
        String baseUrl = connectedBaseUrl;
        if (baseUrl == null || destroyed) return false;
        String cookie = CookieManager.getInstance().getCookie(baseUrl);
        boolean started = apiProfileProvisioner.request(
            baseUrl,
            cookie,
            profileName,
            event -> runOnUiThread(() -> {
                if (destroyed) return;
                refreshStandaloneButton();
                String script = "window.dispatchEvent(new CustomEvent('novelai-api-profile',{detail:"
                    + event.toString() + "}))";
                webView.evaluateJavascript(script, null);
            })
        );
        return started;
    }

    boolean openStandaloneFromBridge() {
        if (!apiProfileStore.hasProfiles()) return false;
        runOnUiThread(this::showStandaloneMode);
        return true;
    }

    boolean setActiveApiProfile(String profileId) {
        boolean changed = apiProfileStore.setActive(profileId);
        if (changed) dispatchApiProfiles();
        return changed;
    }

    boolean renameApiProfile(String profileId, String name) {
        boolean changed = apiProfileStore.rename(profileId, name);
        if (changed) dispatchApiProfiles();
        return changed;
    }

    boolean deleteApiProfile(String profileId) {
        boolean changed = apiProfileStore.delete(profileId);
        if (changed) {
            runOnUiThread(this::refreshStandaloneButton);
            dispatchApiProfiles();
        }
        return changed;
    }

    private void dispatchApiProfiles() {
        runOnUiThread(() -> {
            if (destroyed || standaloneVisible) return;
            String script = "window.dispatchEvent(new CustomEvent('novelai-api-profiles',{detail:"
                + apiProfileStore.listSafe().toString() + "}))";
            webView.evaluateJavascript(script, null);
        });
    }

    private void startOfflineGallerySync() {
        String baseUrl = connectedBaseUrl;
        if (baseUrl == null || offlineGalleryVisible || destroyed) {
            return;
        }
        long lastSync = offlineGalleryCache.getLastSyncedAt();
        if (lastSync > 0 && System.currentTimeMillis() - lastSync < OFFLINE_SYNC_DEBOUNCE_MS) {
            return;
        }
        if (!offlineSyncRunning.compareAndSet(false, true)) {
            return;
        }
        String cookie = CookieManager.getInstance().getCookie(baseUrl);
        String userAgent = webView.getSettings().getUserAgentString();
        cacheExecutor.execute(() -> {
            try {
                OfflineGalleryCache.SyncResult result = offlineGalleryCache.sync(
                    baseUrl,
                    cookie,
                    userAgent
                );
                runOnUiThread(() -> {
                    if (destroyed) {
                        return;
                    }
                    refreshOfflineGalleryButton();
                    if (result.downloaded > 0 || result.removed > 0) {
                        Toast.makeText(
                            this,
                            getString(R.string.offline_cache_updated, result.total),
                            Toast.LENGTH_SHORT
                        ).show();
                    }
                });
            } catch (Exception ignored) {
                // The online WebView remains usable. A later page load or resume retries the cache sync.
            } finally {
                offlineSyncRunning.set(false);
            }
        });
    }

    private void scheduleOfflineGallerySync() {
        mainHandler.removeCallbacks(offlineSyncRunnable);
        if (!destroyed) {
            mainHandler.postDelayed(offlineSyncRunnable, OFFLINE_SYNC_INTERVAL_MS);
        }
    }

    private void handlePeriodicOfflineSync() {
        if (destroyed) {
            return;
        }
        if (connectedBaseUrl != null && !offlineGalleryVisible) {
            startOfflineGallerySync();
        }
        scheduleOfflineGallerySync();
    }

    private boolean handleOfflineDownloadUrl(String url) {
        if (url == null) {
            return false;
        }
        Uri uri = Uri.parse(url);
        if (!"novelai-offline-download".equalsIgnoreCase(uri.getScheme())
            || !"image".equalsIgnoreCase(uri.getHost())) {
            return false;
        }
        String id = uri.getLastPathSegment();
        String metadata = uri.getQueryParameter("metadata");
        if (metadata != null && !metadata.equals("preserve") && !metadata.equals("remove")) {
            Toast.makeText(this, R.string.download_failed, Toast.LENGTH_LONG).show();
            return true;
        }
        boolean removeMetadata = "remove".equals(metadata);
        if (offlineGalleryCache.getImageFile(id) == null) {
            Toast.makeText(this, R.string.download_failed, Toast.LENGTH_LONG).show();
            return true;
        }
        if (Build.VERSION.SDK_INT <= Build.VERSION_CODES.P
            && checkSelfPermission(Manifest.permission.WRITE_EXTERNAL_STORAGE)
                != PackageManager.PERMISSION_GRANTED) {
            pendingCachedDownloadId = id;
            pendingCachedDownloadRemoveMetadata = removeMetadata;
            requestPermissions(
                new String[]{Manifest.permission.WRITE_EXTERNAL_STORAGE},
                STORAGE_PERMISSION_REQUEST
            );
            return true;
        }
        startCachedDownload(id, removeMetadata);
        return true;
    }

    private void startCachedDownload(String id, boolean removeMetadata) {
        File source = offlineGalleryCache.getImageFile(id);
        if (source == null) {
            Toast.makeText(this, R.string.download_failed, Toast.LENGTH_LONG).show();
            return;
        }
        String mimeType = removeMetadata ? "image/png" : offlineGalleryCache.getMimeType(id);
        String fileName = removeMetadata ? "novelai-" + id + "-no-metadata.png" : offlineGalleryCache.getDownloadFileName(id);
        downloadExecutor.execute(() -> {
            boolean saved;
            try {
                saveCachedFileToDownloads(source, fileName, mimeType, removeMetadata);
                saved = true;
            } catch (IOException | RuntimeException error) {
                saved = false;
            }
            boolean completed = saved;
            runOnUiThread(() -> Toast.makeText(
                this,
                completed ? R.string.cached_download_complete : R.string.download_failed,
                Toast.LENGTH_LONG
            ).show());
        });
    }

    void downloadStandaloneImage(File source, String fileName, String mimeType, boolean removeMetadata) {
        if (source == null || !source.isFile()) {
            runOnUiThread(() -> Toast.makeText(this, R.string.download_failed, Toast.LENGTH_LONG).show());
            return;
        }
        if (Build.VERSION.SDK_INT <= Build.VERSION_CODES.P
            && checkSelfPermission(Manifest.permission.WRITE_EXTERNAL_STORAGE)
                != PackageManager.PERMISSION_GRANTED) {
            runOnUiThread(() -> Toast.makeText(this, R.string.storage_permission_needed, Toast.LENGTH_LONG).show());
            return;
        }
        downloadExecutor.execute(() -> {
            boolean saved;
            try {
                saveCachedFileToDownloads(source, fileName, mimeType, removeMetadata);
                saved = true;
            } catch (IOException | RuntimeException error) {
                saved = false;
            }
            boolean completed = saved;
            runOnUiThread(() -> Toast.makeText(
                this,
                completed ? R.string.cached_download_complete : R.string.download_failed,
                Toast.LENGTH_LONG
            ).show());
        });
    }

    private void saveCachedFileToDownloads(File source, String fileName, String mimeType, boolean removeMetadata)
        throws IOException {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            ContentResolver resolver = getContentResolver();
            ContentValues values = new ContentValues();
            values.put(MediaStore.Downloads.DISPLAY_NAME, fileName);
            values.put(MediaStore.Downloads.MIME_TYPE, mimeType);
            values.put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS);
            values.put(MediaStore.Downloads.IS_PENDING, 1);
            Uri destination = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values);
            if (destination == null) {
                throw new IOException("failed to create download destination");
            }
            try {
                try (OutputStream output = resolver.openOutputStream(destination)) {
                    if (output == null) {
                        throw new IOException("failed to open download destination");
                    }
                    if (removeMetadata) ImageExport.writeWithoutMetadata(source, output);
                    else copyFile(source, output);
                }
                values.clear();
                values.put(MediaStore.Downloads.IS_PENDING, 0);
                resolver.update(destination, values, null, null);
            } catch (IOException | RuntimeException error) {
                resolver.delete(destination, null, null);
                throw error;
            }
            return;
        }

        File downloads = Environment.getExternalStoragePublicDirectory(
            Environment.DIRECTORY_DOWNLOADS
        );
        if (!downloads.isDirectory() && !downloads.mkdirs() && !downloads.isDirectory()) {
            throw new IOException("failed to create downloads directory");
        }
        File destination = uniqueDownloadFile(downloads, fileName);
        try (OutputStream output = new FileOutputStream(destination)) {
            if (removeMetadata) ImageExport.writeWithoutMetadata(source, output);
            else copyFile(source, output);
        } catch (IOException | RuntimeException error) {
            if (!destination.delete()) destination.deleteOnExit();
            throw error;
        }
    }

    private static void copyFile(File source, OutputStream output) throws IOException {
        try (InputStream input = new FileInputStream(source)) {
            byte[] buffer = new byte[64 * 1024];
            int read;
            while ((read = input.read(buffer)) != -1) {
                output.write(buffer, 0, read);
            }
            output.flush();
        }
    }

    private static File uniqueDownloadFile(File directory, String fileName) {
        File candidate = new File(directory, fileName);
        if (!candidate.exists()) {
            return candidate;
        }
        int dot = fileName.lastIndexOf('.');
        String base = dot > 0 ? fileName.substring(0, dot) : fileName;
        String extension = dot > 0 ? fileName.substring(dot) : "";
        for (int index = 2; index < 10_000; index++) {
            candidate = new File(directory, base + " (" + index + ")" + extension);
            if (!candidate.exists()) {
                return candidate;
            }
        }
        return new File(directory, base + "-" + System.currentTimeMillis() + extension);
    }

    /** Copies the server image (already scrubbed when metadata=remove) to the clipboard as a file. */
    boolean copyImageToClipboard(String url) {
        Uri parsed = url == null ? null : Uri.parse(url);
        if (parsed == null || !("http".equals(parsed.getScheme()) || "https".equals(parsed.getScheme()))) {
            return false;
        }
        final String userAgent = webView == null ? "" : webView.getSettings().getUserAgentString();
        final String cookies = CookieManager.getInstance().getCookie(url);
        final boolean removed = "remove".equals(parsed.getQueryParameter("metadata"));
        downloadExecutor.execute(() -> {
            try {
                File folder = new File(getCacheDir(), ClipboardImageProvider.DIRECTORY);
                if (!folder.isDirectory() && !folder.mkdirs() && !folder.isDirectory()) {
                    throw new IOException("failed to create clipboard directory");
                }
                File[] old = folder.listFiles();
                if (old != null) for (File file : old) if (!file.delete()) file.deleteOnExit();
                File target = new File(folder, "novelai-" + System.currentTimeMillis() + (removed ? "-no-metadata" : "") + ".png");
                HttpURLConnection connection = (HttpURLConnection) new URL(url).openConnection();
                connection.setConnectTimeout(10_000);
                connection.setReadTimeout(30_000);
                connection.setRequestProperty("User-Agent", userAgent);
                if (cookies != null && !cookies.isEmpty()) connection.setRequestProperty("Cookie", cookies);
                try {
                    if (connection.getResponseCode() != HttpURLConnection.HTTP_OK) throw new IOException("HTTP " + connection.getResponseCode());
                    try (InputStream input = connection.getInputStream(); OutputStream output = new FileOutputStream(target)) {
                        byte[] buffer = new byte[64 * 1024];
                        int read;
                        while ((read = input.read(buffer)) != -1) output.write(buffer, 0, read);
                    }
                } finally {
                    connection.disconnect();
                }
                Uri content = ClipboardImageProvider.uriFor(getPackageName(), target);
                runOnUiThread(() -> {
                    android.content.ClipboardManager manager = (android.content.ClipboardManager) getSystemService(Context.CLIPBOARD_SERVICE);
                    manager.setPrimaryClip(android.content.ClipData.newUri(getContentResolver(), "NovelAI image", content));
                    Toast.makeText(this, removed ? R.string.copy_done_removed : R.string.copy_done, Toast.LENGTH_SHORT).show();
                });
            } catch (IOException | RuntimeException error) {
                runOnUiThread(() -> Toast.makeText(this, R.string.copy_failed, Toast.LENGTH_LONG).show());
            }
        });
        return true;
    }

    private void startDownload(PendingDownload download) {
        try {
            String fileName = android.webkit.URLUtil.guessFileName(download.url, download.contentDisposition, download.mimeType);
            DownloadManager.Request request = new DownloadManager.Request(Uri.parse(download.url));
            request.setTitle(fileName);
            request.setDescription(getString(R.string.app_name));
            request.setMimeType(download.mimeType);
            request.setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
            request.setAllowedOverMetered(true);
            request.setAllowedOverRoaming(false);
            request.addRequestHeader("User-Agent", download.userAgent);
            String cookies = CookieManager.getInstance().getCookie(download.url);
            if (cookies != null && !cookies.isEmpty()) {
                request.addRequestHeader("Cookie", cookies);
            }
            request.setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, fileName);
            DownloadManager manager = (DownloadManager) getSystemService(Context.DOWNLOAD_SERVICE);
            manager.enqueue(request);
            Toast.makeText(this, R.string.download_started, Toast.LENGTH_LONG).show();
        } catch (RuntimeException error) {
            Toast.makeText(this, R.string.download_failed, Toast.LENGTH_LONG).show();
        }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode != FILE_CHOOSER_REQUEST || fileChooserCallback == null) {
            return;
        }
        Uri[] result = null;
        if (resultCode == RESULT_OK && data != null && data.getData() != null) {
            result = new Uri[]{data.getData()};
        }
        fileChooserCallback.onReceiveValue(result);
        fileChooserCallback = null;
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode != STORAGE_PERMISSION_REQUEST) {
            return;
        }
        boolean granted = grantResults.length > 0
            && grantResults[0] == PackageManager.PERMISSION_GRANTED;
        if (pendingCachedDownloadId != null) {
            String id = pendingCachedDownloadId;
            boolean removeMetadata = pendingCachedDownloadRemoveMetadata;
            pendingCachedDownloadId = null;
            pendingCachedDownloadRemoveMetadata = false;
            if (granted) {
                startCachedDownload(id, removeMetadata);
            } else {
                Toast.makeText(this, R.string.storage_permission_needed, Toast.LENGTH_LONG).show();
            }
            return;
        }
        if (pendingDownload == null) {
            return;
        }
        PendingDownload download = pendingDownload;
        pendingDownload = null;
        if (granted) {
            startDownload(download);
        } else {
            Toast.makeText(this, R.string.storage_permission_needed, Toast.LENGTH_LONG).show();
        }
    }

    @Override
    @SuppressLint("GestureBackNavigation")
    @SuppressWarnings("deprecation")
    public void onBackPressed() {
        handleBack();
    }

    private void handleBack() {
        if (connectionPanel.getVisibility() == View.VISIBLE) {
            finish();
        } else if (standaloneVisible) {
            requestWebBack(
                "Boolean(window.Standalone && window.Standalone.handleSystemBack && window.Standalone.handleSystemBack())",
                this::leaveStandaloneMode
            );
        } else if (offlineGalleryVisible) {
            requestWebBack(
                "Boolean(window.OfflineGalleryBack && window.OfflineGalleryBack())",
                () -> showConnection("")
            );
        } else {
            requestWebBack(
                "Boolean(window.NovelAIStudioBack && window.NovelAIStudioBack())",
                this::leaveConnectedPage
            );
        }
    }

    private void requestWebBack(String script, Runnable fallback) {
        webView.evaluateJavascript(script, value -> {
            if ("true".equals(value)) return;
            fallback.run();
        });
    }

    private void leaveConnectedPage() {
        if (webView.canGoBack()) {
            webView.goBack();
            return;
        }
        showConnection("");
        Toast.makeText(this, R.string.change_address_hint, Toast.LENGTH_SHORT).show();
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (connectedBaseUrl != null && !offlineGalleryVisible) {
            startOfflineGallerySync();
            scheduleOfflineGallerySync();
            standaloneBridge.foregroundSync();
        }
    }

    @Override
    protected void onSaveInstanceState(Bundle outState) {
        if (webView.getVisibility() == View.VISIBLE) {
            webView.saveState(outState);
        }
        super.onSaveInstanceState(outState);
    }

    @Override
    protected void onDestroy() {
        destroyed = true;
        mainHandler.removeCallbacks(offlineSyncRunnable);
        executor.shutdownNow();
        cacheExecutor.shutdownNow();
        downloadExecutor.shutdownNow();
        apiProfileProvisioner.shutdown();
        standaloneBridge.shutdown();
        if (fileChooserCallback != null) {
            fileChooserCallback.onReceiveValue(null);
            fileChooserCallback = null;
        }
        webView.stopLoading();
        CookieManager.getInstance().flush();
        webView.loadUrl("about:blank");
        webView.clearHistory();
        webView.removeAllViews();
        webView.destroy();
        super.onDestroy();
    }

    private enum ProbeResult {
        OK,
        WRONG_SERVER,
        UNREACHABLE
    }

    private static final class PendingDownload {
        private final String url;
        private final String userAgent;
        private final String contentDisposition;
        private final String mimeType;

        private PendingDownload(String url, String userAgent, String contentDisposition, String mimeType) {
            this.url = url;
            this.userAgent = userAgent == null
                ? "NovelAI-LAN-Studio-Android/" + BuildConfig.VERSION_NAME
                : userAgent;
            this.contentDisposition = contentDisposition;
            this.mimeType = mimeType == null ? "application/octet-stream" : mimeType;
        }
    }
}
