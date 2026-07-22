package com.deerflow.mobile.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test

class ServerUrlTest {
    @Test
    fun defaultsPublicHostsToHttps() {
        assertEquals("https://deerflow.example.com", normalizeServerUrl("deerflow.example.com/"))
    }

    @Test
    fun keepsLocalDevelopmentOnHttp() {
        assertEquals("http://10.0.2.2:2026", normalizeServerUrl("10.0.2.2:2026"))
        assertEquals("http://192.168.1.20:2026", normalizeServerUrl("192.168.1.20:2026"))
    }

    @Test
    fun defaultsAnIpv4GatewayToHttpUntilTheUserExplicitlySelectsHttps() {
        assertEquals("http://47.108.210.135:32756", normalizeServerUrl("47.108.210.135:32756"))
        assertEquals("https://47.108.210.135:32756", normalizeServerUrl("https://47.108.210.135:32756"))
    }

    @Test
    fun rejectsApiPathsAndUnsupportedSchemes() {
        assertThrows(IllegalArgumentException::class.java) {
            normalizeServerUrl("https://example.com/api")
        }
        assertThrows(IllegalArgumentException::class.java) {
            normalizeServerUrl("ftp://example.com")
        }
    }
}
