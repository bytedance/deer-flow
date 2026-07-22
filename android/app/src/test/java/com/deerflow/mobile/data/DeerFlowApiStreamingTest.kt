package com.deerflow.mobile.data

import java.io.Closeable
import java.net.ServerSocket
import java.net.Socket
import java.nio.charset.StandardCharsets
import java.util.Collections
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicInteger
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.json.JSONObject

class DeerFlowApiStreamingTest {
    @Test
    fun reconnectsWithLastEventIdAndSkipsDuplicateFrames() = runBlocking {
        val server = ScriptedSseServer(
            listOf(
                sse(
                    "event: metadata\nid: event-1\ndata: {\"run_id\":\"run-1\"}",
                    "event: messages-tuple\nid: event-2\ndata: {\"type\":\"ai\",\"id\":\"ai-1\",\"content\":\"Hello \"}",
                ),
                sse(
                    "event: messages-tuple\nid: event-2\ndata: {\"type\":\"ai\",\"id\":\"ai-1\",\"content\":\"Hello \"}",
                    "event: messages-tuple\nid: event-3\ndata: {\"type\":\"ai\",\"id\":\"ai-1\",\"content\":\"world\"}",
                    "event: end\nid: event-4\ndata: null",
                ),
            ),
        )
        try {
            val updates = mutableListOf<StreamUpdate>()
            withTimeout(10_000) {
                DeerFlowApi(server.url, NoopSessionCookieStore).streamMessage(
                    threadId = "thread-1",
                    message = "Reconnect this run",
                    options = RunOptions(),
                ) { updates += it }
            }

            assertEquals(2, server.requests.size)
            assertEquals("event-2", server.requests[1].headers["last-event-id"])
            assertEquals(
                listOf("Hello ", "world"),
                updates.filterIsInstance<StreamUpdate.MessageChunk>().map { it.value.text },
            )
            assertEquals(
                listOf("event-1", "event-2", "event-3", "event-4"),
                updates.filterIsInstance<StreamUpdate.EventId>().map { it.value },
            )
            assertTrue(updates.any { it == StreamUpdate.Reconnecting(1) })
            assertTrue(updates.last() == StreamUpdate.Finished)
        } finally {
            server.close()
        }
    }

    @Test
    fun convertsHttpErrorPayloadIntoApiException() = runBlocking {
        val server = ScriptedSseServer(
            listOf(
                ScriptedResponse(
                    statusCode = 409,
                    contentType = "application/json",
                    body = "{\"detail\":\"This conversation is already running.\"}",
                ),
            ),
        )
        try {
            var caught: ApiException? = null
            try {
                DeerFlowApi(server.url, NoopSessionCookieStore).streamMessage(
                    threadId = "thread-1",
                    message = "Conflict",
                    options = RunOptions(),
                ) { }
            } catch (error: ApiException) {
                caught = error
            }

            assertEquals(409, caught?.statusCode)
            assertEquals("This conversation is already running.", caught?.message)
        } finally {
            server.close()
        }
    }

    @Test
    fun persistsSkillEnabledStateThroughTheGatewayContract() = runBlocking {
        val server = ScriptedSseServer(
            listOf(
                ScriptedResponse(
                    contentType = "application/json",
                    body = "{\"name\":\"writing-studio\",\"description\":\"Draft reports\",\"category\":\"public\",\"enabled\":false}",
                ),
            ),
        )
        try {
            val skill = DeerFlowApi(server.url, NoopSessionCookieStore).setSkillEnabled("writing-studio", false)

            assertEquals("writing-studio", skill.name)
            assertFalse(skill.enabled)
            assertEquals("PUT", server.requests.single().method)
            assertEquals("/api/skills/writing-studio", server.requests.single().path)
            assertFalse(JSONObject(server.requests.single().body).getBoolean("enabled"))
        } finally {
            server.close()
        }
    }

    @Test
    fun readsScheduledTaskExecutionHistoryThroughTheGatewayContract() = runBlocking {
        val server = ScriptedSseServer(
            listOf(
                ScriptedResponse(
                    contentType = "application/json",
                    body = """[{"id":"task-run-1","task_id":"daily-brief","thread_id":"thread-1","run_id":"gateway-run-1","scheduled_for":"2026-07-20T09:00:00+08:00","trigger":"scheduled","status":"success","error":null,"started_at":"2026-07-20T09:00:04+08:00","finished_at":"2026-07-20T09:01:09+08:00","created_at":"2026-07-20T09:00:00+08:00"}]""",
                ),
            ),
        )
        try {
            val runs = DeerFlowApi(server.url, NoopSessionCookieStore).listScheduledTaskRuns("daily-brief")

            assertEquals(1, runs.size)
            assertEquals("task-run-1", runs.single().id)
            assertEquals("thread-1", runs.single().threadId)
            assertEquals("gateway-run-1", runs.single().runId)
            assertEquals("success", runs.single().status)
            assertNull(runs.single().error)
            assertEquals("GET", server.requests.single().method)
            assertEquals("/api/scheduled-tasks/daily-brief/runs", server.requests.single().path)
        } finally {
            server.close()
        }
    }

    @Test
    fun createsAndUpdatesOnceTasksThroughTheGatewayContract() = runBlocking {
        val schedule = TaskSchedule.Once("2026-12-31T09:30:00+08:00")
        val server = ScriptedSseServer(
            listOf(
                ScriptedResponse(contentType = "application/json", body = "{}"),
                ScriptedResponse(contentType = "application/json", body = "{}"),
            ),
        )
        try {
            val api = DeerFlowApi(server.url, NoopSessionCookieStore)
            api.createScheduledTask("Release review", "Review the release", schedule, "Asia/Shanghai")
            api.updateScheduledTask("release once", "Updated review", "Review the final release", schedule, "Asia/Shanghai")

            val create = JSONObject(server.requests[0].body)
            assertEquals("POST", server.requests[0].method)
            assertEquals("/api/scheduled-tasks", server.requests[0].path)
            assertEquals("once", create.getString("schedule_type"))
            assertEquals(schedule.runAt, create.getJSONObject("schedule_spec").getString("run_at"))

            val update = JSONObject(server.requests[1].body)
            assertEquals("PATCH", server.requests[1].method)
            assertEquals("/api/scheduled-tasks/release+once", server.requests[1].path)
            assertFalse(update.has("schedule_type"))
            assertEquals(schedule.runAt, update.getJSONObject("schedule_spec").getString("run_at"))
        } finally {
            server.close()
        }
    }

    @Test
    fun readsOneTimeTaskScheduleFromTheGatewayContract() = runBlocking {
        val server = ScriptedSseServer(
            listOf(
                ScriptedResponse(
                    contentType = "application/json",
                    body = """[{"id":"release-review","title":"Release review","prompt":"Review the release","schedule_type":"once","schedule_spec":{"run_at":"2026-12-31T09:30:00+08:00"},"timezone":"Asia/Shanghai","status":"enabled","next_run_at":"2026-12-31T09:30:00+08:00","last_error":null,"run_count":0}]""",
                ),
            ),
        )
        try {
            val task = DeerFlowApi(server.url, NoopSessionCookieStore).listScheduledTasks().single()

            assertEquals("once", task.scheduleType)
            assertEquals("2026-12-31T09:30:00+08:00", task.scheduleLabel)
            assertEquals("Asia/Shanghai", task.timezone)
            assertEquals("GET", server.requests.single().method)
            assertEquals("/api/scheduled-tasks", server.requests.single().path)
        } finally {
            server.close()
        }
    }

    @Test
    fun readsAgentExecutionHistoryAndSafelyEncodesTheAgentFilter() = runBlocking {
        val server = ScriptedSseServer(
            listOf(
                ScriptedResponse(
                    contentType = "application/json",
                    body =
                        """{"runs":[{"run_id":"run-1","thread_id":"thread-1","thread_title":"Release review","assistant_id":"research & review/+?#%","status":"success","model_name":"deepseek-chat","created_at":"2026-07-20T09:00:00Z","updated_at":"2026-07-20T09:00:12Z","duration_seconds":12.5,"total_tokens":4312,"message_count":8,"cost":0.012345,"error":null},{"run_id":"run-2","thread_id":"thread-2","thread_title":null,"assistant_id":null,"status":"error","model_name":null,"created_at":null,"updated_at":null,"duration_seconds":null,"total_tokens":0,"message_count":0,"cost":null,"error":"Provider unavailable"}],"has_more":false}""",
                ),
            ),
        )
        try {
            val runs = DeerFlowApi(server.url, NoopSessionCookieStore).listAgentRuns(
                agentId = "research & review/+?#%",
            )

            assertEquals(2, runs.size)
            assertEquals(
                AgentRunInfo(
                    runId = "run-1",
                    threadId = "thread-1",
                    threadTitle = "Release review",
                    assistantId = "research & review/+?#%",
                    status = "success",
                    modelName = "deepseek-chat",
                    createdAt = "2026-07-20T09:00:00Z",
                    updatedAt = "2026-07-20T09:00:12Z",
                    durationSeconds = 12.5,
                    totalTokens = 4312,
                    messageCount = 8,
                    cost = 0.012345,
                    error = null,
                ),
                runs.first(),
            )
            assertNull(runs.last().threadTitle)
            assertNull(runs.last().assistantId)
            assertNull(runs.last().modelName)
            assertNull(runs.last().createdAt)
            assertNull(runs.last().updatedAt)
            assertNull(runs.last().durationSeconds)
            assertNull(runs.last().cost)
            assertEquals("Provider unavailable", runs.last().error)
            assertEquals("GET", server.requests.single().method)
            assertEquals(
                "/api/console/runs?assistant_id=research%20%26%20review%2F%2B%3F%23%25&limit=50",
                server.requests.single().path,
            )
        } finally {
            server.close()
        }
    }

    @Test
    fun readsPublicSsoProvidersAndBuildsAnEncodedGatewayLoginUrl() = runBlocking {
        val server = ScriptedSseServer(
            listOf(
                ScriptedResponse(
                    contentType = "application/json",
                    body = """{"providers":[{"id":"google","display_name":"Google","type":"oidc"},{"id":"keycloak","display_name":"Company SSO","type":"oidc"},{"display_name":"Invalid"}]}""",
                ),
            ),
        )
        try {
            val api = DeerFlowApi(server.url, NoopSessionCookieStore)

            assertEquals(listOf("Company SSO", "Google"), api.ssoProviders().map { it.displayName })
            assertEquals("GET", server.requests.single().method)
            assertEquals("/api/v1/auth/providers", server.requests.single().path)
            assertEquals("${server.url}/api/v1/auth/oauth/keycloak", api.ssoLoginUrl("keycloak"))
        } finally {
            server.close()
        }
    }

    @Test
    fun persistsOnlyTheTargetMcpServerToggleWhilePreservingMaskedConfiguration() = runBlocking {
        val initial = """{"mcp_servers":{"research":{"enabled":true,"type":"http","headers":{"Authorization":"***"},"description":"Research","tools":{"search":{"enabled":true}},"future_field":{"mode":"strict"}},"files":{"enabled":false,"type":"stdio","command":"npx","args":["-y","files"]}}}"""
        val updated = """{"mcp_servers":{"research":{"enabled":false,"type":"http","headers":{"Authorization":"***"},"description":"Research","tools":{"search":{"enabled":true}},"future_field":{"mode":"strict"}},"files":{"enabled":false,"type":"stdio","command":"npx","args":["-y","files"]}}}"""
        val server = ScriptedSseServer(
            listOf(
                ScriptedResponse(contentType = "application/json", body = initial),
                ScriptedResponse(contentType = "application/json", body = updated),
            ),
        )
        try {
            val api = DeerFlowApi(server.url, NoopSessionCookieStore)
            val config = api.loadMcpConfig()
            val result = api.setMcpServerEnabled(config, "research", false)

            assertFalse(result.servers.single { it.name == "research" }.enabled)
            assertEquals(listOf("search"), result.servers.single { it.name == "research" }.toolOverrides)
            assertEquals("GET", server.requests[0].method)
            assertEquals("PUT", server.requests[1].method)
            val request = JSONObject(server.requests[1].body).getJSONObject("mcp_servers")
            assertFalse(request.getJSONObject("research").getBoolean("enabled"))
            assertEquals("***", request.getJSONObject("research").getJSONObject("headers").getString("Authorization"))
            assertEquals("strict", request.getJSONObject("research").getJSONObject("future_field").getString("mode"))
            assertFalse(request.getJSONObject("files").getBoolean("enabled"))
        } finally {
            server.close()
        }
    }

    @Test
    fun readsMcpToolCatalogAndSavesFullMaskedConfiguration() = runBlocking {
        val tools = """{"tools":[{"server_name":"research","name":"summarize","description":"Summarize sources"},{"server_name":"research","name":"search","description":"Search sources"}]}"""
        val updated = """{"mcp_servers":{"research":{"enabled":true,"type":"http","headers":{"Authorization":"***"},"description":"Research","routing":{"keywords":["research"]}}}}"""
        val server = ScriptedSseServer(
            listOf(
                ScriptedResponse(contentType = "application/json", body = tools),
                ScriptedResponse(contentType = "application/json", body = updated),
            ),
        )
        try {
            val api = DeerFlowApi(server.url, NoopSessionCookieStore)
            val catalog = api.loadMcpTools()
            val config = api.updateMcpConfig(updated)

            assertEquals(listOf("search", "summarize"), catalog.map { it.name })
            assertEquals("research", catalog.first().serverName)
            assertEquals("GET", server.requests[0].method)
            assertEquals("/api/mcp/tools", server.requests[0].path)
            assertEquals("PUT", server.requests[1].method)
            assertEquals("***", JSONObject(server.requests[1].body)
                .getJSONObject("mcp_servers")
                .getJSONObject("research")
                .getJSONObject("headers")
                .getString("Authorization"))
            assertEquals("Research", config.servers.single().description)
        } finally {
            server.close()
        }
    }

    @Test
    fun fallsBackToConfiguredMcpToolsWhenDiscoveryIsUnavailable() = runBlocking {
        val config = """{"mcp_servers":{"research":{"enabled":true,"type":"http","description":"Research sources","tools":["search","summarize"]},"files":{"enabled":true,"type":"stdio","description":"Workspace files"}}}"""
        val server = ScriptedSseServer(
            listOf(
                ScriptedResponse(statusCode = 404, contentType = "application/json", body = "{\"detail\":\"Not found\"}"),
                ScriptedResponse(contentType = "application/json", body = config),
            ),
        )
        try {
            val catalog = DeerFlowApi(server.url, NoopSessionCookieStore).loadMcpTools()

            assertEquals(
                listOf("files:MCP server", "research:search", "research:summarize"),
                catalog.map { "${it.serverName}:${it.name}" },
            )
            assertEquals(listOf("/api/mcp/tools", "/api/mcp/config"), server.requests.map { it.path })
        } finally {
            server.close()
        }
    }

    @Test
    fun managesChannelRuntimeConfigAndBindingThroughTheGatewayContract() = runBlocking {
        val providers = """{"enabled":true,"providers":[{"provider":"telegram","display_name":"Telegram","enabled":true,"configured":false,"connectable":false,"unavailable_reason":"Runtime credentials are required.","auth_mode":"deep_link","connection_status":"not_connected","credential_fields":[{"name":"bot_token","label":"Bot token","type":"password","required":true},{"name":"bot_username","label":"Bot username","type":"text","required":true}],"credential_values":{}}]}"""
        val configured = """{"provider":"telegram","display_name":"Telegram","enabled":true,"configured":true,"connectable":true,"unavailable_reason":null,"auth_mode":"deep_link","connection_status":"not_connected","credential_fields":[{"name":"bot_token","label":"Bot token","type":"password","required":true},{"name":"bot_username","label":"Bot username","type":"text","required":true}],"credential_values":{"bot_token":"********","bot_username":"fixture_bot"}}"""
        val disconnected = """{"provider":"telegram","display_name":"Telegram","enabled":true,"configured":false,"connectable":false,"unavailable_reason":"Runtime credentials are required.","auth_mode":"deep_link","connection_status":"not_connected","credential_fields":[],"credential_values":{}}"""
        val connection = """{"provider":"telegram","mode":"deep_link","url":"https://channels.example.test/telegram","code":"bind-telegram","instruction":"Open Telegram to finish binding.","expires_in":600}"""
        val server = ScriptedSseServer(
            listOf(
                ScriptedResponse(contentType = "application/json", body = providers),
                ScriptedResponse(contentType = "application/json", body = configured),
                ScriptedResponse(contentType = "application/json", body = disconnected),
                ScriptedResponse(contentType = "application/json", body = connection),
            ),
        )
        try {
            val api = DeerFlowApi(server.url, NoopSessionCookieStore)
            val initial = api.loadChannelProviders()
            val updated = api.configureChannelProvider(
                "telegram",
                mapOf("bot_token" to "secret", "bot_username" to "fixture_bot"),
            )
            val disabled = api.disconnectChannelProvider("telegram")
            val binding = api.connectChannelProvider("telegram")

            assertFalse(initial.providers.single().configured)
            assertEquals("password", initial.providers.single().credentialFields.first().type)
            assertTrue(updated.configured)
            assertEquals("********", updated.credentialValues["bot_token"])
            assertFalse(disabled.configured)
            assertEquals("bind-telegram", binding.code)
            assertEquals("https://channels.example.test/telegram", binding.url)

            assertEquals("GET", server.requests[0].method)
            assertEquals("/api/channels/providers", server.requests[0].path)
            assertEquals("POST", server.requests[1].method)
            assertEquals("/api/channels/telegram/runtime-config", server.requests[1].path)
            val configuration = JSONObject(server.requests[1].body).getJSONObject("values")
            assertEquals("secret", configuration.getString("bot_token"))
            assertEquals("fixture_bot", configuration.getString("bot_username"))
            assertEquals("DELETE", server.requests[2].method)
            assertEquals("/api/channels/telegram/runtime-config", server.requests[2].path)
            assertEquals("POST", server.requests[3].method)
            assertEquals("/api/channels/telegram/connect", server.requests[3].path)
        } finally {
            server.close()
        }
    }

    @Test
    fun exposesSseErrorAsFailureUpdateBeforeEnd() = runBlocking {
        val server = ScriptedSseServer(
            listOf(
                sse(
                    "event: error\nid: error-1\ndata: {\"message\":\"Provider unavailable\"}",
                    "event: end\nid: end-1\ndata: null",
                ),
            ),
        )
        try {
            val updates = mutableListOf<StreamUpdate>()
            DeerFlowApi(server.url, NoopSessionCookieStore).streamMessage(
                threadId = "thread-1",
                message = "Surface the error",
                options = RunOptions(),
            ) { updates += it }

            assertEquals(
                listOf("Provider unavailable"),
                updates.filterIsInstance<StreamUpdate.Failure>().map { it.message },
            )
            assertTrue(updates.last() == StreamUpdate.Finished)
        } finally {
            server.close()
        }
    }

    @Test
    fun streamRequestUsesOnlyTheSelectedModelsSupportedOptions() = runBlocking {
        val server = ScriptedSseServer(
            listOf(
                sse("event: end\nid: fast-end\ndata: null"),
                sse("event: end\nid: pro-end\ndata: null"),
            ),
        )
        try {
            val api = DeerFlowApi(server.url, NoopSessionCookieStore)
            api.streamMessage(
                threadId = "thread-fast",
                message = "Use the fast model",
                options = RunOptions(
                    modelName = "deerflow-fast",
                    mode = RunMode.Flash,
                    reasoningEffortEnabled = false,
                ),
            ) { }
            api.streamMessage(
                threadId = "thread-pro",
                message = "Use the pro model",
                options = RunOptions(
                    modelName = "deerflow-pro",
                    mode = RunMode.Ultra,
                    reasoningEffortEnabled = true,
                ),
            ) { }

            val fastContext = JSONObject(server.requests[0].body).getJSONObject("context")
            assertEquals("deerflow-fast", fastContext.getString("model_name"))
            assertFalse(fastContext.getBoolean("thinking_enabled"))
            assertFalse(fastContext.getBoolean("is_plan_mode"))
            assertFalse(fastContext.getBoolean("subagent_enabled"))
            assertFalse(fastContext.has("reasoning_effort"))

            val proContext = JSONObject(server.requests[1].body).getJSONObject("context")
            assertEquals("deerflow-pro", proContext.getString("model_name"))
            assertTrue(proContext.getBoolean("thinking_enabled"))
            assertTrue(proContext.getBoolean("is_plan_mode"))
            assertTrue(proContext.getBoolean("subagent_enabled"))
            assertEquals("high", proContext.getString("reasoning_effort"))
        } finally {
            server.close()
        }
    }

    @Test
    fun sendsTheStableClientMessageIdAndMergesUpdateFieldsWithoutValuesStream() = runBlocking {
        val server = ScriptedSseServer(
            listOf(
                sse(
                    "event: updates\nid: update-1\ndata: {\"agent\":{\"title\":\"Research\",\"todos\":[{\"content\":\"Write\",\"status\":\"in_progress\"}],\"artifacts\":[\"report.md\"]}}",
                    "event: end\nid: end-1\ndata: null",
                ),
            ),
        )
        try {
            val updates = mutableListOf<StreamUpdate>()
            DeerFlowApi(server.url, NoopSessionCookieStore).streamMessage(
                threadId = "thread-1",
                message = "Research this",
                options = RunOptions(),
                clientMessageId = "client-message-1",
            ) { updates += it }

            val request = server.requests.single()
            val payload = JSONObject(request.body)
            assertEquals("client-message-1", payload.getJSONObject("input").getJSONArray("messages").getJSONObject(0).getString("id"))
            assertEquals(listOf("messages-tuple", "updates"), payload.getJSONArray("stream_mode").let { modes ->
                List(modes.length()) { modes.getString(it) }
            })
            assertFalse(payload.getBoolean("stream_subgraphs"))
            assertFalse(request.headers["accept-encoding"].equals("identity", ignoreCase = true))

            val snapshot = updates.filterIsInstance<StreamUpdate.Snapshot>().single().value
            assertEquals("Research", snapshot.title)
            assertTrue(snapshot.hasTodos)
            assertTrue(snapshot.hasArtifacts)
            assertEquals("Write", snapshot.todos.single().content)
            assertEquals(listOf("report.md"), snapshot.artifacts)
        } finally {
            server.close()
        }
    }

    @Test
    fun unexpectedEofRecoversAtMostOnce() = runBlocking {
        val server = ScriptedSseServer(
            listOf(
                sse("event: metadata\nid: one\ndata: {\"run_id\":\"run-1\"}"),
                sse("event: messages-tuple\nid: two\ndata: {\"type\":\"ai\",\"id\":\"ai-1\",\"content\":\"partial\"}"),
                sse("event: end\nid: unexpected\ndata: null"),
            ),
        )
        try {
            DeerFlowApi(server.url, NoopSessionCookieStore).streamMessage(
                threadId = "thread-1",
                message = "Recover once",
                options = RunOptions(),
            ) { }

            assertEquals(2, server.requests.size)
            assertEquals("run-1", server.requests[1].path.substringAfter("/runs/").substringBefore('/'))
        } finally {
            server.close()
        }
    }
}

private data class ScriptedResponse(
    val statusCode: Int = 200,
    val contentType: String = "text/event-stream",
    val body: String,
)

private data class CapturedRequest(
    val method: String,
    val path: String,
    val headers: Map<String, String>,
    val body: String,
)

private class ScriptedSseServer(
    private val responses: List<ScriptedResponse>,
) : Closeable {
    private val server = ServerSocket(0)
    private val responseIndex = AtomicInteger()
    private val executor: ExecutorService = Executors.newCachedThreadPool()
    val requests = Collections.synchronizedList(mutableListOf<CapturedRequest>())
    val url: String = "http://127.0.0.1:${server.localPort}"

    init {
        executor.execute {
            try {
                while (!server.isClosed) {
                    val client = server.accept()
                    executor.execute { serve(client) }
                }
            } catch (_: Exception) {
                if (!server.isClosed) throw AssertionError("SSE fixture accept loop stopped")
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
            val headers = buildMap {
                while (true) {
                    val line = reader.readLine() ?: break
                    if (line.isEmpty()) break
                    val separator = line.indexOf(':')
                    if (separator > 0) put(line.substring(0, separator).lowercase(), line.substring(separator + 1).trim())
                }
            }
            val bodyLength = headers["content-length"]?.toIntOrNull() ?: 0
            val bodyCharacters = CharArray(bodyLength)
            var bodyOffset = 0
            while (bodyOffset < bodyLength) {
                val read = reader.read(bodyCharacters, bodyOffset, bodyLength - bodyOffset)
                if (read < 0) break
                bodyOffset += read
            }
            val separator = requestLine.indexOf(' ')
            val pathSeparator = requestLine.indexOf(' ', separator + 1)
            requests += CapturedRequest(
                method = requestLine.substring(0, separator),
                path = requestLine.substring(separator + 1, pathSeparator),
                headers = headers,
                body = String(bodyCharacters, 0, bodyOffset),
            )

            val scripted = responses.getOrNull(responseIndex.getAndIncrement()) ?: ScriptedResponse(body = "")
            val body = scripted.body.toByteArray(StandardCharsets.UTF_8)
            val reason = when (scripted.statusCode) {
                409 -> "Conflict"
                500 -> "Internal Server Error"
                else -> "OK"
            }
            val response = buildString {
                append("HTTP/1.1 ${scripted.statusCode} $reason\r\n")
                append("Content-Type: ${scripted.contentType}\r\n")
                append("Content-Length: ${body.size}\r\n")
                append("Content-Location: /api/threads/thread-1/runs/run-1\r\n")
                append("Connection: close\r\n\r\n")
            }.toByteArray(StandardCharsets.UTF_8)
            socket.getOutputStream().apply {
                write(response)
                write(body)
                flush()
            }
        }
    }
}

private fun sse(vararg frames: String): ScriptedResponse = ScriptedResponse(
    body = frames.joinToString("\n\n", postfix = "\n\n"),
)

private object NoopSessionCookieStore : SessionCookieStore {
    override fun cookieHeader(url: String): String? = null

    override fun csrfToken(url: String): String? = null

    override fun capture(url: String, responseHeaders: Map<String?, List<String>>) = Unit

    override fun clear() = Unit
}
