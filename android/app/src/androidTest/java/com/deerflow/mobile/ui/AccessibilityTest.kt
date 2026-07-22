package com.deerflow.mobile.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.width
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.SemanticsNodeInteraction
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.text.input.TextFieldValue
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.dp
import androidx.test.core.app.ApplicationProvider
import com.deerflow.mobile.R
import com.deerflow.mobile.data.ChatMessage
import com.deerflow.mobile.data.ComposerState
import com.deerflow.mobile.data.MessageRole
import com.deerflow.mobile.data.ModelInfo
import com.deerflow.mobile.data.RunMode
import com.deerflow.mobile.data.RunOptions
import com.deerflow.mobile.data.ScheduledTaskInfo
import com.deerflow.mobile.data.WorkspaceCapabilities
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

class AccessibilityTest {
    @get:Rule val compose = createComposeRule()

    private val context = ApplicationProvider.getApplicationContext<android.content.Context>()

    @Test
    fun primaryChatControlsExposeTalkBackDescriptions() {
        setChatSurface()

        listOf(
            R.string.back,
            R.string.export_conversation,
            R.string.add_attachment,
            R.string.send_message,
        ).forEach { label ->
            compose.onNodeWithContentDescription(context.getString(label)).assertIsDisplayed()
        }
    }

    @Test
    fun taskStatusExposesTalkBackDescription() {
        compose.setContent {
            MaterialTheme {
                TaskRow(
                    task = task(status = "paused"),
                    onPause = {},
                    onTrigger = {},
                    onEdit = {},
                    onDelete = {},
                )
            }
        }
        compose.onNodeWithContentDescription(context.getString(R.string.status_description, "paused"))
            .assertIsDisplayed()
    }

    @Test
    fun chatTopBarDeclaresNavigationSelectorAndActionTraversalOrder() {
        setChatSurface()

        val actual = listOf(
            UiTags.ChatNavigationButton,
            UiTags.ModelSelector,
            UiTags.ModeSelector,
            UiTags.ConversationExportButton,
        ).map { tag ->
            compose.onNodeWithTag(tag).fetchSemanticsNode().config[SemanticsProperties.TraversalIndex]
        }

        assertEquals(listOf(0f, 1f, 2f, 3f), actual)
    }

    @Test
    fun primaryChatActionsMeetThe48DpMinimumTouchTarget() {
        setChatSurface()
        val minimumPx = with(compose.density) { 48.dp.toPx() }

        listOf(
            UiTags.ChatNavigationButton,
            UiTags.ModelSelector,
            UiTags.ModeSelector,
            UiTags.ConversationExportButton,
            UiTags.ComposerAttachmentButton,
            UiTags.SendStopButton,
        ).forEach { tag ->
            val bounds = compose.onNodeWithTag(tag).fetchSemanticsNode().boundsInRoot
            assertTrue("$tag width ${bounds.width} is below $minimumPx", bounds.width >= minimumPx)
            assertTrue("$tag height ${bounds.height} is below $minimumPx", bounds.height >= minimumPx)
        }
    }

    @Test
    fun phoneChatControlsStayInsideBoundsWithoutOverlapAtOnePointThreeFontScale() {
        val state = chatState()
        compose.setContent {
            val density = LocalDensity.current
            CompositionLocalProvider(LocalDensity provides Density(density.density, fontScale = 1.3f)) {
                MaterialTheme {
                    Column(Modifier.width(360.dp).testTag(VIEWPORT_TAG)) {
                        var expanded by remember { mutableStateOf<TopSelectorKind?>(null) }
                        ChatTopBar(
                            state = state,
                            onOpenDrawer = {},
                            onBack = {},
                            onModelSelected = {},
                            onModeSelected = {},
                            onExport = {},
                            expandedSelector = expanded,
                            onExpandedSelectorChange = { expanded = it },
                        )
                        Spacer(Modifier.height(16.dp))
                        MessageComposer(
                            state = state,
                            editorValue = TextFieldValue(state.composer.text),
                            onDraftChange = {},
                            onAttachment = {},
                            onAgent = {},
                            onQuickAction = { _, _ -> },
                            onRemoveAttachment = {},
                            onRetryAttachment = {},
                            onSend = {},
                            onStop = {},
                        )
                    }
                }
            }
        }

        val viewport = compose.onNodeWithTag(VIEWPORT_TAG).bounds()
        val topControls = listOf(
            UiTags.ChatNavigationButton,
            UiTags.ModelSelector,
            UiTags.ModeSelector,
            UiTags.ConversationExportButton,
        ).map { compose.onNodeWithTag(it).bounds() }
        val composerControls = listOf(
            UiTags.ComposerInput,
            UiTags.SendStopButton,
        ).map { compose.onNodeWithTag(it).bounds() }

        (topControls + composerControls).forEach { bounds ->
            assertTrue("Control $bounds is clipped by $viewport", viewport.containsRect(bounds))
        }
        topControls.zipWithNext().forEach { (left, right) ->
            assertTrue("Top controls overlap: $left and $right", left.right <= right.left)
        }
        assertTrue(
            "Composer input overlaps send action: ${composerControls[0]} and ${composerControls[1]}",
            composerControls[0].right <= composerControls[1].left,
        )
    }

    private fun setChatSurface() {
        val state = chatState()
        compose.setContent {
            MaterialTheme {
                Column {
                    var expanded by remember { mutableStateOf<TopSelectorKind?>(null) }
                    ChatTopBar(
                        state = state,
                        onOpenDrawer = {},
                        onBack = {},
                        onModelSelected = {},
                        onModeSelected = {},
                        onExport = {},
                        expandedSelector = expanded,
                        onExpandedSelectorChange = { expanded = it },
                    )
                    MessageComposer(
                        state = state,
                        editorValue = TextFieldValue(state.composer.text),
                        onDraftChange = {},
                        onAttachment = {},
                        onAgent = {},
                        onQuickAction = { _, _ -> },
                        onRemoveAttachment = {},
                        onRetryAttachment = {},
                        onSend = {},
                        onStop = {},
                    )
                }
            }
        }
    }

    private fun chatState() = AppUiState(
        serverUrl = "http://10.0.2.2:2027",
        route = AppRoute.Conversation,
        checkingSession = false,
        messages = listOf(ChatMessage("assistant-1", MessageRole.Assistant, "Ready to help.")),
        composer = ComposerState(
            text = "Review the latest workspace changes",
            options = RunOptions(modelName = "research", mode = RunMode.Thinking),
        ),
        capabilities = WorkspaceCapabilities(
            models = listOf(
                ModelInfo(
                    name = "research",
                    displayName = "DeerFlow Research Model",
                    description = "Research",
                    supportsThinking = true,
                    supportsReasoningEffort = true,
                ),
            ),
        ),
    )

    private fun task(status: String) = ScheduledTaskInfo(
        id = "task-1",
        title = "Daily brief",
        prompt = "Review changes",
        scheduleType = "cron",
        scheduleLabel = "0 9 * * *",
        timezone = "UTC",
        status = status,
        nextRunAt = null,
        lastError = null,
        runCount = 2,
    )

    private fun SemanticsNodeInteraction.bounds(): Rect = fetchSemanticsNode().boundsInRoot

    private fun Rect.containsRect(other: Rect): Boolean =
        other.left >= left && other.top >= top && other.right <= right && other.bottom <= bottom

    private companion object {
        const val VIEWPORT_TAG = "accessibility-viewport"
    }
}
