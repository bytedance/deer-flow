package com.deerflow.mobile.ui

import androidx.compose.ui.text.TextRange
import androidx.compose.ui.text.input.TextFieldValue
import com.deerflow.mobile.data.ComposerState
import com.deerflow.mobile.data.RunOptions
import com.deerflow.mobile.data.SkillInfo
import com.deerflow.mobile.data.WorkspaceCapabilities
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ChatComposerTest {
    @Test
    fun `skill command is inserted at the cursor with trailing space`() {
        val result = insertSkillCommand(
            value = TextFieldValue("hello world", selection = TextRange(6)),
            skillName = "animate",
        )

        assertEquals("hello /animate world", result.text)
        assertEquals(TextRange(15), result.selection)
    }

    @Test
    fun `skill command replaces the selected text`() {
        val result = insertSkillCommand(
            value = TextFieldValue("use old now", selection = TextRange(4, 7)),
            skillName = "/animate",
        )

        assertEquals("use /animate  now", result.text)
        assertEquals(TextRange(13), result.selection)
    }

    @Test
    fun `thread load result only applies to the still selected conversation`() {
        assertTrue(isCurrentThreadLoad("thread-2", "thread-2"))
        assertFalse(isCurrentThreadLoad("thread-2", "thread-1"))
        assertFalse(isCurrentThreadLoad(null, "thread-1"))
    }

    @Test
    fun `quick action replaces non-empty draft and adds matching enabled skill`() {
        val updated = applyQuickActionToComposer(
            composer = ComposerState(
                text = "Existing draft",
                options = RunOptions(enabledSkills = setOf("already-enabled")),
            ),
            capabilities = WorkspaceCapabilities(
                skills = listOf(
                    SkillInfo("deep-research", "Research reports", "research", enabled = true),
                ),
            ),
            prompt = "Research [topic]",
            skillKeywords = listOf("research"),
        )

        assertEquals("Research [topic]", updated.text)
        assertEquals(setOf("already-enabled", "deep-research"), updated.options.enabledSkills)
    }

    @Test
    fun `quick action ignores matching disabled skill`() {
        val updated = applyQuickActionToComposer(
            composer = ComposerState(text = "Existing draft"),
            capabilities = WorkspaceCapabilities(
                skills = listOf(
                    SkillInfo("deep-research", "Research reports", "research", enabled = false),
                ),
            ),
            prompt = "Research [topic]",
            skillKeywords = listOf("research"),
        )

        assertEquals("Research [topic]", updated.text)
        assertTrue(updated.options.enabledSkills.isEmpty())
    }
}
