package com.deerflow.mobile.data

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class MemoryModelsTest {
    @Test
    fun gatewayPayloadParsesAllMemorySectionsAndFacts() {
        val memory = JSONObject(
            """
            {
              "version":"1.2",
              "lastUpdated":"2026-07-20T08:30:00Z",
              "user":{
                "workContext":{"summary":"Builds Android clients","updatedAt":"2026-07-20T08:00:00Z"},
                "personalContext":{"summary":"Prefers concise answers","updatedAt":"2026-07-19T08:00:00Z"},
                "topOfMind":{"summary":"Finish Memory","updatedAt":"2026-07-20T08:20:00Z"}
              },
              "history":{
                "recentMonths":{"summary":"Migrated settings","updatedAt":"2026-07-18T08:00:00Z"},
                "earlierContext":{"summary":"Built chat flows","updatedAt":"2026-06-01T08:00:00Z"},
                "longTermBackground":{"summary":"Uses Kotlin","updatedAt":"2025-01-01T08:00:00Z"}
              },
              "facts":[
                {
                  "id":"fact-1",
                  "content":"Use JDK 17 for Android builds",
                  "category":"preference",
                  "confidence":0.95,
                  "createdAt":"2026-07-20T08:25:00Z",
                  "source":"thread-1",
                  "sourceError":"Java 25 is unsupported"
                },
                {"id":"fact-2","content":"Confidence is clamped","confidence":2.0},
                {"id":"","content":"Invalid facts are ignored"}
              ]
            }
            """.trimIndent(),
        ).toMemoryData()

        assertEquals("1.2", memory.version)
        assertEquals("Builds Android clients", memory.user.workContext.summary)
        assertEquals("Prefers concise answers", memory.user.personalContext.summary)
        assertEquals("Finish Memory", memory.user.topOfMind.summary)
        assertEquals("Migrated settings", memory.history.recentMonths.summary)
        assertEquals("Built chat flows", memory.history.earlierContext.summary)
        assertEquals("Uses Kotlin", memory.history.longTermBackground.summary)
        assertEquals(2, memory.facts.size)
        assertEquals("Java 25 is unsupported", memory.facts.first().sourceError)
        assertEquals(1.0, memory.facts.last().confidence, 0.0)
        assertEquals("context", memory.facts.last().category)
        assertEquals("unknown", memory.facts.last().source)
        assertTrue(!memory.isEmpty)
    }

    @Test
    fun memoryCacheRoundTripPreservesNullableValuesAndRejectsInvalidPayloads() {
        val value = MemoryData(
            version = "1.0",
            lastUpdated = "2026-07-20T08:30:00Z",
            user = MemoryUserContext(
                workContext = MemorySection("Android development", "2026-07-20T08:00:00Z"),
            ),
            history = MemoryHistoryContext(
                longTermBackground = MemorySection("Kotlin", "2025-01-01T00:00:00Z"),
            ),
            facts = listOf(
                MemoryFact(
                    id = "fact-1",
                    content = "Use Room for offline data",
                    category = "preference",
                    confidence = 0.9,
                    createdAt = "2026-07-20T08:25:00Z",
                    source = "manual",
                    sourceError = null,
                ),
            ),
        )

        assertEquals(value, decodeMemory(encodeMemory(value)))
        assertNull(decodeMemory("not-json"))
        assertNull(decodeMemory("{\"version\":2,\"data\":{}}"))
    }
}
