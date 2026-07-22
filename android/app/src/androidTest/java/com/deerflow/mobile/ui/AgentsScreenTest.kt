package com.deerflow.mobile.ui

import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.material3.MaterialTheme
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onAllNodesWithTag
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextReplacement
import androidx.compose.ui.test.performTouchInput
import androidx.compose.ui.test.swipeUp
import androidx.test.core.app.ApplicationProvider
import com.deerflow.mobile.R
import com.deerflow.mobile.data.AgentInfo
import com.deerflow.mobile.data.AgentRunInfo
import com.deerflow.mobile.data.ModelInfo
import com.deerflow.mobile.data.WorkspaceCapabilities
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

class AgentsScreenTest {
    @get:Rule val compose = createComposeRule()

    @Test
    fun nonDefaultAgentStarDispatchesSelection() {
        var selected = ""
        setAgentRow(isDefault = false, onSetDefault = { selected = "researcher" })

        compose.onNodeWithTag(UiTags.AgentDefaultPrefix + "researcher").performClick()

        compose.runOnIdle { assertEquals("researcher", selected) }
    }

    @Test
    fun currentDefaultAgentUsesDefaultSemantics() {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        setAgentRow(isDefault = true)

        compose.onNodeWithContentDescription(context.getString(R.string.default_agent))
            .assertIsDisplayed()
    }

    @Test
    fun tappingAgentRowOpensDetail() {
        var opened = ""
        setAgentRow(isDefault = false, onOpen = { opened = "researcher" })

        compose.onNodeWithTag(UiTags.AgentRowPrefix + "researcher").performClick()

        compose.runOnIdle { assertEquals("researcher", opened) }
    }

    @Test
    fun detailShowsAgentConfigurationAndDispatchesActions() {
        var action = ""
        compose.setContent {
            MaterialTheme {
                AgentDetailScreen(
                    agent = AgentInfo(
                        name = "researcher",
                        description = "Checks every source",
                        model = "model-1",
                        skills = listOf("search", "reporting"),
                        soul = "Verify every claim.",
                    ),
                    isDefault = false,
                    mutationBusy = false,
                    onBack = { action = "back" },
                    onSetDefault = { action = "default" },
                    onChat = { action = "chat" },
                    onHistory = { action = "history" },
                    onEdit = { action = "edit" },
                    contentPadding = PaddingValues(),
                )
            }
        }

        compose.onNodeWithText("Checks every source").assertIsDisplayed()
        compose.onNodeWithText("model-1").assertIsDisplayed()
        compose.onNodeWithTag(UiTags.AgentDetailEdit).performClick()
        compose.runOnIdle { assertEquals("edit", action) }
        compose.onNodeWithText("search").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("reporting").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("Verify every claim.").performScrollTo().assertIsDisplayed()
        compose.onNodeWithTag(UiTags.AgentDetailChat).performScrollTo().performClick()
        compose.runOnIdle { assertEquals("chat", action) }
        compose.onNodeWithTag(UiTags.AgentDetailHistory).performScrollTo().performClick()
        compose.runOnIdle { assertEquals("history", action) }
        compose.onNodeWithTag(UiTags.AgentDetailSetDefault).performScrollTo().performClick()
        compose.runOnIdle { assertEquals("default", action) }
    }

    @Test
    fun builtInDefaultDetailHasNoEditOrSetDefaultAction() {
        compose.setContent {
            MaterialTheme {
                AgentDetailScreen(
                    agent = AgentInfo("lead_agent", "Built in", null, emptyList()),
                    isDefault = true,
                    mutationBusy = false,
                    onBack = {},
                    onSetDefault = {},
                    onChat = {},
                    onEdit = null,
                )
            }
        }

        compose.onNodeWithTag(UiTags.AgentDetailDefault).assertIsDisplayed()
        compose.onAllNodesWithTag(UiTags.AgentDetailEdit).assertCountEquals(0)
        compose.onAllNodesWithTag(UiTags.AgentDetailSetDefault).assertCountEquals(0)
    }

    @Test
    fun executionHistoryShowsRunDetailAndOpensConversation() {
        var openedRun = ""
        compose.setContent {
            MaterialTheme {
                AgentRunHistorySheet(
                    agent = AgentInfo("researcher", "Checks sources", null, emptyList()),
                    runs = listOf(
                        AgentRunInfo(
                            runId = "run-1",
                            threadId = "thread-1",
                            threadTitle = "Release review",
                            assistantId = "researcher",
                            status = "success",
                            modelName = "model-1",
                            createdAt = "2026-07-21T09:00:00Z",
                            updatedAt = "2026-07-21T09:00:12Z",
                            durationSeconds = 12.5,
                            totalTokens = 4312,
                            messageCount = 8,
                            cost = 0.0123,
                            error = null,
                        ),
                    ),
                    loading = false,
                    error = null,
                    onDismiss = {},
                    onRefresh = {},
                    onOpenConversation = { openedRun = it.runId },
                )
            }
        }

        compose.onNodeWithTag(UiTags.AgentRunHistorySheet).assertIsDisplayed()
        compose.onNodeWithTag(UiTags.AgentRunPrefix + "run-1").performClick()
        compose.onNodeWithText("Release review").assertIsDisplayed()
        compose.onNodeWithText("model-1").assertIsDisplayed()
        compose.onNodeWithText("4312").performScrollTo().assertIsDisplayed()
        repeat(3) {
            compose.onNodeWithTag(UiTags.AgentRunDetail).performTouchInput { swipeUp() }
        }
        compose.onNodeWithTag(UiTags.AgentRunOpenConversation).assertIsDisplayed().performClick()

        compose.runOnIdle { assertEquals("run-1", openedRun) }
    }

    @Test
    fun executionHistoryShowsErrorAndRetries() {
        var retries = 0
        compose.setContent {
            MaterialTheme {
                AgentRunHistorySheet(
                    agent = AgentInfo("researcher", "Checks sources", null, emptyList()),
                    runs = emptyList(),
                    loading = false,
                    error = "Console storage is unavailable.",
                    onDismiss = {},
                    onRefresh = { retries += 1 },
                    onOpenConversation = {},
                )
            }
        }

        compose.onNodeWithText("Console storage is unavailable.").assertIsDisplayed()
        compose.onNodeWithText("Retry").performClick()

        compose.runOnIdle { assertEquals(1, retries) }
    }

    @Test
    fun createAgentEditorCollectsNameDescriptionAndModel() {
        var saved: Triple<String, String, String?>? = null
        compose.setContent {
            MaterialTheme {
                AgentEditorSheet(
                    state = editorState(),
                    agent = null,
                    onDismiss = {},
                    onSave = { name, description, model -> saved = Triple(name, description, model) },
                    onDelete = null,
                )
            }
        }

        compose.onNodeWithTag(UiTags.AgentEditorName).performTextReplacement("analyst")
        compose.onNodeWithTag(UiTags.AgentEditorDescription).performTextReplacement("Checks financial evidence")
        compose.waitForIdle()
        compose.onNodeWithTag(UiTags.AgentEditorModelPrefix + "model-1").performClick()
        compose.onNodeWithTag(UiTags.AgentEditorSave).performScrollTo()
        compose.waitForIdle()
        compose.onNodeWithTag(UiTags.AgentEditorSave).assertIsEnabled().performClick()
        compose.waitUntil(timeoutMillis = 5_000) { saved != null }

        compose.runOnIdle {
            assertEquals(Triple("analyst", "Checks financial evidence", "model-1"), saved)
        }
    }

    @Test
    fun editAgentLocksNameAndDispatchesUpdateAndDelete() {
        val existing = AgentInfo("researcher", "Old description", "model-1", emptyList())
        var saved: Triple<String, String, String?>? = null
        var deletes = 0
        compose.setContent {
            MaterialTheme {
                AgentEditorSheet(
                    state = editorState(),
                    agent = existing,
                    onDismiss = {},
                    onSave = { name, description, model -> saved = Triple(name, description, model) },
                    onDelete = { deletes += 1 },
                )
            }
        }

        compose.onNodeWithTag(UiTags.AgentEditorName).assertIsNotEnabled()
        compose.onNodeWithTag(UiTags.AgentEditorDescription).performTextReplacement("Updated description")
        compose.waitForIdle()
        compose.onNodeWithTag(UiTags.AgentEditorModelPrefix + "server-default").performClick()
        compose.onNodeWithTag(UiTags.AgentEditorSave).performScrollTo()
        compose.waitForIdle()
        compose.onNodeWithTag(UiTags.AgentEditorSave).assertIsEnabled().performClick()
        compose.waitUntil(timeoutMillis = 5_000) { saved != null }
        compose.onNodeWithTag(UiTags.AgentEditorDelete).performScrollTo()
        compose.waitForIdle()
        compose.onNodeWithTag(UiTags.AgentEditorDelete).assertIsEnabled().performClick()
        compose.waitUntil(timeoutMillis = 5_000) { deletes == 1 }

        compose.runOnIdle {
            assertEquals(Triple("researcher", "Updated description", null), saved)
            assertEquals(1, deletes)
        }
    }

    private fun setAgentRow(
        isDefault: Boolean,
        onOpen: () -> Unit = {},
        onSetDefault: () -> Unit = {},
    ) {
        compose.setContent {
            MaterialTheme {
                AgentRow(
                    agent = AgentInfo("researcher", "Checks evidence", "model-1", emptyList()),
                    isDefault = isDefault,
                    onOpen = onOpen,
                    onSetDefault = onSetDefault,
                    onChat = {},
                    onEdit = {},
                )
            }
        }
    }

    private fun editorState() = AppUiState(
        serverUrl = "http://10.0.2.2:2027",
        capabilities = WorkspaceCapabilities(
            models = listOf(ModelInfo("model-1", "Model One", "", true, true)),
            agentsEnabled = true,
        ),
    )
}
