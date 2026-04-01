"""Tests for upload-event filtering in the memory pipeline.

Covers two functions introduced to prevent ephemeral file-upload context from
persisting in long-term memory:

  - _filter_messages_for_memory  (memory_middleware)
  - _strip_upload_mentions_from_memory  (updater)
"""

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from deerflow.agents.memory.updater import _strip_upload_mentions_from_memory
from deerflow.agents.middlewares.memory_middleware import _filter_messages_for_memory, detect_correction

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_UPLOAD_BLOCK = "<uploaded_files>\nThe following files have been uploaded and are available for use:\n\n- filename: secret.txt\n  path: /mnt/user-data/uploads/abc123/secret.txt\n  size: 42 bytes\n</uploaded_files>"


def _human(text: str) -> HumanMessage:
    return HumanMessage(content=text)


def _ai(text: str, tool_calls=None) -> AIMessage:
    msg = AIMessage(content=text)
    if tool_calls:
        msg.tool_calls = tool_calls
    return msg


# ===========================================================================
# _filter_messages_for_memory
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
        result = _filter_messages_for_memory(msgs)
        assert result == []

    def test_upload_with_real_question_preserves_question(self):
        """When the user asks a question alongside an upload, the question text
        must reach the memory queue (upload block stripped, AI response kept)."""
        combined = _UPLOAD_BLOCK + "\n\nWhat does this file contain?"
        msgs = [
            _human(combined),
            _ai("The file contains: Hello DeerFlow."),
        ]
        result = _filter_messages_for_memory(msgs)

        assert len(result) == 2
        human_result = result[0]
        assert "<uploaded_files>" not in human_result.content
        assert "What does this file contain?" in human_result.content
        assert result[1].content == "The file contains: Hello DeerFlow."

    # --- non-upload turns pass through unchanged ---

    def test_plain_conversation_passes_through(self):
        msgs = [
            _human("What is the capital of France?"),
            _ai("The capital of France is Paris."),
        ]
        result = _filter_messages_for_memory(msgs)
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
        result = _filter_messages_for_memory(msgs)
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
        result = _filter_messages_for_memory(msgs)
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
        result = _filter_messages_for_memory(msgs)
        assert result == []

    def test_file_path_not_in_filtered_content(self):
        """After filtering, no upload file path should appear in any message."""
        combined = _UPLOAD_BLOCK + "\n\nSummarise the file please."
        msgs = [_human(combined), _ai("It says hello.")]
        result = _filter_messages_for_memory(msgs)
        all_content = " ".join(m.content for m in result if isinstance(m.content, str))
        assert "/mnt/user-data/uploads/" not in all_content
        assert "<uploaded_files>" not in all_content


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
