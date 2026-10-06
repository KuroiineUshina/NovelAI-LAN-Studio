package com.novelai.lanstudio;

import android.content.Context;
import android.content.SharedPreferences;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.nio.charset.StandardCharsets;
import java.security.KeyPairGenerator;
import java.security.KeyStore;
import java.security.MessageDigest;
import java.security.PrivateKey;
import java.security.PublicKey;
import java.security.spec.MGF1ParameterSpec;
import java.util.ArrayList;
import java.util.List;

import javax.crypto.Cipher;
import javax.crypto.spec.OAEPParameterSpec;
import javax.crypto.spec.PSource;

public final class ApiProfileStore {
    public static final String KEY_ID = "android-rsa-profile-v1";
    private static final String KEYSTORE = "AndroidKeyStore";
    private static final String KEY_ALIAS = "novelai_lan_studio_api_profiles_v1";
    private static final String PREFERENCES = "lan_studio_api_profiles";
    private static final String PROFILES_KEY = "profiles";
    private static final String ACTIVE_KEY = "active_profile_id";

    private final SharedPreferences preferences;

    public ApiProfileStore(Context context) {
        preferences = context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE);
    }

    public synchronized String publicKeyBase64() {
        try {
            return Base64.encodeToString(getOrCreatePublicKey().getEncoded(), Base64.NO_WRAP);
        } catch (Exception error) {
            throw new IllegalStateException("모바일 API 프로필 키를 만들지 못했습니다.", error);
        }
    }

    public synchronized String verificationCode() {
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256").digest(getOrCreatePublicKey().getEncoded());
            long value = ((long) (digest[0] & 0xff) << 24)
                | ((long) (digest[1] & 0xff) << 16)
                | ((long) (digest[2] & 0xff) << 8)
                | (long) (digest[3] & 0xff);
            return String.format(java.util.Locale.ROOT, "%06d", value % 1_000_000L);
        } catch (Exception error) {
            throw new IllegalStateException("모바일 API 프로필 확인 코드를 만들지 못했습니다.", error);
        }
    }

    public synchronized JSONObject addApprovedProfile(JSONObject transfer, String serverUrl)
        throws Exception {
        if (!"approved".equals(transfer.optString("status"))) {
            throw new IllegalArgumentException("승인되지 않은 API 프로필입니다.");
        }
        if (!KEY_ID.equals(transfer.optString("key_id"))) {
            throw new IllegalArgumentException("다른 기기 키로 암호화된 API 프로필입니다.");
        }
        String encrypted = transfer.optString("encrypted_token_b64", "");
        if (encrypted.isEmpty()) throw new IllegalArgumentException("암호화된 API 토큰이 없습니다.");
        // Decrypt once before saving to reject corrupted or mismatched payloads. The plaintext
        // is never written; the RSA ciphertext remains the persisted representation.
        decryptCiphertext(encrypted);

        JSONObject profile = new JSONObject();
        profile.put("id", transfer.getString("id"));
        profile.put("name", transfer.optString("profile_name", "NovelAI"));
        profile.put("server_id", transfer.optString("server_id", ""));
        profile.put("server_url", serverUrl == null ? "" : serverUrl);
        profile.put("key_id", KEY_ID);
        profile.put("encrypted_token_b64", encrypted);
        profile.put("created_at", System.currentTimeMillis());

        JSONArray profiles = readProfiles();
        JSONArray next = new JSONArray();
        boolean replaced = false;
        for (int index = 0; index < profiles.length(); index++) {
            JSONObject existing = profiles.optJSONObject(index);
            if (existing != null && profile.getString("id").equals(existing.optString("id"))) {
                next.put(profile);
                replaced = true;
            } else if (existing != null) {
                next.put(existing);
            }
        }
        if (!replaced) next.put(profile);
        preferences.edit()
            .putString(PROFILES_KEY, next.toString())
            .putString(ACTIVE_KEY, profile.getString("id"))
            .apply();
        return safeProfile(profile);
    }

    public synchronized JSONArray listSafe() {
        JSONArray result = new JSONArray();
        JSONArray profiles = readProfiles();
        String active = activeId();
        for (int index = 0; index < profiles.length(); index++) {
            JSONObject profile = profiles.optJSONObject(index);
            if (profile == null) continue;
            try {
                JSONObject safe = safeProfile(profile);
                safe.put("active", safe.optString("id").equals(active));
                result.put(safe);
            } catch (JSONException ignored) {
                // Skip malformed metadata without exposing encrypted contents.
            }
        }
        return result;
    }

    public synchronized boolean hasProfiles() {
        return readProfiles().length() > 0;
    }

    public synchronized String activeId() {
        String active = preferences.getString(ACTIVE_KEY, "");
        if (!active.isEmpty() && find(active) != null) return active;
        JSONArray profiles = readProfiles();
        JSONObject first = profiles.optJSONObject(0);
        if (first == null) return "";
        active = first.optString("id", "");
        if (!active.isEmpty()) preferences.edit().putString(ACTIVE_KEY, active).apply();
        return active;
    }

    public synchronized boolean setActive(String profileId) {
        if (find(profileId) == null) return false;
        preferences.edit().putString(ACTIVE_KEY, profileId).apply();
        return true;
    }

    public synchronized boolean rename(String profileId, String name) {
        String normalized = name == null ? "" : name.trim();
        if (normalized.isEmpty() || normalized.length() > 80) return false;
        JSONArray profiles = readProfiles();
        boolean changed = false;
        for (int index = 0; index < profiles.length(); index++) {
            JSONObject profile = profiles.optJSONObject(index);
            if (profile != null && profileId.equals(profile.optString("id"))) {
                try {
                    profile.put("name", normalized);
                    changed = true;
                } catch (JSONException ignored) {
                    return false;
                }
            }
        }
        if (changed) preferences.edit().putString(PROFILES_KEY, profiles.toString()).apply();
        return changed;
    }

    public synchronized boolean delete(String profileId) {
        JSONArray profiles = readProfiles();
        JSONArray next = new JSONArray();
        boolean removed = false;
        for (int index = 0; index < profiles.length(); index++) {
            JSONObject profile = profiles.optJSONObject(index);
            if (profile == null) continue;
            if (profileId.equals(profile.optString("id"))) removed = true;
            else next.put(profile);
        }
        if (!removed) return false;
        SharedPreferences.Editor editor = preferences.edit().putString(PROFILES_KEY, next.toString());
        if (profileId.equals(preferences.getString(ACTIVE_KEY, ""))) {
            JSONObject first = next.optJSONObject(0);
            editor.putString(ACTIVE_KEY, first == null ? "" : first.optString("id", ""));
        }
        editor.apply();
        return true;
    }

    public synchronized String activeToken() {
        JSONObject profile = find(activeId());
        if (profile == null) return null;
        try {
            return decryptCiphertext(profile.getString("encrypted_token_b64"));
        } catch (Exception error) {
            return null;
        }
    }

    public synchronized JSONObject activeProfileSafe() {
        JSONObject profile = find(activeId());
        if (profile == null) return null;
        try {
            JSONObject safe = safeProfile(profile);
            safe.put("active", true);
            return safe;
        } catch (JSONException error) {
            return null;
        }
    }

    private String decryptCiphertext(String encoded) throws Exception {
        KeyStore keyStore = KeyStore.getInstance(KEYSTORE);
        keyStore.load(null);
        PrivateKey privateKey = (PrivateKey) keyStore.getKey(KEY_ALIAS, null);
        if (privateKey == null) throw new IllegalStateException("모바일 API 프로필 개인키가 없습니다.");
        Cipher cipher = Cipher.getInstance("RSA/ECB/OAEPWithSHA-256AndMGF1Padding");
        OAEPParameterSpec spec = new OAEPParameterSpec(
            "SHA-256",
            "MGF1",
            MGF1ParameterSpec.SHA1,
            PSource.PSpecified.DEFAULT
        );
        cipher.init(Cipher.DECRYPT_MODE, privateKey, spec);
        byte[] plaintext = cipher.doFinal(Base64.decode(encoded, Base64.NO_WRAP));
        return new String(plaintext, StandardCharsets.UTF_8);
    }

    private PublicKey getOrCreatePublicKey() throws Exception {
        KeyStore keyStore = KeyStore.getInstance(KEYSTORE);
        keyStore.load(null);
        java.security.cert.Certificate certificate = keyStore.getCertificate(KEY_ALIAS);
        if (certificate != null) return certificate.getPublicKey();
        KeyPairGenerator generator = KeyPairGenerator.getInstance(
            KeyProperties.KEY_ALGORITHM_RSA,
            KEYSTORE
        );
        generator.initialize(new KeyGenParameterSpec.Builder(
            KEY_ALIAS,
            KeyProperties.PURPOSE_DECRYPT
        ).setKeySize(3072)
            .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_RSA_OAEP)
            .setDigests(KeyProperties.DIGEST_SHA256, KeyProperties.DIGEST_SHA1)
            .setRandomizedEncryptionRequired(true)
            .build());
        return generator.generateKeyPair().getPublic();
    }

    private JSONObject find(String profileId) {
        if (profileId == null || profileId.isEmpty()) return null;
        JSONArray profiles = readProfiles();
        for (int index = 0; index < profiles.length(); index++) {
            JSONObject profile = profiles.optJSONObject(index);
            if (profile != null && profileId.equals(profile.optString("id"))) return profile;
        }
        return null;
    }

    private JSONArray readProfiles() {
        try {
            return new JSONArray(preferences.getString(PROFILES_KEY, "[]"));
        } catch (JSONException error) {
            return new JSONArray();
        }
    }

    private static JSONObject safeProfile(JSONObject profile) throws JSONException {
        return new JSONObject()
            .put("id", profile.optString("id"))
            .put("name", profile.optString("name", "NovelAI"))
            .put("server_id", profile.optString("server_id"))
            .put("server_url", profile.optString("server_url"))
            .put("created_at", profile.optLong("created_at"));
    }
}
