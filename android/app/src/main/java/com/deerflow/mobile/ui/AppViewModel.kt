package com.deerflow.mobile.ui

import android.app.Application
import android.net.Uri
import android.provider.OpenableColumns
import androidx.appcompat.app.AppCompatDelegate
import androidx.core.os.LocaleListCompat
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.deerflow.mobile.ConversationShortcuts
import com.deerflow.mobile.R
import com.deerflow.mobile.data.AgentInfo
import com.deerflow.mobile.data.AgentRunInfo
import com.deerflow.mobile.data.AssistantTurn
import com.deerflow.mobile.data.ApiException
import com.deerflow.mobile.data.AttachmentStatus
import com.deerflow.mobile.data.ChatMessage
import com.deerflow.mobile.data.ChannelConnectResult
import com.deerflow.mobile.data.ChannelProviderInfo
import com.deerflow.mobile.data.ChannelProviders
import com.deerflow.mobile.data.CacheRetentionPolicy
import com.deerflow.mobile.data.CacheStats
import com.deerflow.mobile.data.ComposerState
import com.deerflow.mobile.data.ConversationExportFormat
import com.deerflow.mobile.data.DeerFlowApi
import com.deerflow.mobile.data.DeerFlowUser
import com.deerflow.mobile.data.MessageAttachment
import com.deerflow.mobile.data.MessageRole
import com.deerflow.mobile.data.MemoryData
import com.deerflow.mobile.data.MemoryFact
import com.deerflow.mobile.data.McpConfig
import com.deerflow.mobile.data.McpToolInfo
import com.deerflow.mobile.data.LEAD_AGENT_ID
import com.deerflow.mobile.data.LanguagePreference
import com.deerflow.mobile.data.HumanInputRequest
import com.deerflow.mobile.data.HumanInputResponse
import com.deerflow.mobile.data.PendingAttachment
import com.deerflow.mobile.data.RunMode
import com.deerflow.mobile.data.RunRepository
import com.deerflow.mobile.data.RunState
import com.deerflow.mobile.data.RunStatus
import com.deerflow.mobile.data.ScheduledTaskInfo
import com.deerflow.mobile.data.ScheduledTaskRunInfo
import com.deerflow.mobile.data.SettingsStore
import com.deerflow.mobile.data.SsoProvider
import com.deerflow.mobile.data.TaskSchedule
import com.deerflow.mobile.data.ThemePreference
import com.deerflow.mobile.data.ThreadRepository
import com.deerflow.mobile.data.ThreadSummary
import com.deerflow.mobile.data.UploadSource
import com.deerflow.mobile.data.WebViewSessionCookieStore
import com.deerflow.mobile.data.WorkspaceCache
import com.deerflow.mobile.data.WorkspaceCapabilities
import com.deerflow.mobile.data.WorkspaceRepository
import com.deerflow.mobile.data.assistantTurnForMessage
import com.deerflow.mobile.data.isLatestAssistantTurn
import com.deerflow.mobile.data.normalizeServerUrl
import com.deerflow.mobile.data.resolveAgentSelection
import com.deerflow.mobile.run.CoordinatedRunRequest
import com.deerflow.mobile.run.CoordinatedRunState
import com.deerflow.mobile.run.RunCoordinator
import com.deerflow.mobile.run.RunProgress
import com.deerflow.mobile.run.RunService
import java.io.IOException
import java.io.File
import java.util.UUID
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.async
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

internal const val NEW_DRAFT_KEY = "__new__"

data class AppUiState(
    val serverUrl: String,
    val user: DeerFlowUser? = null,
    val route: AppRoute = AppRoute.Workspace,
    val checkingSession: Boolean = true,
    val loginBusy: Boolean = false,
    val loadingSsoProviders: Boolean = false,
    val ssoProviders: List<SsoProvider> = emptyList(),
    val ssoLoginProvider: SsoProvider? = null,
    val checkingSsoSession: Boolean = false,
    val loadingThreads: Boolean = false,
    val loadingChat: Boolean = false,
    val loadingCapabilities: Boolean = false,
    val loadingMcpConfig: Boolean = false,
    val loadingMcpTools: Boolean = false,
    val loadingChannels: Boolean = false,
    val loadingTasks: Boolean = false,
    val loadingTaskRuns: Boolean = false,
    val loadingAgentRuns: Boolean = false,
    val loadingMemory: Boolean = false,
    val workspaceMutationBusy: Boolean = false,
    val memoryMutationBusy: Boolean = false,
    val messageActionBusy: Boolean = false,
    val exportBusy: Boolean = false,
    val offline: Boolean = false,
    val threads: List<ThreadSummary> = emptyList(),
    val selectedThread: ThreadSummary? = null,
    val messages: List<ChatMessage> = emptyList(),
    val todos: List<com.deerflow.mobile.data.TodoItem> = emptyList(),
    val artifacts: List<String> = emptyList(),
    val artifactBusy: Boolean = false,
    val artifactPreview: ArtifactPreviewState? = null,
    val composer: ComposerState = ComposerState(),
    /** Storage follows the conversation, while this key belongs to the editor session. */
    val draftStorageKey: String = NEW_DRAFT_KEY,
    val draftSessionKey: String = "new-draft",
    val composerResetToken: Long = 0,
    val run: RunState = RunState(),
    val capabilities: WorkspaceCapabilities = WorkspaceCapabilities(),
    val mcpConfig: McpConfig? = null,
    val mcpTools: List<McpToolInfo> = emptyList(),
    val channelProviders: ChannelProviders? = null,
    val channelConnect: ChannelConnectResult? = null,
    val defaultAgentId: String = LEAD_AGENT_ID,
    val tasks: List<ScheduledTaskInfo> = emptyList(),
    val taskRunsTaskId: String? = null,
    val taskRuns: List<ScheduledTaskRunInfo> = emptyList(),
    val agentRunsAgentId: String? = null,
    val agentRuns: List<AgentRunInfo> = emptyList(),
    val agentRunsError: String? = null,
    val memory: MemoryData? = null,
    val theme: ThemePreference = ThemePreference.System,
    val useDynamicColor: Boolean = true,
    val language: LanguagePreference = LanguagePreference.System,
    val notifyOnRunCompletion: Boolean = true,
    val cacheRetentionPolicy: CacheRetentionPolicy = CacheRetentionPolicy.KeepUntilCleared,
    val cacheStats: CacheStats = CacheStats(),
    val loadingCacheStats: Boolean = false,
    val clearingCache: Boolean = false,
    val error: String? = null,
    val notice: String? = null,
) {
    val inConversation: Boolean get() = selectedThread != null
}

data class ArtifactPreviewState(
    val path: String,
    val filename: String,
    val mimeType: String,
    val text: String?,
    val localPath: String,
)

private fun ChannelProviders.replaceChannelProvider(updated: ChannelProviderInfo): ChannelProviders = copy(
    providers = providers.map { provider -> if (provider.provider == updated.provider) updated else provider },
)

private data class PendingRunDestination(
    val serverUrl: String,
    val threadId: String,
)

internal fun applyQuickActionToComposer(
    composer: ComposerState,
    capabilities: WorkspaceCapabilities,
    prompt: String,
    skillKeywords: List<String>,
): ComposerState {
    val matchingSkill = capabilities.skills
        .asSequence()
        .filter { it.enabled }
        .firstOrNull { skill ->
            val searchable = "${skill.name} ${skill.description}".lowercase()
            skillKeywords.any { keyword -> searchable.contains(keyword.lowercase()) }
        }
    val selectedSkills = composer.options.enabledSkills.toMutableSet()
    matchingSkill?.let { selectedSkills += it.name }
    return composer.copy(
        text = prompt,
        options = composer.options.copy(enabledSkills = selectedSkills),
    )
}

class AppViewModel(application: Application) : AndroidViewModel(application) {
    private val settings = SettingsStore(application)
    private val cookieStore = WebViewSessionCookieStore()
    private val api = DeerFlowApi(UNCONFIGURED_API_ORIGIN, cookieStore)
    private val cache = WorkspaceCache(application)
    private val conversationShortcuts = ConversationShortcuts(application)
    private val submissionGate = MessageSubmissionGate()
    private val threads = ThreadRepository(api, cache, settings)
    private val runs = RunRepository(api)
    private val workspace = WorkspaceRepository(api, cache)
    private val runCoordinator = RunCoordinator.get(application)
    private val mutableState = MutableStateFlow(
        AppUiState(
            serverUrl = SettingsStore.DEFAULT_SERVER_URL,
            language = currentLanguagePreference(),
        ),
    )
    val state: StateFlow<AppUiState> = mutableState.asStateFlow()

    private var draftJob: Job? = null
    private var attachmentJob: Job? = null
    private var threadLoadJob: Job? = null
    private var pendingRunDestination: PendingRunDestination? = null
    private var pendingNewConversation = false
    private var runRecoveryAttemptedForServer: String? = null

    init {
        observeCoordinatedRun()
        viewModelScope.launch {
            val saved = settings.read()
            val defaultAgentId = settings.defaultAgent(saved.serverUrl)
            val configuredServerUrl = saved.serverUrl.takeIf { it.isNotBlank() }
            configuredServerUrl?.let(api::updateServerUrl)
            mutableState.update {
                it.copy(
                    serverUrl = configuredServerUrl?.let { api.serverUrl }.orEmpty(),
                    theme = saved.theme,
                    useDynamicColor = saved.useDynamicColor,
                    language = currentLanguagePreference(),
                    notifyOnRunCompletion = saved.notifyOnRunCompletion,
                    cacheRetentionPolicy = saved.cacheRetentionPolicy,
                    defaultAgentId = defaultAgentId,
                    composer = it.composer.copy(
                        options = it.composer.options.copy(assistantId = defaultAgentId),
                    ),
                )
            }
            runCoordinator.state.value?.let(::applyCoordinatedRunState)
            if (configuredServerUrl == null) {
                mutableState.update { it.copy(checkingSession = false, ssoProviders = emptyList()) }
                consumePendingShortcutDestination()
            } else {
                checkSessionNow()
            }
        }
    }

    private fun observeCoordinatedRun() {
        viewModelScope.launch {
            runCoordinator.state.collect { coordinated ->
                coordinated?.let(::applyCoordinatedRunState)
            }
        }
    }

    private fun applyCoordinatedRunState(coordinated: CoordinatedRunState) {
        mutableState.update { current ->
            val selected = current.selectedThread
            if (current.serverUrl != coordinated.serverUrl) {
                current
            } else {
                val updatedThreads = current.threads.map { thread ->
                    if (thread.id == coordinated.threadId && coordinated.title.isNotBlank()) {
                        thread.copy(title = coordinated.title)
                    } else {
                        thread
                    }
                }
                current.copy(
                    threads = updatedThreads,
                    selectedThread = selected?.takeIf { it.id == coordinated.threadId }?.copy(title = coordinated.title) ?: selected,
                    messages = if (selected?.id == coordinated.threadId) coordinated.messages else current.messages,
                    todos = if (selected?.id == coordinated.threadId) coordinated.todos else current.todos,
                    artifacts = if (selected?.id == coordinated.threadId) coordinated.artifacts else current.artifacts,
                    run = if (selected?.id == coordinated.threadId) coordinated.run else current.run,
                    messageActionBusy = if (selected?.id == coordinated.threadId && !coordinated.run.active) false else current.messageActionBusy,
                    error = if (selected?.id == coordinated.threadId) coordinated.error ?: current.error else current.error,
                )
            }
        }
        if (!coordinated.run.active) refreshThreads()
    }

    fun checkSession() {
        viewModelScope.launch { checkSessionNow() }
    }

    private suspend fun checkSessionNow() {
        if (mutableState.value.serverUrl.isBlank()) {
            mutableState.update { it.copy(checkingSession = false, user = null, ssoProviders = emptyList(), error = null) }
            conversationShortcuts.clear()
            return
        }
        mutableState.update { it.copy(checkingSession = true, error = null) }
        try {
            val user = api.currentUser()
            mutableState.update { it.copy(user = user, checkingSession = false) }
            if (user != null) {
                refreshWorkspace()
                recoverLatestRunIfNeeded()
                consumePendingShortcutDestination()
            } else {
                conversationShortcuts.clear()
                refreshSsoProviders()
            }
        } catch (error: Exception) {
            conversationShortcuts.clear()
            mutableState.update {
                it.copy(
                    checkingSession = false,
                    user = null,
                    error = error.userMessage("Could not reach the DeerFlow server."),
                )
            }
        }
    }

    private fun refreshSsoProviders() {
        if (mutableState.value.loadingSsoProviders) return
        viewModelScope.launch {
            mutableState.update { it.copy(loadingSsoProviders = true) }
            try {
                val providers = api.ssoProviders()
                mutableState.update { it.copy(ssoProviders = providers, loadingSsoProviders = false) }
            } catch (_: Exception) {
                // SSO is optional. A failed provider directory must not block local login.
                mutableState.update { it.copy(ssoProviders = emptyList(), loadingSsoProviders = false) }
            }
        }
    }

    fun beginSsoLogin(provider: SsoProvider) {
        if (provider.id.isBlank()) return
        mutableState.update {
            it.copy(
                ssoLoginProvider = provider,
                checkingSsoSession = false,
                error = null,
            )
        }
    }

    fun ssoLoginUrl(provider: SsoProvider): String = api.ssoLoginUrl(provider.id)

    fun completeSsoLoginIfAvailable() {
        if (mutableState.value.ssoLoginProvider == null || mutableState.value.checkingSsoSession) return
        viewModelScope.launch {
            mutableState.update { it.copy(checkingSsoSession = true) }
            try {
                val user = api.currentUser()
                if (user != null) {
                    mutableState.update {
                        it.copy(
                            user = user,
                            checkingSsoSession = false,
                            ssoLoginProvider = null,
                        )
                    }
                    refreshWorkspace()
                    recoverLatestRunIfNeeded()
                    consumePendingShortcutDestination()
                } else {
                    mutableState.update { it.copy(checkingSsoSession = false) }
                }
            } catch (_: Exception) {
                // A page transition can finish before the Gateway callback sets its session cookie.
                mutableState.update { it.copy(checkingSsoSession = false) }
            }
        }
    }

    fun cancelSsoLogin() {
        mutableState.update { it.copy(ssoLoginProvider = null, checkingSsoSession = false) }
    }

    fun login(email: String, password: String) {
        if (email.isBlank() || password.isBlank()) {
            mutableState.update { it.copy(error = "Enter your email and password.") }
            return
        }
        viewModelScope.launch {
            mutableState.update { it.copy(loginBusy = true, error = null) }
            try {
                val user = api.login(email.trim(), password)
                mutableState.update { it.copy(user = user, loginBusy = false) }
                refreshWorkspace()
                recoverLatestRunIfNeeded()
                consumePendingShortcutDestination()
            } catch (error: Exception) {
                mutableState.update { it.copy(loginBusy = false, error = error.userMessage("Sign-in failed.")) }
            }
        }
    }

    fun connectAndLogin(serverUrl: String, email: String, password: String) {
        val normalized = normalizeOrReport(serverUrl) ?: return
        disconnectRun()
        conversationShortcuts.clear()
        api.updateServerUrl(normalized)
        persistSetting { setServerUrl(normalized) }
        mutableState.update { it.copy(serverUrl = normalized, error = null) }
        login(email, password)
    }

    fun saveServerUrl(value: String) {
        val normalized = normalizeOrReport(value) ?: return
        disconnectRun()
        conversationShortcuts.clear()
        api.updateServerUrl(normalized)
        persistSetting { setServerUrl(normalized) }
        val current = mutableState.value
        mutableState.value = AppUiState(
            serverUrl = normalized,
            checkingSession = true,
            theme = current.theme,
            useDynamicColor = current.useDynamicColor,
            language = current.language,
            notifyOnRunCompletion = current.notifyOnRunCompletion,
            cacheRetentionPolicy = current.cacheRetentionPolicy,
            cacheStats = current.cacheStats,
        )
        checkSession()
    }

    fun openRunDestination(serverUrl: String?, threadId: String?) {
        val normalizedServerUrl = serverUrl?.let { value -> runCatching { normalizeServerUrl(value) }.getOrNull() }
        if (normalizedServerUrl.isNullOrBlank() || threadId.isNullOrBlank()) return
        pendingNewConversation = false
        pendingRunDestination = PendingRunDestination(normalizedServerUrl, threadId)
        consumePendingShortcutDestination()
    }

    fun openNewConversationShortcut() {
        pendingRunDestination = null
        pendingNewConversation = true
        consumePendingShortcutDestination()
    }

    private fun consumePendingShortcutDestination() {
        val current = mutableState.value
        if (current.checkingSession || current.user == null) return
        if (pendingNewConversation) {
            pendingNewConversation = false
            createThread()
            return
        }
        val destination = pendingRunDestination ?: return
        if (current.serverUrl != destination.serverUrl) {
            mutableState.update {
                it.copy(error = "Sign in to ${destination.serverUrl} to open this task.")
            }
            return
        }
        pendingRunDestination = null
        val thread = current.threads.firstOrNull { it.id == destination.threadId }
            ?: ThreadSummary(destination.threadId, "Conversation", "completed", "")
        openThread(thread)
    }

    private suspend fun recoverLatestRunIfNeeded() {
        val serverUrl = api.serverUrl
        if (runRecoveryAttemptedForServer == serverUrl) return
        runRecoveryAttemptedForServer = serverUrl
        if (!runCoordinator.recoverLatest(serverUrl)) return

        val recovered = runCoordinator.state.value
            ?.takeIf { it.serverUrl == serverUrl }
            ?: return
        val thread = mutableState.value.threads.firstOrNull { it.id == recovered.threadId }
            ?: cache.loadThreads(serverUrl).firstOrNull { it.id == recovered.threadId }
            ?: ThreadSummary(
                id = recovered.threadId,
                title = recovered.title.ifBlank { "Run in progress" },
                status = "running",
                updatedAt = "",
            )
        openThread(thread)
    }

    fun logout() {
        viewModelScope.launch {
            disconnectRun()
            conversationShortcuts.clear()
            api.logout()
            val current = mutableState.value
            val updatedCacheStats = if (current.cacheRetentionPolicy == CacheRetentionPolicy.ClearOnSignOut) {
                runCatching {
                    cache.clearAll()
                    cache.stats()
                }.getOrDefault(current.cacheStats)
            } else {
                current.cacheStats
            }
            mutableState.value = AppUiState(
                serverUrl = api.serverUrl,
                checkingSession = false,
                theme = current.theme,
                useDynamicColor = current.useDynamicColor,
                language = current.language,
                notifyOnRunCompletion = current.notifyOnRunCompletion,
                cacheRetentionPolicy = current.cacheRetentionPolicy,
                cacheStats = updatedCacheStats,
            )
            refreshSsoProviders()
        }
    }

    fun refreshWorkspace() {
        refreshThreads()
        refreshCapabilities()
        refreshMcpConfig()
        refreshMcpTools()
        refreshChannels()
        refreshTasks()
    }

    fun refreshThreads() {
        if (mutableState.value.user == null) return
        viewModelScope.launch {
            mutableState.update { it.copy(loadingThreads = true, error = null) }
            try {
                val result = threads.threads()
                mutableState.update { current ->
                    val selected = current.selectedThread?.let { active ->
                        result.value.firstOrNull { it.id == active.id } ?: active
                    }
                    current.copy(
                        threads = result.value,
                        selectedThread = selected,
                        loadingThreads = false,
                        offline = result.fromCache,
                    )
                }
                publishConversationShortcuts(result.value)
            } catch (error: Exception) {
                handleAuthenticatedError(error) {
                    it.copy(loadingThreads = false, error = error.userMessage("Could not load conversations."))
                }
            }
        }
    }

    private fun publishConversationShortcuts(threads: List<ThreadSummary> = mutableState.value.threads) {
        val current = mutableState.value
        if (current.user == null) conversationShortcuts.clear()
        else conversationShortcuts.publish(current.serverUrl, threads)
    }

    fun refreshCapabilities() {
        if (mutableState.value.user == null) return
        viewModelScope.launch {
            mutableState.update { it.copy(loadingCapabilities = true) }
            val result = try {
                workspace.capabilities()
            } catch (error: Exception) {
                handleAuthenticatedError(error) { state -> state.copy(loadingCapabilities = false) }
                return@launch
            }
            val capabilities = result.value
            val savedDefaultAgentId = settings.defaultAgent(api.serverUrl)
            val savedRunOptions = settings.savedRunOptions(api.serverUrl)
            mutableState.update { current ->
                val agentSelection = resolveAgentSelection(
                    savedDefaultAgentId = savedDefaultAgentId,
                    currentDefaultAgentId = current.defaultAgentId,
                    currentSelectedAgentId = current.composer.options.assistantId,
                    capabilities = capabilities,
                )
                val modelName = current.composer.options.modelName
                    ?: savedRunOptions.modelName?.takeIf { savedModelName ->
                        capabilities.models.any { model -> model.name == savedModelName }
                    }
                    ?: capabilities.models.firstOrNull()?.name
                val availableModes = capabilities.availableRunModes(modelName)
                val requestedMode = if (current.composer.options.modelName == null) {
                    savedRunOptions.mode
                } else {
                    current.composer.options.mode
                }
                val mode = requestedMode.takeIf { it in availableModes }
                    ?: availableModes.first()
                current.copy(
                    capabilities = capabilities,
                    defaultAgentId = agentSelection.defaultAgentId,
                    composer = current.composer.copy(
                        options = current.composer.options.copy(
                            assistantId = agentSelection.selectedAgentId,
                            modelName = modelName,
                            mode = mode,
                            reasoningEffortEnabled = capabilities.supportsReasoningEffort(modelName),
                        ),
                    ),
                    loadingCapabilities = false,
                    offline = current.offline || result.fromCache,
                )
            }
            if (savedDefaultAgentId !in capabilities.agents.map { it.name } + LEAD_AGENT_ID) {
                runCatching { settings.setDefaultAgent(api.serverUrl, LEAD_AGENT_ID) }
            }
        }
    }

    fun refreshMcpConfig() {
        if (mutableState.value.user == null) return
        viewModelScope.launch {
            mutableState.update { it.copy(loadingMcpConfig = true) }
            try {
                val config = workspace.mcpConfig()
                mutableState.update { it.copy(mcpConfig = config, loadingMcpConfig = false) }
            } catch (error: Exception) {
                handleAuthenticatedError(error) {
                    it.copy(
                        loadingMcpConfig = false,
                        error = error.userMessage("Could not load MCP servers."),
                    )
                }
            }
        }
    }

    fun refreshMcpTools() {
        if (mutableState.value.user == null || mutableState.value.loadingMcpTools) return
        viewModelScope.launch {
            mutableState.update { it.copy(loadingMcpTools = true) }
            try {
                val result = workspace.mcpTools()
                mutableState.update {
                    it.copy(
                        mcpTools = result.value,
                        loadingMcpTools = false,
                        offline = it.offline || result.fromCache,
                    )
                }
            } catch (error: Exception) {
                handleAuthenticatedError(error) {
                    it.copy(
                        loadingMcpTools = false,
                        error = error.userMessage("Could not load MCP tools."),
                    )
                }
            }
        }
    }

    fun refreshChannels() {
        if (mutableState.value.user == null) return
        viewModelScope.launch {
            mutableState.update { it.copy(loadingChannels = true) }
            try {
                val providers = workspace.channelProviders()
                mutableState.update { it.copy(channelProviders = providers, loadingChannels = false) }
            } catch (error: Exception) {
                handleAuthenticatedError(error) {
                    it.copy(
                        loadingChannels = false,
                        error = error.userMessage("Could not load Channels."),
                    )
                }
            }
        }
    }

    fun refreshTasks() {
        if (mutableState.value.user == null) return
        viewModelScope.launch {
            mutableState.update { it.copy(loadingTasks = true) }
            try {
                val result = workspace.tasks()
                mutableState.update {
                    it.copy(
                        tasks = result.value,
                        loadingTasks = false,
                        offline = it.offline || result.fromCache,
                    )
                }
            } catch (error: Exception) {
                handleAuthenticatedError(error) { it.copy(loadingTasks = false) }
            }
        }
    }

    fun loadTaskRuns(task: ScheduledTaskInfo) {
        val taskId = task.id
        mutableState.update {
            it.copy(
                taskRunsTaskId = taskId,
                taskRuns = emptyList(),
                loadingTaskRuns = true,
                error = null,
            )
        }
        viewModelScope.launch {
            try {
                val runs = workspace.taskRuns(taskId)
                mutableState.update { current ->
                    if (current.taskRunsTaskId != taskId) current
                    else current.copy(taskRuns = runs, loadingTaskRuns = false)
                }
            } catch (error: Exception) {
                mutableState.update { current ->
                    if (current.taskRunsTaskId != taskId) current
                    else current.copy(
                        loadingTaskRuns = false,
                        error = error.userMessage("Could not load task execution history."),
                    )
                }
            }
        }
    }

    fun openTaskRunConversation(task: ScheduledTaskInfo, run: ScheduledTaskRunInfo) {
        if (run.threadId.isBlank()) return
        val current = mutableState.value
        val thread = current.threads.firstOrNull { it.id == run.threadId }
            ?: ThreadSummary(
                id = run.threadId,
                title = task.title,
                status = run.status,
                updatedAt = run.finishedAt ?: run.startedAt ?: run.createdAt,
            )
        openThread(thread)
    }

    fun loadAgentRuns(agent: AgentInfo) {
        val agentId = agent.name
        mutableState.update {
            it.copy(
                agentRunsAgentId = agentId,
                agentRuns = emptyList(),
                loadingAgentRuns = true,
                agentRunsError = null,
            )
        }
        viewModelScope.launch {
            try {
                val runs = workspace.agentRuns(agentId)
                mutableState.update { current ->
                    if (current.agentRunsAgentId != agentId) current
                    else current.copy(agentRuns = runs, loadingAgentRuns = false)
                }
            } catch (error: Exception) {
                mutableState.update { current ->
                    if (current.agentRunsAgentId != agentId) current
                    else current.copy(
                        loadingAgentRuns = false,
                        agentRunsError = error.userMessage("Could not load agent execution history."),
                    )
                }
            }
        }
    }

    fun openAgentRunConversation(agent: AgentInfo, run: AgentRunInfo) {
        if (run.threadId.isBlank()) return
        selectAgent(agent.name)
        val current = mutableState.value
        val thread = current.threads.firstOrNull { it.id == run.threadId }
            ?: ThreadSummary(
                id = run.threadId,
                title = run.threadTitle?.takeIf(String::isNotBlank) ?: agent.name,
                status = run.status,
                updatedAt = run.updatedAt ?: run.createdAt.orEmpty(),
            )
        openThread(thread)
    }

    fun refreshMemory() {
        if (mutableState.value.user == null || mutableState.value.loadingMemory) return
        viewModelScope.launch {
            mutableState.update { it.copy(loadingMemory = true) }
            try {
                val result = workspace.memory()
                mutableState.update {
                    it.copy(
                        memory = result.value,
                        loadingMemory = false,
                        offline = it.offline || result.fromCache,
                    )
                }
            } catch (error: Exception) {
                handleAuthenticatedError(error) {
                    it.copy(
                        loadingMemory = false,
                        error = error.userMessage("Could not load memory."),
                    )
                }
            }
        }
    }

    fun openWorkspaceChild(route: AppRoute) {
        require(route.isWorkspaceChild) { "Expected a workspace child route." }
        mutableState.update {
            it.copy(
                route = route,
                error = null,
            )
        }
        if (route == AppRoute.Memory && mutableState.value.memory == null) refreshMemory()
    }

    fun closeWorkspaceChild() {
        mutableState.update { current ->
            if (current.route.isWorkspaceChild) current.copy(route = AppRoute.Workspace, error = null) else current
        }
    }

    fun createThread() {
        threadLoadJob?.cancel()
        viewModelScope.launch {
            val assistant = mutableState.value.defaultAgentId
            val draft = threads.loadDraft(NEW_DRAFT_KEY)
            val attachments = runCatching { threads.loadAttachments(NEW_DRAFT_KEY) }.getOrDefault(emptyList())
            mutableState.update {
                it.copy(
                    selectedThread = null,
                    messages = emptyList(),
                    todos = emptyList(),
                    artifacts = emptyList(),
                    artifactPreview = null,
                    composer = it.composer.copy(
                        text = draft,
                        attachments = attachments,
                        options = it.composer.options.copy(assistantId = assistant),
                    ),
                    loadingChat = false,
                    draftStorageKey = NEW_DRAFT_KEY,
                    draftSessionKey = "new-draft",
                    composerResetToken = it.composerResetToken + 1,
                    route = AppRoute.Conversation,
                    error = null,
                )
            }
        }
    }

    fun openThread(thread: ThreadSummary) {
        if (mutableState.value.selectedThread?.id == thread.id && mutableState.value.route == AppRoute.Conversation) return
        threadLoadJob?.cancel()
        mutableState.update {
            it.copy(
                route = AppRoute.Conversation,
                selectedThread = thread,
                messages = emptyList(),
                todos = emptyList(),
                artifacts = emptyList(),
                artifactPreview = null,
                loadingChat = true,
                draftStorageKey = thread.id,
                draftSessionKey = "thread-draft-${thread.id}",
                composerResetToken = it.composerResetToken + 1,
                error = null,
            )
        }
        threadLoadJob = viewModelScope.launch {
            val draft = async { threads.loadDraft(thread.id) }
            val attachments = async { runCatching { threads.loadAttachments(thread.id) }.getOrDefault(emptyList()) }
            try {
                val snapshot = threads.snapshot(thread.id)
                val savedDraft = draft.await()
                val savedAttachments = attachments.await()
                mutableState.update { current ->
                    if (!isCurrentThreadLoad(current.selectedThread?.id, thread.id)) {
                        current
                    } else {
                        current.copy(
                            selectedThread = current.selectedThread?.copy(title = snapshot.value.title),
                            messages = snapshot.value.messages,
                            todos = snapshot.value.todos,
                            artifacts = snapshot.value.artifacts,
                            composer = current.composer.copy(text = savedDraft, attachments = savedAttachments),
                            composerResetToken = current.composerResetToken + 1,
                            loadingChat = false,
                            offline = snapshot.fromCache,
                        )
                    }
                }
                if (!isCurrentThreadLoad(mutableState.value.selectedThread?.id, thread.id)) return@launch
                resumeRunIfNeeded(thread.id)
            } catch (error: Exception) {
                val savedDraft = draft.await()
                val savedAttachments = attachments.await()
                mutableState.update {
                    if (!isCurrentThreadLoad(it.selectedThread?.id, thread.id)) {
                        it
                    } else {
                        it.copy(
                            loadingChat = false,
                            composer = it.composer.copy(text = savedDraft, attachments = savedAttachments),
                            composerResetToken = it.composerResetToken + 1,
                            error = error.userMessage("Could not load this conversation."),
                        )
                    }
                }
            }
        }
    }

    fun closeConversation() {
        threadLoadJob?.cancel()
        if (mutableState.value.run.active) {
            mutableState.update { it.copy(route = AppRoute.Workspace, error = null) }
            return
        }
        mutableState.update {
            it.copy(
                route = AppRoute.Workspace,
                selectedThread = null,
                messages = emptyList(),
                todos = emptyList(),
                artifacts = emptyList(),
                artifactPreview = null,
                composer = it.composer.copy(
                    text = "",
                    attachments = emptyList(),
                    options = it.composer.options.copy(assistantId = it.defaultAgentId),
                ),
                draftStorageKey = NEW_DRAFT_KEY,
                draftSessionKey = "new-draft",
                composerResetToken = it.composerResetToken + 1,
                error = null,
            )
        }
        viewModelScope.launch {
            val draft = threads.loadDraft(NEW_DRAFT_KEY)
            val attachments = runCatching { threads.loadAttachments(NEW_DRAFT_KEY) }.getOrDefault(emptyList())
            mutableState.update {
                it.copy(
                    composer = it.composer.copy(text = draft, attachments = attachments),
                    composerResetToken = it.composerResetToken + 1,
                )
            }
        }
    }

    fun deleteThread(thread: ThreadSummary) {
        val current = mutableState.value
        if (current.run.active && current.selectedThread?.id == thread.id) {
            mutableState.update { it.copy(error = "Stop the active run before deleting this conversation.") }
            return
        }
        viewModelScope.launch {
            try {
                threads.delete(thread.id)
                mutableState.update {
                    it.copy(
                        threads = it.threads.filterNot { item -> item.id == thread.id },
                        selectedThread = it.selectedThread?.takeUnless { selected -> selected.id == thread.id },
                        messages = if (it.selectedThread?.id == thread.id) emptyList() else it.messages,
                        todos = if (it.selectedThread?.id == thread.id) emptyList() else it.todos,
                        artifacts = if (it.selectedThread?.id == thread.id) emptyList() else it.artifacts,
                        route = if (it.selectedThread?.id == thread.id) AppRoute.Workspace else it.route,
                    )
                }
                publishConversationShortcuts()
            } catch (error: Exception) {
                handleAuthenticatedError(error) { it.copy(error = error.userMessage("Could not delete this conversation.")) }
            }
        }
    }

    fun renameThread(thread: ThreadSummary, title: String) {
        val value = title.trim()
        if (value.isBlank()) return
        viewModelScope.launch {
            try {
                threads.rename(thread.id, value)
                mutableState.update {
                    it.copy(
                        threads = it.threads.map { item -> if (item.id == thread.id) item.copy(title = value) else item },
                        selectedThread = it.selectedThread?.let { selected -> if (selected.id == thread.id) selected.copy(title = value) else selected },
                    )
                }
                publishConversationShortcuts()
            } catch (error: Exception) {
                mutableState.update { it.copy(error = error.userMessage("Could not rename this conversation.")) }
            }
        }
    }

    fun toggleThreadPinned(thread: ThreadSummary) {
        viewModelScope.launch {
            threads.setPinned(thread, !thread.isPinned)
            mutableState.update {
                val updated = it.threads.map { item -> if (item.id == thread.id) item.copy(isPinned = !item.isPinned) else item }
                    .sortedWith(compareByDescending<ThreadSummary> { item -> item.isPinned }.thenByDescending { item -> item.updatedAt })
                it.copy(threads = updated)
            }
            publishConversationShortcuts()
        }
    }

    fun updateDraft(value: String) {
        val key = mutableState.value.draftStorageKey
        mutableState.update { it.copy(composer = it.composer.copy(text = value)) }
        draftJob?.cancel()
        draftJob = viewModelScope.launch {
            threads.saveDraft(key, value)
        }
    }

    fun addAttachment(uri: Uri) {
        val resolver = getApplication<Application>().contentResolver
        runCatching {
            resolver.takePersistableUriPermission(uri, android.content.Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
        val metadata = resolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE), null, null, null)?.use { cursor ->
            if (!cursor.moveToFirst()) null else {
                val nameIndex = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                val sizeIndex = cursor.getColumnIndex(OpenableColumns.SIZE)
                (if (nameIndex >= 0) cursor.getString(nameIndex) else null) to
                    (if (sizeIndex >= 0 && !cursor.isNull(sizeIndex)) cursor.getLong(sizeIndex) else -1L)
            }
        }
        val filename = metadata?.first ?: uri.lastPathSegment ?: "attachment"
        val size = metadata?.second ?: -1L
        val mime = resolver.getType(uri) ?: "application/octet-stream"
        val attachment = PendingAttachment(uri.toString(), filename, mime, size)
        mutableState.update { current ->
            if (current.composer.attachments.any { it.uri == attachment.uri }) current
            else current.copy(composer = current.composer.copy(attachments = current.composer.attachments + attachment))
        }
        persistAttachmentDraft(
            mutableState.value.draftStorageKey,
            mutableState.value.composer.attachments,
        )
    }

    fun removeAttachment(uri: String) {
        mutableState.update { it.copy(composer = it.composer.copy(attachments = it.composer.attachments.filterNot { item -> item.uri == uri })) }
        persistAttachmentDraft(
            mutableState.value.draftStorageKey,
            mutableState.value.composer.attachments,
        )
    }

    fun retryAttachment(uri: String) {
        val current = mutableState.value
        if (current.run.active || current.composer.uploading) return
        val attachments = current.composer.attachments.map { attachment ->
            if (attachment.uri == uri && attachment.status == AttachmentStatus.Failed) {
                attachment.copy(status = AttachmentStatus.Pending, error = null)
            } else {
                attachment
            }
        }
        if (attachments == current.composer.attachments) return
        mutableState.update { it.copy(composer = it.composer.copy(attachments = attachments), error = null) }
        persistAttachmentDraft(current.draftStorageKey, attachments)
        sendMessage()
    }

    fun selectModel(name: String?) {
        mutableState.update { current ->
            val modes = current.capabilities.availableRunModes(name)
            val mode = current.composer.options.mode.takeIf { it in modes } ?: modes.first()
            current.copy(
                composer = current.composer.copy(
                    options = current.composer.options.copy(
                        modelName = name,
                        mode = mode,
                        reasoningEffortEnabled = current.capabilities.supportsReasoningEffort(name),
                    ),
                ),
            )
        }
        persistSelectedRunOptions()
    }

    fun selectAgent(name: String) {
        mutableState.update { it.copy(composer = it.composer.copy(options = it.composer.options.copy(assistantId = name))) }
    }

    fun setDefaultAgent(name: String) {
        val current = mutableState.value
        val available = current.capabilities.agents.map { it.name } + LEAD_AGENT_ID
        if (name !in available || current.loadingCapabilities) return
        viewModelScope.launch {
            try {
                settings.setDefaultAgent(api.serverUrl, name)
                mutableState.update {
                    it.copy(
                        defaultAgentId = name,
                        composer = if (it.selectedThread == null) {
                            it.composer.copy(options = it.composer.options.copy(assistantId = name))
                        } else {
                            it.composer
                        },
                    )
                }
            } catch (error: Exception) {
                mutableState.update { it.copy(error = error.userMessage("Could not save the default agent.")) }
            }
        }
    }

    fun selectMode(mode: RunMode) {
        if (mode !in mutableState.value.capabilities.availableRunModes(mutableState.value.composer.options.modelName)) return
        mutableState.update { current ->
            current.copy(composer = current.composer.copy(options = current.composer.options.copy(mode = mode)))
        }
        persistSelectedRunOptions()
    }

    fun toggleSkill(name: String) {
        mutableState.update { current ->
            if (current.capabilities.skills.none { it.name == name && it.enabled }) return@update current
            val skills = current.composer.options.enabledSkills.toMutableSet()
            if (!skills.add(name)) skills.remove(name)
            current.copy(composer = current.composer.copy(options = current.composer.options.copy(enabledSkills = skills)))
        }
    }

    fun enableSkill(name: String) {
        mutableState.update { current ->
            if (current.capabilities.skills.none { it.name == name && it.enabled }) return@update current
            current.copy(
                composer = current.composer.copy(
                    options = current.composer.options.copy(
                        enabledSkills = current.composer.options.enabledSkills + name,
                    ),
                ),
            )
        }
    }

    fun setSkillEnabled(name: String, enabled: Boolean) {
        val current = mutableState.value
        val skill = current.capabilities.skills.firstOrNull { it.name == name } ?: return
        if (current.user?.role != "admin" || current.workspaceMutationBusy || skill.enabled == enabled) return
        viewModelScope.launch {
            mutableState.update { it.copy(workspaceMutationBusy = true, error = null) }
            try {
                val capabilities = workspace.setSkillEnabled(current.capabilities, name, enabled)
                mutableState.update { state ->
                    val selectedSkills = if (enabled) {
                        state.composer.options.enabledSkills
                    } else {
                        state.composer.options.enabledSkills - name
                    }
                    state.copy(
                        capabilities = capabilities,
                        composer = state.composer.copy(options = state.composer.options.copy(enabledSkills = selectedSkills)),
                        workspaceMutationBusy = false,
                    )
                }
            } catch (error: Exception) {
                handleAuthenticatedError(error) {
                    it.copy(
                        workspaceMutationBusy = false,
                        error = error.userMessage("Could not update this skill."),
                    )
                }
            }
        }
    }

    fun setMcpServerEnabled(name: String, enabled: Boolean) {
        val current = mutableState.value
        val config = current.mcpConfig ?: return
        val server = config.servers.firstOrNull { it.name == name } ?: return
        if (current.user?.role != "admin" || current.workspaceMutationBusy || server.enabled == enabled) return
        viewModelScope.launch {
            mutableState.update { it.copy(workspaceMutationBusy = true, error = null) }
            try {
                val updatedConfig = workspace.setMcpServerEnabled(config, name, enabled)
                mutableState.update { it.copy(mcpConfig = updatedConfig, workspaceMutationBusy = false) }
                refreshMcpTools()
            } catch (error: Exception) {
                handleAuthenticatedError(error) {
                    it.copy(
                        workspaceMutationBusy = false,
                        error = error.userMessage("Could not update this MCP server."),
                    )
                }
            }
        }
    }

    fun updateMcpConfiguration(rawJson: String, onUpdated: () -> Unit = {}) {
        val current = mutableState.value
        if (current.user?.role != "admin" || current.workspaceMutationBusy) return
        viewModelScope.launch {
            mutableState.update { it.copy(workspaceMutationBusy = true, error = null) }
            try {
                val updatedConfig = workspace.updateMcpConfig(rawJson)
                mutableState.update { it.copy(mcpConfig = updatedConfig, workspaceMutationBusy = false) }
                refreshMcpTools()
                onUpdated()
            } catch (error: Exception) {
                handleAuthenticatedError(error) {
                    it.copy(
                        workspaceMutationBusy = false,
                        error = error.userMessage("Could not update MCP configuration."),
                    )
                }
            }
        }
    }

    fun configureChannelProvider(providerId: String, values: Map<String, String>) {
        val current = mutableState.value
        val provider = current.channelProviders?.providers?.firstOrNull { it.provider == providerId } ?: return
        if (current.user?.role != "admin" || current.workspaceMutationBusy || !provider.enabled) return
        viewModelScope.launch {
            mutableState.update { it.copy(workspaceMutationBusy = true, error = null, channelConnect = null) }
            try {
                val updated = workspace.configureChannelProvider(providerId, values)
                mutableState.update { state ->
                    state.copy(
                        channelProviders = state.channelProviders?.replaceChannelProvider(updated),
                        workspaceMutationBusy = false,
                    )
                }
            } catch (error: Exception) {
                handleAuthenticatedError(error) {
                    it.copy(
                        workspaceMutationBusy = false,
                        error = error.userMessage("Could not configure this Channel."),
                    )
                }
            }
        }
    }

    fun disconnectChannelProvider(providerId: String) {
        val current = mutableState.value
        val provider = current.channelProviders?.providers?.firstOrNull { it.provider == providerId } ?: return
        if (current.user?.role != "admin" || current.workspaceMutationBusy || !provider.configured) return
        viewModelScope.launch {
            mutableState.update { it.copy(workspaceMutationBusy = true, error = null, channelConnect = null) }
            try {
                val updated = workspace.disconnectChannelProvider(providerId)
                mutableState.update { state ->
                    state.copy(
                        channelProviders = state.channelProviders?.replaceChannelProvider(updated),
                        workspaceMutationBusy = false,
                    )
                }
            } catch (error: Exception) {
                handleAuthenticatedError(error) {
                    it.copy(
                        workspaceMutationBusy = false,
                        error = error.userMessage("Could not disable this Channel."),
                    )
                }
            }
        }
    }

    fun connectChannelProvider(providerId: String) {
        val current = mutableState.value
        val provider = current.channelProviders?.providers?.firstOrNull { it.provider == providerId } ?: return
        if (current.workspaceMutationBusy || !provider.connectable || provider.connectionStatus == "connected") return
        viewModelScope.launch {
            mutableState.update { it.copy(workspaceMutationBusy = true, error = null, channelConnect = null) }
            try {
                val connection = workspace.connectChannelProvider(providerId)
                mutableState.update { it.copy(channelConnect = connection, workspaceMutationBusy = false) }
            } catch (error: Exception) {
                handleAuthenticatedError(error) {
                    it.copy(
                        workspaceMutationBusy = false,
                        error = error.userMessage("Could not start Channel connection."),
                    )
                }
            }
        }
    }

    fun clearChannelConnect() {
        mutableState.update { it.copy(channelConnect = null) }
    }

    fun applyQuickAction(prompt: String, skillKeywords: List<String>) {
        mutableState.update { state ->
            state.copy(
                composer = applyQuickActionToComposer(
                    composer = state.composer,
                    capabilities = state.capabilities,
                    prompt = prompt,
                    skillKeywords = skillKeywords,
                ),
            )
        }
        draftJob?.cancel()
        draftJob = viewModelScope.launch {
            val state = mutableState.value
            threads.saveDraft(state.draftStorageKey, state.composer.text)
        }
    }

    fun startChatWithAgent(agentId: String) {
        closeWorkspaceChild()
        closeConversation()
        selectAgent(agentId)
    }

    fun saveMemoryFact(
        existing: MemoryFact?,
        content: String,
        category: String,
        confidence: Double,
        onSaved: () -> Unit,
    ) {
        val normalizedContent = content.trim()
        val normalizedCategory = category.trim().ifBlank { "context" }
        if (normalizedContent.isBlank()) {
            mutableState.update { it.copy(error = "Memory fact content cannot be empty.") }
            return
        }
        if (!confidence.isFinite() || confidence !in 0.0..1.0) {
            mutableState.update { it.copy(error = "Memory confidence must be between 0 and 1.") }
            return
        }
        viewModelScope.launch {
            mutableState.update { it.copy(memoryMutationBusy = true, error = null) }
            try {
                val memory = if (existing == null) {
                    workspace.createMemoryFact(normalizedContent, normalizedCategory, confidence)
                } else {
                    workspace.updateMemoryFact(existing.id, normalizedContent, normalizedCategory, confidence)
                }
                mutableState.update { it.copy(memory = memory, memoryMutationBusy = false) }
                onSaved()
            } catch (error: Exception) {
                handleAuthenticatedError(error) {
                    it.copy(
                        memoryMutationBusy = false,
                        error = error.userMessage("Could not save this memory fact."),
                    )
                }
            }
        }
    }

    fun deleteMemoryFact(fact: MemoryFact) {
        viewModelScope.launch {
            mutableState.update { it.copy(memoryMutationBusy = true, error = null) }
            try {
                val memory = workspace.deleteMemoryFact(fact.id)
                mutableState.update { it.copy(memory = memory, memoryMutationBusy = false) }
            } catch (error: Exception) {
                handleAuthenticatedError(error) {
                    it.copy(
                        memoryMutationBusy = false,
                        error = error.userMessage("Could not delete this memory fact."),
                    )
                }
            }
        }
    }

    fun clearMemory() {
        viewModelScope.launch {
            mutableState.update { it.copy(memoryMutationBusy = true, error = null) }
            try {
                val memory = workspace.clearMemory()
                mutableState.update { it.copy(memory = memory, memoryMutationBusy = false) }
            } catch (error: Exception) {
                handleAuthenticatedError(error) {
                    it.copy(
                        memoryMutationBusy = false,
                        error = error.userMessage("Could not clear memory."),
                    )
                }
            }
        }
    }

    fun saveAgent(existing: AgentInfo?, name: String, description: String, model: String?, onSaved: () -> Unit) {
        val normalized = name.trim().lowercase()
        if (!normalized.matches(Regex("^[a-z0-9-]+$"))) {
            mutableState.update { it.copy(error = "Agent names may contain only letters, numbers, and hyphens.") }
            return
        }
        viewModelScope.launch {
            mutableState.update { it.copy(workspaceMutationBusy = true) }
            try {
                if (existing == null) workspace.createAgent(normalized, description.trim(), model)
                else workspace.updateAgent(existing.name, description.trim(), model)
                mutableState.update { it.copy(workspaceMutationBusy = false) }
                refreshCapabilities()
                onSaved()
            } catch (error: Exception) {
                mutableState.update { it.copy(workspaceMutationBusy = false, error = error.userMessage("Could not save this agent.")) }
            }
        }
    }

    fun deleteAgent(agent: AgentInfo) {
        viewModelScope.launch {
            mutableState.update { it.copy(workspaceMutationBusy = true) }
            try {
                workspace.deleteAgent(agent.name)
                mutableState.update { it.copy(workspaceMutationBusy = false) }
                refreshCapabilities()
            } catch (error: Exception) {
                mutableState.update { it.copy(workspaceMutationBusy = false, error = error.userMessage("Could not delete this agent.")) }
            }
        }
    }

    fun saveTask(existing: ScheduledTaskInfo?, title: String, prompt: String, schedule: TaskSchedule, timezone: String, onSaved: () -> Unit) {
        val scheduleValue = when (schedule) {
            is TaskSchedule.Cron -> schedule.expression
            is TaskSchedule.Once -> schedule.runAt
        }
        if (title.isBlank() || prompt.isBlank() || scheduleValue.isBlank() || timezone.isBlank()) {
            mutableState.update { it.copy(error = "Complete the title, prompt, schedule, and timezone.") }
            return
        }
        viewModelScope.launch {
            mutableState.update { it.copy(workspaceMutationBusy = true) }
            try {
                if (existing == null) workspace.createTask(title.trim(), prompt.trim(), schedule, timezone.trim())
                else workspace.updateTask(existing.id, title.trim(), prompt.trim(), schedule, timezone.trim())
                mutableState.update { it.copy(workspaceMutationBusy = false) }
                refreshTasks()
                onSaved()
            } catch (error: Exception) {
                mutableState.update { it.copy(workspaceMutationBusy = false, error = error.userMessage("Could not save this task.")) }
            }
        }
    }

    fun deleteTask(task: ScheduledTaskInfo) {
        viewModelScope.launch {
            mutableState.update { it.copy(workspaceMutationBusy = true) }
            try {
                workspace.deleteTask(task.id)
                mutableState.update { it.copy(workspaceMutationBusy = false) }
                refreshTasks()
            } catch (error: Exception) {
                mutableState.update { it.copy(workspaceMutationBusy = false, error = error.userMessage("Could not delete this task.")) }
            }
        }
    }

    fun sendMessage() {
        val state = mutableState.value
        val text = state.composer.text.trim()
        if (
            (text.isBlank() && state.composer.attachments.isEmpty()) ||
            state.run.active ||
            state.selectedThread?.let { runCoordinator.isActive(api.serverUrl, it.id) } == true
        ) return

        if (!submissionGate.tryAcquire()) return
        val composer = state.composer
        val draftKey = state.draftStorageKey
        val clientMessageId = UUID.randomUUID().toString()
        val optimistic = ChatMessage(
            id = clientMessageId,
            role = MessageRole.User,
            text = text,
            attachments = composer.attachments.map { MessageAttachment(it.filename, it.size, null) },
        )
        mutableState.update {
            it.copy(
                messages = it.messages + optimistic,
                composer = it.composer.copy(text = "", attachments = emptyList(), uploading = composer.attachments.isNotEmpty()),
                composerResetToken = it.composerResetToken + 1,
                error = null,
            )
        }

        viewModelScope.launch {
            try {
                runCatching { threads.saveDraft(draftKey, "") }
                runCatching { threads.saveAttachments(draftKey, composer.attachments) }
                val thread = mutableState.value.selectedThread ?: try {
                    val created = threads.create(composer.options.assistantId)
                    mutableState.update {
                        it.copy(
                            threads = listOf(created) + it.threads,
                            selectedThread = created,
                            draftStorageKey = created.id,
                            route = AppRoute.Conversation,
                        )
                    }
                    publishConversationShortcuts()
                    created
                } catch (error: Exception) {
                    restoreSubmissionDraft(clientMessageId, draftKey, text, composer, error.userMessage("Could not create a conversation."))
                    return@launch
                }
                startRun(thread, text, composer, draftKey, clientMessageId)
            } finally {
                submissionGate.release()
            }
        }
    }

    private suspend fun startRun(
        thread: ThreadSummary,
        text: String,
        composer: ComposerState,
        draftKey: String,
        clientMessageId: String,
    ) {
        val pending = composer.attachments
        mutableState.update {
            it.copy(
                run = RunState(RunStatus.Connecting),
                composer = it.composer.copy(uploading = pending.isNotEmpty()),
                error = null,
            )
        }
        runCatching {
            threads.saveAttachments(
                draftKey,
                pending.map { file -> file.copy(status = AttachmentStatus.Uploading, error = null) },
            )
        }
        if (pending.isNotEmpty()) {
            RunService.start(getApplication(), thread.title, api.serverUrl, thread.id)
            RunService.update(getApplication(), RunProgress.Uploading, thread.title)
        }
        val uploaded = try {
            if (pending.isEmpty()) {
                emptyList()
            } else {
                runs.upload(thread.id, pending.map(::toUploadSource))
            }
        } catch (error: Exception) {
            val message = error.userMessage("Upload failed.")
            restoreSubmissionDraft(clientMessageId, draftKey, text, composer, message, error.message)
            RunService.fail(getApplication(), message, thread.title)
            return
        }
        mutableState.update {
            it.copy(
                messages = it.messages.map { message ->
                    if (message.id == clientMessageId) {
                        message.copy(attachments = uploaded.map { file -> MessageAttachment(file.filename, file.size, file.virtualPath) })
                    } else {
                        message
                    }
                },
                composer = it.composer.copy(uploading = false),
            )
        }
        threads.saveDraft(draftKey, "")
        runCatching {
            threads.saveAttachments(draftKey, emptyList())
        }
        val current = mutableState.value
        runCoordinator.start(
            CoordinatedRunRequest(
                serverUrl = api.serverUrl,
                threadId = thread.id,
                title = thread.title,
                message = text,
                options = composer.options,
                clientMessageId = clientMessageId,
                files = uploaded,
                initialMessages = current.messages,
                initialTodos = current.todos,
                initialArtifacts = current.artifacts,
            ),
        )
    }

    private fun restoreSubmissionDraft(
        clientMessageId: String,
        draftKey: String,
        text: String,
        composer: ComposerState,
        message: String,
        attachmentError: String? = null,
    ) {
        val restoredComposer = restoreFailedComposer(composer, text, attachmentError)
        mutableState.update {
            it.copy(
                run = RunState(),
                messages = it.messages.filterNot { chat -> chat.id == clientMessageId },
                composer = restoredComposer,
                composerResetToken = it.composerResetToken + 1,
                error = message,
            )
        }
        viewModelScope.launch {
            threads.saveDraft(draftKey, text)
            runCatching { threads.saveAttachments(draftKey, restoredComposer.attachments) }
        }
    }

    fun stopRun() {
        val current = mutableState.value
        val thread = current.selectedThread ?: return
        if (!current.run.active) return
        mutableState.update { it.copy(run = it.run.copy(status = RunStatus.Stopping)) }
        viewModelScope.launch {
            val snapshot = runCoordinator.cancelActive()
            mutableState.update {
                it.copy(
                    run = RunState(),
                    messages = snapshot?.messages ?: it.messages.map { message -> message.copy(isStreaming = false) },
                    todos = snapshot?.todos ?: it.todos,
                    artifacts = snapshot?.artifacts ?: it.artifacts,
                )
            }
        }
    }

    fun submitHumanInput(request: HumanInputRequest, value: String, optionId: String? = null) {
        val answer = value.trim()
        val current = mutableState.value
        val thread = current.selectedThread ?: return
        if (answer.isBlank() || current.run.active) return
        val response = HumanInputResponse(
            source = request.source,
            requestId = request.requestId,
            responseKind = if (optionId == null) "text" else "option",
            value = answer,
            optionId = optionId,
        )
        val message = "For your clarification \"${request.question}\", my answer is: $answer"
        mutableState.update { it.copy(run = RunState(RunStatus.Connecting), error = null) }
        viewModelScope.launch {
            runCoordinator.start(
                CoordinatedRunRequest(
                    serverUrl = api.serverUrl,
                    threadId = thread.id,
                    title = thread.title,
                    message = message,
                    options = current.composer.options,
                    humanInputResponse = response,
                    initialMessages = current.messages,
                    initialTodos = current.todos,
                    initialArtifacts = current.artifacts,
                ),
            )
        }
    }

    fun branchConversation(messageId: String) {
        val current = mutableState.value
        val source = current.selectedThread ?: return
        if (current.run.active || current.messageActionBusy) return
        val turn = assistantTurnForMessage(current.messages, messageId) ?: return
        viewModelScope.launch {
            mutableState.update { it.copy(messageActionBusy = true, error = null) }
            try {
                val branch = createBranch(source, turn)
                mutableState.update {
                    it.copy(
                        threads = listOf(branch.first) + it.threads.filterNot { item -> item.id == branch.first.id },
                        selectedThread = branch.first,
                        messages = branch.second.messages,
                        todos = branch.second.todos,
                        artifacts = branch.second.artifacts,
                        composer = it.composer.copy(text = "", attachments = emptyList()),
                        route = AppRoute.Conversation,
                        messageActionBusy = false,
                        offline = false,
                        notice = getApplication<Application>().getString(R.string.conversation_branch_created),
                    )
                }
                refreshThreads()
            } catch (error: Exception) {
                mutableState.update { it.copy(messageActionBusy = false, error = error.userMessage("Could not branch this conversation.")) }
            }
        }
    }

    fun regenerateResponse(messageId: String) {
        val current = mutableState.value
        val thread = current.selectedThread ?: return
        if (current.run.active || current.messageActionBusy) return
        val turn = assistantTurnForMessage(current.messages, messageId) ?: return
        if (!isLatestAssistantTurn(current.messages, turn)) return
        val originalMessages = current.messages
        viewModelScope.launch {
            mutableState.update { it.copy(messageActionBusy = true, error = null) }
            try {
                val preparation = runs.prepareRegenerate(thread.id, turn.targetMessageId)
                mutableState.update {
                    it.copy(
                        messages = originalMessages.take(turn.firstMessageIndex),
                        run = RunState(RunStatus.Connecting),
                        messageActionBusy = false,
                    )
                }
                runCoordinator.start(
                    CoordinatedRunRequest(
                        serverUrl = api.serverUrl,
                        threadId = thread.id,
                        title = thread.title,
                        message = "",
                        options = current.composer.options,
                        regenerate = preparation,
                        initialMessages = mutableState.value.messages,
                        initialTodos = current.todos,
                        initialArtifacts = current.artifacts,
                        failureMessages = originalMessages,
                    ),
                )
            } catch (error: Exception) {
                mutableState.update {
                    it.copy(
                        messages = originalMessages,
                        messageActionBusy = false,
                        error = error.userMessage("Could not regenerate this response."),
                    )
                }
            }
        }
    }

    private suspend fun createBranch(
        source: ThreadSummary,
        turn: AssistantTurn,
    ): Pair<ThreadSummary, com.deerflow.mobile.data.ThreadSnapshot> {
        val result = threads.branch(source.id, turn.targetMessageId, turn.messageIds)
        val snapshot = threads.snapshot(result.threadId).value
        return ThreadSummary(
            id = result.threadId,
            title = snapshot.title,
            status = "idle",
            updatedAt = source.updatedAt,
        ) to snapshot
    }

    private suspend fun resumeRunIfNeeded(threadId: String) {
        runCoordinator.state.value
            ?.takeIf { it.serverUrl == api.serverUrl && it.threadId == threadId }
            ?.let {
                applyCoordinatedRunState(it)
                if (it.run.active) return
        }
        val thread = mutableState.value.selectedThread?.takeIf { it.id == threadId } ?: return
        val saved = cache.loadRun(api.serverUrl, threadId)
        if (saved?.active == true) {
            mutableState.update { it.copy(run = saved.copy(status = RunStatus.Reconnecting)) }
            if (!runCoordinator.resume(api.serverUrl, thread.id, thread.title, saved)) {
                mutableState.update { it.copy(run = RunState()) }
            }
            return
        }

        // A backgrounded client can lose its local run row while the Gateway keeps
        // the resumable run alive. Discover and attach to that run instead of
        // allowing the next send to create a conflicting run on the same thread.
        val active = try {
            api.latestActiveRun(threadId)
        } catch (_: Exception) {
            return
        }
        if (active == null) {
            cache.saveRun(api.serverUrl, threadId, RunState())
            mutableState.update { current ->
                if (current.selectedThread?.id == threadId && !runCoordinator.isActive(api.serverUrl, threadId)) {
                    current.copy(run = RunState(), messageActionBusy = false)
                } else {
                    current
                }
            }
            return
        }
        val recovered = RunState(RunStatus.Reconnecting, runId = active.runId)
        cache.saveRun(api.serverUrl, threadId, recovered)
        mutableState.update { it.copy(run = recovered) }
        if (!runCoordinator.resume(api.serverUrl, thread.id, thread.title, recovered)) {
            mutableState.update { it.copy(run = RunState()) }
        }
    }

    fun pauseTask(task: ScheduledTaskInfo) {
        viewModelScope.launch {
            try {
                workspace.pauseTask(task.id, task.status != "paused")
                refreshTasks()
            } catch (error: Exception) {
                mutableState.update { it.copy(error = error.userMessage("Could not update this task.")) }
            }
        }
    }

    fun triggerTask(task: ScheduledTaskInfo) {
        viewModelScope.launch {
            try {
                workspace.triggerTask(task.id)
                refreshTasks()
            } catch (error: Exception) {
                mutableState.update { it.copy(error = error.userMessage("Could not run this task.")) }
            }
        }
    }

    fun setTheme(value: ThemePreference) {
        persistSetting { setTheme(value) }
        mutableState.update { it.copy(theme = value) }
    }

    fun setDynamicColor(enabled: Boolean) {
        persistSetting { setDynamicColor(enabled) }
        mutableState.update { it.copy(useDynamicColor = enabled) }
    }

    fun setLanguage(value: LanguagePreference) {
        mutableState.update { it.copy(language = value) }
        AppCompatDelegate.setApplicationLocales(LocaleListCompat.forLanguageTags(value.languageTag))
    }

    fun syncLanguagePreference() {
        val current = currentLanguagePreference()
        mutableState.update { state -> if (state.language == current) state else state.copy(language = current) }
    }

    fun setNotifyOnRunCompletion(enabled: Boolean) {
        persistSetting { setNotifyOnRunCompletion(enabled) }
        mutableState.update { it.copy(notifyOnRunCompletion = enabled) }
    }

    fun setCacheRetentionPolicy(value: CacheRetentionPolicy) {
        persistSetting { setCacheRetentionPolicy(value) }
        mutableState.update { it.copy(cacheRetentionPolicy = value) }
    }

    fun refreshCacheStats() {
        if (mutableState.value.loadingCacheStats || mutableState.value.clearingCache) return
        viewModelScope.launch {
            mutableState.update { it.copy(loadingCacheStats = true) }
            try {
                val stats = cache.stats()
                mutableState.update { it.copy(cacheStats = stats, loadingCacheStats = false) }
            } catch (error: Exception) {
                mutableState.update {
                    it.copy(
                        loadingCacheStats = false,
                        error = error.userMessage("Could not inspect cached data."),
                    )
                }
            }
        }
    }

    fun clearCache() {
        if (mutableState.value.clearingCache) return
        if (mutableState.value.run.active) {
            mutableState.update { it.copy(error = "Stop the active run before clearing cached data.") }
            return
        }
        viewModelScope.launch {
            mutableState.update { it.copy(clearingCache = true) }
            try {
                cache.clearAll()
                val stats = cache.stats()
                mutableState.update { it.copy(cacheStats = stats, clearingCache = false) }
            } catch (error: Exception) {
                mutableState.update {
                    it.copy(
                        clearingCache = false,
                        error = error.userMessage("Could not clear cached data."),
                    )
                }
            }
        }
    }

    private fun persistSetting(block: suspend SettingsStore.() -> Unit) {
        viewModelScope.launch {
            try {
                settings.block()
            } catch (error: Exception) {
                mutableState.update { it.copy(error = error.userMessage("Could not save settings.")) }
            }
        }
    }

    fun dismissError() {
        mutableState.update { it.copy(error = null) }
    }

    fun showNotice(message: String) {
        mutableState.update { it.copy(notice = message) }
    }

    fun dismissNotice() {
        mutableState.update { it.copy(notice = null) }
    }

    fun reportError(message: String) {
        mutableState.update { it.copy(error = message) }
    }

    private fun persistSelectedRunOptions() {
        val current = mutableState.value
        if (current.serverUrl.isBlank()) return
        viewModelScope.launch {
            try {
                settings.setSavedRunOptions(
                    serverUrl = api.serverUrl,
                    modelName = current.composer.options.modelName,
                    mode = current.composer.options.mode,
                )
            } catch (error: Exception) {
                mutableState.update { it.copy(error = error.userMessage("Could not save the selected model.")) }
            }
        }
    }

    fun exportConversation(uri: Uri, format: ConversationExportFormat) {
        val current = mutableState.value
        if (current.exportBusy || current.messages.isEmpty()) return
        mutableState.update { it.copy(exportBusy = true, error = null) }
        viewModelScope.launch(Dispatchers.IO) {
            try {
                val title = current.selectedThread?.title ?: "DeerFlow conversation"
                val content = com.deerflow.mobile.data.exportConversation(title, current.messages, format)
                val resolver = getApplication<Application>().contentResolver
                resolver.openOutputStream(uri)?.use { output ->
                    output.bufferedWriter(Charsets.UTF_8).use { writer -> writer.write(content) }
                } ?: throw IOException("Could not open the selected destination.")
                mutableState.update { it.copy(exportBusy = false) }
            } catch (error: Exception) {
                mutableState.update {
                    it.copy(exportBusy = false, error = error.userMessage("Could not export this conversation."))
                }
            }
        }
    }

    fun openArtifact(path: String) {
        val current = mutableState.value
        val thread = current.selectedThread ?: return
        if (path.isBlank() || current.artifactBusy) return
        mutableState.update { it.copy(artifactBusy = true, artifactPreview = null, error = null) }
        viewModelScope.launch(Dispatchers.IO) {
            try {
                val payload = threads.artifact(thread.id, path)
                val directory = File(getApplication<Application>().cacheDir, "artifacts").apply { mkdirs() }
                val safeName = payload.filename.replace(Regex("[^\\p{L}\\p{N}._-]+"), "-").ifBlank { "artifact" }
                val file = File(directory, "${path.hashCode().toUInt()}-$safeName")
                file.writeBytes(payload.bytes)
                val text = if (isTextArtifact(payload.mimeType, payload.filename)) {
                    payload.bytes.toString(Charsets.UTF_8)
                } else {
                    null
                }
                mutableState.update { latest ->
                    if (latest.selectedThread?.id != thread.id) latest.copy(artifactBusy = false)
                    else latest.copy(
                        artifactBusy = false,
                        artifactPreview = ArtifactPreviewState(path, payload.filename, payload.mimeType, text, file.absolutePath),
                    )
                }
            } catch (error: Exception) {
                mutableState.update {
                    it.copy(artifactBusy = false, error = error.userMessage("Could not open this artifact."))
                }
            }
        }
    }

    fun saveArtifact(uri: Uri) {
        val preview = mutableState.value.artifactPreview ?: return
        viewModelScope.launch(Dispatchers.IO) {
            try {
                val resolver = getApplication<Application>().contentResolver
                resolver.openOutputStream(uri)?.use { output ->
                    File(preview.localPath).inputStream().use { input -> input.copyTo(output) }
                } ?: throw IOException("Could not open the selected destination.")
            } catch (error: Exception) {
                mutableState.update { it.copy(error = error.userMessage("Could not save this artifact.")) }
            }
        }
    }

    fun dismissArtifactPreview() {
        mutableState.update { it.copy(artifactPreview = null) }
    }

    fun reportArtifactOpenFailure() {
        mutableState.update { it.copy(error = "No installed app can open this artifact.") }
    }

    private fun persistAttachmentDraft(threadId: String, attachments: List<PendingAttachment>) {
        attachmentJob?.cancel()
        attachmentJob = viewModelScope.launch {
            runCatching { threads.saveAttachments(threadId, attachments) }
        }
    }

    private fun isTextArtifact(mimeType: String, filename: String): Boolean {
        if (mimeType in setOf("text/html", "application/xhtml+xml", "image/svg+xml")) return false
        if (mimeType.startsWith("text/") || mimeType in setOf("application/json", "application/xml", "application/javascript")) return true
        return filename.substringAfterLast('.', "").lowercase() in setOf(
            "md", "markdown", "txt", "json", "yaml", "yml", "toml", "csv", "tsv",
            "kt", "kts", "java", "py", "js", "ts", "tsx", "jsx", "css", "xml", "sh", "sql",
            "go", "rs", "rb", "php", "c", "h", "cpp", "hpp",
        )
    }

    private fun toUploadSource(file: PendingAttachment): UploadSource {
        val resolver = getApplication<Application>().contentResolver
        val uri = Uri.parse(file.uri)
        return UploadSource(file.filename, file.mimeType, file.size) {
            resolver.openInputStream(uri) ?: throw IOException("Could not open ${file.filename}.")
        }
    }

    private fun normalizeOrReport(value: String): String? = try {
        normalizeServerUrl(value)
    } catch (error: IllegalArgumentException) {
        mutableState.update { it.copy(error = error.message) }
        null
    }

    private fun disconnectRun() {
        runCoordinator.abandonActive()
        mutableState.update { it.copy(run = RunState()) }
    }

    private fun handleAuthenticatedError(error: Exception, update: (AppUiState) -> AppUiState) {
        if (error is ApiException && error.statusCode == 401) {
            mutableState.update { it.copy(user = null, checkingSession = false, run = RunState(), error = "Your session expired. Sign in again.") }
        } else {
            mutableState.update(update)
        }
    }

    private fun Exception.userMessage(fallback: String): String = when (this) {
        is ApiException -> message
        is IOException -> "$fallback Check ${api.serverUrl}."
        else -> message?.takeIf { it.isNotBlank() } ?: fallback
    }

    companion object {
        private const val NEW_DRAFT_KEY = "__new__"
        const val UNCONFIGURED_API_ORIGIN = "http://127.0.0.1"
    }
}

private fun currentLanguagePreference(): LanguagePreference =
    LanguagePreference.fromLanguageTags(AppCompatDelegate.getApplicationLocales().toLanguageTags())

internal fun isCurrentThreadLoad(selectedThreadId: String?, loadedThreadId: String): Boolean =
    selectedThreadId == loadedThreadId
