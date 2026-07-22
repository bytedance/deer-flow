package com.deerflow.mobile.data

import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeNoException
import org.junit.Test

class GatewayStreamingInstrumentedTest {
    @Test
    fun mockGatewayDeliversThreeIncrementalMessageChunks() = runBlocking {
        val api = DeerFlowApi("http://10.0.2.2:2027", WebViewSessionCookieStore())
        val thread = try {
            api.createThread("lead_agent")
        } catch (error: Exception) {
            assumeNoException("Mock Gateway is not running on host port 2027", error)
            return@runBlocking
        }
        val chunks = mutableListOf<String>()
        val callbackTimes = mutableListOf<Long>()

        api.streamMessage(
            threadId = thread.id,
            message = "Verify incremental Android streaming",
            options = RunOptions(),
        ) { update ->
            if (update is StreamUpdate.MessageChunk && update.value.text.isNotEmpty()) {
                chunks += update.value.text
                callbackTimes += System.nanoTime()
            }
        }

        assertEquals(
            listOf(
                "I mapped the request into a concise plan, ",
                "checked the available workspace skills, ",
                "and prepared the next concrete action.",
            ),
            chunks,
        )
        assertTrue("Chunks should arrive over time", callbackTimes.last() - callbackTimes.first() >= 2_000_000_000L)
        val snapshot = api.threadState(thread.id)
        assertEquals(listOf("mnt/user-data/outputs/report.md"), snapshot.artifacts)
        val artifact = api.fetchArtifact(thread.id, snapshot.artifacts.single())
        assertEquals("text/markdown", artifact.mimeType)
        assertTrue(artifact.bytes.toString(Charsets.UTF_8).contains("Fixture report"))
    }

    @Test
    fun mockGatewayRegeneratesLatestResponseAndCreatesBranch() = runBlocking {
        val api = DeerFlowApi("http://10.0.2.2:2027", WebViewSessionCookieStore())
        val thread = try {
            api.createThread("lead_agent")
        } catch (error: Exception) {
            assumeNoException("Mock Gateway is not running on host port 2027", error)
            return@runBlocking
        }
        api.streamMessage(thread.id, "Original prompt", RunOptions()) { }
        val original = api.threadState(thread.id)
        val originalAssistant = original.messages.last { it.role == MessageRole.Assistant }
        val preparation = api.prepareRegenerate(thread.id, originalAssistant.id)

        api.streamMessage(
            threadId = thread.id,
            message = "",
            options = RunOptions(),
            regenerate = preparation,
        ) { }

        val regenerated = api.threadState(thread.id)
        val regeneratedAssistant = regenerated.messages.last { it.role == MessageRole.Assistant }
        assertEquals(2, regenerated.messages.size)
        assertTrue(regeneratedAssistant.id != originalAssistant.id)
        val branch = api.branchThread(thread.id, regeneratedAssistant.id, listOf(regeneratedAssistant.id))
        val branchState = api.threadState(branch.threadId)
        assertEquals(thread.id, branch.parentThreadId)
        assertEquals(regenerated.messages.map { it.id }, branchState.messages.map { it.id })
    }
}
