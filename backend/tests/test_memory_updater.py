from unittest.mock import MagicMock, patch

from deerflow.agents.memory.prompt import format_conversation_for_update
from deerflow.agents.memory.updater import MemoryUpdater, _extract_text
from deerflow.config.memory_config import MemoryConfig


def _make_memory(facts: list[dict[str, object]] | None = None) -> dict[str, object]:
    return {
        "version": "1.0",
        "lastUpdated": "",
        "user": {
            "workContext": {"summary": "", "updatedAt": ""},
            "personalContext": {"summary": "", "updatedAt": ""},
            "topOfMind": {"summary": "", "updatedAt": ""},
        },
        "history": {
            "recentMonths": {"summary": "", "updatedAt": ""},
            "earlierContext": {"summary": "", "updatedAt": ""},
            "longTermBackground": {"summary": "", "updatedAt": ""},
        },
        "facts": facts or [],
    }


def _memory_config(**overrides: object) -> MemoryConfig:
    config = MemoryConfig()
    for key, value in overrides.items():
        setattr(config, key, value)
    return config


def test_apply_updates_skips_existing_duplicate_and_preserves_removals() -> None:
    updater = MemoryUpdater()
    current_memory = _make_memory(
        facts=[
            {
                "id": "fact_existing",
                "content": "User likes Python",
                "category": "preference",
                "confidence": 0.9,
                "createdAt": "2026-03-18T00:00:00Z",
                "source": "thread-a",
            },
            {
                "id": "fact_remove",
                "content": "Old context to remove",
                "category": "context",
                "confidence": 0.8,
                "createdAt": "2026-03-18T00:00:00Z",
                "source": "thread-a",
            },
        ]
    )
    update_data = {
        "factsToRemove": ["fact_remove"],
        "newFacts": [
            {"content": "User likes Python", "category": "preference", "confidence": 0.95},
        ],
    }

    with patch(
        "deerflow.agents.memory.updater.get_memory_config",
        return_value=_memory_config(max_facts=100, fact_confidence_threshold=0.7),
    ):
        result = updater._apply_updates(current_memory, update_data, thread_id="thread-b")

    assert [fact["content"] for fact in result["facts"]] == ["User likes Python"]
    assert all(fact["id"] != "fact_remove" for fact in result["facts"])


def test_apply_updates_skips_same_batch_duplicates_and_keeps_source_metadata() -> None:
    updater = MemoryUpdater()
    current_memory = _make_memory()
    update_data = {
        "newFacts": [
            {"content": "User prefers dark mode", "category": "preference", "confidence": 0.91},
            {"content": "User prefers dark mode", "category": "preference", "confidence": 0.92},
            {"content": "User works on DeerFlow", "category": "context", "confidence": 0.87},
        ],
    }

    with patch(
        "deerflow.agents.memory.updater.get_memory_config",
        return_value=_memory_config(max_facts=100, fact_confidence_threshold=0.7),
    ):
        result = updater._apply_updates(current_memory, update_data, thread_id="thread-42")

    assert [fact["content"] for fact in result["facts"]] == [
        "User prefers dark mode",
        "User works on DeerFlow",
    ]
    assert all(fact["id"].startswith("fact_") for fact in result["facts"])
    assert all(fact["source"] == "thread-42" for fact in result["facts"])


def test_apply_updates_preserves_threshold_and_max_facts_trimming() -> None:
    updater = MemoryUpdater()
    current_memory = _make_memory(
        facts=[
            {
                "id": "fact_python",
                "content": "User likes Python",
                "category": "preference",
                "confidence": 0.95,
                "createdAt": "2026-03-18T00:00:00Z",
                "source": "thread-a",
            },
            {
                "id": "fact_dark_mode",
                "content": "User prefers dark mode",
                "category": "preference",
                "confidence": 0.8,
                "createdAt": "2026-03-18T00:00:00Z",
                "source": "thread-a",
            },
        ]
    )
    update_data = {
        "newFacts": [
            {"content": "User prefers dark mode", "category": "preference", "confidence": 0.9},
            {"content": "User uses uv", "category": "context", "confidence": 0.85},
            {"content": "User likes noisy logs", "category": "behavior", "confidence": 0.6},
        ],
    }

    with patch(
        "deerflow.agents.memory.updater.get_memory_config",
        return_value=_memory_config(max_facts=2, fact_confidence_threshold=0.7),
    ):
        result = updater._apply_updates(current_memory, update_data, thread_id="thread-9")

    assert [fact["content"] for fact in result["facts"]] == [
        "User likes Python",
        "User uses uv",
    ]
    assert all(fact["content"] != "User likes noisy logs" for fact in result["facts"])
    assert result["facts"][1]["source"] == "thread-9"


# ---------------------------------------------------------------------------
# _extract_text — LLM response content normalization
# ---------------------------------------------------------------------------


class TestExtractText:
    """_extract_text should normalize all content shapes to plain text."""

    def test_string_passthrough(self):
        assert _extract_text("hello world") == "hello world"

    def test_list_single_text_block(self):
        assert _extract_text([{"type": "text", "text": "hello"}]) == "hello"

    def test_list_multiple_text_blocks_joined(self):
        content = [
            {"type": "text", "text": "part one"},
            {"type": "text", "text": "part two"},
        ]
        assert _extract_text(content) == "part one\npart two"

    def test_list_plain_strings(self):
        assert _extract_text(["raw string"]) == "raw string"

    def test_list_string_chunks_join_without_separator(self):
        content = ["{\"user\"", ': "alice"}']
        assert _extract_text(content) == '{"user": "alice"}'

    def test_list_mixed_strings_and_blocks(self):
        content = [
            "raw text",
            {"type": "text", "text": "block text"},
        ]
        assert _extract_text(content) == "raw text\nblock text"

    def test_list_adjacent_string_chunks_then_block(self):
        content = [
            "prefix",
            "-continued",
            {"type": "text", "text": "block text"},
        ]
        assert _extract_text(content) == "prefix-continued\nblock text"

    def test_list_skips_non_text_blocks(self):
        content = [
            {"type": "image_url", "image_url": {"url": "http://img.png"}},
            {"type": "text", "text": "actual text"},
        ]
        assert _extract_text(content) == "actual text"

    def test_empty_list(self):
        assert _extract_text([]) == ""

    def test_list_no_text_blocks(self):
        assert _extract_text([{"type": "image_url", "image_url": {}}]) == ""

    def test_non_str_non_list(self):
        assert _extract_text(42) == "42"


# ---------------------------------------------------------------------------
# format_conversation_for_update — handles mixed list content
# ---------------------------------------------------------------------------


class TestFormatConversationForUpdate:
    def test_plain_string_messages(self):
        human_msg = MagicMock()
        human_msg.type = "human"
        human_msg.content = "What is Python?"

        ai_msg = MagicMock()
        ai_msg.type = "ai"
        ai_msg.content = "Python is a programming language."

        result = format_conversation_for_update([human_msg, ai_msg])
        assert "User: What is Python?" in result
        assert "Assistant: Python is a programming language." in result

    def test_list_content_with_plain_strings(self):
        """Plain strings in list content should not be lost."""
        msg = MagicMock()
        msg.type = "human"
        msg.content = ["raw user text", {"type": "text", "text": "structured text"}]

        result = format_conversation_for_update([msg])
        assert "raw user text" in result
        assert "structured text" in result


# ---------------------------------------------------------------------------
# update_memory — structured LLM response handling
# ---------------------------------------------------------------------------


class TestUpdateMemoryStructuredResponse:
    """update_memory should handle LLM responses returned as list content blocks."""

    def _make_mock_model(self, content):
        model = MagicMock()
        response = MagicMock()
        response.content = content
        model.invoke.return_value = response
        return model

    def test_string_response_parses(self):
        updater = MemoryUpdater()
        valid_json = '{"user": {}, "history": {}, "newFacts": [], "factsToRemove": []}'

        with (
            patch.object(updater, "_get_model", return_value=self._make_mock_model(valid_json)),
            patch("deerflow.agents.memory.updater.get_memory_config", return_value=_memory_config(enabled=True)),
            patch("deerflow.agents.memory.updater.get_memory_data", return_value=_make_memory()),
            patch("deerflow.agents.memory.updater._save_memory_to_file", return_value=True),
        ):
            msg = MagicMock()
            msg.type = "human"
            msg.content = "Hello"
            ai_msg = MagicMock()
            ai_msg.type = "ai"
            ai_msg.content = "Hi there"
            ai_msg.tool_calls = []
            result = updater.update_memory([msg, ai_msg])

        assert result is True

    def test_list_content_response_parses(self):
        """LLM response as list-of-blocks should be extracted, not repr'd."""
        updater = MemoryUpdater()
        valid_json = '{"user": {}, "history": {}, "newFacts": [], "factsToRemove": []}'
        list_content = [{"type": "text", "text": valid_json}]

        with (
            patch.object(updater, "_get_model", return_value=self._make_mock_model(list_content)),
            patch("deerflow.agents.memory.updater.get_memory_config", return_value=_memory_config(enabled=True)),
            patch("deerflow.agents.memory.updater.get_memory_data", return_value=_make_memory()),
            patch("deerflow.agents.memory.updater._save_memory_to_file", return_value=True),
        ):
            msg = MagicMock()
            msg.type = "human"
            msg.content = "Hello"
            ai_msg = MagicMock()
            ai_msg.type = "ai"
            ai_msg.content = "Hi"
            ai_msg.tool_calls = []
            result = updater.update_memory([msg, ai_msg])

        assert result is True
