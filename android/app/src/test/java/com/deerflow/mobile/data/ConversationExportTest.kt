package com.deerflow.mobile.data

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ConversationExportTest {
    @Test
    fun markdownExportPreservesStructuredBlocksAndSkipsHiddenMessages() {
        val messages = listOf(
            ChatMessage("human-1", MessageRole.User, "Find the answer"),
            ChatMessage(
                id = "ai-1",
                role = MessageRole.Assistant,
                text = "",
                blocks = listOf(
                    MessageBlock.Markdown("Here is the answer."),
                    MessageBlock.Code(null, "println(1)"),
                    MessageBlock.Todo("Ship it", completed = true),
                ),
            ),
            ChatMessage("hidden", MessageRole.User, "internal", hiddenFromUi = true),
        )

        val output = exportConversation("Research", messages, ConversationExportFormat.Markdown)

        assertTrue(output.startsWith("# Research"))
        assertTrue(output.contains("## You"))
        assertTrue(output.contains("## DeerFlow"))
        assertTrue(output.contains("```\nprintln(1)\n```"))
        assertTrue(output.contains("- [x] Ship it"))
        assertFalse(output.contains("internal"))
    }

    @Test
    fun plainTextExportUsesReadableRoleSections() {
        val output = exportConversation(
            "Conversation",
            listOf(ChatMessage("ai-1", MessageRole.Assistant, "A plain answer")),
            ConversationExportFormat.PlainText,
        )

        assertTrue(output.contains("Conversation"))
        assertTrue(output.contains("DeerFlow\n"))
        assertTrue(output.contains("A plain answer"))
        assertFalse(output.contains("## DeerFlow"))
    }

    @Test
    fun exportFileNameSanitizesTitleAndKeepsFormatExtension() {
        assertTrue(
            conversationExportFileName("  A conversation: 2026/07  ", ConversationExportFormat.Markdown)
                .endsWith("A-conversation-2026-07.md"),
        )
        assertTrue(
            conversationExportFileName("", ConversationExportFormat.PlainText)
                .endsWith("deerflow-conversation.txt"),
        )
    }
}
