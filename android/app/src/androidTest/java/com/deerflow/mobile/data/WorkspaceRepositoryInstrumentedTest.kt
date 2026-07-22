package com.deerflow.mobile.data

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import java.io.Closeable
import java.net.ServerSocket
import java.net.Socket
import java.nio.charset.StandardCharsets
import java.util.Collections
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class WorkspaceRepositoryInstrumentedTest {
    @Test
    fun onlineWorkspaceMetadataIsCachedAndReturnedAfterDisconnect() = runBlocking {
        val server = MetadataGatewayServer()
        val api = DeerFlowApi(server.url, MetadataTestCookieStore)
        val cache = WorkspaceCache(ApplicationProvider.getApplicationContext())
        val repository = WorkspaceRepository(api, cache)

        val onlineCapabilities = repository.capabilities()
        val onlineTasks = repository.tasks()
        val onlineMcpTools = repository.mcpTools()

        assertFalse(onlineCapabilities.fromCache)
        assertFalse(onlineTasks.fromCache)
        assertFalse(onlineMcpTools.fromCache)
        assertEquals("model-1", onlineCapabilities.value.models.single().name)
        assertEquals("researcher", onlineCapabilities.value.agents.single().name)
        assertEquals("search", onlineCapabilities.value.skills.single().name)
        assertEquals("task-1", onlineTasks.value.single().id)
        assertEquals("search", onlineMcpTools.value.single().name)
        assertEquals(
            listOf("/api/features", "/api/models", "/api/agents", "/api/skills", "/api/scheduled-tasks", "/api/mcp/tools"),
            server.paths.toList(),
        )

        server.unauthorized = true
        val authError = runCatching { repository.tasks() }.exceptionOrNull()
        assertTrue(authError is ApiException)
        assertEquals(401, (authError as ApiException).statusCode)

        server.close()

        val offlineCapabilities = repository.capabilities()
        val offlineTasks = repository.tasks()
        val offlineMcpTools = repository.mcpTools()

        assertTrue(offlineCapabilities.fromCache)
        assertTrue(offlineTasks.fromCache)
        assertTrue(offlineMcpTools.fromCache)
        assertEquals(onlineCapabilities.value, offlineCapabilities.value)
        assertEquals(onlineTasks.value, offlineTasks.value)
        assertEquals(onlineMcpTools.value, offlineMcpTools.value)
    }
}

private class MetadataGatewayServer : Closeable {
    private val server = ServerSocket(0)
    private val executor: ExecutorService = Executors.newCachedThreadPool()
    val paths = Collections.synchronizedList(mutableListOf<String>())
    val url = "http://127.0.0.1:${server.localPort}"
    @Volatile var unauthorized = false

    init {
        executor.execute {
            try {
                while (!server.isClosed) {
                    val client = server.accept()
                    executor.execute { serve(client) }
                }
            } catch (_: Exception) {
                if (!server.isClosed) throw AssertionError("Metadata fixture accept loop stopped")
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
            while (reader.readLine()?.isNotEmpty() == true) Unit
            val path = requestLine.substringAfter(' ').substringBefore(' ')
            paths += path
            val statusCode = if (unauthorized) 401 else 200
            val reason = if (unauthorized) "Unauthorized" else "OK"
            val responseBody = if (unauthorized) "{\"detail\":\"Session expired\"}" else responseFor(path)
            val body = responseBody.toByteArray(StandardCharsets.UTF_8)
            val headers = buildString {
                append("HTTP/1.1 $statusCode $reason\r\n")
                append("Content-Type: application/json\r\n")
                append("Content-Length: ${body.size}\r\n")
                append("Connection: close\r\n\r\n")
            }.toByteArray(StandardCharsets.UTF_8)
            socket.getOutputStream().apply {
                write(headers)
                write(body)
                flush()
            }
        }
    }

    private fun responseFor(path: String): String = when (path) {
        "/api/features" -> """{"agents_api":{"enabled":true}}"""
        "/api/models" -> """{"models":[{"name":"model-1","display_name":"Model one","description":"Research","supports_thinking":true,"supports_reasoning_effort":false}]}"""
        "/api/agents" -> """{"agents":[{"name":"researcher","description":"Research agent","model":"model-1","skills":["search"],"soul":"Verify sources."}]}"""
        "/api/skills" -> """{"skills":[{"name":"search","description":"Searches sources","category":"public","enabled":true}]}"""
        "/api/scheduled-tasks" -> """[{"id":"task-1","title":"Daily brief","prompt":"Summarize updates","schedule_type":"cron","schedule_spec":{"cron":"0 9 * * *"},"timezone":"Asia/Shanghai","status":"active","next_run_at":"2026-07-21T01:00:00Z","last_error":null,"run_count":3}]"""
        "/api/mcp/tools" -> """{"tools":[{"server_name":"research","name":"search","description":"Search cited sources"}]}"""
        else -> "{}"
    }
}

private object MetadataTestCookieStore : SessionCookieStore {
    override fun cookieHeader(url: String): String? = null

    override fun csrfToken(url: String): String? = null

    override fun capture(url: String, responseHeaders: Map<String?, List<String>>) = Unit

    override fun clear() = Unit
}
