package com.deerflow.mobile.data

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class MessageCacheCodecTest {
    @Test
    fun roundTripPreservesEveryStructuredBlockAndAttachmentField() {
        val request = HumanInputRequest(
            source = "interrupt",
            requestId = "request-1",
            toolCallId = "call-1",
            title = "Choose a source",
            clarificationType = "single_choice",
            question = "Which source should be used?",
            context = "The report needs one primary source.",
            inputMode = "choice_with_other",
            options = listOf(HumanInputOption("official", "Official docs", "official")),
        )
        val response = HumanInputResponse(
            source = "interrupt",
            requestId = "request-1",
            responseKind = "option",
            value = "official",
            optionId = "official",
        )
        val message = ChatMessage(
            id = "message-1",
            role = MessageRole.Assistant,
            text = "Structured response",
            isStreaming = true,
            blocks = listOf(
                MessageBlock.Markdown("Structured response"),
                MessageBlock.Code("kotlin", "val cached = true"),
                MessageBlock.Quote("Keep the structure"),
                MessageBlock.Reasoning("Inspect the cache first"),
                MessageBlock.ToolCall("search", "{\"query\":\"Room\"}", "call-1"),
                MessageBlock.ToolResult("call-1", "search", "Found one result", failed = false),
                MessageBlock.Subtask(
                    callId = "call-2",
                    subagentType = "researcher",
                    description = "Check Room",
                    prompt = "Inspect persistence",
                    status = MessageBlock.SubtaskStatus.Completed,
                    result = "Room supports migrations",
                    modelName = "test-model",
                ),
                MessageBlock.HumanInput(request),
                MessageBlock.Approval(request.copy(clarificationType = "risk_confirmation")),
                MessageBlock.HumanInputResponseBlock(response),
                MessageBlock.Todo("Persist JSON", completed = true, status = "completed"),
                MessageBlock.Artifact("report.md", "/mnt/user-data/outputs/report.md"),
                MessageBlock.Error("Recovered error"),
            ),
            attachments = listOf(
                MessageAttachment("notes.txt", 42, "/mnt/user-data/uploads/notes.txt"),
                MessageAttachment("pending.txt", 7, null, AttachmentStatus.Pending),
            ),
            hiddenFromUi = true,
            tokenUsage = TokenUsage(12, 34, 46),
        )

        assertEquals(message, decodeCachedChatMessage(encodeCachedChatMessage(message)))
    }

    @Test
    fun malformedUnknownAndVersionMismatchedPayloadsAreRejected() {
        assertNull(decodeCachedChatMessage("not-json"))
        assertNull(decodeCachedChatMessage("{\"version\":2}"))

        val valid = JSONObject(
            encodeCachedChatMessage(ChatMessage("message-1", MessageRole.Assistant, "text")),
        )
        valid.put("blocks", JSONArray().put(JSONObject().put("type", "future_block")))

        assertNull(decodeCachedChatMessage(valid.toString()))
    }
}
