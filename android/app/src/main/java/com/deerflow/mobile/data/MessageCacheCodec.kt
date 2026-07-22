package com.deerflow.mobile.data

import org.json.JSONArray
import org.json.JSONObject

private const val MESSAGE_CACHE_VERSION = 1

internal fun encodeCachedChatMessage(message: ChatMessage): String = JSONObject().apply {
    put("version", MESSAGE_CACHE_VERSION)
    put("id", message.id)
    put("role", message.role.name)
    put("text", message.text)
    put("isStreaming", message.isStreaming)
    put("hiddenFromUi", message.hiddenFromUi)
    put("tokenUsage", message.tokenUsage?.toCacheJson() ?: JSONObject.NULL)
    put("blocks", JSONArray().apply { message.blocks.forEach { put(it.toCacheJson()) } })
    put("attachments", JSONArray().apply { message.attachments.forEach { put(it.toCacheJson()) } })
}.toString()

internal fun decodeCachedChatMessage(payload: String): ChatMessage? = runCatching {
    val json = JSONObject(payload)
    if (json.getInt("version") != MESSAGE_CACHE_VERSION) return null
    ChatMessage(
        id = json.getString("id"),
        role = MessageRole.valueOf(json.getString("role")),
        text = json.getString("text"),
        isStreaming = json.getBoolean("isStreaming"),
        blocks = json.getJSONArray("blocks").toMessageBlocks() ?: return null,
        attachments = json.getJSONArray("attachments").toMessageAttachments() ?: return null,
        hiddenFromUi = json.getBoolean("hiddenFromUi"),
        tokenUsage = json.optJSONObject("tokenUsage")?.toTokenUsage(),
    )
}.getOrNull()

private fun MessageBlock.toCacheJson(): JSONObject = JSONObject().apply {
    when (val block = this@toCacheJson) {
        is MessageBlock.Markdown -> {
            put("type", "markdown")
            put("text", block.text)
        }
        is MessageBlock.Code -> {
            put("type", "code")
            putNullable("language", block.language)
            put("code", block.code)
        }
        is MessageBlock.Quote -> {
            put("type", "quote")
            put("text", block.text)
        }
        is MessageBlock.Reasoning -> {
            put("type", "reasoning")
            put("text", block.text)
        }
        is MessageBlock.ToolCall -> {
            put("type", "tool_call")
            put("name", block.name)
            put("detail", block.detail)
            put("id", block.id)
        }
        is MessageBlock.ToolResult -> {
            put("type", "tool_result")
            put("callId", block.callId)
            put("name", block.name)
            put("detail", block.detail)
            put("failed", block.failed)
        }
        is MessageBlock.Subtask -> {
            put("type", "subtask")
            put("callId", block.callId)
            put("subagentType", block.subagentType)
            put("description", block.description)
            put("prompt", block.prompt)
            put("status", block.status.name)
            putNullable("result", block.result)
            putNullable("error", block.error)
            putNullable("modelName", block.modelName)
        }
        is MessageBlock.HumanInput -> {
            put("type", "human_input")
            put("request", block.request.toCacheJson())
        }
        is MessageBlock.Approval -> {
            put("type", "approval")
            put("request", block.request.toCacheJson())
        }
        is MessageBlock.HumanInputResponseBlock -> {
            put("type", "human_input_response")
            put("response", block.response.toCacheJson())
        }
        is MessageBlock.Todo -> {
            put("type", "todo")
            put("title", block.title)
            put("completed", block.completed)
            put("status", block.status)
        }
        is MessageBlock.Artifact -> {
            put("type", "artifact")
            put("title", block.title)
            put("path", block.path)
        }
        is MessageBlock.Error -> {
            put("type", "error")
            put("message", block.message)
        }
    }
}

private fun JSONObject.toMessageBlock(): MessageBlock? = runCatching {
    when (getString("type")) {
        "markdown" -> MessageBlock.Markdown(getString("text"))
        "code" -> MessageBlock.Code(nullableString("language"), getString("code"))
        "quote" -> MessageBlock.Quote(getString("text"))
        "reasoning" -> MessageBlock.Reasoning(getString("text"))
        "tool_call" -> MessageBlock.ToolCall(getString("name"), getString("detail"), getString("id"))
        "tool_result" -> MessageBlock.ToolResult(
            getString("callId"),
            getString("name"),
            getString("detail"),
            getBoolean("failed"),
        )
        "subtask" -> MessageBlock.Subtask(
            callId = getString("callId"),
            subagentType = getString("subagentType"),
            description = getString("description"),
            prompt = getString("prompt"),
            status = MessageBlock.SubtaskStatus.valueOf(getString("status")),
            result = nullableString("result"),
            error = nullableString("error"),
            modelName = nullableString("modelName"),
        )
        "human_input" -> MessageBlock.HumanInput(getJSONObject("request").toHumanInputRequest())
        "approval" -> MessageBlock.Approval(getJSONObject("request").toHumanInputRequest())
        "human_input_response" -> MessageBlock.HumanInputResponseBlock(
            getJSONObject("response").toHumanInputResponse(),
        )
        "todo" -> MessageBlock.Todo(getString("title"), getBoolean("completed"), getString("status"))
        "artifact" -> MessageBlock.Artifact(getString("title"), getString("path"))
        "error" -> MessageBlock.Error(getString("message"))
        else -> return null
    }
}.getOrNull()

private fun JSONArray.toMessageBlocks(): List<MessageBlock>? = buildList {
    for (index in 0 until length()) {
        add(getJSONObject(index).toMessageBlock() ?: return null)
    }
}

private fun MessageAttachment.toCacheJson(): JSONObject = JSONObject().apply {
    put("filename", filename)
    put("size", size)
    putNullable("path", path)
    put("status", status.name)
}

private fun JSONArray.toMessageAttachments(): List<MessageAttachment>? = buildList {
    for (index in 0 until length()) {
        val json = getJSONObject(index)
        add(
            MessageAttachment(
                filename = json.getString("filename"),
                size = json.getLong("size"),
                path = json.nullableString("path"),
                status = AttachmentStatus.valueOf(json.getString("status")),
            ),
        )
    }
}

private fun TokenUsage.toCacheJson(): JSONObject = JSONObject().apply {
    put("inputTokens", inputTokens)
    put("outputTokens", outputTokens)
    put("totalTokens", totalTokens)
}

private fun JSONObject.toTokenUsage(): TokenUsage = TokenUsage(
    inputTokens = getLong("inputTokens"),
    outputTokens = getLong("outputTokens"),
    totalTokens = getLong("totalTokens"),
)

private fun HumanInputRequest.toCacheJson(): JSONObject = JSONObject().apply {
    put("source", source)
    put("requestId", requestId)
    putNullable("toolCallId", toolCallId)
    putNullable("title", title)
    putNullable("clarificationType", clarificationType)
    put("question", question)
    putNullable("context", context)
    put("inputMode", inputMode)
    put(
        "options",
        JSONArray().apply {
            options.forEach { option ->
                put(
                    JSONObject().apply {
                        put("id", option.id)
                        put("label", option.label)
                        put("value", option.value)
                    },
                )
            }
        },
    )
}

private fun JSONObject.toHumanInputRequest(): HumanInputRequest = HumanInputRequest(
    source = getString("source"),
    requestId = getString("requestId"),
    toolCallId = nullableString("toolCallId"),
    title = nullableString("title"),
    clarificationType = nullableString("clarificationType"),
    question = getString("question"),
    context = nullableString("context"),
    inputMode = getString("inputMode"),
    options = getJSONArray("options").let { raw ->
        buildList {
            for (index in 0 until raw.length()) {
                val option = raw.getJSONObject(index)
                add(
                    HumanInputOption(
                        id = option.getString("id"),
                        label = option.getString("label"),
                        value = option.getString("value"),
                    ),
                )
            }
        }
    },
)

private fun HumanInputResponse.toCacheJson(): JSONObject = JSONObject().apply {
    put("source", source)
    put("requestId", requestId)
    put("responseKind", responseKind)
    put("value", value)
    putNullable("optionId", optionId)
}

private fun JSONObject.toHumanInputResponse(): HumanInputResponse = HumanInputResponse(
    source = getString("source"),
    requestId = getString("requestId"),
    responseKind = getString("responseKind"),
    value = getString("value"),
    optionId = nullableString("optionId"),
)

private fun JSONObject.putNullable(name: String, value: String?) {
    put(name, value ?: JSONObject.NULL)
}

private fun JSONObject.nullableString(name: String): String? =
    if (!has(name) || isNull(name)) null else getString(name)
