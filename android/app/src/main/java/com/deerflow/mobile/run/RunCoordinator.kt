package com.deerflow.mobile.run

import android.content.Context
import com.deerflow.mobile.data.ApiException
import com.deerflow.mobile.data.ChatMessage
import com.deerflow.mobile.data.DeerFlowApi
import com.deerflow.mobile.data.HumanInputResponse
import com.deerflow.mobile.data.RegeneratePreparation
import com.deerflow.mobile.data.RunOptions
import com.deerflow.mobile.data.RunState
import com.deerflow.mobile.data.RunStatus
import com.deerflow.mobile.data.SettingsStore
import com.deerflow.mobile.data.StreamUpdate
import com.deerflow.mobile.data.ThreadSnapshot
import com.deerflow.mobile.data.TodoItem
import com.deerflow.mobile.data.UploadedFileInfo
import com.deerflow.mobile.data.WebViewSessionCookieStore
import com.deerflow.mobile.data.WorkspaceCache
import com.deerflow.mobile.data.mergeStreamChunk
import com.deerflow.mobile.data.mergeStreamSnapshot
import java.io.IOException
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

data class CoordinatedRunRequest(
    val serverUrl: String,
    val threadId: String,
    val title: String,
    val message: String,
    val options: RunOptions,
    val clientMessageId: String = java.util.UUID.randomUUID().toString(),
    val files: List<UploadedFileInfo> = emptyList(),
    val humanInputResponse: HumanInputResponse? = null,
    val regenerate: RegeneratePreparation? = null,
    val initialMessages: List<ChatMessage> = emptyList(),
    val initialTodos: List<TodoItem> = emptyList(),
    val initialArtifacts: List<String> = emptyList(),
    val failureMessages: List<ChatMessage>? = null,
)

data class CoordinatedRunState(
    val serverUrl: String,
    val threadId: String,
    val title: String,
    val run: RunState,
    val messages: List<ChatMessage>,
    val todos: List<TodoItem> = emptyList(),
    val artifacts: List<String> = emptyList(),
    val error: String? = null,
    val revision: Long = 0,
)

class RunCoordinator private constructor(context: Context) {
    private val appContext = context.applicationContext
    private val cache = WorkspaceCache(appContext)
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val operationMutex = Mutex()
    private val persistenceMutex = Mutex()
    private val mutableState = MutableStateFlow<CoordinatedRunState?>(null)

    val state: StateFlow<CoordinatedRunState?> = mutableState.asStateFlow()

    @Volatile private var activeApi: DeerFlowApi? = null
    @Volatile private var streamJob: Job? = null

    suspend fun start(request: CoordinatedRunRequest) = operationMutex.withLock {
        if (mutableState.value?.run?.active == true) return@withLock
        val initial = CoordinatedRunState(
            serverUrl = request.serverUrl,
            threadId = request.threadId,
            title = request.title,
            run = RunState(RunStatus.Connecting),
            messages = request.initialMessages,
            todos = request.initialTodos,
            artifacts = request.initialArtifacts,
        )
        mutableState.value = initial
        persist(initial)
        RunService.start(appContext, request.title, request.serverUrl, request.threadId)
        launchStream(request, resume = null)
    }

    suspend fun resume(
        serverUrl: String,
        threadId: String,
        title: String,
        saved: RunState,
    ): Boolean = operationMutex.withLock {
        val current = mutableState.value
        if (current?.serverUrl == serverUrl && current.threadId == threadId && current.run.active) {
            return@withLock true
        }

        val api = DeerFlowApi(serverUrl, WebViewSessionCookieStore())
        val resumable = resolveResumableRun(api, threadId, saved)
        if (resumable == null) {
            val snapshot = runCatching { api.threadState(threadId) }.getOrNull()
            cache.saveRun(serverUrl, threadId, RunState())
            snapshot?.let {
                cache.saveMessages(serverUrl, threadId, it.messages)
                mutableState.value = CoordinatedRunState(
                    serverUrl = serverUrl,
                    threadId = threadId,
                    title = it.title,
                    run = RunState(),
                    messages = it.messages,
                    todos = it.todos,
                    artifacts = it.artifacts,
                )
            }
            return@withLock false
        }

        val request = CoordinatedRunRequest(
            serverUrl = serverUrl,
            threadId = threadId,
            title = title,
            message = "",
            options = RunOptions(),
            initialMessages = cache.loadMessages(serverUrl, threadId),
        )
        val reconnecting = CoordinatedRunState(
            serverUrl = serverUrl,
            threadId = threadId,
            title = title,
            run = resumable.copy(status = RunStatus.Reconnecting),
            messages = request.initialMessages,
        )
        mutableState.value = reconnecting
        persist(reconnecting)
        RunService.start(appContext, title, serverUrl, threadId)
        launchStream(request, resumable)
        true
    }

    suspend fun recoverLatest(serverUrlOverride: String? = null): Boolean {
        val serverUrl = serverUrlOverride ?: SettingsStore(appContext).read().serverUrl
        val recoverable = cache.loadLatestActiveRun(serverUrl) ?: return false
        return resume(serverUrl, recoverable.threadId, recoverable.title, recoverable.run)
    }

    suspend fun cancelActive(): ThreadSnapshot? = operationMutex.withLock {
        val current = mutableState.value ?: return@withLock null
        if (!current.run.active) return@withLock null
        mutableState.value = current.copy(
            run = current.run.copy(status = RunStatus.Stopping),
            revision = current.revision + 1,
        )

        val api = activeApi ?: DeerFlowApi(current.serverUrl, WebViewSessionCookieStore())
        api.cancelActiveStream()
        streamJob?.cancelAndJoin()
        current.run.runId?.let { runId -> runCatching { api.cancelRun(current.threadId, runId) } }
        val snapshot = runCatching { api.threadState(current.threadId) }.getOrNull()
        val stopped = current.copy(
            title = snapshot?.title ?: current.title,
            run = RunState(),
            messages = snapshot?.messages ?: current.messages.map { it.copy(isStreaming = false) },
            todos = snapshot?.todos ?: current.todos,
            artifacts = snapshot?.artifacts ?: current.artifacts,
            revision = current.revision + 2,
        )
        mutableState.value = stopped
        persist(stopped, clearRun = true)
        activeApi = null
        streamJob = null
        RunService.stop(appContext)
        snapshot
    }

    fun abandonActive() {
        val current = mutableState.value
        activeApi?.cancelActiveStream()
        streamJob?.cancel()
        activeApi = null
        streamJob = null
        mutableState.value = null
        if (current != null) {
            scope.launch {
                persistenceMutex.withLock {
                    val replacement = mutableState.value
                    val sameRunRestarted = replacement?.serverUrl == current.serverUrl &&
                        replacement.threadId == current.threadId && replacement.run.active
                    if (!sameRunRestarted) {
                        cache.saveRun(current.serverUrl, current.threadId, RunState())
                    }
                }
            }
        }
        RunService.stop(appContext)
    }

    fun isActive(serverUrl: String, threadId: String): Boolean =
        mutableState.value?.let { it.serverUrl == serverUrl && it.threadId == threadId && it.run.active } == true

    private fun launchStream(request: CoordinatedRunRequest, resume: RunState?) {
        val api = DeerFlowApi(request.serverUrl, WebViewSessionCookieStore())
        activeApi = api
        streamJob = scope.launch {
            val owningJob = coroutineContext[Job]
            try {
                RunService.update(
                    appContext,
                    if (resume == null) RunProgress.Connecting else RunProgress.Reconnecting,
                    request.title,
                )
                api.streamMessage(
                    threadId = request.threadId,
                    message = request.message,
                    options = request.options,
                    clientMessageId = request.clientMessageId,
                    files = request.files,
                    resume = resume,
                    humanInputResponse = request.humanInputResponse,
                    regenerate = request.regenerate,
                    onUpdate = { update -> applyStreamUpdate(request, update) },
                )
                val previous = mutableState.value ?: return@launch
                if (previous.serverUrl != request.serverUrl || previous.threadId != request.threadId) return@launch
                if (previous.run.status == RunStatus.Failed) {
                    persist(previous)
                    return@launch
                }
                val snapshot = api.threadState(request.threadId)
                val completed = previous.copy(
                    title = snapshot.title,
                    run = RunState(),
                    messages = snapshot.messages,
                    todos = snapshot.todos,
                    artifacts = snapshot.artifacts,
                    revision = previous.revision + 1,
                )
                persistAndPublish(completed, clearRun = true)
                RunService.complete(appContext, completed.title)
            } catch (_: CancellationException) {
                // Explicit stop or server change owns the visible terminal state.
            } catch (error: Exception) {
                val previous = mutableState.value ?: return@launch
                if (previous.serverUrl != request.serverUrl || previous.threadId != request.threadId) return@launch
                if (resume != null && error.isTerminalResumeError()) {
                    val snapshot = runCatching { api.threadState(request.threadId) }.getOrNull()
                    if (snapshot != null) {
                        val completed = previous.copy(
                            title = snapshot.title,
                            run = RunState(),
                            messages = snapshot.messages,
                            todos = snapshot.todos,
                            artifacts = snapshot.artifacts,
                            revision = previous.revision + 1,
                        )
                        persistAndPublish(completed, clearRun = true)
                        RunService.complete(appContext, completed.title)
                        return@launch
                    }
                }
                val message = error.userMessage(request.serverUrl, "The run stopped unexpectedly.")
                val failed = previous.copy(
                    run = RunState(RunStatus.Failed),
                    messages = request.failureMessages ?: previous.messages,
                    error = message,
                    revision = previous.revision + 1,
                )
                persistAndPublish(failed)
                RunService.fail(appContext, message, failed.title)
            } finally {
                if (streamJob === owningJob) streamJob = null
                if (activeApi === api) activeApi = null
            }
        }
    }

    private fun applyStreamUpdate(request: CoordinatedRunRequest, update: StreamUpdate) {
        val current = mutableState.value ?: return
        if (current.serverUrl != request.serverUrl || current.threadId != request.threadId) return
        val next = reduceRunState(current, update)
        // launchStream publishes Idle after the final snapshot and Room cleanup commit together.
        val deferSuccessfulFinish = update == StreamUpdate.Finished && current.run.status != RunStatus.Failed
        if (!deferSuccessfulFinish) {
            mutableState.value = next
            scope.launch { persist(next) }
        }

        when (update) {
            is StreamUpdate.Started -> RunService.update(appContext, runProgressUpdate(RunProgress.Working, next.todos), next.title)
            is StreamUpdate.Reconnecting -> RunService.update(appContext, runProgressUpdate(RunProgress.Reconnecting, next.todos), next.title)
            is StreamUpdate.MessageChunk -> RunService.update(appContext, runProgressUpdate(RunProgress.Responding, next.todos), next.title)
            is StreamUpdate.Snapshot -> RunService.update(appContext, runProgressUpdate(RunProgress.Working, next.todos), next.title)
            StreamUpdate.Finished -> Unit
            is StreamUpdate.Failure -> RunService.fail(appContext, update.message, next.title)
            is StreamUpdate.EventId -> Unit
        }
    }

    private suspend fun resolveResumableRun(api: DeerFlowApi, threadId: String, saved: RunState): RunState? {
        return resumableRun(saved, api.latestActiveRun(threadId)?.runId)
    }

    private suspend fun persist(state: CoordinatedRunState, clearRun: Boolean = false) {
        persistenceMutex.withLock {
            val latest = mutableState.value
            if (!clearRun && latest != null && latest.revision > state.revision) return
            cache.saveRun(state.serverUrl, state.threadId, if (clearRun) RunState() else state.run)
            cache.saveMessages(state.serverUrl, state.threadId, state.messages)
        }
    }

    private suspend fun persistAndPublish(state: CoordinatedRunState, clearRun: Boolean = false) {
        persistenceMutex.withLock {
            val latest = mutableState.value ?: return
            if (
                latest.serverUrl != state.serverUrl ||
                latest.threadId != state.threadId ||
                latest.revision > state.revision
            ) return
            cache.saveRun(state.serverUrl, state.threadId, if (clearRun) RunState() else state.run)
            cache.saveMessages(state.serverUrl, state.threadId, state.messages)
            mutableState.value = state
        }
    }

    private fun Exception.userMessage(serverUrl: String, fallback: String): String = when (this) {
        is ApiException -> message
        is IOException -> "$fallback Check $serverUrl."
        else -> message?.takeIf { it.isNotBlank() } ?: fallback
    }

    companion object {
        @Volatile private var instance: RunCoordinator? = null

        fun get(context: Context): RunCoordinator = instance ?: synchronized(this) {
            instance ?: RunCoordinator(context).also { instance = it }
        }
    }
}

internal fun resumableRun(saved: RunState, activeRunId: String?): RunState? = when {
    !activeRunId.isNullOrBlank() -> saved.copy(
        runId = activeRunId,
        lastEventId = saved.lastEventId.takeIf { saved.runId == activeRunId },
    )
    saved.active && !saved.runId.isNullOrBlank() -> saved
    else -> null
}

private fun Exception.isTerminalResumeError(): Boolean =
    this is ApiException && statusCode in setOf(404, 409)

internal fun reduceRunState(current: CoordinatedRunState, update: StreamUpdate): CoordinatedRunState {
    val revision = current.revision + 1
    return when (update) {
        is StreamUpdate.Started -> current.copy(
            run = current.run.copy(status = RunStatus.Streaming, runId = update.runId ?: current.run.runId),
            revision = revision,
        )
        is StreamUpdate.EventId -> current.copy(
            run = current.run.copy(lastEventId = update.value),
            revision = revision,
        )
        is StreamUpdate.Reconnecting -> current.copy(
            run = current.run.copy(status = RunStatus.Reconnecting, reconnectAttempt = update.attempt),
            revision = revision,
        )
        is StreamUpdate.MessageChunk -> current.copy(
            run = current.run.copy(status = RunStatus.Streaming),
            messages = mergeStreamChunk(current.messages, update.value),
            revision = revision,
        )
        is StreamUpdate.Snapshot -> current.copy(
            title = if (update.value.hasTitle) update.value.title else current.title,
            messages = mergeStreamSnapshot(current.messages, update.value),
            todos = if (update.value.hasTodos) update.value.todos else current.todos,
            artifacts = if (update.value.hasArtifacts) update.value.artifacts else current.artifacts,
            revision = revision,
        )
        is StreamUpdate.Failure -> current.copy(
            run = RunState(RunStatus.Failed),
            error = update.message,
            revision = revision,
        )
        StreamUpdate.Finished -> current.copy(
            run = if (current.run.status == RunStatus.Failed) current.run else RunState(),
            messages = current.messages.map { it.copy(isStreaming = false) },
            revision = revision,
        )
    }
}
