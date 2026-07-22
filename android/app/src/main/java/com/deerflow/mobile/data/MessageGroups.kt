package com.deerflow.mobile.data

sealed interface ChatMessageGroup {
    val key: String

    data class Message(
        val message: ChatMessage,
        val showReasoning: Boolean = true,
        val trailingArtifacts: List<MessageBlock.Artifact> = emptyList(),
    ) : ChatMessageGroup {
        override val key: String = "message:${message.id}"
    }

    data class Processing(
        override val key: String,
        val messages: List<ChatMessage>,
        val trailingReasoning: MessageBlock.Reasoning? = null,
    ) : ChatMessageGroup

    data class HumanInput(
        val request: HumanInputRequest,
        val response: HumanInputResponse?,
        val isLatestOpen: Boolean,
    ) : ChatMessageGroup {
        override val key: String = "human-input:${request.requestId}"
    }

    data class Approval(
        val request: HumanInputRequest,
        val response: HumanInputResponse?,
        val isLatestOpen: Boolean,
    ) : ChatMessageGroup {
        override val key: String = "approval:${request.requestId}"
    }
}

data class AssistantTurn(
    val targetMessageId: String,
    val messageIds: List<String>,
    val firstMessageIndex: Int,
)

fun assistantTurnForMessage(messages: List<ChatMessage>, messageId: String): AssistantTurn? {
    val targetIndex = messages.indexOfFirst { it.id == messageId && it.role == MessageRole.Assistant }
    if (targetIndex < 0) return null
    val start = (targetIndex downTo 0).firstOrNull { messages[it].role == MessageRole.User }?.plus(1) ?: 0
    val end = ((targetIndex + 1) until messages.size).firstOrNull { messages[it].role == MessageRole.User } ?: messages.size
    val assistantEntries = (start until end)
        .filter { messages[it].role == MessageRole.Assistant && !messages[it].hiddenFromUi }
    val ids = assistantEntries.map { messages[it].id }.filter { it.isNotBlank() }
    if (ids.isEmpty()) return null
    return AssistantTurn(
        targetMessageId = ids.last(),
        messageIds = ids,
        firstMessageIndex = assistantEntries.first(),
    )
}

fun previousAssistantTurnBeforeUser(messages: List<ChatMessage>, userMessageId: String): AssistantTurn? {
    val userIndex = messages.indexOfFirst { it.id == userMessageId && it.role == MessageRole.User }
    if (userIndex <= 0) return null
    val previousAssistant = (userIndex - 1 downTo 0).firstOrNull {
        messages[it].role == MessageRole.Assistant && !messages[it].hiddenFromUi
    } ?: return null
    return assistantTurnForMessage(messages, messages[previousAssistant].id)
}

fun isLatestAssistantTurn(messages: List<ChatMessage>, turn: AssistantTurn): Boolean =
    messages.indexOfLast { it.role == MessageRole.Assistant && !it.hiddenFromUi }
        .takeIf { it >= 0 }
        ?.let { messages[it].id == turn.targetMessageId } == true

fun groupChatMessages(messages: List<ChatMessage>): List<ChatMessageGroup> {
    val responses = messages.asSequence()
        .flatMap { it.blocks.asSequence() }
        .filterIsInstance<MessageBlock.HumanInputResponseBlock>()
        .associate { it.response.requestId to it.response }
    val requests = messages.asSequence()
        .flatMap { it.blocks.asSequence() }
        .mapNotNull { block ->
            when (block) {
                is MessageBlock.HumanInput -> block.request
                is MessageBlock.Approval -> block.request
                else -> null
            }
        }
        .toList()
    val latestOpenRequestId = requests.lastOrNull { it.requestId !in responses }?.requestId
    val groups = mutableListOf<ChatMessageGroup>()
    val pendingArtifacts = mutableListOf<MessageBlock.Artifact>()
    val pendingPresentFileCallIds = mutableSetOf<String>()

    fun appendProcessing(message: ChatMessage) {
        val last = groups.lastOrNull()
        if (last is ChatMessageGroup.Processing) {
            groups[groups.lastIndex] = last.copy(messages = last.messages + message)
        } else {
            groups += ChatMessageGroup.Processing("processing:${message.id}", listOf(message))
        }
    }

    fun attachTrailingReasoning(reasoning: MessageBlock.Reasoning): Boolean {
        val last = groups.lastOrNull() as? ChatMessageGroup.Processing ?: return false
        groups[groups.lastIndex] = last.copy(trailingReasoning = reasoning)
        return true
    }

    fun takePendingArtifacts(): List<MessageBlock.Artifact> = pendingArtifacts.toList().also { pendingArtifacts.clear() }

    messages.forEach { message ->
        if (message.hiddenFromUi) return@forEach
        val humanInput = message.blocks.filterIsInstance<MessageBlock.HumanInput>().lastOrNull()?.request
        val approval = message.blocks.filterIsInstance<MessageBlock.Approval>().lastOrNull()?.request
        when {
            message.role == MessageRole.Tool -> {
                val result = message.blocks.filterIsInstance<MessageBlock.ToolResult>().lastOrNull()
                if (result?.name == "present_files" || result?.callId in pendingPresentFileCallIds) {
                    result?.callId?.let(pendingPresentFileCallIds::remove)
                    return@forEach
                }
                appendProcessing(message)
                if (approval != null) {
                    groups += ChatMessageGroup.Approval(
                        request = approval,
                        response = responses[approval.requestId],
                        isLatestOpen = approval.requestId == latestOpenRequestId,
                    )
                } else if (humanInput != null) {
                    groups += ChatMessageGroup.HumanInput(
                        request = humanInput,
                        response = responses[humanInput.requestId],
                        isLatestOpen = humanInput.requestId == latestOpenRequestId,
                    )
                }
            }
            message.role == MessageRole.Assistant && message.blocks.any { it is MessageBlock.Artifact } -> {
                pendingArtifacts += message.blocks.filterIsInstance<MessageBlock.Artifact>()
                pendingPresentFileCallIds += message.blocks
                    .filterIsInstance<MessageBlock.ToolCall>()
                    .filter { it.name == "present_files" }
                    .mapNotNull { it.id.takeIf(String::isNotBlank) }
            }
            message.role == MessageRole.Assistant && message.text.isNotBlank() && message.blocks.none {
                it is MessageBlock.ToolCall
            } -> {
                val reasoning = message.blocks.filterIsInstance<MessageBlock.Reasoning>().lastOrNull()
                groups += ChatMessageGroup.Message(
                    message = message,
                    showReasoning = reasoning == null || !attachTrailingReasoning(reasoning),
                    trailingArtifacts = takePendingArtifacts(),
                )
            }
            message.role == MessageRole.Assistant && message.blocks.any {
                it is MessageBlock.ToolCall || it is MessageBlock.Reasoning
            } -> appendProcessing(message)
            else -> groups += ChatMessageGroup.Message(message)
        }
    }
    if (pendingArtifacts.isNotEmpty()) {
        groups += ChatMessageGroup.Message(
            message = ChatMessage(
                id = "presented-files:${pendingArtifacts.first().path}",
                role = MessageRole.Assistant,
                text = "",
            ),
            trailingArtifacts = takePendingArtifacts(),
        )
    }
    return groups
}
