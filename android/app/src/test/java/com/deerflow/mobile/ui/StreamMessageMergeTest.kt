package com.deerflow.mobile.ui

import com.deerflow.mobile.data.ChatMessage
import com.deerflow.mobile.data.MessageRole
import com.deerflow.mobile.data.ThreadSnapshot
import com.deerflow.mobile.data.mergeStreamChunk
import com.deerflow.mobile.data.mergeStreamSnapshot
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class StreamMessageMergeTest {
    @Test
    fun appendsMessageChunksWithTheSameMessageId() {
        val first = mergeStreamChunk(emptyList(), ChatMessage("ai-1", MessageRole.Assistant, "Hel"))
        val second = mergeStreamChunk(first, ChatMessage("ai-1", MessageRole.Assistant, "lo"))

        assertEquals(1, second.size)
        assertEquals("Hello", second.single().text)
        assertTrue(second.single().isStreaming)
    }

    @Test
    fun shorterValuesSnapshotDoesNotRollBackVisibleStreamText() {
        val current = listOf(ChatMessage("ai-1", MessageRole.Assistant, "Hello world", isStreaming = true))
        val snapshot = ThreadSnapshot(
            title = "Greeting",
            messages = listOf(ChatMessage("ai-1", MessageRole.Assistant, "Hello")),
        )

        val merged = mergeStreamSnapshot(current, snapshot)

        assertEquals("Hello world", merged.single().text)
        assertTrue(merged.single().isStreaming)
    }

    @Test
    fun valuesWithoutMessagesPreserveCurrentConversation() {
        val current = listOf(ChatMessage("ai-1", MessageRole.Assistant, "Still streaming", isStreaming = true))

        val merged = mergeStreamSnapshot(current, ThreadSnapshot("New title", emptyList(), hasMessages = false))

        assertEquals(current, merged)
    }
}
