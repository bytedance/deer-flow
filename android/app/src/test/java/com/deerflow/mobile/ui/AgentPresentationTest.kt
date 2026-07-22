package com.deerflow.mobile.ui

import com.deerflow.mobile.data.AgentInfo
import org.junit.Assert.assertEquals
import org.junit.Test

class AgentPresentationTest {
    @Test
    fun reservedLeadAgentIsNotRepeatedInCustomAgentLists() {
        val agents = listOf(
            AgentInfo("lead_agent", "Built in", null, emptyList()),
            AgentInfo("researcher", "Researches", null, emptyList()),
            AgentInfo("creator", "Creates", null, emptyList()),
        )

        assertEquals(listOf("researcher", "creator"), agents.customAgentsOnly().map { it.name })
    }
}
