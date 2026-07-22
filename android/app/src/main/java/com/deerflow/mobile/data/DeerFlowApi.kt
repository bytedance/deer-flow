package com.deerflow.mobile.data

import java.io.BufferedReader
import java.io.FilterInputStream
import java.io.IOException
import java.io.InputStream
import java.io.InputStreamReader
import java.net.HttpURLConnection
import java.net.URLEncoder
import java.nio.charset.StandardCharsets
import java.util.UUID
import java.util.concurrent.TimeUnit
import android.util.Log
import com.deerflow.mobile.BuildConfig
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import okhttp3.Call
import okhttp3.Interceptor
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.ResponseBody
import okhttp3.RequestBody.Companion.toRequestBody
import okio.BufferedSink
import okio.source
import org.json.JSONArray
import org.json.JSONException
import org.json.JSONObject
import org.json.JSONTokener
import retrofit2.Response
import retrofit2.Retrofit
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.HTTP
import retrofit2.http.PATCH
import retrofit2.http.POST
import retrofit2.http.PUT
import retrofit2.http.Url

class ApiException(
    val statusCode: Int,
    override val message: String,
) : Exception(message)

data class UploadSource(
    val filename: String,
    val mimeType: String,
    val length: Long,
    val open: () -> InputStream,
)

private interface GatewayService {
    @GET suspend fun get(@Url url: String): Response<ResponseBody>
    @POST suspend fun post(@Url url: String, @Body body: RequestBody): Response<ResponseBody>
    @PATCH suspend fun patch(@Url url: String, @Body body: RequestBody): Response<ResponseBody>
    @PUT suspend fun put(@Url url: String, @Body body: RequestBody): Response<ResponseBody>
    @HTTP(method = "DELETE", hasBody = false) suspend fun delete(@Url url: String): Response<ResponseBody>
}

class DeerFlowApi(
    serverUrl: String,
    private val cookies: SessionCookieStore,
) {
    @Volatile
    var serverUrl: String = normalizeServerUrl(serverUrl)
        private set

    private val client = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(60, TimeUnit.SECONDS)
        .addNetworkInterceptor(SessionInterceptor(cookies))
        .build()
    private val streamClient = client.newBuilder().readTimeout(0, TimeUnit.MILLISECONDS).build()
    private val service = Retrofit.Builder()
        .baseUrl("https://localhost/")
        .client(client)
        .build()
        .create(GatewayService::class.java)

    @Volatile private var activeCall: Call? = null

    fun updateServerUrl(value: String) {
        serverUrl = normalizeServerUrl(value)
    }

    suspend fun currentUser(): DeerFlowUser? = try {
        parseUser(request("GET", "/api/v1/auth/me"))
    } catch (error: ApiException) {
        if (error.statusCode == HttpURLConnection.HTTP_UNAUTHORIZED) null else throw error
    }

    suspend fun login(email: String, password: String): DeerFlowUser {
        val form = "username=${formEncode(email)}&password=${formEncode(password)}"
        request("POST", "/api/v1/auth/login/local", form, "application/x-www-form-urlencoded")
        return currentUser() ?: throw ApiException(401, "The server did not create a session.")
    }

    suspend fun ssoProviders(): List<SsoProvider> {
        val providers = JSONObject(request("GET", "/api/v1/auth/providers")).optJSONArray("providers") ?: JSONArray()
        return buildList {
            for (index in 0 until providers.length()) {
                val provider = providers.optJSONObject(index) ?: continue
                val id = provider.optString("id")
                if (id.isBlank()) continue
                add(SsoProvider(id = id, displayName = provider.optString("display_name", id)))
            }
        }.sortedBy(SsoProvider::displayName)
    }

    fun ssoLoginUrl(providerId: String): String = url("/api/v1/auth/oauth/${pathSegment(providerId)}")

    suspend fun logout() {
        runCatching { request("POST", "/api/v1/auth/logout", "") }
        cookies.clear()
    }

    suspend fun listThreads(): List<ThreadSummary> {
        val response = request("POST", "/api/threads/search", """{"limit":100,"offset":0}""")
        val array = JSONArray(response)
        return buildList {
            for (index in 0 until array.length()) array.optJSONObject(index)?.let { add(it.toThreadSummary()) }
        }.sortedByDescending { it.updatedAt }
    }

    suspend fun createThread(assistantId: String = "lead_agent"): ThreadSummary = JSONObject(
        request("POST", "/api/threads", JSONObject().put("assistant_id", assistantId).toString()),
    ).toThreadSummary()

    suspend fun deleteThread(threadId: String) {
        request("DELETE", "/api/threads/${pathSegment(threadId)}")
    }

    suspend fun renameThread(threadId: String, title: String) {
        request(
            "POST",
            "/api/threads/${pathSegment(threadId)}/state",
            JSONObject().put("values", JSONObject().put("title", title)).toString(),
        )
    }

    suspend fun threadState(threadId: String): ThreadSnapshot = JSONObject(
        request("GET", "/api/threads/${pathSegment(threadId)}/state"),
    ).toThreadSnapshot()

    suspend fun prepareRegenerate(threadId: String, messageId: String): RegeneratePreparation {
        val payload = JSONObject(
            request(
                "POST",
                "/api/threads/${pathSegment(threadId)}/runs/regenerate/prepare",
                JSONObject().put("message_id", messageId).toString(),
            ),
        )
        return RegeneratePreparation(
            inputJson = payload.getJSONObject("input").toString(),
            checkpointJson = payload.getJSONObject("checkpoint").toString(),
            metadataJson = payload.getJSONObject("metadata").toString(),
            targetRunId = payload.getString("target_run_id"),
        )
    }

    suspend fun branchThread(threadId: String, messageId: String, messageIds: List<String>): ThreadBranchResult {
        val payload = JSONObject(
            request(
                "POST",
                "/api/threads/${pathSegment(threadId)}/branches",
                JSONObject()
                    .put("message_id", messageId)
                    .put("message_ids", JSONArray(messageIds))
                    .toString(),
            ),
        )
        return ThreadBranchResult(
            threadId = payload.getString("thread_id"),
            parentThreadId = payload.getString("parent_thread_id"),
            parentCheckpointId = payload.getString("parent_checkpoint_id"),
            branchedFromMessageId = payload.getString("branched_from_message_id"),
            workspaceCloneMode = payload.optString("workspace_clone_mode"),
        )
    }

    suspend fun loadCapabilities(): WorkspaceCapabilities {
        val features = JSONObject(request("GET", "/api/features"))
        val agentsEnabled = features.optJSONObject("agents_api")?.optBoolean("enabled") == true
        val models = parseModels(request("GET", "/api/models"))
        val agents = if (agentsEnabled) {
            parseAgents(request("GET", "/api/agents"))
        } else emptyList()
        val skills = parseSkills(request("GET", "/api/skills"))
        return WorkspaceCapabilities(models, agents, skills, agentsEnabled)
    }

    suspend fun setSkillEnabled(skillName: String, enabled: Boolean): SkillInfo {
        val body = JSONObject().put("enabled", enabled)
        return JSONObject(request("PUT", "/api/skills/${pathSegment(skillName)}", body.toString())).toSkillInfo()
    }

    suspend fun loadMcpConfig(): McpConfig = parseMcpConfig(request("GET", "/api/mcp/config"))

    suspend fun loadMcpTools(): List<McpToolInfo> = try {
        parseMcpTools(request("GET", "/api/mcp/tools"))
    } catch (error: ApiException) {
        if (error.statusCode != 404) throw error
        loadMcpConfig().servers.flatMap { server ->
            val toolNames = server.toolOverrides.ifEmpty { listOf("MCP server") }
            toolNames.map { name ->
                McpToolInfo(
                    serverName = server.name,
                    name = name,
                    description = server.description,
                )
            }
        }
    }

    suspend fun updateMcpConfig(rawJson: String): McpConfig {
        val root = JSONObject(rawJson)
        if (root.optJSONObject("mcp_servers") == null) {
            throw IllegalArgumentException("MCP configuration must contain an mcp_servers object.")
        }
        return parseMcpConfig(request("PUT", "/api/mcp/config", root.toString()))
    }

    suspend fun setMcpServerEnabled(config: McpConfig, serverName: String, enabled: Boolean): McpConfig {
        val root = JSONObject(config.rawJson)
        val servers = root.optJSONObject("mcp_servers")
            ?: throw IllegalStateException("The Gateway returned no MCP server configuration.")
        val server = servers.optJSONObject(serverName)
            ?: throw IllegalArgumentException("MCP server '$serverName' is unavailable.")
        server.put("enabled", enabled)
        return updateMcpConfig(root.toString())
    }

    suspend fun loadChannelProviders(): ChannelProviders = parseChannelProviders(request("GET", "/api/channels/providers"))

    suspend fun configureChannelProvider(provider: String, values: Map<String, String>): ChannelProviderInfo {
        val payload = JSONObject().put("values", JSONObject().apply {
            values.forEach { (name, value) -> put(name, value) }
        })
        return parseChannelProvider(
            JSONObject(request("POST", "/api/channels/${pathSegment(provider)}/runtime-config", payload.toString())),
        )
    }

    suspend fun disconnectChannelProvider(provider: String): ChannelProviderInfo = parseChannelProvider(
        JSONObject(request("DELETE", "/api/channels/${pathSegment(provider)}/runtime-config")),
    )

    suspend fun connectChannelProvider(provider: String): ChannelConnectResult {
        val response = JSONObject(request("POST", "/api/channels/${pathSegment(provider)}/connect", ""))
        return ChannelConnectResult(
            provider = response.getString("provider"),
            mode = response.optString("mode"),
            url = response.optString("url").takeIf { it.isNotBlank() },
            code = response.getString("code"),
            instruction = response.optString("instruction"),
            expiresInSeconds = response.optInt("expires_in"),
        )
    }

    suspend fun listScheduledTasks(): List<ScheduledTaskInfo> {
        val array = JSONArray(request("GET", "/api/scheduled-tasks"))
        return buildList {
            for (index in 0 until array.length()) {
                val item = array.optJSONObject(index) ?: continue
                val spec = item.optJSONObject("schedule_spec") ?: JSONObject()
                val scheduleLabel = if (item.optString("schedule_type") == "cron") {
                    spec.optString("cron")
                } else {
                    spec.optString("run_at")
                }
                add(
                    ScheduledTaskInfo(
                        id = item.optString("id"),
                        title = item.optString("title", "Scheduled task"),
                        prompt = item.optString("prompt"),
                        scheduleType = item.optString("schedule_type"),
                        scheduleLabel = scheduleLabel,
                        timezone = item.optString("timezone"),
                        status = item.optString("status"),
                        nextRunAt = nullableJsonString(item.opt("next_run_at")),
                        lastError = nullableJsonString(item.opt("last_error")),
                        runCount = item.optInt("run_count"),
                    ),
                )
            }
        }
    }

    suspend fun listScheduledTaskRuns(taskId: String): List<ScheduledTaskRunInfo> {
        val array = JSONArray(request("GET", "/api/scheduled-tasks/${pathSegment(taskId)}/runs"))
        return buildList {
            for (index in 0 until array.length()) {
                val item = array.optJSONObject(index) ?: continue
                add(
                    ScheduledTaskRunInfo(
                        id = item.optString("id"),
                        taskId = item.optString("task_id"),
                        threadId = item.optString("thread_id"),
                        runId = nullableJsonString(item.opt("run_id")),
                        scheduledFor = item.optString("scheduled_for"),
                        trigger = item.optString("trigger"),
                        status = item.optString("status"),
                        error = nullableJsonString(item.opt("error")),
                        startedAt = nullableJsonString(item.opt("started_at")),
                        finishedAt = nullableJsonString(item.opt("finished_at")),
                        createdAt = item.optString("created_at"),
                    ),
                )
            }
        }
    }

    suspend fun loadMemory(): MemoryData = JSONObject(request("GET", "/api/memory")).toMemoryData()

    suspend fun createMemoryFact(content: String, category: String, confidence: Double): MemoryData {
        val body = JSONObject()
            .put("content", content)
            .put("category", category)
            .put("confidence", confidence)
        return JSONObject(request("POST", "/api/memory/facts", body.toString())).toMemoryData()
    }

    suspend fun updateMemoryFact(factId: String, content: String, category: String, confidence: Double): MemoryData {
        val body = JSONObject()
            .put("content", content)
            .put("category", category)
            .put("confidence", confidence)
        return JSONObject(request("PATCH", "/api/memory/facts/${pathSegment(factId)}", body.toString())).toMemoryData()
    }

    suspend fun deleteMemoryFact(factId: String): MemoryData = JSONObject(
        request("DELETE", "/api/memory/facts/${pathSegment(factId)}"),
    ).toMemoryData()

    suspend fun clearMemory(): MemoryData = JSONObject(request("DELETE", "/api/memory")).toMemoryData()

    suspend fun createAgent(name: String, description: String, model: String?): AgentInfo {
        val body = JSONObject()
            .put("name", name)
            .put("description", description)
            .put("model", model ?: JSONObject.NULL)
            .put("soul", "")
        return JSONObject(request("POST", "/api/agents", body.toString())).toAgentInfo()
    }

    suspend fun updateAgent(name: String, description: String, model: String?): AgentInfo {
        val body = JSONObject()
            .put("description", description)
            .put("model", model ?: JSONObject.NULL)
        return JSONObject(request("PUT", "/api/agents/${pathSegment(name)}", body.toString())).toAgentInfo()
    }

    suspend fun deleteAgent(name: String) {
        request("DELETE", "/api/agents/${pathSegment(name)}")
    }

    suspend fun listAgentRuns(agentId: String, limit: Int = 50): List<AgentRunInfo> =
        parseAgentRuns(request("GET", agentRunsPath(agentId, limit)))

    suspend fun createScheduledTask(title: String, prompt: String, schedule: TaskSchedule, timezone: String) {
        val body = JSONObject()
            .put("context_mode", "fresh_thread_per_run")
            .put("title", title)
            .put("prompt", prompt)
            .put("schedule_type", schedule.gatewayType())
            .put("schedule_spec", schedule.gatewaySpec())
            .put("timezone", timezone)
        request("POST", "/api/scheduled-tasks", body.toString())
    }

    suspend fun updateScheduledTask(taskId: String, title: String, prompt: String, schedule: TaskSchedule, timezone: String) {
        val body = JSONObject()
            .put("title", title)
            .put("prompt", prompt)
            .put("schedule_spec", schedule.gatewaySpec())
            .put("timezone", timezone)
        request("PATCH", "/api/scheduled-tasks/${pathSegment(taskId)}", body.toString())
    }

    suspend fun deleteScheduledTask(taskId: String) {
        request("DELETE", "/api/scheduled-tasks/${pathSegment(taskId)}")
    }

    suspend fun setScheduledTaskPaused(taskId: String, paused: Boolean) {
        val action = if (paused) "pause" else "resume"
        request("POST", "/api/scheduled-tasks/${pathSegment(taskId)}/$action", "")
    }

    suspend fun triggerScheduledTask(taskId: String) {
        request("POST", "/api/scheduled-tasks/${pathSegment(taskId)}/trigger", "")
    }

    suspend fun uploadFiles(threadId: String, sources: List<UploadSource>): List<UploadedFileInfo> = withContext(Dispatchers.IO) {
        if (sources.isEmpty()) return@withContext emptyList()
        val multipart = MultipartBody.Builder().setType(MultipartBody.FORM).apply {
            sources.forEach { source ->
                addFormDataPart("files", source.filename, StreamingRequestBody(source))
            }
        }.build()
        val call = client.newCall(
            Request.Builder()
                .url(url("/api/threads/${pathSegment(threadId)}/uploads"))
                .post(multipart)
                .build(),
        )
        activeCall = call
        try {
            call.execute().use { response ->
                val payload = response.body?.string().orEmpty()
                if (!response.isSuccessful) throw apiError(response.code, payload)
                val files = JSONObject(payload).optJSONArray("files") ?: JSONArray()
                buildList {
                    for (index in 0 until files.length()) {
                        val file = files.optJSONObject(index) ?: continue
                        add(UploadedFileInfo(file.optString("filename"), file.optLong("size"), file.optString("virtual_path")))
                    }
                }
            }
        } finally {
            activeCall = null
        }
    }

    suspend fun fetchArtifact(threadId: String, path: String): ArtifactPayload = withContext(Dispatchers.IO) {
        val encodedPath = path.trimStart('/').split('/').joinToString("/") { pathSegment(it) }
        val call = client.newCall(
            Request.Builder()
                .url(url("/api/threads/${pathSegment(threadId)}/artifacts/$encodedPath"))
                .get()
                .build(),
        )
        call.execute().use { response ->
            val body = response.body
            if (!response.isSuccessful) throw apiError(response.code, body?.string().orEmpty())
            val contentLength = body?.contentLength() ?: -1L
            if (contentLength > MAX_ARTIFACT_BYTES) throw ApiException(413, "This artifact is too large to preview on Android.")
            val bytes = body?.bytes() ?: byteArrayOf()
            if (bytes.size > MAX_ARTIFACT_BYTES) throw ApiException(413, "This artifact is too large to preview on Android.")
            ArtifactPayload(
                filename = path.substringAfterLast('/').ifBlank { "artifact" },
                mimeType = response.header("Content-Type")?.substringBefore(';')?.trim().orEmpty()
                    .ifBlank { "application/octet-stream" },
                bytes = bytes,
            )
        }
    }

    suspend fun streamMessage(
        threadId: String,
        message: String,
        options: RunOptions,
        clientMessageId: String = UUID.randomUUID().toString(),
        files: List<UploadedFileInfo> = emptyList(),
        resume: RunState? = null,
        humanInputResponse: HumanInputResponse? = null,
        regenerate: RegeneratePreparation? = null,
        onUpdate: (StreamUpdate) -> Unit,
    ) = withContext(Dispatchers.IO) {
        var runId = resume?.runId
        var lastEventId = resume?.lastEventId
        var attempt = 0
        var initial = runId == null
        val deliveredEventIds = linkedSetOf<String>().apply {
            resume?.lastEventId?.let(::add)
        }
        while (true) {
            val request = if (initial) {
                buildInitialStreamRequest(threadId, message, options, clientMessageId, files, humanInputResponse, regenerate)
            } else {
                buildResumeStreamRequest(threadId, requireNotNull(runId), lastEventId)
            }
            val call = streamClient.newCall(request)
            activeCall = call
            try {
                call.execute().use { response ->
                    val payload = response.body
                    if (!response.isSuccessful) {
                        throw apiError(response.code, payload?.string().orEmpty())
                    }
                    StreamDiagnostics.log(
                        threadId = threadId,
                        runId = runId,
                        reconnectAttempt = attempt,
                        cursor = lastEventId,
                        responseEncoding = response.header("Content-Encoding"),
                        receivedBytes = 0,
                        endReason = "opened",
                    )
                    if (initial) {
                        runId = response.header("Content-Location")?.substringAfterLast('/')
                        onUpdate(StreamUpdate.Started(runId))
                    }
                    val streamResult = payload?.byteStream()?.let { input ->
                        readEventStream(
                            input = input,
                            maxBytes = if (initial) null else MAX_RESUME_BYTES,
                            maxDurationMs = if (initial) null else MAX_RESUME_DURATION_MS,
                        ) { event ->
                            event.id?.let { eventId ->
                                if (!deliveredEventIds.add(eventId)) return@readEventStream false
                                lastEventId = eventId
                                onUpdate(StreamUpdate.EventId(eventId))
                            }
                            decodeStreamEvent(event) { update ->
                                if (update is StreamUpdate.Started && !update.runId.isNullOrBlank()) {
                                    runId = update.runId
                                }
                                onUpdate(update)
                            }
                        }
                    } ?: StreamReadResult(StreamEndReason.UnexpectedEof, 0)
                    StreamDiagnostics.log(
                        threadId = threadId,
                        runId = runId,
                        reconnectAttempt = attempt,
                        cursor = lastEventId,
                        responseEncoding = response.header("Content-Encoding"),
                        receivedBytes = streamResult.bytesRead,
                        endReason = streamResult.reason.name,
                    )
                    if (streamResult.reason != StreamEndReason.UnexpectedEof) return@withContext
                }
                if (runId == null || attempt >= MAX_RECONNECTS) return@withContext
            } catch (error: IOException) {
                if (call.isCanceled()) throw CancellationException("Stream cancelled", error)
                if (runId == null || attempt >= MAX_RECONNECTS) throw error
            } finally {
                if (activeCall === call) activeCall = null
            }
            initial = false
            attempt += 1
            onUpdate(StreamUpdate.Reconnecting(attempt))
            delay(RECONNECT_DELAY_MS * attempt)
        }
    }

    suspend fun cancelRun(threadId: String, runId: String) {
        request("POST", "/api/threads/${pathSegment(threadId)}/runs/${pathSegment(runId)}/cancel?wait=false&action=interrupt", "")
    }

    suspend fun latestActiveRun(threadId: String): GatewayRunInfo? {
        val payload = JSONArray(request("GET", "/api/threads/${pathSegment(threadId)}/runs"))
        return (0 until payload.length())
            .asSequence()
            .mapNotNull { index -> payload.optJSONObject(index) }
            .mapNotNull { item ->
                val runId = item.optString("run_id").takeIf { it.isNotBlank() } ?: return@mapNotNull null
                GatewayRunInfo(runId, item.optString("status"))
            }
            .firstOrNull { it.status == "pending" || it.status == "running" }
    }

    fun cancelActiveStream() {
        activeCall?.cancel()
        activeCall = null
    }

    private suspend fun request(method: String, path: String, body: String? = null, contentType: String = "application/json"): String {
        val requestBody = (body ?: "").toRequestBody(contentType.toMediaTypeOrNull())
        val response = when (method) {
            "GET" -> service.get(url(path))
            "POST" -> service.post(url(path), requestBody)
            "PATCH" -> service.patch(url(path), requestBody)
            "PUT" -> service.put(url(path), requestBody)
            "DELETE" -> service.delete(url(path))
            else -> error("Unsupported HTTP method: $method")
        }
        val payload = if (response.isSuccessful) response.body()?.string().orEmpty() else response.errorBody()?.string().orEmpty()
        if (!response.isSuccessful) throw apiError(response.code(), payload)
        return payload
    }

    private fun buildInitialStreamRequest(
        threadId: String,
        message: String,
        options: RunOptions,
        clientMessageId: String,
        files: List<UploadedFileInfo>,
        humanInputResponse: HumanInputResponse?,
        regenerate: RegeneratePreparation?,
    ): Request {
        val human = JSONObject()
            .put("type", "human")
            .put("content", message)
            .put("id", clientMessageId)
        if (files.isNotEmpty()) {
            human.put("additional_kwargs", JSONObject().put("files", JSONArray().apply {
                files.forEach { file ->
                    put(
                        JSONObject()
                            .put("filename", file.filename)
                            .put("size", file.size)
                            .put("path", file.virtualPath)
                            .put("status", "uploaded"),
                    )
                }
            }))
        }
        humanInputResponse?.let { response ->
            val additional = human.optJSONObject("additional_kwargs") ?: JSONObject().also {
                human.put("additional_kwargs", it)
            }
            additional
                .put("hide_from_ui", true)
                .put(
                    "human_input_response",
                    JSONObject()
                        .put("version", 1)
                        .put("kind", "human_input_response")
                        .put("source", response.source)
                        .put("request_id", response.requestId)
                        .put("response_kind", response.responseKind)
                        .put("value", response.value)
                        .apply { response.optionId?.let { put("option_id", it) } },
                )
        }
        val context = JSONObject()
            .put("thread_id", threadId)
            .put("thinking_enabled", options.mode.thinkingEnabled)
            .put("is_plan_mode", options.mode.planMode)
            .put("subagent_enabled", options.mode.subagentEnabled)
        options.modelName?.let { context.put("model_name", it) }
        if (options.reasoningEffortEnabled) {
            context.put("reasoning_effort", options.mode.reasoningEffort)
        }
        if (options.enabledSkills.isNotEmpty()) context.put("enabled_skills", JSONArray(options.enabledSkills.toList()))
        val body = JSONObject()
            .put("assistant_id", options.assistantId)
            .put("input", regenerate?.let { JSONObject(it.inputJson) } ?: JSONObject().put("messages", JSONArray().put(human)))
            .put("stream_mode", JSONArray().put("messages-tuple").put("updates"))
            .put("stream_subgraphs", false)
            .put("stream_resumable", true)
            .put("on_disconnect", "continue")
            .put("config", JSONObject().put("recursion_limit", 1000))
            .put("context", context)
            .apply {
                regenerate?.let {
                    put("checkpoint", JSONObject(it.checkpointJson))
                    put("metadata", JSONObject(it.metadataJson))
                }
            }
            .toString()
        return Request.Builder()
            .url(url("/api/threads/${pathSegment(threadId)}/runs/stream"))
            .post(body.toRequestBody(JSON_MEDIA_TYPE))
            .header("Accept", "text/event-stream")
            .build()
    }

    private fun buildResumeStreamRequest(threadId: String, runId: String, lastEventId: String?): Request =
        Request.Builder()
            .url(url("/api/threads/${pathSegment(threadId)}/runs/${pathSegment(runId)}/stream"))
            .get()
            .header("Accept", "text/event-stream")
            .apply { lastEventId?.let { header("Last-Event-ID", it) } }
            .build()

    private fun readEventStream(
        input: InputStream,
        maxBytes: Long?,
        maxDurationMs: Long?,
        onEvent: (SseEvent) -> Boolean,
    ): StreamReadResult {
        val counted = CountingInputStream(input)
        val startedAt = System.nanoTime()
        BufferedReader(InputStreamReader(counted, StandardCharsets.UTF_8)).use { reader ->
            val parser = SseParser()
            while (true) {
                if (maxBytes != null && counted.bytesRead > maxBytes) {
                    return StreamReadResult(StreamEndReason.ResumeByteLimit, counted.bytesRead)
                }
                if (maxDurationMs != null && elapsedMillis(startedAt) > maxDurationMs) {
                    return StreamReadResult(StreamEndReason.ResumeTimeLimit, counted.bytesRead)
                }
                val line = reader.readLine() ?: break
                parser.accept(line)?.let { if (onEvent(it)) return StreamReadResult(StreamEndReason.EndEvent, counted.bytesRead) }
            }
            parser.finish()?.let { if (onEvent(it)) return StreamReadResult(StreamEndReason.EndEvent, counted.bytesRead) }
        }
        return StreamReadResult(StreamEndReason.UnexpectedEof, counted.bytesRead)
    }

    private fun decodeStreamEvent(event: SseEvent, onUpdate: (StreamUpdate) -> Unit): Boolean {
        when (event.event) {
            "metadata" -> onUpdate(StreamUpdate.Started(runCatching { JSONObject(event.data).optString("run_id") }.getOrNull()))
            "messages", "messages-tuple" -> {
                val message = findMessageObject(parseJson(event.data)) ?: return false
                val chunk = message.toChatMessage() ?: return false
                if (chunk.text.isNotEmpty() || chunk.blocks.isNotEmpty() || chunk.attachments.isNotEmpty()) {
                    onUpdate(
                        StreamUpdate.MessageChunk(
                            if (message.optString("id").isBlank() && chunk.role == MessageRole.Assistant) {
                                chunk.copy(id = "assistant-live")
                            } else {
                                chunk
                            },
                        ),
                    )
                }
            }
            "updates" -> findValuesObject(parseJson(event.data))?.let { onUpdate(StreamUpdate.Snapshot(it.toThreadSnapshot())) }
            "error" -> {
                val payload = parseJson(event.data)
                val message = when (payload) {
                    is JSONObject -> payload.optString("message").ifBlank { payload.optString("error") }
                    else -> payload?.toString().orEmpty()
                }.ifBlank { "The run failed." }
                onUpdate(StreamUpdate.Failure(message))
            }
            "end" -> {
                onUpdate(StreamUpdate.Finished)
                return true
            }
        }
        return false
    }

    private fun parseModels(raw: String): List<ModelInfo> {
        val array = JSONObject(raw).optJSONArray("models") ?: JSONArray()
        return buildList {
            for (index in 0 until array.length()) array.optJSONObject(index)?.let {
                add(ModelInfo(it.optString("name"), it.optString("display_name").ifBlank { it.optString("name") }, it.optString("description"), it.optBoolean("supports_thinking"), it.optBoolean("supports_reasoning_effort")))
            }
        }
    }

    private fun parseAgents(raw: String): List<AgentInfo> {
        val array = JSONObject(raw).optJSONArray("agents") ?: JSONArray()
        return buildList {
            for (index in 0 until array.length()) array.optJSONObject(index)?.let {
                add(it.toAgentInfo())
            }
        }
    }

    private fun parseSkills(raw: String): List<SkillInfo> {
        val array = JSONObject(raw).optJSONArray("skills") ?: JSONArray()
        return buildList {
            for (index in 0 until array.length()) array.optJSONObject(index)?.let {
                add(it.toSkillInfo())
            }
        }
    }

    private fun parseMcpConfig(raw: String): McpConfig {
        val servers = JSONObject(raw).optJSONObject("mcp_servers") ?: JSONObject()
        return McpConfig(
            servers = servers.keys().asSequence().sorted().mapNotNull { name ->
                servers.optJSONObject(name)?.let { server ->
                    McpServerInfo(
                        name = name,
                        description = server.optString("description"),
                        transport = server.optString("type", "stdio"),
                        enabled = server.optBoolean("enabled", true),
                        toolOverrides = server.toolNames(),
                    )
                }
            }.toList(),
            rawJson = raw,
        )
    }

    private fun JSONObject.toolNames(): List<String> = when (val tools = opt("tools")) {
        is JSONObject -> tools.keys().asSequence().sorted().toList()
        is JSONArray -> buildList {
            for (index in 0 until tools.length()) {
                when (val tool = tools.opt(index)) {
                    is String -> tool.takeIf { it.isNotBlank() }?.let(::add)
                    is JSONObject -> tool.optString("name").takeIf { it.isNotBlank() }?.let(::add)
                }
            }
        }.sorted()
        else -> emptyList()
    }

    private fun parseMcpTools(raw: String): List<McpToolInfo> {
        val tools = JSONObject(raw).optJSONArray("tools") ?: JSONArray()
        return buildList {
            for (index in 0 until tools.length()) {
                val tool = tools.optJSONObject(index) ?: continue
                val serverName = tool.optString("server_name")
                val name = tool.optString("name")
                if (serverName.isBlank() || name.isBlank()) continue
                add(
                    McpToolInfo(
                        serverName = serverName,
                        name = name,
                        description = tool.optString("description"),
                    ),
                )
            }
        }.sortedWith(compareBy(McpToolInfo::serverName, McpToolInfo::name))
    }

    private fun parseChannelProviders(raw: String): ChannelProviders {
        val root = JSONObject(raw)
        val providers = root.optJSONArray("providers") ?: JSONArray()
        return ChannelProviders(
            enabled = root.optBoolean("enabled"),
            providers = buildList {
                for (index in 0 until providers.length()) {
                    providers.optJSONObject(index)?.let { add(parseChannelProvider(it)) }
                }
            },
        )
    }

    private fun parseChannelProvider(provider: JSONObject): ChannelProviderInfo = ChannelProviderInfo(
        provider = provider.getString("provider"),
        displayName = provider.optString("display_name"),
        enabled = provider.optBoolean("enabled"),
        configured = provider.optBoolean("configured"),
        connectable = provider.optBoolean("connectable"),
        unavailableReason = provider.optString("unavailable_reason").takeIf { it.isNotBlank() },
        authMode = provider.optString("auth_mode"),
        connectionStatus = provider.optString("connection_status"),
        credentialFields = provider.optJSONArray("credential_fields")?.let { fields ->
            buildList {
                for (index in 0 until fields.length()) {
                    fields.optJSONObject(index)?.let { field ->
                        add(
                            ChannelCredentialField(
                                name = field.getString("name"),
                                label = field.optString("label"),
                                type = field.optString("type", "text"),
                                required = field.optBoolean("required", true),
                            ),
                        )
                    }
                }
            }
        }.orEmpty(),
        credentialValues = provider.optJSONObject("credential_values")?.let { values ->
            values.keys().asSequence().associateWith { name -> values.optString(name) }
        }.orEmpty(),
    )

    private fun parseUser(raw: String): DeerFlowUser {
        val json = JSONObject(raw)
        return DeerFlowUser(json.getString("id"), json.optString("email", "Local user"), json.optString("system_role", "user"), json.optBoolean("needs_setup"))
    }

    private fun findMessageObject(value: Any?): JSONObject? = when (value) {
        is JSONObject -> if (value.has("type") || value.has("role")) value else value.keys().asSequence().mapNotNull { findMessageObject(value.opt(it)) }.firstOrNull()
        is JSONArray -> (0 until value.length()).asSequence().mapNotNull { findMessageObject(value.opt(it)) }.firstOrNull()
        else -> null
    }

    private fun findValuesObject(value: Any?): JSONObject? = when (value) {
        is JSONObject -> if (value.has("messages") || value.has("title") || value.has("todos") || value.has("artifacts")) value else value.keys().asSequence().mapNotNull { findValuesObject(value.opt(it)) }.firstOrNull()
        is JSONArray -> (0 until value.length()).asSequence().mapNotNull { findValuesObject(value.opt(it)) }.firstOrNull()
        else -> null
    }

    private fun parseJson(raw: String): Any? = try { JSONTokener(raw).nextValue() } catch (_: JSONException) { null }

    private fun TaskSchedule.gatewayType(): String = when (this) {
        is TaskSchedule.Cron -> "cron"
        is TaskSchedule.Once -> "once"
    }

    private fun TaskSchedule.gatewaySpec(): JSONObject = when (this) {
        is TaskSchedule.Cron -> JSONObject().put("cron", expression)
        is TaskSchedule.Once -> JSONObject().put("run_at", runAt)
    }

    private fun formEncode(value: String): String = URLEncoder.encode(value, StandardCharsets.UTF_8.name())
    private fun pathSegment(value: String): String = URLEncoder.encode(value, StandardCharsets.UTF_8.name())
    private fun url(path: String): String = "$serverUrl$path"

    private fun apiError(status: Int, payload: String): ApiException {
        val detail = runCatching {
            when (val value = JSONObject(payload).opt("detail")) {
                is String -> value
                is JSONObject -> value.optString("message").ifBlank { value.toString() }
                else -> ""
            }
        }.getOrDefault("")
        return ApiException(status, detail.ifBlank {
            when (status) {
                401 -> "Sign in to continue."
                403 -> "The server rejected this request."
                404 -> "The requested DeerFlow resource was not found."
                409 -> "This conversation is already running."
                413 -> "The selected files exceed the server upload limit."
                else -> "DeerFlow returned HTTP $status."
            }
        })
    }

    private class SessionInterceptor(private val cookies: SessionCookieStore) : Interceptor {
        override fun intercept(chain: Interceptor.Chain): okhttp3.Response {
            val original = chain.request()
            val builder = original.newBuilder()
            cookies.cookieHeader(original.url.toString())?.let { builder.header("Cookie", it) }
            if (original.method in STATE_CHANGING_METHODS) {
                cookies.csrfToken(original.url.toString())?.let { builder.header("X-CSRF-Token", it) }
            }
            val response = chain.proceed(builder.build())
            val responseHeaders = mutableMapOf<String?, List<String>>()
            responseHeaders.putAll(response.headers.toMultimap())
            cookies.capture(response.request.url.toString(), responseHeaders)
            return response
        }
    }

    private class StreamingRequestBody(private val source: UploadSource) : RequestBody() {
        override fun contentType() = source.mimeType.toMediaTypeOrNull()
        override fun contentLength(): Long = source.length
        override fun writeTo(sink: BufferedSink) {
            source.open().use { input -> sink.writeAll(input.source()) }
        }
    }

    companion object {
        private val STATE_CHANGING_METHODS = setOf("POST", "PUT", "PATCH", "DELETE")
        private val JSON_MEDIA_TYPE = "application/json; charset=utf-8".toMediaTypeOrNull()
        private const val MAX_RECONNECTS = 1
        private const val RECONNECT_DELAY_MS = 700L
        private const val MAX_RESUME_BYTES = 256L * 1024L
        private const val MAX_RESUME_DURATION_MS = 30_000L
        private const val MAX_ARTIFACT_BYTES = 16 * 1024 * 1024
    }
}

private enum class StreamEndReason { EndEvent, UnexpectedEof, ResumeByteLimit, ResumeTimeLimit }

private data class StreamReadResult(val reason: StreamEndReason, val bytesRead: Long)

private class CountingInputStream(input: InputStream) : FilterInputStream(input) {
    var bytesRead: Long = 0
        private set

    override fun read(): Int = super.read().also { if (it >= 0) bytesRead += 1 }

    override fun read(buffer: ByteArray, offset: Int, length: Int): Int =
        super.read(buffer, offset, length).also { if (it > 0) bytesRead += it }
}

private fun elapsedMillis(startedAtNanos: Long): Long = (System.nanoTime() - startedAtNanos) / 1_000_000L

private object StreamDiagnostics {
    private const val TAG = "DeerFlowStream"

    fun log(
        threadId: String,
        runId: String?,
        reconnectAttempt: Int,
        cursor: String?,
        responseEncoding: String?,
        receivedBytes: Long,
        endReason: String,
    ) {
        if (!BuildConfig.DEBUG) return
        runCatching {
            Log.d(
                TAG,
                "thread=$threadId run=${runId.orEmpty()} reconnects=$reconnectAttempt cursor=${cursor.orEmpty()} encoding=${responseEncoding.orEmpty().ifBlank { "identity" }} bytes=$receivedBytes end=$endReason",
            )
        }
    }
}

private fun JSONArray?.toStringList(): List<String> = buildList {
    val array = this@toStringList ?: return@buildList
    for (index in 0 until array.length()) array.optString(index).takeIf { it.isNotBlank() }?.let(::add)
}

internal fun JSONObject.toAgentInfo() = AgentInfo(
    name = optString("name"),
    description = optString("description"),
    model = nullableJsonString(opt("model")),
    skills = optJSONArray("skills").toStringList(),
    soul = optString("soul"),
)

internal fun JSONObject.toSkillInfo() = SkillInfo(
    name = optString("name"),
    description = optString("description"),
    category = optString("category"),
    enabled = optBoolean("enabled"),
)

internal fun parseAgentRuns(raw: String): List<AgentRunInfo> {
    val runs = JSONObject(raw).optJSONArray("runs") ?: JSONArray()
    return buildList {
        for (index in 0 until runs.length()) {
            val run = runs.optJSONObject(index) ?: continue
            add(
                AgentRunInfo(
                    runId = run.optString("run_id"),
                    threadId = run.optString("thread_id"),
                    threadTitle = nullableJsonString(run.opt("thread_title")),
                    assistantId = nullableJsonString(run.opt("assistant_id")),
                    status = run.optString("status"),
                    modelName = nullableJsonString(run.opt("model_name")),
                    createdAt = nullableJsonString(run.opt("created_at")),
                    updatedAt = nullableJsonString(run.opt("updated_at")),
                    durationSeconds = nullableJsonDouble(run.opt("duration_seconds")),
                    totalTokens = run.optInt("total_tokens"),
                    messageCount = run.optInt("message_count"),
                    cost = nullableJsonDouble(run.opt("cost")),
                    error = nullableJsonString(run.opt("error")),
                ),
            )
        }
    }
}

internal fun agentRunsPath(agentId: String, limit: Int): String {
    require(agentId.isNotBlank()) { "Agent id must not be blank." }
    require(limit in 1..100) { "Agent run history limit must be between 1 and 100." }
    return "/api/console/runs?assistant_id=${queryParameter(agentId)}&limit=$limit"
}

private fun queryParameter(value: String): String =
    URLEncoder.encode(value, StandardCharsets.UTF_8.name()).replace("+", "%20")

internal fun nullableJsonString(value: Any?): String? = (value as? String)?.takeIf { it.isNotBlank() }

private fun nullableJsonDouble(value: Any?): Double? = (value as? Number)?.toDouble()?.takeIf { it.isFinite() }
