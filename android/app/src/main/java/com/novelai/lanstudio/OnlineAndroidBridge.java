package com.novelai.lanstudio;

import android.webkit.JavascriptInterface;

public final class OnlineAndroidBridge {
    private final MainActivity activity;

    public OnlineAndroidBridge(MainActivity activity) {
        this.activity = activity;
    }

    @JavascriptInterface
    public boolean copyImage(String url) {
        return activity.copyImageToClipboard(url);
    }
}
