package com.deerflow.mobile.data

internal fun mergeStreamChunk(messages: List<ChatMessage>, chunk: ChatMessage): List<ChatMessage> {
    val index = messages.indexOfLast { it.id == chunk.id }
    val streamingChunk = chunk.copy(isStreaming = chunk.role == MessageRole.Assistant)
    if (index < 0) return messages + streamingChunk

    val existing = messages[index]
    val mergedText = if (chunk.role == MessageRole.Assistant) {
        existing.text + chunk.text
    } else {
        chunk.text.ifBlank { existing.text }
    }
    val textMerged = existing.withText(mergedText, streaming = streamingChunk.isStreaming)
    val merged = textMerged.copy(
        blocks = mergeStructuredBlocks(textMerged.blocks, chunk.blocks),
        attachments = (existing.attachments + chunk.attachments).distinctBy { it.path ?: it.filename },
        hiddenFromUi = existing.hiddenFromUi || chunk.hiddenFromUi,
    )
    return messages.toMutableList().also { it[index] = merged }
}

internal fun mergeStreamSnapshot(current: List<ChatMessage>, snapshot: ThreadSnapshot): List<ChatMessage> {
    if (!snapshot.hasMessages) return current
    val activeById = current.filter { it.isStreaming }.associateBy { it.id }
    val merged = snapshot.messages.map { message ->
        val active = activeById[message.id] ?: return@map message
        if (active.text.length > message.text.length && active.text.startsWith(message.text)) {
            message.copy(
                text = active.text,
                blocks = mergeStructuredBlocks(message.withText(active.text).blocks, active.blocks),
                isStreaming = true,
            )
        } else {
            message
        }
    }.toMutableList()
    val snapshotIds = snapshot.messages.mapTo(mutableSetOf()) { it.id }
    current.filterTo(merged) { it.isStreaming && it.id !in snapshotIds }
    return merged
}

private fun mergeStructuredBlocks(existing: List<MessageBlock>, incoming: List<MessageBlock>): List<MessageBlock> {
    val result = existing.toMutableList()
    incoming.forEach { block ->
        if (block is MessageBlock.Markdown || block is MessageBlock.Code || block is MessageBlock.Quote) return@forEach
        val index = result.indexOfFirst { it.structuredKey() == block.structuredKey() }
        if (index >= 0) {
            result[index] = if (result[index] is MessageBlock.Subtask && block is MessageBlock.Subtask) {
                mergeSubtaskBlock(result[index] as MessageBlock.Subtask, block)
            } else {
                block
            }
        } else {
            result += block
        }
    }
    return result
}

private fun mergeSubtaskBlock(previous: MessageBlock.Subtask, incoming: MessageBlock.Subtask): MessageBlock.Subtask =
    previous.copy(
        subagentType = incoming.subagentType.ifBlank { previous.subagentType },
        description = incoming.description.takeUnless { it == "Subtask" || it.isBlank() } ?: previous.description,
        prompt = incoming.prompt.ifBlank { previous.prompt },
        status = if (incoming.status != MessageBlock.SubtaskStatus.InProgress) incoming.status else previous.status,
        result = incoming.result ?: previous.result,
        error = incoming.error ?: previous.error,
        modelName = incoming.modelName ?: previous.modelName,
    )

private fun MessageBlock.structuredKey(): String = when (this) {
    is MessageBlock.ToolCall -> "call:${id.ifBlank { "$name:$detail" }}"
    is MessageBlock.ToolResult -> "result:${callId.ifBlank { name }}"
    is MessageBlock.HumanInput -> "input:${request.requestId}"
    is MessageBlock.Approval -> "input:${request.requestId}"
    is MessageBlock.HumanInputResponseBlock -> "response:${response.requestId}"
    is MessageBlock.Subtask -> "subtask:${callId.ifBlank { description }}"
    is MessageBlock.Reasoning -> "reasoning"
    else -> toString()
}
