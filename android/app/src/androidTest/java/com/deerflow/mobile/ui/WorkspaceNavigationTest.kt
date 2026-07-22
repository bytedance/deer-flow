package com.deerflow.mobile.ui

import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.assertIsFocused
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertIsNotFocused
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.longClick
import androidx.compose.ui.test.onAllNodesWithContentDescription
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performTextReplacement
import androidx.compose.ui.test.performTouchInput
import androidx.test.core.app.ApplicationProvider
import com.deerflow.mobile.R
import com.deerflow.mobile.data.ThreadSummary
import com.deerflow.mobile.data.TodoItem
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

class WorkspaceNavigationTest {
    @get:Rule val compose = createComposeRule()

    private val context = ApplicationProvider.getApplicationContext<android.content.Context>()

    @Test
    fun drawerAgentsDestinationUsesChildRoute() {
        var destination: DrawerDestination? = null
        compose.setContent {
            MaterialTheme {
                WorkspaceDrawer(
                    state = AppUiState(serverUrl = "http://10.0.2.2:2027"),
                    onNewChat = {},
                    onOpenThread = {},
                    onRenameThread = { _, _ -> },
                    onDeleteThread = {},
                    onPinThread = {},
                    onDestination = { destination = it },
                )
            }
        }

        compose.onNodeWithText("Agents").performClick()
        compose.runOnIdle { assertEquals(DrawerDestination.Agents, destination) }
    }

    @Test
    fun drawerHasOneWorkingNewChatActionAndSearchStartsUnfocused() {
        var newChatClicks = 0
        compose.setContent {
            MaterialTheme {
                WorkspaceDrawer(
                    state = AppUiState(serverUrl = "http://10.0.2.2:2027"),
                    onNewChat = { newChatClicks += 1 },
                    onOpenThread = {},
                    onRenameThread = { _, _ -> },
                    onDeleteThread = {},
                    onPinThread = {},
                    onDestination = {},
                )
            }
        }

        compose.onNodeWithTag(UiTags.ConversationSearch).assertIsNotFocused()
        compose.onNodeWithTag(UiTags.NewChatButton).performClick()
        compose.runOnIdle { assertEquals(1, newChatClicks) }
    }

    @Test
    fun drawerHeaderProfileIconOpensProfileWithoutADuplicateAction() {
        var profileOpens = 0
        compose.setContent {
            MaterialTheme {
                WorkspaceDrawer(
                    state = AppUiState(serverUrl = "http://10.0.2.2:2027"),
                    onNewChat = {},
                    onOpenThread = {},
                    onRenameThread = { _, _ -> },
                    onDeleteThread = {},
                    onPinThread = {},
                    onDestination = {},
                    onOpenProfile = { profileOpens += 1 },
                )
            }
        }

        compose
            .onAllNodesWithContentDescription(context.getString(R.string.tab_profile))
            .assertCountEquals(1)
        compose.onNodeWithContentDescription(context.getString(R.string.tab_profile)).performClick()
        compose.runOnIdle { assertEquals(1, profileOpens) }
    }

    @Test
    fun chatTopBarShowsMenuInWorkspaceAndBackInsideConversation() {
        var openDrawer = 0
        var goBack = 0
        val route = mutableStateOf(AppRoute.Workspace)
        compose.setContent {
            MaterialTheme {
                ChatTopBar(
                    state = AppUiState(serverUrl = "http://10.0.2.2:2027", route = route.value),
                    onOpenDrawer = { openDrawer += 1 },
                    onBack = { goBack += 1 },
                    onModelSelected = {},
                    onModeSelected = {},
                    onExport = {},
                    expandedSelector = null,
                    onExpandedSelectorChange = {},
                )
            }
        }

        compose.onNodeWithContentDescription(context.getString(R.string.open_navigation)).performClick()
        compose.onNodeWithContentDescription(context.getString(R.string.back)).assertDoesNotExist()
        compose.runOnIdle {
            assertEquals(1, openDrawer)
            assertEquals(0, goBack)
            route.value = AppRoute.Conversation
        }
        compose.waitForIdle()

        compose.onNodeWithContentDescription(context.getString(R.string.back)).performClick()
        compose.onNodeWithContentDescription(context.getString(R.string.open_navigation)).assertDoesNotExist()
        compose.runOnIdle {
            assertEquals(1, openDrawer)
            assertEquals(1, goBack)
        }
    }

    @Test
    fun conversationLongPressPinsSelectedThread() {
        val thread = testThread()
        var pinned: ThreadSummary? = null
        setDrawer(thread, onPin = { pinned = it })

        openThreadMenu(thread)
        compose.onNodeWithTag(UiTags.ThreadPinAction).performClick()

        compose.runOnIdle { assertEquals(thread, pinned) }
    }

    @Test
    fun conversationLongPressRenamesSelectedThread() {
        val thread = testThread()
        var renamed: Pair<ThreadSummary, String>? = null
        setDrawer(thread, onRename = { selected, title -> renamed = selected to title })

        openThreadMenu(thread)
        compose.onNodeWithTag(UiTags.ThreadRenameAction).performClick()
        compose.onNodeWithTag(UiTags.ThreadRenameTitle).performTextReplacement("Updated title")
        compose.waitForIdle()
        compose.onNodeWithTag(UiTags.ThreadRenameSave).assertIsEnabled().performClick()
        compose.waitUntil(timeoutMillis = 5_000) { renamed != null }

        compose.runOnIdle { assertEquals(thread to "Updated title", renamed) }
    }

    @Test
    fun conversationLongPressDeletesOnlyAfterConfirmation() {
        val thread = testThread()
        var deleted: ThreadSummary? = null
        setDrawer(thread, onDelete = { deleted = it })

        openThreadMenu(thread)
        compose.onNodeWithTag(UiTags.ThreadDeleteAction).performClick()
        compose.runOnIdle { assertEquals(null, deleted) }
        compose.onNodeWithTag(UiTags.ThreadDeleteConfirm).performClick()

        compose.runOnIdle { assertEquals(thread, deleted) }
    }

    @Test
    fun todoSummaryExpandsAndShowsProgress() {
        compose.setContent {
            MaterialTheme {
                TodoSummary(
                    listOf(
                        TodoItem("Inspect code", "completed"),
                        TodoItem("Add tests", "in_progress"),
                    ),
                )
            }
        }

        compose.onNodeWithText("Todo progress: 1/2 complete").assertExists()
        compose.onNodeWithText("Add tests").assertDoesNotExist()
        compose.onNodeWithText("Todo progress: 1/2 complete").performClick()
        compose.onNodeWithText("Add tests").assertExists()
    }

    @Test
    fun codeArtifactPreviewShowsDetectedLanguage() {
        compose.setContent {
            MaterialTheme {
                ArtifactPreviewDialog(
                    preview = ArtifactPreviewState(
                        path = "mnt/user-data/outputs/Main.kt",
                        filename = "Main.kt",
                        mimeType = "text/plain",
                        text = "fun main() = println(42)",
                        localPath = "/tmp/Main.kt",
                    ),
                    onDismiss = {},
                    onSave = {},
                    onOpen = {},
                )
            }
        }

        compose.onNodeWithText("kotlin").assertExists()
        compose.onNodeWithText("fun main() = println(42)").assertExists()
    }

    private fun setDrawer(
        thread: ThreadSummary,
        onRename: (ThreadSummary, String) -> Unit = { _, _ -> },
        onDelete: (ThreadSummary) -> Unit = {},
        onPin: (ThreadSummary) -> Unit = {},
    ) {
        compose.setContent {
            MaterialTheme {
                WorkspaceDrawer(
                    state = AppUiState(
                        serverUrl = "http://10.0.2.2:2027",
                        threads = listOf(thread),
                    ),
                    onNewChat = {},
                    onOpenThread = {},
                    onRenameThread = onRename,
                    onDeleteThread = onDelete,
                    onPinThread = onPin,
                    onDestination = {},
                )
            }
        }
    }

    private fun openThreadMenu(thread: ThreadSummary) {
        compose.onNodeWithTag(UiTags.ThreadRowPrefix + thread.id).performTouchInput { longClick() }
    }

    private fun testThread() = ThreadSummary(
        id = "thread-1",
        title = "Original title",
        status = "idle",
        updatedAt = "2026-07-20T10:00:00Z",
    )
}
