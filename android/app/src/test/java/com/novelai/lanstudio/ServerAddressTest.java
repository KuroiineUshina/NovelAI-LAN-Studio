package com.novelai.lanstudio;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertThrows;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public final class ServerAddressTest {
    @Test
    public void normalizesPrivateAddressAndDefaultPort() {
        assertEquals("http://192.168.0.2:8787", ServerAddress.normalize("192.168.0.2"));
        assertEquals("http://10.0.2.2:9000", ServerAddress.normalize("http://10.0.2.2:9000/"));
    }

    @Test
    public void acceptsAllSupportedPrivateRanges() {
        assertTrue(ServerAddress.isPrivateIpv4("10.9.8.7"));
        assertTrue(ServerAddress.isPrivateIpv4("172.16.0.1"));
        assertTrue(ServerAddress.isPrivateIpv4("172.31.255.254"));
        assertTrue(ServerAddress.isPrivateIpv4("192.168.100.4"));
        assertTrue(ServerAddress.isPrivateIpv4("169.254.1.9"));
        assertTrue(ServerAddress.isPrivateIpv4("127.0.0.1"));
    }

    @Test
    public void acceptsOnlyTheTailscaleCgnatRangeForRemoteAccess() {
        assertTrue(ServerAddress.isTailscaleIpv4("100.64.0.0"));
        assertTrue(ServerAddress.isTailscaleIpv4("100.100.20.30"));
        assertTrue(ServerAddress.isTailscaleIpv4("100.127.255.255"));
        assertTrue(ServerAddress.isAllowedIpv4("100.101.102.103"));
        assertEquals(
            "http://100.101.102.103:8787",
            ServerAddress.normalize("100.101.102.103")
        );
        assertFalse(ServerAddress.isTailscaleIpv4("100.63.255.255"));
        assertFalse(ServerAddress.isTailscaleIpv4("100.128.0.0"));
    }

    @Test
    public void rejectsPublicOrMalformedAddresses() {
        assertFalse(ServerAddress.isPrivateIpv4("8.8.8.8"));
        assertFalse(ServerAddress.isPrivateIpv4("172.32.0.1"));
        assertFalse(ServerAddress.isPrivateIpv4("192.168.1.999"));
        assertFalse(ServerAddress.isPrivateIpv4("example.com"));
        assertThrows(IllegalArgumentException.class, () -> ServerAddress.normalize("https://192.168.0.2"));
        assertThrows(IllegalArgumentException.class, () -> ServerAddress.normalize("http://8.8.8.8:8787"));
        assertThrows(IllegalArgumentException.class, () -> ServerAddress.normalize("http://100.128.0.1:8787"));
        assertThrows(IllegalArgumentException.class, () -> ServerAddress.normalize("http://192.168.0.2:8787/admin"));
    }

    @Test
    public void allowsOnlyTheConnectedOrigin() {
        String base = "http://192.168.0.2:8787";
        assertTrue(ServerAddress.isAllowedUrl(base, "http://192.168.0.2:8787/api/status"));
        assertFalse(ServerAddress.isAllowedUrl(base, "http://192.168.0.3:8787/api/status"));
        assertFalse(ServerAddress.isAllowedUrl(base, "http://192.168.0.2:9000/api/status"));
        assertFalse(ServerAddress.isAllowedUrl(base, "http://192.168.0.2/api/status"));
        assertFalse(ServerAddress.isAllowedUrl(base, "http://guest@192.168.0.2:8787/api/status"));
        assertFalse(ServerAddress.isAllowedUrl(base, "https://192.168.0.2:8787/api/status"));
    }
}
