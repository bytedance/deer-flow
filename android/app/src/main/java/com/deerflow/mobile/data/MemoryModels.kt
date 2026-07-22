package com.deerflow.mobile.data

import org.json.JSONArray
import org.json.JSONObject

data class MemorySection(
    val summary: String = "",
    val updatedAt: String = "",
)

data class MemoryUserContext(
    val workContext: MemorySection = MemorySection(),
    val personalContext: MemorySection = MemorySection(),
    val topOfMind: MemorySection = MemorySection(),
)

data class MemoryHistoryContext(
    val recentMonths: MemorySection = MemorySection(),
    val earlierContext: MemorySection = MemorySection(),
    val longTermBackground: MemorySection = MemorySection(),
)

data class MemoryFact(
    val id: String,
    val content: String,
    val category: String,
    val confidence: Double,
    val createdAt: String,
    val source: String,
    val sourceError: String? = null,
)

data class MemoryData(
    val version: String = "1.0",
    val lastUpdated: String = "",
    val user: MemoryUserContext = MemoryUserContext(),
    val history: MemoryHistoryContext = MemoryHistoryContext(),
    val facts: List<MemoryFact> = emptyList(),
) {
    val isEmpty: Boolean
        get() = facts.isEmpty() && listOf(
            user.workContext,
            user.personalContext,
            user.topOfMind,
            history.recentMonths,
            history.earlierContext,
            history.longTermBackground,
        ).all { it.summary.isBlank() }
}

internal fun JSONObject.toMemoryData(): MemoryData {
    val userJson = optJSONObject("user") ?: JSONObject()
    val historyJson = optJSONObject("history") ?: JSONObject()
    return MemoryData(
        version = optString("version", "1.0"),
        lastUpdated = optString("lastUpdated"),
        user = MemoryUserContext(
            workContext = userJson.memorySection("workContext"),
            personalContext = userJson.memorySection("personalContext"),
            topOfMind = userJson.memorySection("topOfMind"),
        ),
        history = MemoryHistoryContext(
            recentMonths = historyJson.memorySection("recentMonths"),
            earlierContext = historyJson.memorySection("earlierContext"),
            longTermBackground = historyJson.memorySection("longTermBackground"),
        ),
        facts = optJSONArray("facts").memoryFacts(),
    )
}

internal fun MemoryData.toJsonObject(): JSONObject = JSONObject()
    .put("version", version)
    .put("lastUpdated", lastUpdated)
    .put(
        "user",
        JSONObject()
            .put("workContext", user.workContext.toJsonObject())
            .put("personalContext", user.personalContext.toJsonObject())
            .put("topOfMind", user.topOfMind.toJsonObject()),
    )
    .put(
        "history",
        JSONObject()
            .put("recentMonths", history.recentMonths.toJsonObject())
            .put("earlierContext", history.earlierContext.toJsonObject())
            .put("longTermBackground", history.longTermBackground.toJsonObject()),
    )
    .put(
        "facts",
        JSONArray().apply {
            facts.forEach { fact ->
                put(
                    JSONObject()
                        .put("id", fact.id)
                        .put("content", fact.content)
                        .put("category", fact.category)
                        .put("confidence", fact.confidence)
                        .put("createdAt", fact.createdAt)
                        .put("source", fact.source)
                        .put("sourceError", fact.sourceError ?: JSONObject.NULL),
                )
            }
        },
    )

private fun JSONObject.memorySection(name: String): MemorySection {
    val section = optJSONObject(name) ?: JSONObject()
    return MemorySection(
        summary = section.optString("summary"),
        updatedAt = section.optString("updatedAt"),
    )
}

private fun MemorySection.toJsonObject(): JSONObject = JSONObject()
    .put("summary", summary)
    .put("updatedAt", updatedAt)

private fun JSONArray?.memoryFacts(): List<MemoryFact> = buildList {
    val source = this@memoryFacts ?: return@buildList
    for (index in 0 until source.length()) {
        val fact = source.optJSONObject(index) ?: continue
        val id = fact.optString("id")
        val content = fact.optString("content")
        if (id.isBlank() || content.isBlank()) continue
        add(
            MemoryFact(
                id = id,
                content = content,
                category = fact.optString("category", "context"),
                confidence = fact.optDouble("confidence", 0.5).coerceIn(0.0, 1.0),
                createdAt = fact.optString("createdAt"),
                source = fact.optString("source", "unknown"),
                sourceError = nullableJsonString(fact.opt("sourceError")),
            ),
        )
    }
}
