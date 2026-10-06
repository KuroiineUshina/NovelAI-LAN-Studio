package com.novelai.lanstudio;

import java.net.URI;
import java.net.URISyntaxException;
import java.util.Locale;

public final class ServerAddress {
    public static final int DEFAULT_PORT = 8787;

    private ServerAddress() {
    }

    public static String normalize(String raw) {
        if (raw == null || raw.trim().isEmpty()) {
            throw new IllegalArgumentException("empty address");
        }

        String value = raw.trim();
        if (!value.contains("://")) {
            value = "http://" + value;
        }

        final URI uri;
        try {
            uri = new URI(value);
        } catch (URISyntaxException error) {
            throw new IllegalArgumentException("invalid address", error);
        }

        if (!"http".equalsIgnoreCase(uri.getScheme()) || uri.getHost() == null || uri.getUserInfo() != null) {
            throw new IllegalArgumentException("only private HTTP addresses are allowed");
        }
        if (uri.getQuery() != null || uri.getFragment() != null) {
            throw new IllegalArgumentException("query and fragment are not allowed");
        }
        String path = uri.getPath();
        if (path != null && !path.isEmpty() && !"/".equals(path)) {
            throw new IllegalArgumentException("server address must not contain a path");
        }

        String host = uri.getHost().toLowerCase(Locale.ROOT);
        if (!isAllowedIpv4(host)) {
            throw new IllegalArgumentException("public addresses are not allowed");
        }

        int port = uri.getPort() == -1 ? DEFAULT_PORT : uri.getPort();
        if (port < 1 || port > 65535) {
            throw new IllegalArgumentException("invalid port");
        }
        return "http://" + host + ":" + port;
    }

    public static boolean isAllowedUrl(String baseUrl, String candidateUrl) {
        if (baseUrl == null || candidateUrl == null) {
            return false;
        }
        try {
            URI base = new URI(normalize(baseUrl));
            URI candidate = new URI(candidateUrl);
            int candidatePort = candidate.getPort() == -1 ? 80 : candidate.getPort();
            return "http".equalsIgnoreCase(candidate.getScheme())
                && candidate.getUserInfo() == null
                && base.getHost().equalsIgnoreCase(candidate.getHost())
                && base.getPort() == candidatePort;
        } catch (IllegalArgumentException | URISyntaxException error) {
            return false;
        }
    }

    public static boolean isPrivateIpv4(String host) {
        int[] octets = parseIpv4(host);
        if (octets == null) {
            return false;
        }
        return octets[0] == 10
            || (octets[0] == 172 && octets[1] >= 16 && octets[1] <= 31)
            || (octets[0] == 192 && octets[1] == 168)
            || octets[0] == 127
            || (octets[0] == 169 && octets[1] == 254);
    }

    public static boolean isTailscaleIpv4(String host) {
        int[] octets = parseIpv4(host);
        return octets != null
            && octets[0] == 100
            && octets[1] >= 64
            && octets[1] <= 127;
    }

    public static boolean isAllowedIpv4(String host) {
        return isPrivateIpv4(host) || isTailscaleIpv4(host);
    }

    private static int[] parseIpv4(String host) {
        String[] parts = host.split("\\.", -1);
        if (parts.length != 4) {
            return null;
        }
        int[] octets = new int[4];
        for (int index = 0; index < parts.length; index++) {
            if (parts[index].isEmpty() || parts[index].length() > 3) {
                return null;
            }
            try {
                octets[index] = Integer.parseInt(parts[index]);
            } catch (NumberFormatException error) {
                return null;
            }
            if (octets[index] < 0 || octets[index] > 255) {
                return null;
            }
        }
        return octets;
    }
}
