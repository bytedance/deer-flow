package com.deerflow.mobile.data

enum class ConversationExportFormat(
    val extension: String,
    val mimeType: String,
) {
    Markdown("md", "text/markdown"),
    PlainText("txt", "text/plain"),
}

fun conversationExportFileName(title: String, format: ConversationExportFormat): String {
    val safeTitle = title
        .trim()
        .replace(Regex("[^\\p{L}\\p{N}._-]+"), "-")
        .trim('-')
        .ifBlank { "deerflow-conversation" }
    return "$safeTitle.${format.extension}"
}

fun exportConversation(title: String, messages: List<ChatMessage>, format: ConversationExportFormat): String {
    val visible = messages.filterNot { it.hiddenFromUi }
    return when (format) {
        ConversationExportFormat.Markdown -> buildMarkdown(title, visible)
        ConversationExportFormat.PlainText -> buildPlainText(title, visible)
    }
}

private fun buildMarkdown(title: String, messages: List<ChatMessage>): String = buildString {
    append("# ").append(title.trim().ifBlank { "DeerFlow conversation" }).append("\n\n")
    messages.forEachIndexed { index, message ->
        if (index > 0) append("\n\n")
        append("## ").append(message.role.exportLabel()).append("\n\n")
        append(message.toExportMarkdown())
    }
    append('\n')
}

private fun buildPlainText(title: String, messages: List<ChatMessage>): String = buildString {
    append(title.trim().ifBlank { "DeerFlow conversation" }).append("\n")
    append("=".repeat(maxOf(4, title.length))).append("\n\n")
    messages.forEachIndexed { index, message ->
        if (index > 0) append("\n\n")
        append(message.role.exportLabel()).append("\n")
        append("-".repeat(maxOf(4, message.role.exportLabel().length))).append("\n")
        append(message.toExportPlainText())
    }
    append('\n')
}

private fun ChatMessage.toExportMarkdown(): String = buildString {
    if (role == MessageRole.User) append(text)
    else blocks.forEachIndexed { index, block ->
        if (index > 0) append("\n\n")
        append(block.toExportMarkdown())
    }
    appendAttachmentsMarkdown(this@toExportMarkdown)
}

private fun ChatMessage.toExportPlainText(): String = buildString {
    if (role == MessageRole.User) append(text)
    else blocks.forEachIndexed { index, block ->
        if (index > 0) append("\n\n")
        append(block.toExportPlainText())
    }
    attachments.forEach { attachment ->
        append("\nAttachment: ").append(attachment.filename)
        if (attachment.path != null) append(" (").append(attachment.path).append(')')
    }
}

private fun MessageBlock.toExportMarkdown(): String = when (this) {
    is MessageBlock.Markdown -> text
    is MessageBlock.Code -> "```" + language.orEmpty() + "\n" + code + "\n```"
    is MessageBlock.Quote -> text.lineSequence().joinToString("\n") { "> $it" }
    is MessageBlock.Reasoning -> "<details>\n<summary>Reasoning</summary>\n\n$text\n\n</details>"
    is MessageBlock.ToolCall -> buildString {
        append("> **Tool: ").append(name).append("**")
        if (detail.isNotBlank()) append("\n> ").append(detail.replace("\n", "\n> "))
    }
    is MessageBlock.ToolResult -> buildString {
        append("> **Tool result: ").append(name)
        if (failed) append(" (failed)")
        append("**")
        if (detail.isNotBlank()) append("\n> ").append(detail.replace("\n", "\n> "))
    }
    is MessageBlock.Subtask -> buildString {
        append("> **Subtask: ").append(description).append("** (").append(status.name.lowercase()).append(')')
        subagentType.takeIf { it.isNotBlank() }?.let { append("\n> Agent: ").append(it) }
        result?.takeIf { it.isNotBlank() }?.let { append("\n> Result: ").append(it.replace("\n", "\n> ")) }
        error?.takeIf { it.isNotBlank() }?.let { append("\n> Error: ").append(it.replace("\n", "\n> ")) }
    }
    is MessageBlock.HumanInput -> "> **Needs your help:** ${request.question}"
    is MessageBlock.Approval -> "> **Approval required:** ${request.question}"
    is MessageBlock.HumanInputResponseBlock -> "> **Human input:** ${response.value}"
    is MessageBlock.Todo -> "- [${when (status) { "completed" -> 'x'; "in_progress" -> '>'; else -> ' ' }}] $title"
    is MessageBlock.Artifact -> "[${title.ifBlank { path }}]($path)"
    is MessageBlock.Error -> "> **Error:** $message"
}

private fun MessageBlock.toExportPlainText(): String = when (this) {
    is MessageBlock.Markdown -> text
    is MessageBlock.Code -> code
    is MessageBlock.Quote -> text
    is MessageBlock.Reasoning -> "Reasoning:\n$text"
    is MessageBlock.ToolCall -> "Tool: $name${detail.takeIf { it.isNotBlank() }?.let { "\n$it" } ?: ""}"
    is MessageBlock.ToolResult -> "Tool result: $name${if (failed) " (failed)" else ""}${detail.takeIf { it.isNotBlank() }?.let { "\n$it" } ?: ""}"
    is MessageBlock.Subtask -> buildString {
        append("Subtask: ").append(description).append(" (").append(status.name.lowercase()).append(')')
        result?.takeIf { it.isNotBlank() }?.let { append("\nResult: ").append(it) }
        error?.takeIf { it.isNotBlank() }?.let { append("\nError: ").append(it) }
    }
    is MessageBlock.HumanInput -> "Needs your help: ${request.question}"
    is MessageBlock.Approval -> "Approval required: ${request.question}"
    is MessageBlock.HumanInputResponseBlock -> "Human input: ${response.value}"
    is MessageBlock.Todo -> "[${status}] $title"
    is MessageBlock.Artifact -> "Artifact: ${title.ifBlank { path }} ($path)"
    is MessageBlock.Error -> "Error: $message"
}

private fun MessageRole.exportLabel(): String = when (this) {
    MessageRole.User -> "You"
    MessageRole.Assistant -> "DeerFlow"
    MessageRole.Tool -> "Tool"
    MessageRole.System -> "System"
}

private fun StringBuilder.appendAttachmentsMarkdown(message: ChatMessage) {
    message.attachments.forEach { attachment ->
        append("\n\nAttachment: ").append(attachment.filename)
        if (attachment.path != null) append(" (").append(attachment.path).append(')')
    }
}
