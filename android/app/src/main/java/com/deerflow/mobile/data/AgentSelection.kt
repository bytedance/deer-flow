package com.deerflow.mobile.data

const val LEAD_AGENT_ID = "lead_agent"

data class ResolvedAgentSelection(
    val defaultAgentId: String,
    val selectedAgentId: String,
)

fun resolveAgentSelection(
    savedDefaultAgentId: String,
    currentDefaultAgentId: String,
    currentSelectedAgentId: String,
    capabilities: WorkspaceCapabilities,
): ResolvedAgentSelection {
    val available = capabilities.agents.mapTo(mutableSetOf(LEAD_AGENT_ID)) { it.name }
    val defaultAgentId = savedDefaultAgentId.takeIf { it in available } ?: LEAD_AGENT_ID
    val selectedAgentId = when {
        currentSelectedAgentId.isBlank() || currentSelectedAgentId == currentDefaultAgentId -> defaultAgentId
        currentSelectedAgentId in available -> currentSelectedAgentId
        else -> defaultAgentId
    }
    return ResolvedAgentSelection(defaultAgentId, selectedAgentId)
}
