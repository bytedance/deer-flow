package com.deerflow.mobile

import android.content.pm.ShortcutManager
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.deerflow.mobile.data.ThreadSummary
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class ConversationShortcutsInstrumentedTest {
    private val context get() = InstrumentationRegistry.getInstrumentation().targetContext
    private val shortcuts get() = ConversationShortcuts(context)

    @After
    fun clearShortcuts() {
        shortcuts.clear()
    }

    @Test
    fun publishesRecentConversationShortcutsWithLaunchIntentsAndCanClearThem() {
        val manager = context.getSystemService(ShortcutManager::class.java)
        shortcuts.clear()
        shortcuts.publish(
            serverUrl = "http://10.0.2.2:2027",
            threads = listOf(
                thread("older", "Older", "2026-07-20T08:00:00Z"),
                thread("newest", "Latest plan", "2026-07-22T08:00:00Z"),
            ),
        )

        val dynamic = manager.dynamicShortcuts
        assertTrue(dynamic.isNotEmpty())
        val latest = dynamic.single { it.shortLabel.toString() == "Latest plan" }
        assertEquals(0, latest.rank)
        val launchIntent = requireNotNull(latest.intent)
        assertEquals(MainActivity.ACTION_OPEN_CONVERSATION, launchIntent.action)
        assertEquals("http://10.0.2.2:2027", launchIntent.getStringExtra("com.deerflow.mobile.shortcut.SERVER_URL"))
        assertEquals("newest", launchIntent.getStringExtra("com.deerflow.mobile.shortcut.THREAD_ID"))

        shortcuts.clear()
        assertTrue(manager.dynamicShortcuts.isEmpty())
    }

    private fun thread(id: String, title: String, updatedAt: String) = ThreadSummary(
        id = id,
        title = title,
        status = "completed",
        updatedAt = updatedAt,
    )
}
