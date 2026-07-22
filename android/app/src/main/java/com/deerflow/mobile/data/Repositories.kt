package com.deerflow.mobile.data

class ThreadRepository(
    private val api: DeerFlowApi,
    private val cache: WorkspaceCache,
    private val settings: SettingsStore,
) {
    data class LoadResult<T>(val value: T, val fromCache: Boolean = false)

    suspend fun threads(): LoadResult<List<ThreadSummary>> = try {
        val pins = settings.pinnedThreads(api.serverUrl)
        val value = api.listThreads()
            .map { it.copy(isPinned = it.id in pins) }
            .sortedWith(compareByDescending<ThreadSummary> { it.isPinned }.thenByDescending { it.updatedAt })
        cache.saveThreads(api.serverUrl, value)
        LoadResult(value)
    } catch (error: Exception) {
        val cached = cache.loadThreads(api.serverUrl)
        if (cached.isEmpty()) throw error
        LoadResult(cached, fromCache = true)
    }

    suspend fun create(assistantId: String): ThreadSummary {
        val thread = api.createThread(assistantId)
        return thread.copy(isPinned = false)
    }

    suspend fun branch(threadId: String, messageId: String, messageIds: List<String>): ThreadBranchResult =
        api.branchThread(threadId, messageId, messageIds)

    suspend fun snapshot(threadId: String): LoadResult<ThreadSnapshot> = try {
        val snapshot = api.threadState(threadId)
        cache.saveMessages(api.serverUrl, threadId, snapshot.messages)
        LoadResult(snapshot)
    } catch (error: Exception) {
        val messages = cache.loadMessages(api.serverUrl, threadId)
        if (messages.isEmpty()) throw error
        LoadResult(ThreadSnapshot("New conversation", messages), fromCache = true)
    }

    suspend fun cacheSnapshot(threadId: String, snapshot: ThreadSnapshot) {
        cache.saveMessages(api.serverUrl, threadId, snapshot.messages)
    }

    suspend fun delete(threadId: String) {
        api.deleteThread(threadId)
        cache.deleteThread(api.serverUrl, threadId)
    }

    suspend fun rename(threadId: String, title: String) = api.renameThread(threadId, title)

    suspend fun setPinned(thread: ThreadSummary, pinned: Boolean) {
        settings.setThreadPinned(api.serverUrl, thread.id, pinned)
    }

    suspend fun saveDraft(threadId: String, text: String) = cache.saveDraft(api.serverUrl, threadId, text)
    suspend fun loadDraft(threadId: String): String = cache.loadDraft(api.serverUrl, threadId)
    suspend fun saveAttachments(threadId: String, attachments: List<PendingAttachment>) =
        cache.saveAttachments(api.serverUrl, threadId, attachments)

    suspend fun loadAttachments(threadId: String): List<PendingAttachment> =
        cache.loadAttachments(api.serverUrl, threadId)

    suspend fun artifact(threadId: String, path: String): ArtifactPayload =
        api.fetchArtifact(threadId, path)
}

class RunRepository(private val api: DeerFlowApi) {
    suspend fun upload(threadId: String, sources: List<UploadSource>) = api.uploadFiles(threadId, sources)

    suspend fun prepareRegenerate(threadId: String, messageId: String) = api.prepareRegenerate(threadId, messageId)

    suspend fun stream(
        threadId: String,
        message: String,
        options: RunOptions,
        files: List<UploadedFileInfo>,
        resume: RunState? = null,
        humanInputResponse: HumanInputResponse? = null,
        regenerate: RegeneratePreparation? = null,
        onUpdate: (StreamUpdate) -> Unit,
    ) = api.streamMessage(
        threadId = threadId,
        message = message,
        options = options,
        files = files,
        resume = resume,
        humanInputResponse = humanInputResponse,
        regenerate = regenerate,
        onUpdate = onUpdate,
    )

    suspend fun cancel(threadId: String, runId: String?) {
        api.cancelActiveStream()
        if (runId != null) runCatching { api.cancelRun(threadId, runId) }
    }

    fun disconnect() = api.cancelActiveStream()
}

class WorkspaceRepository(
    private val api: DeerFlowApi,
    private val cache: WorkspaceCache,
) {
    data class LoadResult<T>(val value: T, val fromCache: Boolean = false)

    suspend fun capabilities(): LoadResult<WorkspaceCapabilities> = try {
        val value = api.loadCapabilities()
        cache.saveCapabilities(api.serverUrl, value)
        LoadResult(value)
    } catch (error: Exception) {
        if (error.isUnauthorized()) throw error
        val cached = cache.loadCapabilities(api.serverUrl) ?: throw error
        LoadResult(cached, fromCache = true)
    }

    suspend fun tasks(): LoadResult<List<ScheduledTaskInfo>> = try {
        val value = api.listScheduledTasks()
        cache.saveTasks(api.serverUrl, value)
        LoadResult(value)
    } catch (error: Exception) {
        if (error.isUnauthorized()) throw error
        val cached = cache.loadTasks(api.serverUrl) ?: throw error
        LoadResult(cached, fromCache = true)
    }

    suspend fun memory(): LoadResult<MemoryData> = try {
        val value = api.loadMemory()
        cache.saveMemory(api.serverUrl, value)
        LoadResult(value)
    } catch (error: Exception) {
        if (error.isUnauthorized()) throw error
        val cached = cache.loadMemory(api.serverUrl) ?: throw error
        LoadResult(cached, fromCache = true)
    }

    suspend fun createMemoryFact(content: String, category: String, confidence: Double): MemoryData =
        cacheMemory(api.createMemoryFact(content, category, confidence))

    suspend fun updateMemoryFact(factId: String, content: String, category: String, confidence: Double): MemoryData =
        cacheMemory(api.updateMemoryFact(factId, content, category, confidence))

    suspend fun deleteMemoryFact(factId: String): MemoryData = cacheMemory(api.deleteMemoryFact(factId))

    suspend fun clearMemory(): MemoryData = cacheMemory(api.clearMemory())

    suspend fun pauseTask(taskId: String, paused: Boolean) = api.setScheduledTaskPaused(taskId, paused)
    suspend fun triggerTask(taskId: String) = api.triggerScheduledTask(taskId)
    suspend fun taskRuns(taskId: String): List<ScheduledTaskRunInfo> = api.listScheduledTaskRuns(taskId)
    suspend fun agentRuns(agentId: String): List<AgentRunInfo> = api.listAgentRuns(agentId)
    suspend fun createAgent(name: String, description: String, model: String?) = api.createAgent(name, description, model)
    suspend fun updateAgent(name: String, description: String, model: String?) = api.updateAgent(name, description, model)
    suspend fun deleteAgent(name: String) = api.deleteAgent(name)
    suspend fun createTask(title: String, prompt: String, schedule: TaskSchedule, timezone: String) =
        api.createScheduledTask(title, prompt, schedule, timezone)
    suspend fun updateTask(taskId: String, title: String, prompt: String, schedule: TaskSchedule, timezone: String) =
        api.updateScheduledTask(taskId, title, prompt, schedule, timezone)
    suspend fun deleteTask(taskId: String) = api.deleteScheduledTask(taskId)

    suspend fun setSkillEnabled(
        capabilities: WorkspaceCapabilities,
        skillName: String,
        enabled: Boolean,
    ): WorkspaceCapabilities {
        val updatedSkill = api.setSkillEnabled(skillName, enabled)
        val updatedCapabilities = capabilities.copy(
            skills = capabilities.skills.map { skill ->
                if (skill.name == updatedSkill.name) updatedSkill else skill
            },
        )
        cache.saveCapabilities(api.serverUrl, updatedCapabilities)
        return updatedCapabilities
    }

    suspend fun mcpConfig(): McpConfig = api.loadMcpConfig()

    suspend fun mcpTools(): LoadResult<List<McpToolInfo>> = try {
        val value = api.loadMcpTools()
        cache.saveMcpTools(api.serverUrl, value)
        LoadResult(value)
    } catch (error: Exception) {
        if (error.isUnauthorized()) throw error
        val cached = cache.loadMcpTools(api.serverUrl) ?: throw error
        LoadResult(cached, fromCache = true)
    }

    suspend fun updateMcpConfig(rawJson: String): McpConfig = api.updateMcpConfig(rawJson)

    suspend fun setMcpServerEnabled(config: McpConfig, serverName: String, enabled: Boolean): McpConfig =
        api.setMcpServerEnabled(config, serverName, enabled)

    suspend fun channelProviders(): ChannelProviders = api.loadChannelProviders()
    suspend fun configureChannelProvider(provider: String, values: Map<String, String>): ChannelProviderInfo =
        api.configureChannelProvider(provider, values)

    suspend fun disconnectChannelProvider(provider: String): ChannelProviderInfo = api.disconnectChannelProvider(provider)
    suspend fun connectChannelProvider(provider: String): ChannelConnectResult = api.connectChannelProvider(provider)

    private suspend fun cacheMemory(value: MemoryData): MemoryData {
        cache.saveMemory(api.serverUrl, value)
        return value
    }
}

private fun Exception.isUnauthorized(): Boolean = this is ApiException && statusCode == 401
