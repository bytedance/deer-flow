package com.deerflow.mobile.data

import android.webkit.CookieManager

interface SessionCookieStore {
    fun cookieHeader(url: String): String?
    fun csrfToken(url: String): String?
    fun capture(url: String, responseHeaders: Map<String?, List<String>>)
    fun clear()
}

class WebViewSessionCookieStore(
    private val manager: CookieManager = CookieManager.getInstance(),
) : SessionCookieStore {
    override fun cookieHeader(url: String): String? = manager.getCookie(url)

    override fun csrfToken(url: String): String? = cookieHeader(url)
        ?.split(';')
        ?.map { it.trim() }
        ?.firstOrNull { it.startsWith("csrf_token=") }
        ?.substringAfter('=')
        ?.takeIf { it.isNotBlank() }

    override fun capture(url: String, responseHeaders: Map<String?, List<String>>) {
        responseHeaders.entries
            .filter { it.key.equals("Set-Cookie", ignoreCase = true) }
            .flatMap { it.value }
            .forEach { manager.setCookie(url, it) }
        manager.flush()
    }

    override fun clear() {
        manager.removeAllCookies(null)
        manager.flush()
    }
}
