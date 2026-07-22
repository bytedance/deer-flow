package com.deerflow.mobile.data

import org.junit.Assert.assertEquals
import org.junit.Test

class AgentSelectionTest {
    private val capabilities = WorkspaceCapabilities(
        agents = listOf(
            AgentInfo("researcher", "Researches", null, emptyList()),
            AgentInfo("writer", "Writes", null, emptyList()),
        ),
        agentsEnabled = true,
    )

    @Test
    fun savedAvailableDefaultReplacesSelectionThatFollowedPreviousDefault() {
        assertEquals(
            ResolvedAgentSelection("researcher", "researcher"),
            resolveAgentSelection("researcher", LEAD_AGENT_ID, LEAD_AGENT_ID, capabilities),
        )
    }

    @Test
    fun explicitAvailableSelectionSurvivesDefaultRefresh() {
        assertEquals(
            ResolvedAgentSelection("researcher", "writer"),
            resolveAgentSelection("researcher", LEAD_AGENT_ID, "writer", capabilities),
        )
    }

    @Test
    fun deletedDefaultAndSelectionFallBackToLeadAgent() {
        assertEquals(
            ResolvedAgentSelection(LEAD_AGENT_ID, LEAD_AGENT_ID),
            resolveAgentSelection("deleted", "deleted", "deleted", capabilities),
        )
    }
}
