package com.deerflow.mobile.run

import com.deerflow.mobile.data.ChatMessage
import com.deerflow.mobile.data.MessageRole
import com.deerflow.mobile.data.RunState
import com.deerflow.mobile.data.RunStatus
import com.deerflow.mobile.data.StreamUpdate
import com.deerflow.mobile.data.ThreadSnapshot
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class RunCoordinatorTest {
    private val initial = CoordinatedRunState(
        serverUrl = "https://deerflow.example",
        threadId = "thread-1",
        title = "Research",
        run = RunState(RunStatus.Connecting),
        messages = emptyList(),
    )

    @Test
    fun `started and event id updates preserve resumable coordinates`() {
        val started = reduceRunState(initial, StreamUpdate.Started("run-1"))
        val checkpointed = reduceRunState(started, StreamUpdate.EventId("event-7"))

        assertEquals(RunStatus.Streaming, checkpointed.run.status)
        assertEquals("run-1", checkpointed.run.runId)
        assertEquals("event-7", checkpointed.run.lastEventId)
        assertEquals(2, checkpointed.revision)
    }

    @Test
    fun `persisted active run remains resumable while the active runs list catches up`() {
        val saved = RunState(RunStatus.Reconnecting, runId = "run-1", lastEventId = "event-7")

        assertEquals(saved, resumableRun(saved, activeRunId = null))
    }

    @Test
    fun `server advertised replacement run clears an incompatible event checkpoint`() {
        val saved = RunState(RunStatus.Reconnecting, runId = "run-1", lastEventId = "event-7")

        assertEquals(
            RunState(RunStatus.Reconnecting, runId = "run-2"),
            resumableRun(saved, activeRunId = "run-2"),
        )
    }

    @Test
    fun `message chunks remain available when the UI observer is recreated`() {
        val first = reduceRunState(
            initial,
            StreamUpdate.MessageChunk(ChatMessage("ai-1", MessageRole.Assistant, "Hello ")),
        )
        val second = reduceRunState(
            first,
            StreamUpdate.MessageChunk(ChatMessage("ai-1", MessageRole.Assistant, "again")),
        )

        assertEquals("Hello again", second.messages.single().text)
        assertTrue(second.messages.single().isStreaming)
    }

    @Test
    fun `shorter snapshot cannot roll back a streamed message`() {
        val streaming = initial.copy(
            run = RunState(RunStatus.Streaming, runId = "run-1"),
            messages = listOf(ChatMessage("ai-1", MessageRole.Assistant, "Complete answer", isStreaming = true)),
        )
        val reduced = reduceRunState(
            streaming,
            StreamUpdate.Snapshot(
                ThreadSnapshot(
                    title = "Updated title",
                    messages = listOf(ChatMessage("ai-1", MessageRole.Assistant, "Complete")),
                ),
            ),
        )

        assertEquals("Updated title", reduced.title)
        assertEquals("Complete answer", reduced.messages.single().text)
        assertTrue(reduced.messages.single().isStreaming)
    }

    @Test
    fun `finished run becomes idle and clears streaming flags`() {
        val streaming = initial.copy(
            run = RunState(RunStatus.Streaming, runId = "run-1", lastEventId = "event-9"),
            messages = listOf(ChatMessage("ai-1", MessageRole.Assistant, "Done", isStreaming = true)),
        )

        val finished = reduceRunState(streaming, StreamUpdate.Finished)

        assertFalse(finished.run.active)
        assertEquals(RunStatus.Idle, finished.run.status)
        assertFalse(finished.messages.single().isStreaming)
    }

    @Test
    fun `finished marker does not erase a stream failure`() {
        val failed = initial.copy(
            run = RunState(RunStatus.Failed, runId = "run-1"),
            error = "Gateway rejected the run",
            messages = listOf(ChatMessage("ai-1", MessageRole.Assistant, "Partial", isStreaming = true)),
        )

        val finished = reduceRunState(failed, StreamUpdate.Finished)

        assertEquals(RunStatus.Failed, finished.run.status)
        assertEquals("Gateway rejected the run", finished.error)
        assertFalse(finished.messages.single().isStreaming)
    }

    @Test
    fun `partial updates only replace fields they carry`() {
        val current = initial.copy(
            title = "Original title",
            todos = listOf(com.deerflow.mobile.data.TodoItem("Keep", "pending")),
            artifacts = listOf("existing.md"),
        )
        val reduced = reduceRunState(
            current,
            StreamUpdate.Snapshot(
                ThreadSnapshot(
                    title = "Ignored title",
                    messages = emptyList(),
                    hasMessages = false,
                    todos = listOf(com.deerflow.mobile.data.TodoItem("Ship", "in_progress")),
                    hasTitle = false,
                    hasTodos = true,
                    hasArtifacts = false,
                ),
            ),
        )

        assertEquals("Original title", reduced.title)
        assertEquals(listOf(com.deerflow.mobile.data.TodoItem("Ship", "in_progress")), reduced.todos)
        assertEquals(listOf("existing.md"), reduced.artifacts)
    }
}
