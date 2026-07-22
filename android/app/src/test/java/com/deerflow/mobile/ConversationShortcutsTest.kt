package com.deerflow.mobile

import com.deerflow.mobile.data.ThreadSummary
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Test

class ConversationShortcutsTest {
    @Test
    fun recentConversationsAreNewestFirstDeduplicatedAndScopedToTheirServer() {
        val threads = listOf(
            thread(id = "older", title = "Older", updatedAt = "2026-07-20T08:00:00Z"),
            thread(id = "newest", title = "  Latest\nplanning  ", updatedAt = "2026-07-22T08:00:00Z"),
            thread(id = "newest", title = "Duplicate", updatedAt = "2026-07-23T08:00:00Z"),
            thread(id = "middle", title = "Middle", updatedAt = "2026-07-21T08:00:00Z"),
        )

        val recent = recentConversationShortcuts("https://one.example", threads, maxCount = 2)
        val sameThreadOtherServer = recentConversationShortcuts("https://two.example", threads, maxCount = 2)

        assertEquals(listOf("newest", "middle"), recent.map { it.threadId })
        assertEquals("Latest planning", recent.first().title)
        assertNotEquals(recent.first().id, sameThreadOtherServer.first().id)
    }

    @Test
    fun recentConversationLimitCanDisableDynamicShortcuts() {
        val recent = recentConversationShortcuts(
            serverUrl = "https://deerflow.example",
            threads = listOf(thread(id = "thread-1", title = "One", updatedAt = "2026-07-22T08:00:00Z")),
            maxCount = 0,
        )

        assertEquals(emptyList<RecentConversationShortcut>(), recent)
    }

    private fun thread(id: String, title: String, updatedAt: String) = ThreadSummary(
        id = id,
        title = title,
        status = "idle",
        updatedAt = updatedAt,
    )
}
