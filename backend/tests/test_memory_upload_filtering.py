"""Tests for upload-event filtering in the memory pipeline.

Covers two functions introduced to prevent ephemeral file-upload context from
persisting in long-term memory:

  - filter_messages_for_memory  (message_processing)
  - _strip_upload_mentions_from_memory  (updater)
"""

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from deerflow.agents.memory.backends.deermem.deermem.core.message_processing import detect_correction, detect_reinforcement, filter_messages_for_memory
from deerflow.agents.memory.backends.deermem.deermem.core.updater import _strip_upload_mentions_from_memory

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_UPLOAD_BLOCK = "<uploaded_files>\nThe following files have been uploaded and are available for use:\n\n- filename: secret.txt\n  path: /mnt/user-data/uploads/abc123/secret.txt\n  size: 42 bytes\n</uploaded_files>"

_CURRENT_UPLOADS_BLOCK = "<current_uploads>\nThe following files have been uploaded in this run:\n\n- filename: report.pdf\n  path: /mnt/user-data/uploads/def456/report.pdf\n  size: 2048 bytes\n</current_uploads>"


def _human(text: str) -> HumanMessage:
    return HumanMessage(content=text)


def _ai(text: str, tool_calls=None) -> AIMessage:
    msg = AIMessage(content=text)
    if tool_calls:
        msg.tool_calls = tool_calls
    return msg


# ===========================================================================
# filter_messages_for_memory
# ===========================================================================


class TestFilterMessagesForMemory:
    # --- upload-only turns are excluded ---

    def test_upload_only_turn_is_excluded(self):
        """A human turn containing only <uploaded_files> (no real question)
        and its paired AI response must both be dropped."""
        msgs = [
            _human(_UPLOAD_BLOCK),
            _ai("I have read the file. It says: Hello."),
        ]
        result = filter_messages_for_memory(msgs)
        assert result == []

    def test_upload_only_turn_is_excluded_current_uploads(self):
        """Same as above but with <current_uploads> — the tag actually emitted
        by UploadsMiddleware in production."""
        msgs = [
            _human(_CURRENT_UPLOADS_BLOCK),
            _ai("I have read the report. It says: Q3 revenue up 12%."),
        ]
        result = filter_messages_for_memory(msgs)
        assert result == []

    def test_upload_with_real_question_preserves_question(self):
        """When the user asks a question alongside an upload, the question text
        must reach the memory queue (upload block stripped, AI response kept)."""
        combined = _UPLOAD_BLOCK + "\n\nWhat does this file contain?"
        msgs = [
            _human(combined),
            _ai("The file contains: Hello DeerFlow."),
        ]
        result = filter_messages_for_memory(msgs)

        assert len(result) == 2
        human_result = result[0]
        assert "<uploaded_files>" not in human_result.content
        assert "What does this file contain?" in human_result.content
        assert result[1].content == "The file contains: Hello DeerFlow."

    def test_upload_with_question_preserves_question_current_uploads(self):
        """Same as above but with <current_uploads> — the tag actually emitted
        by UploadsMiddleware in production."""
        combined = _CURRENT_UPLOADS_BLOCK + "\n\nSummarise this report please."
        msgs = [
            _human(combined),
            _ai("The report indicates Q3 revenue is up 12%."),
        ]
        result = filter_messages_for_memory(msgs)

        assert len(result) == 2
        human_result = result[0]
        assert "<current_uploads>" not in human_result.content
        assert "Summarise this report please." in human_result.content
        assert result[1].content == "The report indicates Q3 revenue is up 12%."

    # --- non-upload turns pass through unchanged ---

    def test_plain_conversation_passes_through(self):
        msgs = [
            _human("What is the capital of France?"),
            _ai("The capital of France is Paris."),
        ]
        result = filter_messages_for_memory(msgs)
        assert len(result) == 2
        assert result[0].content == "What is the capital of France?"
        assert result[1].content == "The capital of France is Paris."

    def test_tool_messages_are_excluded(self):
        """Intermediate tool messages must never reach memory."""
        msgs = [
            _human("Search for something"),
            _ai("Calling search tool", tool_calls=[{"name": "search", "id": "1", "args": {}}]),
            ToolMessage(content="Search results", tool_call_id="1"),
            _ai("Here are the results."),
        ]
        result = filter_messages_for_memory(msgs)
        human_msgs = [m for m in result if m.type == "human"]
        ai_msgs = [m for m in result if m.type == "ai"]
        assert len(human_msgs) == 1
        assert len(ai_msgs) == 1
        assert ai_msgs[0].content == "Here are the results."

    def test_multi_turn_with_upload_in_middle(self):
        """Only the upload turn is dropped; surrounding non-upload turns survive."""
        msgs = [
            _human("Hello, how are you?"),
            _ai("I'm doing well, thank you!"),
            _human(_UPLOAD_BLOCK),  # upload-only → dropped
            _ai("I read the uploaded file."),  # paired AI → dropped
            _human("What is 2 + 2?"),
            _ai("4"),
        ]
        result = filter_messages_for_memory(msgs)
        human_contents = [m.content for m in result if m.type == "human"]
        ai_contents = [m.content for m in result if m.type == "ai"]

        assert "Hello, how are you?" in human_contents
        assert "What is 2 + 2?" in human_contents
        assert _UPLOAD_BLOCK not in human_contents
        assert "I'm doing well, thank you!" in ai_contents
        assert "4" in ai_contents
        # The upload-paired AI response must NOT appear
        assert "I read the uploaded file." not in ai_contents

    def test_multimodal_content_list_handled(self):
        """Human messages with list-style content (multimodal) are handled."""
        msg = HumanMessage(
            content=[
                {"type": "text", "text": _UPLOAD_BLOCK},
            ]
        )
        msgs = [msg, _ai("Done.")]
        result = filter_messages_for_memory(msgs)
        assert result == []

    def test_file_path_not_in_filtered_content(self):
        """After filtering, no upload file path should appear in any message."""
        combined = _UPLOAD_BLOCK + "\n\nSummarise the file please."
        msgs = [_human(combined), _ai("It says hello.")]
        result = filter_messages_for_memory(msgs)
        all_content = " ".join(m.content for m in result if isinstance(m.content, str))
        assert "/mnt/user-data/uploads/" not in all_content
        assert "<uploaded_files>" not in all_content

    # --- hide_from_ui messages are excluded ---

    def test_hide_from_ui_human_message_is_excluded(self):
        """Middleware-injected hidden HumanMessages (TodoMiddleware.todo_reminder,
        ViewImageMiddleware, p0 DynamicContextMiddleware.__memory) must never reach
        the memory-updating LLM."""
        hidden_reminder = HumanMessage(
            content="<system_reminder>\nYour todo list from earlier is no longer visible.\n</system_reminder>",
            additional_kwargs={"hide_from_ui": True, "name": "todo_reminder"},
        )
        msgs = [
            _human("What is the capital of France?"),
            _ai("The capital of France is Paris."),
            hidden_reminder,  # should be skipped
            _ai("Is there anything else I can help with?"),  # should be kept
        ]
        result = filter_messages_for_memory(msgs)

        human_contents = [m.content for m in result if m.type == "human"]
        assert len(human_contents) == 1
        assert "What is the capital of France?" in human_contents[0]
        assert not any("todo list" in c for c in human_contents)
        assert not any(m.additional_kwargs.get("hide_from_ui") for m in result if m.type == "human")

    def test_p0_memory_payload_is_excluded(self):
        """The p0 DynamicContextMiddleware.__memory HumanMessage carries extracted
        memory facts back to the memory LLM; feeding it again risks a
        self-amplification loop, so it must be filtered out."""
        memory_payload = HumanMessage(
            content="<memory>User prefers concise answers</memory>",
            additional_kwargs={"hide_from_ui": True},
        )
        msgs = [
            _human("Help me with Python."),
            _ai("Sure."),
            memory_payload,  # should be skipped
        ]
        result = filter_messages_for_memory(msgs)

        human_contents = [m.content for m in result if m.type == "human"]
        assert len(human_contents) == 1
        assert "Help me with Python." in human_contents[0]
        assert not any("<memory>" in c for c in human_contents)

    def test_hide_from_ui_human_input_response_is_preserved(self):
        """Hidden card replies are user-authored answers, not framework context."""
        hidden_response = HumanMessage(
            content="For your clarification, my answer is: staging",
            additional_kwargs={
                "hide_from_ui": True,
                "human_input_response": {
                    "version": 1,
                    "kind": "human_input_response",
                    "source": "ask_clarification",
                    "request_id": "clarification:call-abc",
                    "response_kind": "option",
                    "option_id": "option-2",
                    "value": "staging",
                },
            },
        )
        msgs = [
            _human("Deploy the app."),
            _ai("Which environment?"),
            hidden_response,
            _ai("Deploying to staging."),
        ]

        result = filter_messages_for_memory(msgs)

        human_contents = [m.content for m in result if m.type == "human"]
        assert "Deploy the app." in human_contents
        assert "For your clarification, my answer is: staging" in human_contents

    def test_hide_from_ui_malformed_human_input_response_is_excluded(self):
        hidden_response = HumanMessage(
            content="For your clarification, my answer is: staging",
            additional_kwargs={
                "hide_from_ui": True,
                "human_input_response": {
                    "version": 1,
                    "kind": "human_input_response",
                    "source": "ask_clarification",
                    "request_id": "clarification:call-abc",
                    "response_kind": "option",
                    "value": "staging",
                },
            },
        )
        msgs = [_human("Deploy the app."), _ai("Which environment?"), hidden_response]

        result = filter_messages_for_memory(msgs)

        human_contents = [m.content for m in result if m.type == "human"]
        assert "Deploy the app." in human_contents
        assert "For your clarification, my answer is: staging" not in human_contents

    def test_hide_from_ui_false_is_preserved(self):
        """Messages without hide_from_ui (or with it set to False) are kept."""
        visible_msg = HumanMessage(content="Visible message", additional_kwargs={"hide_from_ui": False})
        msgs = [visible_msg, _ai("Reply.")]
        result = filter_messages_for_memory(msgs)
        assert len(result) == 2
        assert result[0].content == "Visible message"


# ===========================================================================
# detect_correction
# ===========================================================================


class TestDetectCorrection:
    def test_detects_english_correction_signal(self):
        msgs = [
            _human("Please help me run the project."),
            _ai("Use npm start."),
            _human("That's wrong, use make dev instead."),
            _ai("Understood."),
        ]

        assert detect_correction(msgs) is True

    def test_detects_chinese_correction_signal(self):
        msgs = [
            _human("帮我启动项目"),
            _ai("用 npm start"),
            _human("不对，改用 make dev"),
            _ai("明白了"),
        ]

        assert detect_correction(msgs) is True

    def test_returns_false_without_signal(self):
        msgs = [
            _human("Please explain the build setup."),
            _ai("Here is the build setup."),
            _human("Thanks, that makes sense."),
        ]

        assert detect_correction(msgs) is False

    def test_only_checks_recent_messages(self):
        msgs = [
            _human("That is wrong, use make dev instead."),
            _ai("Noted."),
            _human("Let's discuss tests."),
            _ai("Sure."),
            _human("What about linting?"),
            _ai("Use ruff."),
            _human("And formatting?"),
            _ai("Use make format."),
        ]

        assert detect_correction(msgs) is False

    def test_handles_list_content(self):
        msgs = [
            HumanMessage(content=["That is wrong,", {"type": "text", "text": "use make dev instead."}]),
            _ai("Updated."),
        ]

        assert detect_correction(msgs) is True


# ===========================================================================
# _strip_upload_mentions_from_memory
# ===========================================================================


class TestStripUploadMentionsFromMemory:
    def _make_memory(self, summary: str, facts: list[dict] | None = None) -> dict:
        return {
            "user": {"topOfMind": {"summary": summary}},
            "history": {"recentMonths": {"summary": ""}},
            "facts": facts or [],
        }

    # --- summaries ---

    def test_upload_event_sentence_removed_from_summary(self):
        mem = self._make_memory("User is interested in AI. User uploaded a test file for verification purposes. User prefers concise answers.")
        result = _strip_upload_mentions_from_memory(mem)
        summary = result["user"]["topOfMind"]["summary"]
        assert "uploaded a test file" not in summary
        assert "User is interested in AI" in summary
        assert "User prefers concise answers" in summary

    def test_upload_path_sentence_removed_from_summary(self):
        mem = self._make_memory("User uses Python. User uploaded file to /mnt/user-data/uploads/tid/data.csv. User likes clean code.")
        result = _strip_upload_mentions_from_memory(mem)
        summary = result["user"]["topOfMind"]["summary"]
        assert "/mnt/user-data/uploads/" not in summary
        assert "User uses Python" in summary

    def test_legitimate_csv_mention_is_preserved(self):
        """'User works with CSV files' must NOT be deleted — it's not an upload event."""
        mem = self._make_memory("User regularly works with CSV files for data analysis.")
        result = _strip_upload_mentions_from_memory(mem)
        assert "CSV files" in result["user"]["topOfMind"]["summary"]

    def test_pdf_export_preference_preserved(self):
        """'Prefers PDF export' is a legitimate preference, not an upload event."""
        mem = self._make_memory("User prefers PDF export for reports.")
        result = _strip_upload_mentions_from_memory(mem)
        assert "PDF export" in result["user"]["topOfMind"]["summary"]

    def test_uploading_a_test_file_removed(self):
        """'uploading a test file' (with intervening words) must be caught."""
        mem = self._make_memory("User conducted a hands-on test by uploading a test file titled 'test_deerflow_memory_bug.txt'. User is also learning Python.")
        result = _strip_upload_mentions_from_memory(mem)
        summary = result["user"]["topOfMind"]["summary"]
        assert "test_deerflow_memory_bug.txt" not in summary
        assert "uploading a test file" not in summary

    # --- facts ---

    def test_upload_fact_removed_from_facts(self):
        facts = [
            {"content": "User uploaded a file titled secret.txt", "category": "behavior"},
            {"content": "User prefers dark mode", "category": "preference"},
            {"content": "User is uploading document attachments regularly", "category": "behavior"},
        ]
        mem = self._make_memory("summary", facts=facts)
        result = _strip_upload_mentions_from_memory(mem)
        remaining = [f["content"] for f in result["facts"]]
        assert "User prefers dark mode" in remaining
        assert not any("uploaded a file" in c for c in remaining)
        assert not any("uploading document" in c for c in remaining)

    def test_non_upload_facts_preserved(self):
        facts = [
            {"content": "User graduated from Peking University", "category": "context"},
            {"content": "User prefers Python over JavaScript", "category": "preference"},
        ]
        mem = self._make_memory("", facts=facts)
        result = _strip_upload_mentions_from_memory(mem)
        assert len(result["facts"]) == 2

    def test_empty_memory_handled_gracefully(self):
        mem = {"user": {}, "history": {}, "facts": []}
        result = _strip_upload_mentions_from_memory(mem)
        assert result == {"user": {}, "history": {}, "facts": []}


# ===========================================================================
# detect_reinforcement
# ===========================================================================


class TestDetectReinforcement:
    def test_detects_english_reinforcement_signal(self):
        msgs = [
            _human("Can you summarise it in bullet points?"),
            _ai("Here are the key points: ..."),
            _human("Yes, exactly! That's what I needed."),
            _ai("Glad it helped."),
        ]

        assert detect_reinforcement(msgs) is True

    def test_detects_perfect_signal(self):
        msgs = [
            _human("Write it more concisely."),
            _ai("Here is the concise version."),
            _human("Perfect."),
            _ai("Great!"),
        ]

        assert detect_reinforcement(msgs) is True

    def test_detects_chinese_reinforcement_signal(self):
        msgs = [
            _human("帮我用要点来总结"),
            _ai("好的，要点如下：..."),
            _human("完全正确，就是这个意思"),
            _ai("很高兴能帮到你"),
        ]

        assert detect_reinforcement(msgs) is True

    def test_returns_false_without_signal(self):
        msgs = [
            _human("What does this function do?"),
            _ai("It processes the input data."),
            _human("Can you show me an example?"),
        ]

        assert detect_reinforcement(msgs) is False

    def test_only_checks_recent_messages(self):
        # Reinforcement signal buried beyond the -6 window should not trigger
        msgs = [
            _human("Yes, exactly right."),
            _ai("Noted."),
            _human("Let's discuss tests."),
            _ai("Sure."),
            _human("What about linting?"),
            _ai("Use ruff."),
            _human("And formatting?"),
            _ai("Use make format."),
        ]

        assert detect_reinforcement(msgs) is False

    def test_does_not_conflict_with_correction(self):
        # A message can trigger correction but not reinforcement
        msgs = [
            _human("That's wrong, try again."),
            _ai("Corrected."),
        ]

        assert detect_reinforcement(msgs) is False
