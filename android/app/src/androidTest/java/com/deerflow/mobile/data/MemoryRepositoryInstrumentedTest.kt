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
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class MemoryRepositoryInstrumentedTest {
    @Test
    fun memoryCrudResponsesReplaceTheCachedSnapshotUsedAfterDisconnect() = runBlocking {
        val server = MemoryGatewayServer()
        val cache = WorkspaceCache(ApplicationProvider.getApplicationContext())
        val repository = WorkspaceRepository(DeerFlowApi(server.url, MemoryTestCookieStore), cache)

        val loaded = repository.memory()
        assertFalse(loaded.fromCache)
        assertEquals(listOf("fact-original"), loaded.value.facts.map { it.id })

        val created = repository.createMemoryFact("Remember Room snapshots", "preference", 0.85)
        assertEquals(2, created.facts.size)
        assertEquals("Remember Room snapshots", created.facts.last().content)

        val updated = repository.updateMemoryFact("fact-created", "Remember offline Room snapshots", "workflow", 0.95)
        assertEquals("Remember offline Room snapshots", updated.facts.last().content)
        assertEquals("workflow", updated.facts.last().category)
        assertEquals(0.95, updated.facts.last().confidence, 0.0)

        val afterDelete = repository.deleteMemoryFact("fact-original")
        assertEquals(listOf("fact-created"), afterDelete.facts.map { it.id })

        val cleared = repository.clearMemory()
        assertTrue(cleared.isEmpty)

        assertEquals(
            listOf(
                "GET /api/memory",
                "POST /api/memory/facts",
                "PATCH /api/memory/facts/fact-created",
                "DELETE /api/memory/facts/fact-original",
                "DELETE /api/memory",
            ),
            server.requests.map { "${it.method} ${it.path}" },
        )
        JSONObject(server.requests[1].body).also { body ->
            assertEquals("Remember Room snapshots", body.getString("content"))
            assertEquals("preference", body.getString("category"))
            assertEquals(0.85, body.getDouble("confidence"), 0.0)
        }
        JSONObject(server.requests[2].body).also { body ->
            assertEquals("Remember offline Room snapshots", body.getString("content"))
            assertEquals("workflow", body.getString("category"))
            assertEquals(0.95, body.getDouble("confidence"), 0.0)
        }

        server.close()

        val offline = repository.memory()
        assertTrue(offline.fromCache)
        assertEquals(cleared, offline.value)
    }
}

private data class RecordedMemoryRequest(val method: String, val path: String, val body: String)

private class MemoryGatewayServer : Closeable {
    private val server = ServerSocket(0)
    private val executor: ExecutorService = Executors.newCachedThreadPool()
    private var memory = initialMemory()
    val requests = Collections.synchronizedList(mutableListOf<RecordedMemoryRequest>())
    val url = "http://127.0.0.1:${server.localPort}"

    init {
        executor.execute {
            try {
                while (!server.isClosed) {
                    val client = server.accept()
                    executor.execute { serve(client) }
                }
            } catch (_: Exception) {
                if (!server.isClosed) throw AssertionError("Memory fixture accept loop stopped")
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
            var contentLength = 0
            while (true) {
                val header = reader.readLine() ?: return
                if (header.isEmpty()) break
                if (header.startsWith("Content-Length:", ignoreCase = true)) {
                    contentLength = header.substringAfter(':').trim().toInt()
                }
            }
            val bodyChars = CharArray(contentLength)
            var offset = 0
            while (offset < contentLength) {
                val read = reader.read(bodyChars, offset, contentLength - offset)
                if (read < 0) break
                offset += read
            }
            val method = requestLine.substringBefore(' ')
            val path = requestLine.substringAfter(' ').substringBefore(' ')
            val request = RecordedMemoryRequest(method, path, String(bodyChars, 0, offset))
            requests += request
            val response = respond(request)
            val bytes = response.toString().toByteArray(StandardCharsets.UTF_8)
            val headers = buildString {
                append("HTTP/1.1 200 OK\r\n")
                append("Content-Type: application/json\r\n")
                append("Content-Length: ${bytes.size}\r\n")
                append("Connection: close\r\n\r\n")
            }.toByteArray(StandardCharsets.UTF_8)
            socket.getOutputStream().apply {
                write(headers)
                write(bytes)
                flush()
            }
        }
    }

    private fun respond(request: RecordedMemoryRequest): JSONObject {
        when {
            request.method == "POST" && request.path == "/api/memory/facts" -> {
                val input = JSONObject(request.body)
                memory.getJSONArray("facts").put(
                    JSONObject()
                        .put("id", "fact-created")
                        .put("content", input.getString("content"))
                        .put("category", input.getString("category"))
                        .put("confidence", input.getDouble("confidence"))
                        .put("createdAt", "2026-07-20T08:31:00Z")
                        .put("source", "manual"),
                )
            }
            request.method == "PATCH" && request.path == "/api/memory/facts/fact-created" -> {
                val input = JSONObject(request.body)
                memory.getJSONArray("facts").getJSONObject(1).apply {
                    put("content", input.getString("content"))
                    put("category", input.getString("category"))
                    put("confidence", input.getDouble("confidence"))
                }
            }
            request.method == "DELETE" && request.path == "/api/memory/facts/fact-original" -> {
                memory.getJSONArray("facts").remove(0)
            }
            request.method == "DELETE" && request.path == "/api/memory" -> {
                memory = emptyMemory()
            }
        }
        return memory
    }

    private fun initialMemory(): JSONObject = emptyMemory().apply {
        put("lastUpdated", "2026-07-20T08:30:00Z")
        getJSONObject("user").put(
            "workContext",
            JSONObject().put("summary", "Build Android client").put("updatedAt", "2026-07-20T08:00:00Z"),
        )
        getJSONArray("facts").put(
            JSONObject()
                .put("id", "fact-original")
                .put("content", "Use JDK 17")
                .put("category", "preference")
                .put("confidence", 0.9)
                .put("createdAt", "2026-07-20T08:25:00Z")
                .put("source", "thread-1"),
        )
    }

    private fun emptyMemory(): JSONObject = JSONObject(
        """{"version":"1.0","lastUpdated":"","user":{"workContext":{"summary":"","updatedAt":""},"personalContext":{"summary":"","updatedAt":""},"topOfMind":{"summary":"","updatedAt":""}},"history":{"recentMonths":{"summary":"","updatedAt":""},"earlierContext":{"summary":"","updatedAt":""},"longTermBackground":{"summary":"","updatedAt":""}},"facts":[]}""",
    )
}

private object MemoryTestCookieStore : SessionCookieStore {
    override fun cookieHeader(url: String): String? = null
    override fun csrfToken(url: String): String? = null
    override fun capture(url: String, responseHeaders: Map<String?, List<String>>) = Unit
    override fun clear() = Unit
}
