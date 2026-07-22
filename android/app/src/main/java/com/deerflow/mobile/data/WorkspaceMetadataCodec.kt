package com.deerflow.mobile.data

import org.json.JSONArray
import org.json.JSONObject

internal fun encodeWorkspaceCapabilities(value: WorkspaceCapabilities): String = JSONObject()
    .put("version", CACHE_PAYLOAD_VERSION)
    .put(
        "models",
        JSONArray().apply {
            value.models.forEach { model ->
                put(
                    JSONObject()
                        .put("name", model.name)
                        .put("displayName", model.displayName)
                        .put("description", model.description)
                        .put("supportsThinking", model.supportsThinking)
                        .put("supportsReasoningEffort", model.supportsReasoningEffort),
                )
            }
        },
    )
    .put(
        "agents",
        JSONArray().apply {
            value.agents.forEach { agent ->
                put(
                    JSONObject()
                        .put("name", agent.name)
                        .put("description", agent.description)
                        .put("model", agent.model ?: JSONObject.NULL)
                        .put("skills", JSONArray(agent.skills))
                        .put("soul", agent.soul),
                )
            }
        },
    )
    .put(
        "skills",
        JSONArray().apply {
            value.skills.forEach { skill ->
                put(
                    JSONObject()
                        .put("name", skill.name)
                        .put("description", skill.description)
                        .put("category", skill.category)
                        .put("enabled", skill.enabled),
                )
            }
        },
    )
    .put("agentsEnabled", value.agentsEnabled)
    .toString()

internal fun decodeWorkspaceCapabilities(payload: String): WorkspaceCapabilities? = runCatching {
    val root = JSONObject(payload).requireSupportedVersion()
    WorkspaceCapabilities(
        models = root.optJSONArray("models").mapObjects { item ->
            ModelInfo(
                name = item.optString("name"),
                displayName = item.optString("displayName"),
                description = item.optString("description"),
                supportsThinking = item.optBoolean("supportsThinking"),
                supportsReasoningEffort = item.optBoolean("supportsReasoningEffort"),
            )
        },
        agents = root.optJSONArray("agents").mapObjects { item ->
            AgentInfo(
                name = item.optString("name"),
                description = item.optString("description"),
                model = item.opt("model").nullableString(),
                skills = item.optJSONArray("skills").stringValues(),
                soul = item.optString("soul"),
            )
        },
        skills = root.optJSONArray("skills").mapObjects { item ->
            SkillInfo(
                name = item.optString("name"),
                description = item.optString("description"),
                category = item.optString("category"),
                enabled = item.optBoolean("enabled"),
            )
        },
        agentsEnabled = root.optBoolean("agentsEnabled"),
    )
}.getOrNull()

internal fun encodeScheduledTasks(value: List<ScheduledTaskInfo>): String = JSONObject()
    .put("version", CACHE_PAYLOAD_VERSION)
    .put(
        "items",
        JSONArray().apply {
            value.forEach { task ->
                put(
                    JSONObject()
                        .put("id", task.id)
                        .put("title", task.title)
                        .put("prompt", task.prompt)
                        .put("scheduleType", task.scheduleType)
                        .put("scheduleLabel", task.scheduleLabel)
                        .put("timezone", task.timezone)
                        .put("status", task.status)
                        .put("nextRunAt", task.nextRunAt ?: JSONObject.NULL)
                        .put("lastError", task.lastError ?: JSONObject.NULL)
                        .put("runCount", task.runCount),
                )
            }
        },
    )
    .toString()

internal fun decodeScheduledTasks(payload: String): List<ScheduledTaskInfo>? = runCatching {
    val root = JSONObject(payload).requireSupportedVersion()
    root.optJSONArray("items").mapObjects { item ->
        ScheduledTaskInfo(
            id = item.optString("id"),
            title = item.optString("title"),
            prompt = item.optString("prompt"),
            scheduleType = item.optString("scheduleType"),
            scheduleLabel = item.optString("scheduleLabel"),
            timezone = item.optString("timezone"),
            status = item.optString("status"),
            nextRunAt = item.opt("nextRunAt").nullableString(),
            lastError = item.opt("lastError").nullableString(),
            runCount = item.optInt("runCount"),
        )
    }
}.getOrNull()

internal fun encodeMemory(value: MemoryData): String = JSONObject()
    .put("version", CACHE_PAYLOAD_VERSION)
    .put("data", value.toJsonObject())
    .toString()

internal fun decodeMemory(payload: String): MemoryData? = runCatching {
    JSONObject(payload)
        .requireSupportedVersion()
        .getJSONObject("data")
        .toMemoryData()
}.getOrNull()

internal fun encodeMcpTools(value: List<McpToolInfo>): String = JSONObject()
    .put("version", CACHE_PAYLOAD_VERSION)
    .put(
        "items",
        JSONArray().apply {
            value.forEach { tool ->
                put(
                    JSONObject()
                        .put("serverName", tool.serverName)
                        .put("name", tool.name)
                        .put("description", tool.description),
                )
            }
        },
    )
    .toString()

internal fun decodeMcpTools(payload: String): List<McpToolInfo>? = runCatching {
    val root = JSONObject(payload).requireSupportedVersion()
    root.optJSONArray("items").mapObjects { item ->
        McpToolInfo(
            serverName = item.optString("serverName"),
            name = item.optString("name"),
            description = item.optString("description"),
        )
    }.filter { it.serverName.isNotBlank() && it.name.isNotBlank() }
}.getOrNull()

private fun JSONObject.requireSupportedVersion(): JSONObject = apply {
    require(optInt("version") == CACHE_PAYLOAD_VERSION) { "Unsupported workspace metadata cache version" }
}

private inline fun <T> JSONArray?.mapObjects(transform: (JSONObject) -> T): List<T> = buildList {
    val source = this@mapObjects ?: return@buildList
    for (index in 0 until source.length()) {
        source.optJSONObject(index)?.let { add(transform(it)) }
    }
}

private fun JSONArray?.stringValues(): List<String> = buildList {
    val source = this@stringValues ?: return@buildList
    for (index in 0 until source.length()) {
        source.optString(index).takeIf { it.isNotBlank() }?.let(::add)
    }
}

private fun Any?.nullableString(): String? = (this as? String)?.takeIf { it.isNotBlank() }

private const val CACHE_PAYLOAD_VERSION = 1
