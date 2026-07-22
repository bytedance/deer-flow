package com.deerflow.mobile.ui

import androidx.compose.material3.MaterialTheme
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithContentDescription
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performTextInput
import com.deerflow.mobile.data.ChatMessage
import com.deerflow.mobile.data.ChatMessageGroup
import com.deerflow.mobile.data.HumanInputOption
import com.deerflow.mobile.data.HumanInputRequest
import com.deerflow.mobile.data.MessageBlock
import com.deerflow.mobile.data.MessageRole
import com.deerflow.mobile.data.AttachmentStatus
import com.deerflow.mobile.data.PendingAttachment
import com.deerflow.mobile.data.TokenUsage
import com.deerflow.mobile.data.groupChatMessages
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

class MessageContentTest {
    @get:Rule val compose = createComposeRule()

    @Test
    fun processingGroupCollapsesPreviousStepsAndKeepsLatestToolVisible() {
        val group = ChatMessageGroup.Processing(
            key = "processing",
            messages = listOf(
                ChatMessage(
                    id = "ai-1",
                    role = MessageRole.Assistant,
                    text = "",
                    blocks = listOf(
                        MessageBlock.Reasoning("Plan the search"),
                        MessageBlock.ToolCall("web_search", "{\"query\":\"old query\"}", "call-1"),
                        MessageBlock.Reasoning("Review the result"),
                        MessageBlock.ToolCall("bash", "{\"description\":\"Inspect renderer\"}", "call-2"),
                    ),
                ),
            ),
        )
        compose.setContent {
            MaterialTheme {
                ChatMessageGroupItem(group, runActive = true, onHumanInput = { _, _, _ -> })
            }
        }

        compose.onNodeWithText("3 more steps").assertExists()
        compose.onNodeWithText("Inspect renderer").assertExists()
        compose.onNodeWithText("Plan the search").assertDoesNotExist()
        compose.onNodeWithText("web_search: old query").assertDoesNotExist()

        compose.onNodeWithText("3 more steps").performClick()

        compose.onNodeWithText("Plan the search").assertExists()
        compose.onNodeWithText("web_search: old query").assertExists()
    }

    @Test
    fun webSearchToolShowsLinkedSourceResults() {
        setProcessingToolResult(
            MessageBlock.ToolCall("web_search", "{\"query\":\"Android\"}", "search-1"),
            MessageBlock.ToolResult(
                "search-1",
                "web_search",
                """{"results":[{"title":"Android Developers","url":"https://developer.android.com","content":"Official Android documentation"}]}""",
            ),
        )

        compose.onNodeWithText("web_search: Android").assertExists()
        compose.onNodeWithText("Android Developers").assertDoesNotExist()
    }

    @Test
    fun imageSearchToolShowsResultTilesWithoutRequestingRemoteImages() {
        setProcessingToolResult(
            MessageBlock.ToolCall("image_search", "{\"query\":\"mountains\"}", "image-1"),
            MessageBlock.ToolResult(
                "image-1",
                "image_search",
                """{"results":[{"title":"Mountain reference","source_url":"https://source.example/mountain"}]}""",
            ),
        )

        compose.onNodeWithText("image_search: mountains").assertExists()
        compose.onNodeWithText("Mountain reference").assertDoesNotExist()
    }

    @Test
    fun directoryToolShowsEntriesInsteadOfRawOutput() {
        setProcessingToolResult(
            MessageBlock.ToolCall("ls", "{\"path\":\"/mnt/work\"}", "list-1"),
            MessageBlock.ToolResult("list-1", "ls", "src/\nREADME.md"),
        )

        compose.onNodeWithText("ls: /mnt/work").assertExists()
        compose.onNodeWithText("src/").assertDoesNotExist()
    }

    @Test
    fun shellToolShowsCommandAndDedicatedOutput() {
        setProcessingToolResult(
            MessageBlock.ToolCall("bash", "{\"command\":\"echo hello\"}", "shell-1"),
            MessageBlock.ToolResult("shell-1", "bash", "hello"),
        )

        compose.onNodeWithText("bash: echo hello").assertExists()
        compose.onNodeWithText("hello").assertDoesNotExist()
    }

    @Test
    fun humanInputChoiceSubmitsStructuredOption() {
        val request = HumanInputRequest(
            source = "ask_clarification",
            requestId = "request-1",
            toolCallId = "call-1",
            title = null,
            question = "Which format should I use?",
            context = null,
            inputMode = "choice_with_other",
            options = listOf(HumanInputOption("option-0", "Markdown", "Markdown")),
        )
        var submitted: Triple<String, String, String?>? = null
        compose.setContent {
            MaterialTheme {
                ChatMessageGroupItem(
                    group = ChatMessageGroup.HumanInput(request, response = null, isLatestOpen = true),
                    runActive = false,
                    onHumanInput = { valueRequest, value, optionId ->
                        submitted = Triple(valueRequest.requestId, value, optionId)
                    },
                )
            }
        }

        compose.onNodeWithText("Needs your help").assertExists()
        compose.onNodeWithText("Markdown").performClick()
        compose.runOnIdle { assertEquals(Triple("request-1", "Markdown", "option-0"), submitted) }
    }

    @Test
    fun humanInputFreeTextSubmitsTypedAnswer() {
        val request = HumanInputRequest(
            source = "ask_clarification",
            requestId = "request-free-text",
            toolCallId = "call-free-text",
            title = null,
            question = "What should I continue with?",
            context = null,
            inputMode = "free_text",
            options = emptyList(),
        )
        var submitted: Triple<String, String, String?>? = null
        compose.setContent {
            MaterialTheme {
                ChatMessageGroupItem(
                    group = ChatMessageGroup.HumanInput(request, response = null, isLatestOpen = true),
                    runActive = false,
                    onHumanInput = { valueRequest, value, optionId ->
                        submitted = Triple(valueRequest.requestId, value, optionId)
                    },
                )
            }
        }

        compose.onNodeWithTag(UiTags.HumanInputText).performTextInput("Continue the session")
        compose.onNodeWithTag(UiTags.HumanInputSubmit).performClick()

        compose.runOnIdle {
            assertEquals(Triple("request-free-text", "Continue the session", null), submitted)
        }
    }

    @Test
    fun approvalRequestShowsDistinctApprovalCardAndSubmitsChoice() {
        val request = HumanInputRequest(
            source = "ask_clarification",
            requestId = "approval-1",
            toolCallId = "call-approval",
            title = null,
            clarificationType = "risk_confirmation",
            question = "Delete the selected files?",
            context = null,
            inputMode = "single_choice",
            options = listOf(HumanInputOption("approve", "Approve", "yes")),
        )
        var submitted: Triple<String, String, String?>? = null
        compose.setContent {
            MaterialTheme {
                ChatMessageGroupItem(
                    group = ChatMessageGroup.Approval(request, response = null, isLatestOpen = true),
                    runActive = false,
                    onHumanInput = { valueRequest, value, optionId ->
                        submitted = Triple(valueRequest.requestId, value, optionId)
                    },
                )
            }
        }

        compose.onNodeWithText("Approval required").assertExists()
        compose.onNodeWithText("Approve").performClick()
        compose.runOnIdle { assertEquals(Triple("approval-1", "yes", "approve"), submitted) }
    }

    @Test
    fun userMessageDoesNotExposeEditAndResendAction() {
        compose.setContent {
            MaterialTheme {
                ChatMessageGroupItem(
                    group = ChatMessageGroup.Message(ChatMessage("human-1", MessageRole.User, "Original prompt")),
                    runActive = false,
                    onHumanInput = { _, _, _ -> },
                )
            }
        }

        compose.onNodeWithText("Original prompt").assertExists()
        assertEquals(0, compose.onAllNodesWithContentDescription("Edit and resend").fetchSemanticsNodes().size)
    }

    @Test
    fun assistantActionsInvokeCopyAndBranchCallbacks() {
        var copied = ""
        var branched = ""
        compose.setContent {
            MaterialTheme {
                ChatMessageGroupItem(
                    group = ChatMessageGroup.Message(ChatMessage("ai-1", MessageRole.Assistant, "Answer")),
                    runActive = false,
                    onHumanInput = { _, _, _ -> },
                    onCopy = { copied = it },
                    onBranch = { branched = it },
                )
            }
        }

        compose.onNodeWithContentDescription("Copy").performClick()
        compose.onNodeWithContentDescription("Branch conversation").performClick()
        compose.runOnIdle {
            assertEquals("ai-1", copied)
            assertEquals("ai-1", branched)
        }
        assertEquals(0, compose.onAllNodesWithContentDescription("Regenerate response").fetchSemanticsNodes().size)
    }

    @Test
    fun assistantMessageShowsCopyActionAndTokenUsage() {
        compose.setContent {
            MaterialTheme {
                ChatMessageGroupItem(
                    group = ChatMessageGroup.Message(
                        ChatMessage(
                            id = "ai-usage",
                            role = MessageRole.Assistant,
                            text = "Completed response",
                            tokenUsage = TokenUsage(12, 34, 46),
                        ),
                    ),
                    runActive = false,
                    onHumanInput = { _, _, _ -> },
                )
            }
        }

        compose.onNodeWithContentDescription("Copy").assertExists()
        compose.onNodeWithText("Tokens · In 12 · Out 34 · Total 46").assertExists()
    }

    @Test
    fun finalReplyKeepsThoughtCollapsedWhileMarkdownRemainsVisible() {
        val tool = ChatMessage(
            id = "ai-tool",
            role = MessageRole.Assistant,
            text = "",
            blocks = listOf(MessageBlock.ToolCall("web_search", "{}", "search-1")),
        )
        val final = ChatMessage(
            id = "ai-reasoning",
            role = MessageRole.Assistant,
            text = "Final answer",
            blocks = listOf(
                MessageBlock.Markdown("Final answer"),
                MessageBlock.Reasoning("Private rationale"),
            ),
        )
        compose.setContent {
            MaterialTheme {
                androidx.compose.foundation.layout.Column {
                    groupChatMessages(listOf(tool, final)).forEach { group ->
                        ChatMessageGroupItem(
                            group = group,
                            runActive = false,
                            onHumanInput = { _, _, _ -> },
                        )
                    }
                }
            }
        }

        compose.onNodeWithText("Final answer").assertExists()
        compose.onNodeWithText("Private rationale").assertDoesNotExist()
        val cardBounds = compose.onNodeWithTag(UiTags.ProcessingCard).fetchSemanticsNode().boundsInRoot
        val reasoningBounds = compose.onNodeWithText("Reasoning").fetchSemanticsNode().boundsInRoot
        assertTrue(reasoningBounds.top >= cardBounds.top && reasoningBounds.bottom <= cardBounds.bottom)
        compose.onNodeWithText("Reasoning").performClick()
        compose.onNodeWithText("Private rationale").assertExists()
    }

    @Test
    fun finalTableReplyPlacesTheReasoningControlAboveTheTable() {
        val final = ChatMessage(
            id = "ai-table",
            role = MessageRole.Assistant,
            text = "| Column 1 | Column 2 |\n| --- | --- |\n| One | Two |",
            blocks = listOf(
                MessageBlock.Markdown("| Column 1 | Column 2 |\n| --- | --- |\n| One | Two |"),
                MessageBlock.Reasoning("Explain the table"),
            ),
        )
        val group = groupChatMessages(listOf(final)).single()

        compose.setContent {
            MaterialTheme {
                ChatMessageGroupItem(
                    group = group,
                    runActive = false,
                    onHumanInput = { _, _, _ -> },
                )
            }
        }

        val reasoningBounds = compose.onNodeWithText("Reasoning", useUnmergedTree = true).fetchSemanticsNode().boundsInRoot
        val tableBounds = compose.onNodeWithText("Column 1", useUnmergedTree = true).fetchSemanticsNode().boundsInRoot
        assertTrue(
            "Reasoning bounds $reasoningBounds should be above table bounds $tableBounds",
            reasoningBounds.bottom <= tableBounds.top,
        )
        compose.onNodeWithText("Reasoning").performClick()
        compose.onNodeWithText("Explain the table").assertExists()
    }

    @Test
    fun processingGroupShowsThinkingIndicatorBeforeAnyToolCall() {
        compose.setContent {
            MaterialTheme {
                ChatMessageGroupItem(
                    group = ChatMessageGroup.Processing(
                        key = "thinking",
                        messages = listOf(ChatMessage("ai-thinking", MessageRole.Assistant, "")),
                    ),
                    runActive = true,
                    onHumanInput = { _, _, _ -> },
                )
            }
        }

        compose.onNodeWithText("Thinking").assertExists()
    }

    @Test
    fun markdownTableAndArtifactLinkRenderThroughNativeHandlers() {
        var opened = ""
        compose.setContent {
            MaterialTheme {
                MarkdownContent(
                    "| Name | Value |\n| --- | --- |\n| Deer | Flow |\n\n[Download report](/mnt/user-data/outputs/report.md)",
                    onArtifact = { opened = it },
                )
            }
        }

        compose.onNodeWithText("Name").assertExists()
        compose.onNodeWithText("Flow").assertExists()
        compose.onNodeWithText("Download report").performClick()
        compose.runOnIdle { assertEquals("/mnt/user-data/outputs/report.md", opened) }
    }

    @Test
    fun failedAttachmentOffersRetryAction() {
        var retried = ""
        compose.setContent {
            MaterialTheme {
                AttachmentChip(
                    file = PendingAttachment(
                        uri = "content://failed",
                        filename = "report.pdf",
                        mimeType = "application/pdf",
                        size = 42,
                        status = AttachmentStatus.Failed,
                        error = "network",
                    ),
                    onRemove = {},
                    onRetry = { retried = "content://failed" },
                )
            }
        }

        compose.onNodeWithContentDescription("Retry upload").performClick()
        compose.runOnIdle { assertEquals("content://failed", retried) }
    }

    @Test
    fun subtaskBlockShowsStructuredLifecycleState() {
        compose.setContent {
            MaterialTheme {
                ChatMessageGroupItem(
                    group = ChatMessageGroup.Processing(
                        key = "processing-task",
                        messages = listOf(
                            ChatMessage(
                                id = "task-1",
                                role = MessageRole.Assistant,
                                text = "",
                                blocks = listOf(
                                    MessageBlock.Subtask(
                                        callId = "task-1",
                                        subagentType = "researcher",
                                        description = "Check the docs",
                                        prompt = "Read the API docs",
                                        status = MessageBlock.SubtaskStatus.Completed,
                                        result = "Done",
                                    ),
                                ),
                            ),
                        ),
                    ),
                    runActive = false,
                    onHumanInput = { _, _, _ -> },
                )
            }
        }

        compose.onNodeWithText("Check the docs").assertExists()
        compose.onNodeWithText("Subtask completed").assertExists()
        compose.onNodeWithText("Done").assertDoesNotExist()
        compose.onNodeWithText("Check the docs").performClick()
        compose.onNodeWithText("Done").assertExists()
    }

    @Test
    fun presentFilesMessageRendersInsideTheFinalConversationReply() {
        var opened = ""
        val tool = ChatMessage(
            id = "ai-tool",
            role = MessageRole.Assistant,
            text = "",
            blocks = listOf(MessageBlock.ToolCall("bash", "{}", "call-1")),
        )
        val message = ChatMessage(
            id = "ai-artifact",
            role = MessageRole.Assistant,
            text = "",
            blocks = listOf(
                MessageBlock.ToolCall("present_files", "{\"filepaths\":[\"mnt/user-data/outputs/report.md\"]}", "files-1"),
                MessageBlock.Artifact("report.md", "mnt/user-data/outputs/report.md"),
            ),
        )
        val result = ChatMessage(
            id = "files-result",
            role = MessageRole.Tool,
            text = "Successfully presented files",
            blocks = listOf(MessageBlock.ToolResult("files-1", "present_files", "Successfully presented files")),
        )
        val final = ChatMessage("ai-final", MessageRole.Assistant, "The report is ready.")
        val group = groupChatMessages(listOf(tool, message, result, final)).last()
        assertTrue(group is ChatMessageGroup.Message)
        compose.setContent {
            MaterialTheme {
                ChatMessageGroupItem(
                    group = group,
                    runActive = false,
                    onHumanInput = { _, _, _ -> },
                    onArtifact = { opened = it },
                )
            }
        }

        compose.onNodeWithText("The report is ready.").assertExists()
        compose.onNodeWithText("report.md").performClick()
        compose.runOnIdle { assertEquals("mnt/user-data/outputs/report.md", opened) }
    }

    private fun setProcessingToolResult(call: MessageBlock.ToolCall, result: MessageBlock.ToolResult) {
        compose.setContent {
            MaterialTheme {
                ChatMessageGroupItem(
                    group = ChatMessageGroup.Processing(
                        key = "tool-${call.id}",
                        messages = listOf(
                            ChatMessage(
                                id = "assistant-${call.id}",
                                role = MessageRole.Assistant,
                                text = "",
                                blocks = listOf(call, result),
                            ),
                        ),
                    ),
                    runActive = false,
                    onHumanInput = { _, _, _ -> },
                )
            }
        }
    }
}
