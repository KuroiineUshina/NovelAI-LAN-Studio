package com.novelai.lanstudio;

import android.content.Context;

import java.io.File;
import java.security.KeyStore;

/**
 * Standalone mode was removed in 1.7.0. On first launch after the update, delete what it
 * left on the device: the stored NovelAI API profiles (and their Keystore keys), the local
 * generation database and its images.
 */
final class LegacyStandaloneCleanup {
    private static final String[] PREFERENCES = {"lan_studio_api_profiles", "lan_studio_secure_secrets"};
    private static final String[] KEY_ALIASES = {
        "novelai_lan_studio_api_profiles_v1",
        "novelai_lan_studio_mobile_secrets_v1",
    };
    private static final String DATABASE = "standalone.db";
    private static final String IMAGE_DIRECTORY = "standalone-images";

    private LegacyStandaloneCleanup() {
    }

    static void run(Context context) {
        for (String name : PREFERENCES) {
            context.deleteSharedPreferences(name);
        }
        try {
            KeyStore keyStore = KeyStore.getInstance("AndroidKeyStore");
            keyStore.load(null);
            for (String alias : KEY_ALIASES) {
                if (keyStore.containsAlias(alias)) keyStore.deleteEntry(alias);
            }
        } catch (Exception ignored) {
            // Nothing left to protect once the encrypted preferences are gone.
        }
        context.deleteDatabase(DATABASE);
        deleteRecursively(new File(context.getFilesDir(), IMAGE_DIRECTORY));
    }

    private static void deleteRecursively(File file) {
        if (!file.exists()) return;
        File[] children = file.listFiles();
        if (children != null) {
            for (File child : children) deleteRecursively(child);
        }
        //noinspection ResultOfMethodCallIgnored
        file.delete();
    }
}
