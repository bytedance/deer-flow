package com.deerflow.mobile.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.json.JSONObject

class MessageBlocksTest {
    @Test
    fun stripsUploadedFileContextFromHumanMessagesWithoutChangingMessageOrder() {
        val snapshot = JSONObject(
            """{"values":{"title":"<uploaded_files>old.txt</uploaded_files>Release review","messages":[
                {"id":"human-1","type":"human","content":"<uploaded_files>old.txt</uploaded_files>First question"},
                {"id":"ai-1","type":"ai","content":"First answer"},
                {"id":"human-2","type":"human","content":"<slash_skill_activation>research</slash_skill_activation>Second question"}
            ]}}""",
        ).toThreadSnapshot()

        assertEquals("Release review", snapshot.title)
        assertEquals(listOf("First question", "First answer", "Second question"), snapshot.messages.map { it.text })
    }

    @Test
    fun parsesAssistantUsageMetadata() {
        val message = JSONObject(
            """{"id":"ai-1","type":"ai","content":"Done","usage_metadata":{"input_tokens":12,"output_tokens":34,"total_tokens":46}}""",
        ).toChatMessage()

        assertEquals(TokenUsage(12, 34, 46), message?.tokenUsage)
    }

    @Test
    fun parsesMarkdownAndFencedCodeInOrder() {
        val blocks = parseMessageBlocks("Before\n\n```kotlin\nval answer = 42\n```\n\nAfter")

        assertEquals(MessageBlock.Markdown("Before"), blocks[0])
        assertEquals(MessageBlock.Code("kotlin", "val answer = 42"), blocks[1])
        assertEquals(MessageBlock.Markdown("After"), blocks[2])
    }

    @Test
    fun parsesQuoteBlock() {
        assertEquals(
            listOf(MessageBlock.Quote("first\nsecond")),
            parseMessageBlocks("> first\n> second"),
        )
    }

    @Test
    fun runModesMapToGatewayFlags() {
        assertFalse(RunMode.Flash.thinkingEnabled)
        assertEquals("minimal", RunMode.Flash.reasoningEffort)
        assertTrue(RunMode.Pro.planMode)
        assertEquals("medium", RunMode.Pro.reasoningEffort)
        assertTrue(RunMode.Ultra.subagentEnabled)
        assertEquals("high", RunMode.Ultra.reasoningEffort)
    }

    @Test
    fun modelCapabilitiesRestrictModesAndReasoningEffort() {
        val fast = WorkspaceCapabilities(
            models = listOf(ModelInfo("fast", "Fast", "", supportsThinking = false, supportsReasoningEffort = false)),
        )
        val pro = WorkspaceCapabilities(
            models = listOf(ModelInfo("pro", "Pro", "", supportsThinking = true, supportsReasoningEffort = true)),
        )

        assertEquals(listOf(RunMode.Flash), fast.availableRunModes("fast"))
        assertFalse(fast.supportsReasoningEffort("fast"))
        assertEquals(RunMode.entries, pro.availableRunModes("pro"))
        assertTrue(pro.supportsReasoningEffort("pro"))
    }

    @Test
    fun jsonNullModelRemainsNull() {
        assertEquals(null, nullableJsonString(null))
        assertEquals(null, nullableJsonString(Any()))
        assertEquals("model-a", nullableJsonString("model-a"))
    }

    @Test
    fun parsesGatewayToolCallsFromTopLevelField() {
        val message = JSONObject(
            """{
                "id":"ai-1",
                "type":"AIMessageChunk",
                "content":"",
                "tool_calls":[
                    {"id":"call-1","name":"web_search","args":{"query":"DeerFlow Android"}},
                    {"id":"call-2","name":"bash","args":{"description":"Inspect files","command":"rg TODO"}}
                ]
            }""".trimIndent(),
        ).toChatMessage()

        assertEquals(MessageRole.Assistant, message?.role)
        val calls = message?.blocks?.filterIsInstance<MessageBlock.ToolCall>().orEmpty()
        assertEquals(listOf("call-1", "call-2"), calls.map { it.id })
        assertTrue(calls.first().detail.contains("DeerFlow Android"))
    }

    @Test
    fun parsesTaskCallsAndStructuredSubtaskResults() {
        val call = JSONObject(
            """{
                "id":"task-1",
                "type":"ai",
                "content":"",
                "tool_calls":[{"id":"task-1","name":"task","args":{"subagent_type":"researcher","description":"Check the docs","prompt":"Read the API docs"}}]
            }""".trimIndent(),
        ).toChatMessage()
        val result = JSONObject(
            """{
                "id":"result-1",
                "type":"tool",
                "name":"task",
                "tool_call_id":"task-1",
                "content":"Task Succeeded. Result: done",
                "additional_kwargs":{"subagent_status":"completed","subagent_result_brief":"done","subagent_model_name":"fast-model"}
            }""".trimIndent(),
        ).toChatMessage()

        val pending = call?.blocks?.filterIsInstance<MessageBlock.Subtask>().orEmpty().single()
        val completed = result?.blocks?.filterIsInstance<MessageBlock.Subtask>().orEmpty().single()
        assertEquals("researcher", pending.subagentType)
        assertEquals("Check the docs", pending.description)
        assertEquals(MessageBlock.SubtaskStatus.Completed, completed.status)
        assertEquals("done", completed.result)
        assertEquals("fast-model", completed.modelName)
    }

    @Test
    fun parsesWriteTodosStatusesAndThreadTodoSnapshot() {
        val message = JSONObject(
            """{
                "id":"ai-todo",
                "type":"ai",
                "content":"",
                "tool_calls":[{"id":"todo-1","name":"write_todos","args":{"todos":[{"content":"Inspect code","status":"completed"},{"content":"Add tests","status":"in_progress"}]}}]
            }""".trimIndent(),
        ).toChatMessage()
        val blocks = message?.blocks?.filterIsInstance<MessageBlock.Todo>().orEmpty()
        assertEquals(listOf("completed", "in_progress"), blocks.map { it.status })
        assertEquals(listOf("Inspect code", "Add tests"), blocks.map { it.title })

        val snapshot = JSONObject(
            """{"values":{"title":"Todo thread","messages":[],"todos":[{"content":"Ship Android","status":"pending"}]}}""",
        ).toThreadSnapshot()
        assertEquals(listOf(TodoItem("Ship Android", "pending")), snapshot.todos)
    }

    @Test
    fun parsesPresentFilesAndThreadArtifactSnapshot() {
        val message = JSONObject(
            """{
                "id":"ai-files",
                "type":"ai",
                "content":"",
                "tool_calls":[{"id":"files-1","name":"present_files","args":{"filepaths":["mnt/user-data/outputs/report.md","mnt/user-data/outputs/chart.png"]}}]
            }""".trimIndent(),
        ).toChatMessage()
        val blocks = message?.blocks?.filterIsInstance<MessageBlock.Artifact>().orEmpty()
        assertEquals(listOf("report.md", "chart.png"), blocks.map { it.title })
        val group = groupChatMessages(listOf(requireNotNull(message))).single()
        assertTrue(group is ChatMessageGroup.Message)

        val snapshot = JSONObject(
            """{"values":{"title":"Artifacts","messages":[],"artifacts":["mnt/user-data/outputs/report.md",{"path":"mnt/user-data/outputs/chart.png"}]}}""",
        ).toThreadSnapshot()
        assertEquals(
            listOf("mnt/user-data/outputs/report.md", "mnt/user-data/outputs/chart.png"),
            snapshot.artifacts,
        )
    }

    @Test
    fun preservesStructuredHumanInputAndHiddenResponse() {
        val request = JSONObject(
            """{
                "id":"request-1",
                "type":"tool",
                "name":"ask_clarification",
                "tool_call_id":"call-1",
                "content":"Which format?",
                "artifact":{"human_input":{
                    "version":1,
                    "kind":"human_input_request",
                    "source":"ask_clarification",
                    "request_id":"request-1",
                    "question":"Which format?",
                    "input_mode":"choice_with_other",
                    "options":[{"id":"option-0","label":"Markdown","value":"Markdown"}]
                }}
            }""".trimIndent(),
        ).toChatMessage()
        val response = JSONObject(
            """{
                "id":"response-1",
                "type":"human",
                "content":"hidden",
                "additional_kwargs":{
                    "hide_from_ui":true,
                    "human_input_response":{
                        "version":1,
                        "kind":"human_input_response",
                        "source":"ask_clarification",
                        "request_id":"request-1",
                        "response_kind":"text",
                        "value":"Markdown"
                    }
                }
            }""".trimIndent(),
        ).toChatMessage()

        assertTrue(request?.blocks?.any { it is MessageBlock.HumanInput } == true)
        assertTrue(response?.hiddenFromUi == true)
        assertTrue(response?.blocks?.any { it is MessageBlock.HumanInputResponseBlock } == true)
    }

    @Test
    fun promotesRiskConfirmationToApprovalBlock() {
        val request = JSONObject(
            """{
                "id":"approval-1",
                "type":"tool",
                "name":"ask_clarification",
                "tool_call_id":"call-approval",
                "content":"Confirm deletion?",
                "artifact":{"human_input":{
                    "version":1,
                    "kind":"human_input_request",
                    "source":"ask_clarification",
                    "request_id":"approval-1",
                    "clarification_type":"risk_confirmation",
                    "question":"Confirm deletion?",
                    "input_mode":"single_choice",
                    "options":[{"id":"approve","label":"Approve","value":"yes"},{"id":"deny","label":"Deny","value":"no"}]
                }}
            }""".trimIndent(),
        ).toChatMessage()

        val approval = request?.blocks?.filterIsInstance<MessageBlock.Approval>().orEmpty().single()
        assertEquals("risk_confirmation", approval.request.clarificationType)
        assertEquals(listOf("approve", "deny"), approval.request.options.map { it.id })
    }

    @Test
    fun groupsConsecutiveToolMessagesAndKeepsClarificationSeparate() {
        val first = ChatMessage(
            id = "ai-1",
            role = MessageRole.Assistant,
            text = "I will inspect the workspace.",
            blocks = listOf(
                MessageBlock.Markdown("I will inspect the workspace."),
                MessageBlock.ToolCall("ls", "{\"path\":\".\"}", "call-1"),
            ),
        )
        val result = ChatMessage(
            id = "tool-1",
            role = MessageRole.Tool,
            text = "TODO.MD",
            blocks = listOf(MessageBlock.ToolResult("call-1", "ls", "TODO.MD")),
        )
        val second = ChatMessage(
            id = "ai-2",
            role = MessageRole.Assistant,
            text = "",
            blocks = listOf(MessageBlock.ToolCall("bash", "{\"command\":\"rg TODO\"}", "call-2")),
        )
        val final = ChatMessage("ai-3", MessageRole.Assistant, "Done")

        val groups = groupChatMessages(listOf(first, result, second, final))

        assertEquals(2, groups.size)
        assertEquals(3, (groups.first() as ChatMessageGroup.Processing).messages.size)
        assertEquals(final, (groups.last() as ChatMessageGroup.Message).message)
    }

    @Test
    fun finalAssistantReplyMovesReasoningIntoTheProcessingGroup() {
        val tool = ChatMessage(
            id = "ai-tool",
            role = MessageRole.Assistant,
            text = "",
            blocks = listOf(MessageBlock.ToolCall("web_search", "{}", "call-1")),
        )
        val final = ChatMessage(
            id = "ai-final",
            role = MessageRole.Assistant,
            text = "Answer",
            blocks = listOf(
                MessageBlock.Markdown("Answer"),
                MessageBlock.Reasoning("Explain the result"),
            ),
        )

        val groups = groupChatMessages(listOf(tool, final))

        assertEquals(2, groups.size)
        val processing = groups.first() as ChatMessageGroup.Processing
        val message = groups.last() as ChatMessageGroup.Message
        assertEquals(MessageBlock.Reasoning("Explain the result"), processing.trailingReasoning)
        assertEquals(final, message.message)
        assertTrue(!message.showReasoning)
    }

    @Test
    fun presentsFilesWithTheFinalReplyInsteadOfCreatingAnEmptyProcessingGroup() {
        val tool = ChatMessage(
            id = "ai-tool",
            role = MessageRole.Assistant,
            text = "",
            blocks = listOf(MessageBlock.ToolCall("bash", "{}", "call-1")),
        )
        val toolResult = ChatMessage(
            id = "tool-result",
            role = MessageRole.Tool,
            text = "Done",
            blocks = listOf(MessageBlock.ToolResult("call-1", "bash", "Done")),
        )
        val presentFiles = ChatMessage(
            id = "ai-files",
            role = MessageRole.Assistant,
            text = "",
            blocks = listOf(
                MessageBlock.ToolCall("present_files", "{}", "files-1"),
                MessageBlock.Artifact("report.xlsx", "/mnt/user-data/outputs/report.xlsx"),
            ),
        )
        val presentResult = ChatMessage(
            id = "files-result",
            role = MessageRole.Tool,
            text = "Successfully presented files",
            blocks = listOf(MessageBlock.ToolResult("files-1", "present_files", "Successfully presented files")),
        )
        val final = ChatMessage(
            id = "ai-final",
            role = MessageRole.Assistant,
            text = "Your report is ready.",
            blocks = listOf(
                MessageBlock.Markdown("Your report is ready."),
                MessageBlock.Reasoning("Confirm the output."),
            ),
        )

        val groups = groupChatMessages(listOf(tool, toolResult, presentFiles, presentResult, final))

        assertEquals(2, groups.size)
        val processing = groups.first() as ChatMessageGroup.Processing
        val message = groups.last() as ChatMessageGroup.Message
        assertEquals(listOf(tool, toolResult), processing.messages)
        assertEquals(MessageBlock.Reasoning("Confirm the output."), processing.trailingReasoning)
        assertEquals(final, message.message)
        assertEquals(listOf(MessageBlock.Artifact("report.xlsx", "/mnt/user-data/outputs/report.xlsx")), message.trailingArtifacts)
    }

    @Test
    fun assistantTurnIncludesAllAssistantMessagesBetweenUserMessages() {
        val messages = listOf(
            ChatMessage("human-1", MessageRole.User, "Question"),
            ChatMessage("ai-tool", MessageRole.Assistant, "", blocks = listOf(MessageBlock.ToolCall("web_search", "{}", "call-1"))),
            ChatMessage("tool-1", MessageRole.Tool, "result", blocks = listOf(MessageBlock.ToolResult("call-1", "web_search", "result"))),
            ChatMessage("ai-answer", MessageRole.Assistant, "Answer"),
            ChatMessage("human-2", MessageRole.User, "Next question"),
            ChatMessage("ai-next", MessageRole.Assistant, "Next answer"),
        )

        val turn = assistantTurnForMessage(messages, "ai-tool")

        assertEquals("ai-answer", turn?.targetMessageId)
        assertEquals(listOf("ai-tool", "ai-answer"), turn?.messageIds)
        assertEquals(1, turn?.firstMessageIndex)
        assertTrue(turn?.let { !isLatestAssistantTurn(messages, it) } == true)
    }

    @Test
    fun editResendFindsPreviousAssistantTurn() {
        val messages = listOf(
            ChatMessage("human-1", MessageRole.User, "First"),
            ChatMessage("ai-1", MessageRole.Assistant, "First answer"),
            ChatMessage("human-2", MessageRole.User, "Second"),
            ChatMessage("ai-2", MessageRole.Assistant, "Second answer"),
        )

        assertEquals("ai-1", previousAssistantTurnBeforeUser(messages, "human-2")?.targetMessageId)
        assertEquals(null, previousAssistantTurnBeforeUser(messages, "human-1"))
        assertTrue(isLatestAssistantTurn(messages, requireNotNull(assistantTurnForMessage(messages, "ai-2"))))
    }
}
