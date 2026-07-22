package com.deerflow.mobile.data

import org.json.JSONArray
import org.json.JSONObject

data class DeerFlowUser(
    val id: String,
    val email: String,
    val role: String,
    val needsSetup: Boolean,
)

data class SsoProvider(
    val id: String,
    val displayName: String,
)

data class ThreadSummary(
    val id: String,
    val title: String,
    val status: String,
    val updatedAt: String,
    val isPinned: Boolean = false,
)

enum class MessageRole {
    User,
    Assistant,
    Tool,
    System,
}

sealed interface MessageBlock {
    data class Markdown(val text: String) : MessageBlock
    data class Code(val language: String?, val code: String) : MessageBlock
    data class Quote(val text: String) : MessageBlock
    data class Reasoning(val text: String) : MessageBlock
    data class ToolCall(
        val name: String,
        val detail: String,
        val id: String = "",
    ) : MessageBlock
    data class ToolResult(
        val callId: String,
        val name: String,
        val detail: String,
        val failed: Boolean = false,
    ) : MessageBlock
    enum class SubtaskStatus { InProgress, Completed, Failed }
    data class Subtask(
        val callId: String,
        val subagentType: String,
        val description: String,
        val prompt: String,
        val status: SubtaskStatus = SubtaskStatus.InProgress,
        val result: String? = null,
        val error: String? = null,
        val modelName: String? = null,
    ) : MessageBlock
    data class HumanInput(
        val request: HumanInputRequest,
    ) : MessageBlock
    data class Approval(
        val request: HumanInputRequest,
    ) : MessageBlock
    data class HumanInputResponseBlock(
        val response: HumanInputResponse,
    ) : MessageBlock
    data class Todo(
        val title: String,
        val completed: Boolean,
        val status: String = if (completed) "completed" else "pending",
    ) : MessageBlock
    data class Artifact(val title: String, val path: String) : MessageBlock
    data class Error(val message: String) : MessageBlock
}

data class HumanInputOption(
    val id: String,
    val label: String,
    val value: String,
)

data class HumanInputRequest(
    val source: String,
    val requestId: String,
    val toolCallId: String?,
    val title: String?,
    val clarificationType: String? = null,
    val question: String,
    val context: String?,
    val inputMode: String,
    val options: List<HumanInputOption>,
)

data class HumanInputResponse(
    val source: String,
    val requestId: String,
    val responseKind: String,
    val value: String,
    val optionId: String? = null,
)

data class MessageAttachment(
    val filename: String,
    val size: Long,
    val path: String?,
    val status: AttachmentStatus = AttachmentStatus.Uploaded,
)

data class TokenUsage(
    val inputTokens: Long,
    val outputTokens: Long,
    val totalTokens: Long,
)

enum class AttachmentStatus { Pending, Uploading, Uploaded, Failed }

data class ChatMessage(
    val id: String,
    val role: MessageRole,
    val text: String,
    val isStreaming: Boolean = false,
    val blocks: List<MessageBlock> = parseMessageBlocks(text, role),
    val attachments: List<MessageAttachment> = emptyList(),
    val hiddenFromUi: Boolean = false,
    val tokenUsage: TokenUsage? = null,
) {
    fun withText(value: String, streaming: Boolean = isStreaming) = copy(
        text = value,
        isStreaming = streaming,
        blocks = parseMessageBlocks(value, role) + blocks.filter { it.isStructuredBlock() },
    )
}

private fun MessageBlock.isStructuredBlock(): Boolean = when (this) {
    is MessageBlock.Markdown, is MessageBlock.Code, is MessageBlock.Quote -> false
    else -> true
}

data class ThreadSnapshot(
    val title: String,
    val messages: List<ChatMessage>,
    val hasMessages: Boolean = true,
    val todos: List<TodoItem> = emptyList(),
    val artifacts: List<String> = emptyList(),
    val hasTitle: Boolean = true,
    val hasTodos: Boolean = false,
    val hasArtifacts: Boolean = false,
)

data class TodoItem(
    val content: String,
    val status: String,
)

enum class RunMode {
    Flash,
    Thinking,
    Pro,
    Ultra;

    val thinkingEnabled: Boolean get() = this != Flash
    val planMode: Boolean get() = this == Pro || this == Ultra
    val subagentEnabled: Boolean get() = this == Ultra
    val reasoningEffort: String get() = when (this) {
        Flash -> "minimal"
        Thinking -> "low"
        Pro -> "medium"
        Ultra -> "high"
    }
}

data class RunOptions(
    val assistantId: String = "lead_agent",
    val modelName: String? = null,
    val mode: RunMode = RunMode.Thinking,
    val enabledSkills: Set<String> = emptySet(),
    val reasoningEffortEnabled: Boolean = true,
)

enum class RunStatus { Idle, Connecting, Streaming, Reconnecting, Stopping, Failed }

data class RunState(
    val status: RunStatus = RunStatus.Idle,
    val runId: String? = null,
    val lastEventId: String? = null,
    val reconnectAttempt: Int = 0,
) {
    val active: Boolean get() = status in setOf(RunStatus.Connecting, RunStatus.Streaming, RunStatus.Reconnecting, RunStatus.Stopping)
}

data class PendingAttachment(
    val uri: String,
    val filename: String,
    val mimeType: String,
    val size: Long,
    val status: AttachmentStatus = AttachmentStatus.Pending,
    val error: String? = null,
)

data class ComposerState(
    val text: String = "",
    val attachments: List<PendingAttachment> = emptyList(),
    val options: RunOptions = RunOptions(),
    val uploading: Boolean = false,
)

data class ModelInfo(
    val name: String,
    val displayName: String,
    val description: String,
    val supportsThinking: Boolean,
    val supportsReasoningEffort: Boolean,
)

data class AgentInfo(
    val name: String,
    val description: String,
    val model: String?,
    val skills: List<String>,
    val soul: String = "",
)

data class AgentRunInfo(
    val runId: String,
    val threadId: String,
    val threadTitle: String?,
    val assistantId: String?,
    val status: String,
    val modelName: String?,
    val createdAt: String?,
    val updatedAt: String?,
    val durationSeconds: Double?,
    val totalTokens: Int,
    val messageCount: Int,
    val cost: Double?,
    val error: String?,
)

data class SkillInfo(
    val name: String,
    val description: String,
    val category: String,
    val enabled: Boolean,
)

data class McpServerInfo(
    val name: String,
    val description: String,
    val transport: String,
    val enabled: Boolean,
    val toolOverrides: List<String>,
)

data class McpConfig(
    val servers: List<McpServerInfo>,
    // The masked Gateway response is retained so toggles preserve unknown fields and secrets.
    val rawJson: String,
)

data class McpToolInfo(
    val serverName: String,
    val name: String,
    val description: String,
)

data class ChannelCredentialField(
    val name: String,
    val label: String,
    val type: String,
    val required: Boolean,
)

data class ChannelProviderInfo(
    val provider: String,
    val displayName: String,
    val enabled: Boolean,
    val configured: Boolean,
    val connectable: Boolean,
    val unavailableReason: String?,
    val authMode: String,
    val connectionStatus: String,
    val credentialFields: List<ChannelCredentialField>,
    val credentialValues: Map<String, String>,
)

data class ChannelProviders(
    val enabled: Boolean,
    val providers: List<ChannelProviderInfo>,
)

data class ChannelConnectResult(
    val provider: String,
    val mode: String,
    val url: String?,
    val code: String,
    val instruction: String,
    val expiresInSeconds: Int,
)

data class ScheduledTaskInfo(
    val id: String,
    val title: String,
    val prompt: String,
    val scheduleType: String,
    val scheduleLabel: String,
    val timezone: String,
    val status: String,
    val nextRunAt: String?,
    val lastError: String?,
    val runCount: Int,
)

data class ScheduledTaskRunInfo(
    val id: String,
    val taskId: String,
    val threadId: String,
    val runId: String?,
    val scheduledFor: String,
    val trigger: String,
    val status: String,
    val error: String?,
    val startedAt: String?,
    val finishedAt: String?,
    val createdAt: String,
)

data class WorkspaceCapabilities(
    val models: List<ModelInfo> = emptyList(),
    val agents: List<AgentInfo> = emptyList(),
    val skills: List<SkillInfo> = emptyList(),
    val agentsEnabled: Boolean = false,
) {
    fun selectedModel(modelName: String?): ModelInfo? =
        models.firstOrNull { it.name == modelName } ?: models.firstOrNull()

    fun availableRunModes(modelName: String?): List<RunMode> {
        val model = selectedModel(modelName) ?: return RunMode.entries
        return if (model.supportsThinking) RunMode.entries else listOf(RunMode.Flash)
    }

    fun supportsReasoningEffort(modelName: String?): Boolean =
        selectedModel(modelName)?.supportsReasoningEffort ?: true
}

data class UploadedFileInfo(
    val filename: String,
    val size: Long,
    val virtualPath: String,
)

data class GatewayRunInfo(
    val runId: String,
    val status: String,
)

data class ArtifactPayload(
    val filename: String,
    val mimeType: String,
    val bytes: ByteArray,
)

data class RegeneratePreparation(
    val inputJson: String,
    val checkpointJson: String,
    val metadataJson: String,
    val targetRunId: String,
)

data class ThreadBranchResult(
    val threadId: String,
    val parentThreadId: String,
    val parentCheckpointId: String,
    val branchedFromMessageId: String,
    val workspaceCloneMode: String,
)

sealed interface StreamUpdate {
    data class Started(val runId: String?) : StreamUpdate
    data class EventId(val value: String) : StreamUpdate
    data class Reconnecting(val attempt: Int) : StreamUpdate
    data class MessageChunk(val value: ChatMessage) : StreamUpdate
    data class Snapshot(val value: ThreadSnapshot) : StreamUpdate
    data class Failure(val message: String) : StreamUpdate
    data object Finished : StreamUpdate
}

internal fun JSONObject.toThreadSummary(): ThreadSummary {
    val values = optJSONObject("values")
    val metadata = optJSONObject("metadata")
    val title = values?.optString("title")
        ?.takeIf { it.isNotBlank() }
        ?: metadata?.optString("title")?.takeIf { it.isNotBlank() }
        ?: "New conversation"
    return ThreadSummary(
        id = getString("thread_id"),
        title = stripUploadedFilesTag(title).ifBlank { "New conversation" },
        status = optString("status", "idle"),
        updatedAt = optString("updated_at"),
    )
}

internal fun JSONObject.toThreadSnapshot(): ThreadSnapshot {
    val values = optJSONObject("values") ?: this
    val rawMessages = values.optJSONArray("messages") ?: JSONArray()
    val todos = values.optJSONArray("todos")?.let { rawTodos ->
        buildList {
            for (index in 0 until rawTodos.length()) {
                val todo = rawTodos.optJSONObject(index) ?: continue
                val content = todo.optString("content").trim()
                if (content.isNotBlank()) add(TodoItem(content, todo.optString("status", "pending")))
            }
        }
    }.orEmpty()
    val artifacts = values.optJSONArray("artifacts")?.let { rawArtifacts ->
        buildList {
            for (index in 0 until rawArtifacts.length()) {
                when (val value = rawArtifacts.opt(index)) {
                    is String -> value.takeIf { it.isNotBlank() }?.let(::add)
                    is JSONObject -> value.optString("path").takeIf { it.isNotBlank() }?.let(::add)
                }
            }
        }
    }.orEmpty()
    val messages = buildList {
        for (index in 0 until rawMessages.length()) {
            val message = rawMessages.optJSONObject(index)?.toChatMessage() ?: continue
            if (message.text.isNotBlank() || message.blocks.isNotEmpty() || message.attachments.isNotEmpty()) add(message)
        }
    }
    return ThreadSnapshot(
        title = stripUploadedFilesTag(values.optString("title")).ifBlank { "New conversation" },
        messages = messages,
        hasMessages = values.has("messages"),
        todos = todos,
        artifacts = artifacts,
        hasTitle = values.has("title"),
        hasTodos = values.has("todos"),
        hasArtifacts = values.has("artifacts"),
    )
}

internal fun JSONObject.toChatMessage(): ChatMessage? {
    val additional = optJSONObject("additional_kwargs")
    val hiddenFromUi = additional?.optBoolean("hide_from_ui") == true
    val humanInputResponse = additional?.optJSONObject("human_input_response")?.toHumanInputResponse()
    if (hiddenFromUi && humanInputResponse == null) return null
    val rawRole = optString("type").ifBlank { optString("role") }
    val role = when (rawRole.lowercase().replace("_", "").replace("-", "")) {
        "human", "user" -> MessageRole.User
        "ai", "assistant", "aimessage", "aimessagechunk" -> MessageRole.Assistant
        "tool", "toolmessage" -> MessageRole.Tool
        "system", "systemmessage" -> MessageRole.System
        else -> return null
    }
    val rawText = extractText(opt("content"))
    val text = if (role == MessageRole.User) stripUploadedFilesTag(rawText) else rawText
    val attachments = additional?.optJSONArray("files").toMessageAttachments()
    val tokenUsage = optJSONObject("usage_metadata")?.toTokenUsage()
    val blocks = buildList {
        if (role != MessageRole.Tool) addAll(parseMessageBlocks(text, role))
        extractReasoning(opt("content"), additional)?.let { add(MessageBlock.Reasoning(it)) }
        val calls = optJSONArray("tool_calls") ?: additional?.optJSONArray("tool_calls")
        calls?.let {
            for (index in 0 until calls.length()) {
                val call = calls.optJSONObject(index) ?: continue
                val function = call.optJSONObject("function")
                val name = function?.optString("name").orEmpty().ifBlank { call.optString("name", "Tool") }
                val detail = jsonDetail(function?.opt("arguments") ?: call.opt("args"))
                add(
                    MessageBlock.ToolCall(
                        name = name,
                        detail = detail,
                        id = call.optString("id"),
                    ),
                )
                if (name == "task") {
                    val arguments = parseJsonObject(detail)
                    add(
                        MessageBlock.Subtask(
                            callId = call.optString("id"),
                            subagentType = arguments?.optString("subagent_type").orEmpty(),
                            description = arguments?.optString("description").orEmpty()
                                .ifBlank { arguments?.optString("prompt").orEmpty().lineSequence().firstOrNull().orEmpty() }
                                .ifBlank { "Subtask" },
                            prompt = arguments?.optString("prompt").orEmpty(),
                        ),
                    )
                }
                if (name == "write_todos") {
                    val todoItems = parseJsonObject(detail)?.optJSONArray("todos")
                    if (todoItems != null) {
                        for (todoIndex in 0 until todoItems.length()) {
                            val todo = todoItems.optJSONObject(todoIndex) ?: continue
                            val title = todo.optString("content").trim()
                            if (title.isNotBlank()) {
                                val status = todo.optString("status", "pending")
                                add(MessageBlock.Todo(title, status == "completed", status))
                            }
                        }
                    }
                }
                if (name == "present_files") {
                    val filepaths = parseJsonObject(detail)?.optJSONArray("filepaths")
                    if (filepaths != null) {
                        for (fileIndex in 0 until filepaths.length()) {
                            val path = filepaths.optString(fileIndex).takeIf { it.isNotBlank() } ?: continue
                            add(MessageBlock.Artifact(path.substringAfterLast('/'), path))
                        }
                    }
                }
            }
        }
        if (role == MessageRole.Tool) {
            add(
                MessageBlock.ToolResult(
                    callId = optString("tool_call_id"),
                    name = optString("name").ifBlank { "Tool" },
                    detail = text,
                    failed = optString("status").equals("error", ignoreCase = true),
                ),
            )
            if (optString("name") == "task" || additional?.has("subagent_status") == true) {
                val rawStatus = additional?.optString("subagent_status").orEmpty()
                val subtaskStatus = when {
                    rawStatus == "completed" -> MessageBlock.SubtaskStatus.Completed
                    rawStatus.isNotBlank() || optString("status").equals("error", ignoreCase = true) -> MessageBlock.SubtaskStatus.Failed
                    else -> MessageBlock.SubtaskStatus.InProgress
                }
                add(
                    MessageBlock.Subtask(
                        callId = optString("tool_call_id"),
                        subagentType = additional?.optString("subagent_type").orEmpty(),
                        description = additional?.optString("subagent_description").orEmpty().ifBlank { "Subtask" },
                        prompt = additional?.optString("subagent_prompt").orEmpty(),
                        status = subtaskStatus,
                        result = additional?.optString("subagent_result_brief")?.takeIf { it.isNotBlank() }
                            ?: text.takeIf { subtaskStatus == MessageBlock.SubtaskStatus.Completed },
                        error = additional?.optString("subagent_error")?.takeIf { it.isNotBlank() }
                            ?: text.takeIf { subtaskStatus == MessageBlock.SubtaskStatus.Failed },
                        modelName = additional?.optString("subagent_model_name")?.takeIf { it.isNotBlank() },
                    ),
                )
            }
            optJSONObject("artifact")
                ?.optJSONObject("human_input")
                ?.toHumanInputRequest()
                ?.let { request ->
                    if (request.clarificationType in APPROVAL_CLARIFICATION_TYPES) {
                        add(MessageBlock.Approval(request))
                    } else {
                        add(MessageBlock.HumanInput(request))
                    }
                }
        }
        humanInputResponse?.let { add(MessageBlock.HumanInputResponseBlock(it)) }
    }
    return ChatMessage(
        id = optString("id").ifBlank {
            optString("tool_call_id").ifBlank { "${role.name.lowercase()}-${text.hashCode()}" }
        },
        role = role,
        text = text,
        blocks = blocks,
        attachments = attachments,
        hiddenFromUi = hiddenFromUi,
        tokenUsage = tokenUsage,
    )
}

internal fun stripUploadedFilesTag(content: String): String = content
    .replace(Regex("<uploaded_files>[\\s\\S]*?</uploaded_files>"), "")
    .replace(Regex("<slash_skill_activation>[\\s\\S]*?</slash_skill_activation>"), "")
    .trim()

private fun JSONObject.toTokenUsage(): TokenUsage? {
    val input = optLong("input_tokens", -1L)
    val output = optLong("output_tokens", -1L)
    val total = optLong("total_tokens", -1L)
    if (input < 0L && output < 0L && total < 0L) return null
    return TokenUsage(input.coerceAtLeast(0L), output.coerceAtLeast(0L), total.coerceAtLeast(0L))
}

private fun JSONObject.toHumanInputRequest(): HumanInputRequest? {
    if (optInt("version") != 1 || optString("kind") != "human_input_request") return null
    val source = optString("source")
    val requestId = optString("request_id")
    val question = optString("question")
    val inputMode = optString("input_mode")
    if (source.isBlank() || requestId.isBlank() || question.isBlank()) return null
    if (inputMode !in setOf("free_text", "single_choice", "choice_with_other")) return null
    val options = buildList {
        val raw = optJSONArray("options") ?: return@buildList
        for (index in 0 until raw.length()) {
            val option = raw.optJSONObject(index) ?: continue
            val id = option.optString("id")
            val label = option.optString("label")
            if (id.isNotBlank() && label.isNotBlank()) {
                add(HumanInputOption(id, label, option.optString("value", label)))
            }
        }
    }
    if (inputMode != "free_text" && options.isEmpty()) return null
    return HumanInputRequest(
        source = source,
        requestId = requestId,
        toolCallId = optString("tool_call_id").takeIf { it.isNotBlank() },
        title = optString("title").takeIf { it.isNotBlank() },
        clarificationType = optString("clarification_type").takeIf { it.isNotBlank() },
        question = question,
        context = if (has("context") && !isNull("context")) optString("context") else null,
        inputMode = inputMode,
        options = options,
    )
}

private val APPROVAL_CLARIFICATION_TYPES = setOf("risk_confirmation", "suggestion")

private fun JSONObject.toHumanInputResponse(): HumanInputResponse? {
    if (optInt("version") != 1 || optString("kind") != "human_input_response") return null
    val source = optString("source")
    val requestId = optString("request_id")
    val responseKind = optString("response_kind")
    val value = optString("value")
    if (source.isBlank() || requestId.isBlank() || value.isBlank()) return null
    if (responseKind !in setOf("option", "text")) return null
    val optionId = optString("option_id").takeIf { it.isNotBlank() }
    if (responseKind == "option" && optionId == null) return null
    return HumanInputResponse(source, requestId, responseKind, value, optionId)
}

internal fun extractText(value: Any?): String = when (value) {
    null, JSONObject.NULL -> ""
    is String -> value
    is JSONArray -> buildList {
        for (index in 0 until value.length()) {
            val text = extractText(value.opt(index))
            if (text.isNotBlank()) add(text)
        }
    }.joinToString("\n")
    is JSONObject -> when {
        value.has("text") -> value.optString("text")
        value.has("content") -> extractText(value.opt("content"))
        else -> ""
    }
    else -> value.toString()
}

private fun extractReasoning(content: Any?, additional: JSONObject?): String? {
    additional?.optString("reasoning_content")?.takeIf { it.isNotBlank() }?.let { return it }
    val parts = content as? JSONArray ?: return null
    return buildList {
        for (index in 0 until parts.length()) {
            val part = parts.optJSONObject(index) ?: continue
            if (part.optString("type") == "thinking") {
                part.optString("thinking").takeIf { it.isNotBlank() }?.let(::add)
            }
        }
    }.joinToString("\n").takeIf { it.isNotBlank() }
}

private fun jsonDetail(value: Any?): String = when (value) {
    null, JSONObject.NULL -> ""
    is JSONObject, is JSONArray -> value.toString()
    else -> value.toString()
}

private fun parseJsonObject(value: String): JSONObject? =
    runCatching { JSONObject(value) }.getOrNull()

internal fun parseMessageBlocks(text: String, role: MessageRole = MessageRole.Assistant): List<MessageBlock> {
    if (text.isBlank()) return emptyList()
    if (role == MessageRole.System && text.startsWith("Error:", ignoreCase = true)) {
        return listOf(MessageBlock.Error(text.substringAfter(':').trim()))
    }

    val result = mutableListOf<MessageBlock>()
    val codeFence = Regex("```([A-Za-z0-9_+.-]*)\\n([\\s\\S]*?)```")
    var cursor = 0
    for (match in codeFence.findAll(text)) {
        addTextBlocks(result, text.substring(cursor, match.range.first))
        result += MessageBlock.Code(match.groupValues[1].takeIf { it.isNotBlank() }, match.groupValues[2].trimEnd())
        cursor = match.range.last + 1
    }
    addTextBlocks(result, text.substring(cursor))
    return result.ifEmpty { listOf(MessageBlock.Markdown(text)) }
}

private fun addTextBlocks(target: MutableList<MessageBlock>, value: String) {
    val trimmed = value.trim()
    if (trimmed.isBlank()) return
    val quoteLines = trimmed.lines().takeIf { lines -> lines.all { it.startsWith(">") } }
    if (quoteLines != null) {
        target += MessageBlock.Quote(quoteLines.joinToString("\n") { it.removePrefix(">").trimStart() })
    } else {
        target += MessageBlock.Markdown(trimmed)
    }
}

private fun JSONArray?.toMessageAttachments(): List<MessageAttachment> = buildList {
    val source = this@toMessageAttachments ?: return@buildList
    for (index in 0 until source.length()) {
        val file = source.optJSONObject(index) ?: continue
        add(
            MessageAttachment(
                filename = file.optString("filename", "Attachment"),
                size = file.optLong("size"),
                path = file.optString("path").takeIf { it.isNotBlank() },
                status = when (file.optString("status")) {
                    "uploading" -> AttachmentStatus.Uploading
                    "failed" -> AttachmentStatus.Failed
                    else -> AttachmentStatus.Uploaded
                },
            ),
        )
    }
}
