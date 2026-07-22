package com.deerflow.mobile.ui

import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.material3.MaterialTheme
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextReplacement
import com.deerflow.mobile.data.MemoryData
import com.deerflow.mobile.data.MemoryFact
import com.deerflow.mobile.data.MemoryHistoryContext
import com.deerflow.mobile.data.MemorySection
import com.deerflow.mobile.data.MemoryUserContext
import java.util.concurrent.atomic.AtomicReference
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Rule
import org.junit.Test

class MemoryScreenTest {
    @get:Rule val compose = createComposeRule()

    @Test
    fun searchAndFiltersNarrowFactsAndSummaries() {
        setMemoryContent()

        compose.onNodeWithText("Builds Android apps").assertIsDisplayed()

        compose.onNodeWithTag(UiTags.MemorySearch).performTextReplacement("Kotlin")
        compose.onNodeWithTag("${UiTags.MemoryFactPrefix}fact-kotlin").assertIsDisplayed()
        compose.onNodeWithTag("${UiTags.MemoryFactPrefix}fact-room").assertDoesNotExist()
        compose.onNodeWithText("Builds Android apps").assertDoesNotExist()

        compose.onNodeWithTag(UiTags.MemorySearch).performTextReplacement("Android")
        compose.onNodeWithText("Builds Android apps").assertIsDisplayed()
        compose.onNodeWithTag(UiTags.MemoryFilterPrefix + "facts").performClick()
        compose.onNodeWithText("Builds Android apps").assertDoesNotExist()
        compose.onNodeWithTag("${UiTags.MemoryFactPrefix}fact-kotlin").assertDoesNotExist()

        compose.onNodeWithTag(UiTags.MemoryFilterPrefix + "summaries").performClick()
        compose.onNodeWithText("Builds Android apps").assertIsDisplayed()
    }

    @Test
    fun factDetailSupportsEditAndConfirmedDelete() {
        val savedExisting = AtomicReference<MemoryFact?>(null)
        val savedContent = AtomicReference("")
        val deleted = AtomicReference<MemoryFact?>(null)
        setMemoryContent(
            onSaveFact = { existing, content, _, _, done ->
                savedContent.set(content)
                savedExisting.set(existing)
                done()
            },
            onDeleteFact = { deleted.set(it) },
        )

        compose.onNodeWithTag(UiTags.MemoryFilterPrefix + "facts").performClick()
        compose.onNodeWithTag("${UiTags.MemoryFactPrefix}fact-kotlin").performClick()
        compose.onNodeWithTag(UiTags.MemoryFactDetailEdit).performScrollTo().performClick()
        compose.onNodeWithTag(UiTags.MemoryFactContent).performTextReplacement("Uses Kotlin and Compose")
        compose.waitForIdle()
        compose.onNodeWithTag(UiTags.MemoryFactSave).performScrollTo()
        compose.waitForIdle()
        compose.onNodeWithTag(UiTags.MemoryFactSave).assertIsEnabled().performClick()
        compose.waitUntil(timeoutMillis = 15_000) { savedExisting.get() != null }
        compose.waitForIdle()
        compose.onNodeWithTag(UiTags.MemoryFactContent).assertDoesNotExist()

        assertEquals("fact-kotlin", savedExisting.get()?.id)
        assertEquals("Uses Kotlin and Compose", savedContent.get())

        compose.onNodeWithTag("${UiTags.MemoryFactPrefix}fact-kotlin").performClick()
        compose.onNodeWithTag(UiTags.MemoryFactDetailDelete).performScrollTo().performClick()
        compose.onNodeWithTag(UiTags.MemoryFactDeleteConfirm).performClick()

        compose.waitUntil(timeoutMillis = 15_000) { deleted.get() != null }
        assertEquals("fact-kotlin", deleted.get()?.id)
    }

    @Test
    fun addAndClearActionsDispatchOnlyAfterConfirmation() {
        val createdContent = AtomicReference("")
        var clearCalls = 0
        setMemoryContent(
            onSaveFact = { existing, content, _, _, done ->
                assertNull(existing)
                createdContent.set(content)
                done()
            },
            onClearMemory = { clearCalls += 1 },
        )

        compose.onNodeWithTag(UiTags.MemoryAddFact).performClick()
        compose.onNodeWithTag(UiTags.MemoryFactContent).performTextReplacement("Prefers focused tests")
        compose.waitForIdle()
        compose.onNodeWithTag(UiTags.MemoryFactSave).performScrollTo()
        compose.waitForIdle()
        compose.onNodeWithTag(UiTags.MemoryFactSave).assertIsEnabled().performClick()
        compose.waitUntil(timeoutMillis = 15_000) { createdContent.get().isNotEmpty() }
        compose.waitForIdle()
        compose.onNodeWithTag(UiTags.MemoryFactContent).assertDoesNotExist()
        assertEquals("Prefers focused tests", createdContent.get())

        compose.onNodeWithTag(UiTags.MemoryMoreActions).performClick()
        compose.onNodeWithTag(UiTags.MemoryClearAction).performClick()
        assertEquals(0, clearCalls)
        compose.onNodeWithTag(UiTags.MemoryClearConfirm).performClick()
        assertEquals(1, clearCalls)
    }

    private fun setMemoryContent(
        onSaveFact: (MemoryFact?, String, String, Double, () -> Unit) -> Unit = { _, _, _, _, done -> done() },
        onDeleteFact: (MemoryFact) -> Unit = {},
        onClearMemory: () -> Unit = {},
    ) {
        compose.setContent {
            MaterialTheme {
                MemoryScreen(
                    state = AppUiState(
                        serverUrl = "http://memory.test",
                        memory = memoryFixture(),
                    ),
                    onBack = {},
                    contentPadding = PaddingValues(),
                    onRefresh = {},
                    onSaveFact = onSaveFact,
                    onDeleteFact = onDeleteFact,
                    onClearMemory = onClearMemory,
                )
            }
        }
    }

    private fun memoryFixture() = MemoryData(
        version = "1.0",
        lastUpdated = "2026-07-20T08:30:00Z",
        user = MemoryUserContext(
            workContext = MemorySection("Builds Android apps", "2026-07-20T08:00:00Z"),
            personalContext = MemorySection("Prefers concise answers", "2026-07-19T08:00:00Z"),
        ),
        history = MemoryHistoryContext(
            recentMonths = MemorySection("Migrated settings", "2026-07-18T08:00:00Z"),
        ),
        facts = listOf(
            MemoryFact("fact-kotlin", "Uses Kotlin", "technology", 0.95, "2026-07-20T08:00:00Z", "thread-1"),
            MemoryFact("fact-room", "Uses Room for cache", "technology", 0.9, "2026-07-20T08:10:00Z", "thread-2"),
        ),
    )
}
