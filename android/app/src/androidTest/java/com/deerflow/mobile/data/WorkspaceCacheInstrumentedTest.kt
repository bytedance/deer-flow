package com.deerflow.mobile.data

import androidx.test.core.app.ApplicationProvider
import java.io.File
import java.util.UUID
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class WorkspaceCacheInstrumentedTest {
    @Test
    fun statisticsAndClearCoverRoomAndArtifactCachesWithoutRemovingSettings() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val cache = WorkspaceCache(context)
        val settingsBefore = SettingsStore(context).read()
        val serverUrl = "http://clear-cache-test-${UUID.randomUUID()}"
        val threadId = "thread-${UUID.randomUUID()}"
        val artifact = File(context.cacheDir, "artifacts/cache-test.txt")

        cache.clearAll()
        cache.saveThreads(serverUrl, listOf(ThreadSummary(threadId, "Cached", "idle", "2026-07-20T12:00:00Z")))
        cache.saveMessages(serverUrl, threadId, listOf(ChatMessage("message-1", MessageRole.Assistant, "Cached answer")))
        cache.saveDraft(serverUrl, threadId, "Cached draft")
        cache.saveRun(serverUrl, threadId, RunState(RunStatus.Reconnecting, "run-1", "event-1"))
        cache.saveAttachments(
            serverUrl,
            threadId,
            listOf(PendingAttachment("content://cached", "cached.txt", "text/plain", 12)),
        )
        cache.saveCapabilities(serverUrl, WorkspaceCapabilities(agentsEnabled = true))
        artifact.parentFile?.mkdirs()
        artifact.writeText("cached artifact")

        val populated = cache.stats()
        assertEquals(1, populated.conversationCount)
        assertEquals(1, populated.messageCount)
        assertEquals(1, populated.draftCount)
        assertEquals(1, populated.runCount)
        assertEquals(1, populated.attachmentCount)
        assertEquals(1, populated.metadataCount)
        assertTrue(populated.itemCount >= 6)
        assertTrue(populated.bytesOnDisk > 0)

        cache.clearAll()
        val cleared = cache.stats()
        assertEquals(0, cleared.itemCount)
        assertTrue(cache.loadThreads(serverUrl).isEmpty())
        assertTrue(cache.loadMessages(serverUrl, threadId).isEmpty())
        assertEquals("", cache.loadDraft(serverUrl, threadId))
        assertNull(cache.loadLatestActiveRun(serverUrl))
        assertTrue(cache.loadAttachments(serverUrl, threadId).isEmpty())
        assertNull(cache.loadCapabilities(serverUrl))
        assertFalse(artifact.exists())
        assertEquals(settingsBefore, SettingsStore(context).read())

        cache.clearAll()
        assertEquals(0, cache.stats().itemCount)
    }

    @Test
    fun structuredMessagesRetainToolAndHumanInputContentOffline() = runBlocking {
        val cache = WorkspaceCache(ApplicationProvider.getApplicationContext())
        val serverUrl = "http://message-cache-test-${UUID.randomUUID()}"
        val threadId = "thread-${UUID.randomUUID()}"
        val request = HumanInputRequest(
            source = "interrupt",
            requestId = "request-1",
            toolCallId = "call-1",
            title = "Need a choice",
            question = "Continue with the cached source?",
            context = null,
            inputMode = "single_choice",
            options = listOf(HumanInputOption("yes", "Continue", "yes")),
        )
        val messages = listOf(
            ChatMessage(
                id = "assistant-1",
                role = MessageRole.Assistant,
                text = "Checking the source",
                blocks = listOf(
                    MessageBlock.Markdown("Checking the source"),
                    MessageBlock.Reasoning("Use the configured source"),
                    MessageBlock.ToolCall("search", "{\"query\":\"Room\"}", "call-1"),
                    MessageBlock.Subtask(
                        callId = "call-2",
                        subagentType = "researcher",
                        description = "Check persistence",
                        prompt = "Inspect Room",
                    ),
                    MessageBlock.Todo("Verify cache", false, "in_progress"),
                    MessageBlock.Artifact("notes.md", "/mnt/user-data/outputs/notes.md"),
                ),
                attachments = listOf(MessageAttachment("source.txt", 12, "/mnt/user-data/uploads/source.txt")),
            ),
            ChatMessage(
                id = "tool-1",
                role = MessageRole.Tool,
                text = "Choose before continuing",
                blocks = listOf(
                    MessageBlock.ToolResult("call-1", "search", "Choose before continuing"),
                    MessageBlock.HumanInput(request),
                ),
            ),
            ChatMessage(
                id = "response-1",
                role = MessageRole.User,
                text = "",
                blocks = listOf(
                    MessageBlock.HumanInputResponseBlock(
                        HumanInputResponse("interrupt", "request-1", "option", "yes", "yes"),
                    ),
                ),
                hiddenFromUi = true,
            ),
        )

        cache.saveMessages(serverUrl, threadId, messages)

        val restored = cache.loadMessages(serverUrl, threadId)
        assertEquals(messages, restored)
        val groups = groupChatMessages(restored)
        assertTrue(groups.first() is ChatMessageGroup.Processing)
        val humanInput = groups.filterIsInstance<ChatMessageGroup.HumanInput>().single()
        assertEquals(request, humanInput.request)
        assertEquals("yes", humanInput.response?.value)
        assertTrue(!humanInput.isLatestOpen)
        cache.deleteThread(serverUrl, threadId)
    }

    @Test
    fun interruptedUploadIsRestoredAsRetryablePendingAttachment() = runBlocking {
        val cache = WorkspaceCache(ApplicationProvider.getApplicationContext())
        val serverUrl = "http://cache-test-${UUID.randomUUID()}"
        val threadId = "thread-${UUID.randomUUID()}"
        val attachment = PendingAttachment(
            uri = "content://upload-test",
            filename = "notes.txt",
            mimeType = "text/plain",
            size = 12,
            status = AttachmentStatus.Uploading,
        )

        cache.saveAttachments(serverUrl, threadId, listOf(attachment))
        val restored = cache.loadAttachments(serverUrl, threadId).single()

        assertEquals(AttachmentStatus.Pending, restored.status)
        assertTrue(restored.error?.contains("interrupted") == true)
        cache.saveAttachments(serverUrl, threadId, emptyList())
    }

    @Test
    fun draftsStayScopedToTheirThreadAndBlankTextClearsOnlyThatDraft() = runBlocking {
        val cache = WorkspaceCache(ApplicationProvider.getApplicationContext())
        val serverUrl = "http://draft-cache-test-${UUID.randomUUID()}"
        val firstThread = "thread-${UUID.randomUUID()}"
        val secondThread = "thread-${UUID.randomUUID()}"

        cache.saveDraft(serverUrl, firstThread, "draft for first thread")
        cache.saveDraft(serverUrl, secondThread, "draft for second thread")

        assertEquals("draft for first thread", cache.loadDraft(serverUrl, firstThread))
        assertEquals("draft for second thread", cache.loadDraft(serverUrl, secondThread))

        cache.saveDraft(serverUrl, firstThread, "")

        assertEquals("", cache.loadDraft(serverUrl, firstThread))
        assertEquals("draft for second thread", cache.loadDraft(serverUrl, secondThread))
        cache.deleteThread(serverUrl, firstThread)
        cache.deleteThread(serverUrl, secondThread)
    }

    @Test
    fun latestActiveRunRestoresThreadTitleAndResumeCoordinates() = runBlocking {
        val cache = WorkspaceCache(ApplicationProvider.getApplicationContext())
        val serverUrl = "http://run-cache-test-${UUID.randomUUID()}"
        val threadId = "thread-${UUID.randomUUID()}"
        cache.saveThreads(serverUrl, listOf(ThreadSummary(threadId, "Long research", "busy", "2026-07-19T20:00:00Z")))
        cache.saveRun(
            serverUrl,
            threadId,
            RunState(RunStatus.Reconnecting, runId = "run-42", lastEventId = "event-9"),
        )

        val restored = cache.loadLatestActiveRun(serverUrl)

        assertEquals(threadId, restored?.threadId)
        assertEquals("Long research", restored?.title)
        assertEquals("run-42", restored?.run?.runId)
        assertEquals("event-9", restored?.run?.lastEventId)
        cache.deleteThread(serverUrl, threadId)
    }

    @Test
    fun terminalRunIsNotOfferedForServiceRecovery() = runBlocking {
        val cache = WorkspaceCache(ApplicationProvider.getApplicationContext())
        val serverUrl = "http://terminal-run-test-${UUID.randomUUID()}"
        val threadId = "thread-${UUID.randomUUID()}"
        cache.saveRun(serverUrl, threadId, RunState(RunStatus.Failed, runId = "run-failed"))

        assertNull(cache.loadLatestActiveRun(serverUrl))
        cache.deleteThread(serverUrl, threadId)
    }

    @Test
    fun workspaceMetadataStaysServerScopedAndKeepsEmptyTaskSnapshots() = runBlocking {
        val cache = WorkspaceCache(ApplicationProvider.getApplicationContext())
        val firstServer = "http://metadata-cache-${UUID.randomUUID()}"
        val secondServer = "http://metadata-cache-${UUID.randomUUID()}"
        val capabilities = WorkspaceCapabilities(
            models = listOf(ModelInfo("model-1", "Model one", "", true, false)),
            agents = listOf(AgentInfo("researcher", "Research agent", "model-1", listOf("search"))),
            skills = listOf(SkillInfo("search", "Searches sources", "public", true)),
            agentsEnabled = true,
        )
        val memory = MemoryData(
            lastUpdated = "2026-07-20T08:30:00Z",
            facts = listOf(
                MemoryFact("fact-1", "Use offline snapshots", "preference", 0.9, "", "manual"),
            ),
        )
        val mcpTools = listOf(
            McpToolInfo("research", "search", "Search cited sources"),
        )

        cache.saveCapabilities(firstServer, capabilities)
        cache.saveTasks(firstServer, emptyList())
        cache.saveMemory(firstServer, memory)
        cache.saveMcpTools(firstServer, mcpTools)

        assertEquals(capabilities, cache.loadCapabilities(firstServer))
        assertEquals(emptyList<ScheduledTaskInfo>(), cache.loadTasks(firstServer))
        assertEquals(memory, cache.loadMemory(firstServer))
        assertEquals(mcpTools, cache.loadMcpTools(firstServer))
        assertNull(cache.loadCapabilities(secondServer))
        assertNull(cache.loadTasks(secondServer))
        assertNull(cache.loadMemory(secondServer))
        assertNull(cache.loadMcpTools(secondServer))
    }
}
