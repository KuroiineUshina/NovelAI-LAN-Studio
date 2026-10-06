package com.novelai.lanstudio;

import android.webkit.JavascriptInterface;

public final class OnlineAndroidBridge {
    private final MainActivity activity;

    public OnlineAndroidBridge(MainActivity activity) {
        this.activity = activity;
    }

    @JavascriptInterface
    public String getApiProfiles() {
        return activity.getApiProfilesJson();
    }

    @JavascriptInterface
    public boolean requestApiProfile(String profileName) {
        return activity.requestApiProfile(profileName);
    }

    @JavascriptInterface
    public boolean openStandalone() {
        return activity.openStandaloneFromBridge();
    }

    @JavascriptInterface
    public boolean setActiveApiProfile(String profileId) {
        return activity.setActiveApiProfile(profileId);
    }

    @JavascriptInterface
    public boolean renameApiProfile(String profileId, String name) {
        return activity.renameApiProfile(profileId, name);
    }

    @JavascriptInterface
    public boolean deleteApiProfile(String profileId) {
        return activity.deleteApiProfile(profileId);
    }

    @JavascriptInterface
    public boolean copyImage(String url) {
        return activity.copyImageToClipboard(url);
    }
}
