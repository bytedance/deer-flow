package com.deerflow.mobile.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class WorkspaceMetadataCodecTest {
    @Test
    fun capabilitiesRoundTripPreservesAllExposedFields() {
        val value = WorkspaceCapabilities(
            models = listOf(
                ModelInfo(
                    name = "research-model",
                    displayName = "Research model",
                    description = "Deep research",
                    supportsThinking = true,
                    supportsReasoningEffort = false,
                ),
            ),
            agents = listOf(
                AgentInfo(
                    name = "analyst",
                    description = "Checks evidence",
                    model = null,
                    skills = listOf("web-search", "reporting"),
                    soul = "Be precise.",
                ),
            ),
            skills = listOf(
                SkillInfo(
                    name = "reporting",
                    description = "Writes reports",
                    category = "public",
                    enabled = true,
                ),
            ),
            agentsEnabled = true,
        )

        assertEquals(value, decodeWorkspaceCapabilities(encodeWorkspaceCapabilities(value)))
    }

    @Test
    fun scheduledTasksRoundTripPreservesNullableAndEmptySnapshots() {
        val value = listOf(
            ScheduledTaskInfo(
                id = "task-1",
                title = "Daily brief",
                prompt = "Summarize updates",
                scheduleType = "cron",
                scheduleLabel = "0 9 * * *",
                timezone = "Asia/Shanghai",
                status = "active",
                nextRunAt = "2026-07-21T01:00:00Z",
                lastError = null,
                runCount = 7,
            ),
            ScheduledTaskInfo(
                id = "task-2",
                title = "One shot",
                prompt = "Check release",
                scheduleType = "once",
                scheduleLabel = "2026-07-22T02:00:00Z",
                timezone = "UTC",
                status = "failed",
                nextRunAt = null,
                lastError = "Provider unavailable",
                runCount = 1,
            ),
        )

        assertEquals(value, decodeScheduledTasks(encodeScheduledTasks(value)))
        assertEquals(emptyList<ScheduledTaskInfo>(), decodeScheduledTasks(encodeScheduledTasks(emptyList())))
    }

    @Test
    fun mcpToolsRoundTripPreservesOnlySafeCapabilityFields() {
        val value = listOf(
            McpToolInfo("research", "search", "Search cited sources"),
            McpToolInfo("files", "read", "Read approved files"),
        )

        assertEquals(value, decodeMcpTools(encodeMcpTools(value)))
    }

    @Test
    fun unsupportedOrMalformedPayloadIsIgnored() {
        assertNull(decodeWorkspaceCapabilities("{\"version\":2}"))
        assertNull(decodeScheduledTasks("not-json"))
        assertNull(decodeMcpTools("{\"version\":2}"))
    }
}
