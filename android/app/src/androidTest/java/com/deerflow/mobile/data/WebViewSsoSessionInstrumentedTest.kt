package com.deerflow.mobile.data

import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.io.Closeable
import java.net.ServerSocket
import java.net.Socket
import java.nio.charset.StandardCharsets
import java.util.concurrent.CountDownLatch
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class WebViewSsoSessionInstrumentedTest {
    @Test
    fun oidcCallbackCookieIsAvailableToNativeGatewayRequests() = runBlocking {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val server = SsoCallbackServer()
        val completed = CountDownLatch(1)
        var cookies: WebViewSessionCookieStore? = null
        var browser: WebView? = null

        try {
            instrumentation.runOnMainSync {
                val sessionCookies = WebViewSessionCookieStore().also { it.clear() }
                cookies = sessionCookies
                browser = WebView(ApplicationProvider.getApplicationContext()).apply {
                    webViewClient = object : WebViewClient() {
                        override fun onPageFinished(view: WebView, url: String) {
                            super.onPageFinished(view, url)
                            if (url == "${server.url}/auth/callback") completed.countDown()
                        }
                    }
                    loadUrl(DeerFlowApi(server.url, sessionCookies).ssoLoginUrl("fixture"))
                }
            }

            assertTrue("The WebView did not reach the Gateway callback", completed.await(10, TimeUnit.SECONDS))
            val user = DeerFlowApi(server.url, requireNotNull(cookies)).currentUser()
            assertEquals("sso@deerflow.local", user?.email)
        } finally {
            instrumentation.runOnMainSync {
                browser?.destroy()
                cookies?.clear()
            }
            server.close()
        }
    }
}

private class SsoCallbackServer : Closeable {
    private val server = ServerSocket(0)
    private val executor: ExecutorService = Executors.newCachedThreadPool()
    val url = "http://localhost:${server.localPort}"

    init {
        executor.execute {
            try {
                while (!server.isClosed) {
                    val client = server.accept()
                    executor.execute { serve(client) }
                }
            } catch (_: Exception) {
                if (!server.isClosed) throw AssertionError("SSO callback fixture accept loop stopped")
            }
        }
    }

    override fun close() {
        server.close()
        executor.shutdownNow()
    }

    private fun serve(client: Socket) {
        client.use { socket ->
            val reader = socket.getInputStream().bufferedReader(StandardCharsets.UTF_8)
            val requestLine = reader.readLine() ?: return
            val headers = mutableMapOf<String, String>()
            while (true) {
                val line = reader.readLine() ?: break
                if (line.isEmpty()) break
                val separator = line.indexOf(':')
                if (separator > 0) headers[line.substring(0, separator).lowercase()] = line.substring(separator + 1).trim()
            }
            val path = requestLine.substringAfter(' ').substringBefore(' ').substringBefore('?')
            when (path) {
                "/api/v1/auth/oauth/fixture" -> writeRedirect(socket, "/api/v1/auth/callback/fixture")
                "/api/v1/auth/callback/fixture" -> writeRedirect(
                    socket,
                    "/auth/callback",
                    "access_token=fixture-session; Path=/; HttpOnly",
                )
                "/auth/callback" -> writeResponse(socket, 200, "OK", "<html><body>Signed in</body></html>", "text/html")
                "/api/v1/auth/me" -> {
                    val authorized = headers["cookie"].orEmpty().contains("access_token=fixture-session")
                    if (authorized) {
                        writeResponse(
                            socket,
                            200,
                            "OK",
                            """{"id":"sso-user","email":"sso@deerflow.local","system_role":"user","needs_setup":false}""",
                        )
                    } else {
                        writeResponse(socket, 401, "Unauthorized", """{"detail":"Unauthorized"}""")
                    }
                }
                else -> writeResponse(socket, 404, "Not Found", "{}")
            }
        }
    }

    private fun writeRedirect(socket: Socket, location: String, cookie: String? = null) {
        val headers = buildString {
            append("HTTP/1.1 302 Found\r\n")
            append("Location: $location\r\n")
            cookie?.let { append("Set-Cookie: $it\r\n") }
            append("Content-Length: 0\r\nConnection: close\r\n\r\n")
        }
        socket.getOutputStream().apply {
            write(headers.toByteArray(StandardCharsets.UTF_8))
            flush()
        }
    }

    private fun writeResponse(
        socket: Socket,
        statusCode: Int,
        reason: String,
        payload: String,
        contentType: String = "application/json",
    ) {
        val body = payload.toByteArray(StandardCharsets.UTF_8)
        val headers = buildString {
            append("HTTP/1.1 $statusCode $reason\r\n")
            append("Content-Type: $contentType; charset=utf-8\r\n")
            append("Content-Length: ${body.size}\r\nConnection: close\r\n\r\n")
        }
        socket.getOutputStream().apply {
            write(headers.toByteArray(StandardCharsets.UTF_8))
            write(body)
            flush()
        }
    }
}
