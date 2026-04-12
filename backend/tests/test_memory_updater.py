import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deerflow.agents.memory.prompt import format_conversation_for_update
from deerflow.agents.memory.updater import (
    MemoryUpdater,
    _extract_text,
    _run_async_update_sync,
    clear_memory_data,
    create_memory_fact,
    delete_memory_fact,
    import_memory_data,
    update_memory_fact,
)
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


def test_apply_updates_preserves_source_error() -> None:
    updater = MemoryUpdater()
    current_memory = _make_memory()
    update_data = {
        "newFacts": [
            {
                "content": "Use make dev for local development.",
                "category": "correction",
                "confidence": 0.95,
                "sourceError": "The agent previously suggested npm start.",
            }
        ]
    }

    with patch(
        "deerflow.agents.memory.updater.get_memory_config",
        return_value=_memory_config(max_facts=100, fact_confidence_threshold=0.7),
    ):
        result = updater._apply_updates(current_memory, update_data, thread_id="thread-correction")

    assert result["facts"][0]["sourceError"] == "The agent previously suggested npm start."
    assert result["facts"][0]["category"] == "correction"


def test_apply_updates_ignores_empty_source_error() -> None:
    updater = MemoryUpdater()
    current_memory = _make_memory()
    update_data = {
        "newFacts": [
            {
                "content": "Use make dev for local development.",
                "category": "correction",
                "confidence": 0.95,
                "sourceError": "   ",
            }
        ]
    }

    with patch(
        "deerflow.agents.memory.updater.get_memory_config",
        return_value=_memory_config(max_facts=100, fact_confidence_threshold=0.7),
    ):
        result = updater._apply_updates(current_memory, update_data, thread_id="thread-correction")

    assert "sourceError" not in result["facts"][0]


def test_clear_memory_data_resets_all_sections() -> None:
    with patch("deerflow.agents.memory.updater._save_memory_to_file", return_value=True):
        result = clear_memory_data()

    assert result["version"] == "1.0"
    assert result["facts"] == []
    assert result["user"]["workContext"]["summary"] == ""
    assert result["history"]["recentMonths"]["summary"] == ""


def test_delete_memory_fact_removes_only_matching_fact() -> None:
    current_memory = _make_memory(
        facts=[
            {
                "id": "fact_keep",
                "content": "User likes Python",
                "category": "preference",
                "confidence": 0.9,
                "createdAt": "2026-03-18T00:00:00Z",
                "source": "thread-a",
            },
            {
                "id": "fact_delete",
                "content": "User prefers tabs",
                "category": "preference",
                "confidence": 0.8,
                "createdAt": "2026-03-18T00:00:00Z",
                "source": "thread-b",
            },
        ]
    )

    with (
        patch("deerflow.agents.memory.updater.get_memory_data", return_value=current_memory),
        patch("deerflow.agents.memory.updater._save_memory_to_file", return_value=True),
    ):
        result = delete_memory_fact("fact_delete")

    assert [fact["id"] for fact in result["facts"]] == ["fact_keep"]


def test_create_memory_fact_appends_manual_fact() -> None:
    with (
        patch("deerflow.agents.memory.updater.get_memory_data", return_value=_make_memory()),
        patch("deerflow.agents.memory.updater._save_memory_to_file", return_value=True),
    ):
        result = create_memory_fact(
            content="  User prefers concise code reviews.  ",
            category="preference",
            confidence=0.88,
        )

    assert len(result["facts"]) == 1
    assert result["facts"][0]["content"] == "User prefers concise code reviews."
    assert result["facts"][0]["category"] == "preference"
    assert result["facts"][0]["confidence"] == 0.88
    assert result["facts"][0]["source"] == "manual"


def test_create_memory_fact_rejects_empty_content() -> None:
    try:
        create_memory_fact(content="   ")
    except ValueError as exc:
        assert exc.args == ("content",)
    else:
        raise AssertionError("Expected ValueError for empty fact content")


def test_create_memory_fact_rejects_invalid_confidence() -> None:
    for confidence in (-0.1, 1.1, float("nan"), float("inf"), float("-inf")):
        try:
            create_memory_fact(content="User likes tests", confidence=confidence)
        except ValueError as exc:
            assert exc.args == ("confidence",)
        else:
            raise AssertionError("Expected ValueError for invalid fact confidence")


def test_delete_memory_fact_raises_for_unknown_id() -> None:
    with patch("deerflow.agents.memory.updater.get_memory_data", return_value=_make_memory()):
        try:
            delete_memory_fact("fact_missing")
        except KeyError as exc:
            assert exc.args == ("fact_missing",)
        else:
            raise AssertionError("Expected KeyError for missing fact id")


def test_import_memory_data_saves_and_returns_imported_memory() -> None:
    imported_memory = _make_memory(
        facts=[
            {
                "id": "fact_import",
                "content": "User works on DeerFlow.",
                "category": "context",
                "confidence": 0.87,
                "createdAt": "2026-03-20T00:00:00Z",
                "source": "manual",
            }
        ]
    )
    mock_storage = MagicMock()
    mock_storage.save.return_value = True
    mock_storage.load.return_value = imported_memory

    with patch("deerflow.agents.memory.updater.get_memory_storage", return_value=mock_storage):
        result = import_memory_data(imported_memory)

    mock_storage.save.assert_called_once_with(imported_memory, None, user_id=None)
    mock_storage.load.assert_called_once_with(None, user_id=None)
    assert result == imported_memory


def test_update_memory_fact_updates_only_matching_fact() -> None:
    current_memory = _make_memory(
        facts=[
            {
                "id": "fact_keep",
                "content": "User likes Python",
                "category": "preference",
                "confidence": 0.9,
                "createdAt": "2026-03-18T00:00:00Z",
                "source": "thread-a",
            },
            {
                "id": "fact_edit",
                "content": "User prefers tabs",
                "category": "preference",
                "confidence": 0.8,
                "createdAt": "2026-03-18T00:00:00Z",
                "source": "manual",
            },
        ]
    )

    with (
        patch("deerflow.agents.memory.updater.get_memory_data", return_value=current_memory),
        patch("deerflow.agents.memory.updater._save_memory_to_file", return_value=True),
    ):
        result = update_memory_fact(
            fact_id="fact_edit",
            content="User prefers spaces",
            category="workflow",
            confidence=0.91,
        )

    assert result["facts"][0]["content"] == "User likes Python"
    assert result["facts"][1]["content"] == "User prefers spaces"
    assert result["facts"][1]["category"] == "workflow"
    assert result["facts"][1]["confidence"] == 0.91
    assert result["facts"][1]["createdAt"] == "2026-03-18T00:00:00Z"
    assert result["facts"][1]["source"] == "manual"


def test_update_memory_fact_preserves_omitted_fields() -> None:
    current_memory = _make_memory(
        facts=[
            {
                "id": "fact_edit",
                "content": "User prefers tabs",
                "category": "preference",
                "confidence": 0.8,
                "createdAt": "2026-03-18T00:00:00Z",
                "source": "manual",
            },
        ]
    )

    with (
        patch("deerflow.agents.memory.updater.get_memory_data", return_value=current_memory),
        patch("deerflow.agents.memory.updater._save_memory_to_file", return_value=True),
    ):
        result = update_memory_fact(
            fact_id="fact_edit",
            content="User prefers spaces",
        )

    assert result["facts"][0]["content"] == "User prefers spaces"
    assert result["facts"][0]["category"] == "preference"
    assert result["facts"][0]["confidence"] == 0.8


def test_update_memory_fact_raises_for_unknown_id() -> None:
    with patch("deerflow.agents.memory.updater.get_memory_data", return_value=_make_memory()):
        try:
            update_memory_fact(
                fact_id="fact_missing",
                content="User prefers concise code reviews.",
                category="preference",
                confidence=0.88,
            )
        except KeyError as exc:
            assert exc.args == ("fact_missing",)
        else:
            raise AssertionError("Expected KeyError for missing fact id")


def test_update_memory_fact_rejects_invalid_confidence() -> None:
    current_memory = _make_memory(
        facts=[
            {
                "id": "fact_edit",
                "content": "User prefers tabs",
                "category": "preference",
                "confidence": 0.8,
                "createdAt": "2026-03-18T00:00:00Z",
                "source": "manual",
            },
        ]
    )

    for confidence in (-0.1, 1.1, float("nan"), float("inf"), float("-inf")):
        with patch(
            "deerflow.agents.memory.updater.get_memory_data",
            return_value=current_memory,
        ):
            try:
                update_memory_fact(
                    fact_id="fact_edit",
                    content="User prefers spaces",
                    confidence=confidence,
                )
            except ValueError as exc:
                assert exc.args == ("confidence",)
            else:
                raise AssertionError("Expected ValueError for invalid fact confidence")


# ---------------------------------------------------------------------------
# _extract_text - LLM response content normalization
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
        content = ['{"user"', ': "alice"}']
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
# format_conversation_for_update - handles mixed list content
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
# update_memory - structured LLM response handling
# ---------------------------------------------------------------------------


class TestUpdateMemoryStructuredResponse:
    """update_memory should handle LLM responses returned as list content blocks."""

    def _make_mock_model(self, content):
        model = MagicMock()
        response = MagicMock()
        response.content = content
        model.ainvoke = AsyncMock(return_value=response)
        return model

    def test_string_response_parses(self):
        updater = MemoryUpdater()
        valid_json = '{"user": {}, "history": {}, "newFacts": [], "factsToRemove": []}'
        model = self._make_mock_model(valid_json)

        with (
            patch.object(updater, "_get_model", return_value=model),
            patch("deerflow.agents.memory.updater.get_memory_config", return_value=_memory_config(enabled=True)),
            patch("deerflow.agents.memory.updater.get_memory_data", return_value=_make_memory()),
            patch("deerflow.agents.memory.updater.get_memory_storage", return_value=MagicMock(save=MagicMock(return_value=True))),
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
        model.ainvoke.assert_awaited_once()

    def test_list_content_response_parses(self):
        """LLM response as list-of-blocks should be extracted, not repr'd."""
        updater = MemoryUpdater()
        valid_json = '{"user": {}, "history": {}, "newFacts": [], "factsToRemove": []}'
        list_content = [{"type": "text", "text": valid_json}]

        with (
            patch.object(updater, "_get_model", return_value=self._make_mock_model(list_content)),
            patch("deerflow.agents.memory.updater.get_memory_config", return_value=_memory_config(enabled=True)),
            patch("deerflow.agents.memory.updater.get_memory_data", return_value=_make_memory()),
            patch("deerflow.agents.memory.updater.get_memory_storage", return_value=MagicMock(save=MagicMock(return_value=True))),
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

    def test_async_update_memory_uses_ainvoke(self):
        updater = MemoryUpdater()
        valid_json = '{"user": {}, "history": {}, "newFacts": [], "factsToRemove": []}'
        model = self._make_mock_model(valid_json)

        with (
            patch.object(updater, "_get_model", return_value=model),
            patch("deerflow.agents.memory.updater.get_memory_config", return_value=_memory_config(enabled=True)),
            patch("deerflow.agents.memory.updater.get_memory_data", return_value=_make_memory()),
            patch("deerflow.agents.memory.updater.get_memory_storage", return_value=MagicMock(save=MagicMock(return_value=True))),
        ):
            msg = MagicMock()
            msg.type = "human"
            msg.content = "Hello"
            ai_msg = MagicMock()
            ai_msg.type = "ai"
            ai_msg.content = "Hi there"
            ai_msg.tool_calls = []
            result = asyncio.run(updater.aupdate_memory([msg, ai_msg]))

        assert result is True
        model.ainvoke.assert_awaited_once()
        assert model.ainvoke.await_args.kwargs["config"] == {"run_name": "memory_agent"}

    def test_correction_hint_injected_when_detected(self):
        updater = MemoryUpdater()
        valid_json = '{"user": {}, "history": {}, "newFacts": [], "factsToRemove": []}'
        model = self._make_mock_model(valid_json)

        with (
            patch.object(updater, "_get_model", return_value=model),
            patch("deerflow.agents.memory.updater.get_memory_config", return_value=_memory_config(enabled=True)),
            patch("deerflow.agents.memory.updater.get_memory_data", return_value=_make_memory()),
            patch("deerflow.agents.memory.updater.get_memory_storage", return_value=MagicMock(save=MagicMock(return_value=True))),
        ):
            msg = MagicMock()
            msg.type = "human"
            msg.content = "No, that's wrong."
            ai_msg = MagicMock()
            ai_msg.type = "ai"
            ai_msg.content = "Understood"
            ai_msg.tool_calls = []

            result = updater.update_memory([msg, ai_msg], correction_detected=True)

        assert result is True
        prompt = model.ainvoke.await_args.args[0]
        assert "Explicit correction signals were detected" in prompt

    def test_correction_hint_empty_when_not_detected(self):
        updater = MemoryUpdater()
        valid_json = '{"user": {}, "history": {}, "newFacts": [], "factsToRemove": []}'
        model = self._make_mock_model(valid_json)

        with (
            patch.object(updater, "_get_model", return_value=model),
            patch("deerflow.agents.memory.updater.get_memory_config", return_value=_memory_config(enabled=True)),
            patch("deerflow.agents.memory.updater.get_memory_data", return_value=_make_memory()),
            patch("deerflow.agents.memory.updater.get_memory_storage", return_value=MagicMock(save=MagicMock(return_value=True))),
        ):
            msg = MagicMock()
            msg.type = "human"
            msg.content = "Let's talk about memory."
            ai_msg = MagicMock()
            ai_msg.type = "ai"
            ai_msg.content = "Sure"
            ai_msg.tool_calls = []

            result = updater.update_memory([msg, ai_msg], correction_detected=False)

        assert result is True
        prompt = model.ainvoke.await_args.args[0]
        assert "Explicit correction signals were detected" not in prompt

    def test_sync_update_memory_wrapper_works_in_running_loop(self):
        updater = MemoryUpdater()
        valid_json = '{"user": {}, "history": {}, "newFacts": [], "factsToRemove": []}'
        model = self._make_mock_model(valid_json)

        with (
            patch.object(updater, "_get_model", return_value=model),
            patch("deerflow.agents.memory.updater.get_memory_config", return_value=_memory_config(enabled=True)),
            patch("deerflow.agents.memory.updater.get_memory_data", return_value=_make_memory()),
            patch("deerflow.agents.memory.updater.get_memory_storage", return_value=MagicMock(save=MagicMock(return_value=True))),
        ):
            msg = MagicMock()
            msg.type = "human"
            msg.content = "Hello from loop"
            ai_msg = MagicMock()
            ai_msg.type = "ai"
            ai_msg.content = "Hi"
            ai_msg.tool_calls = []

            async def run_in_loop():
                return updater.update_memory([msg, ai_msg])

            result = asyncio.run(run_in_loop())

        assert result is True
        model.ainvoke.assert_awaited_once()

    def test_sync_update_memory_returns_false_when_bridge_submit_fails(self):
        updater = MemoryUpdater()

        with (
            patch(
                "deerflow.agents.memory.updater._SYNC_MEMORY_UPDATER_EXECUTOR.submit",
                side_effect=RuntimeError("executor down"),
            ),
        ):
            msg = MagicMock()
            msg.type = "human"
            msg.content = "Hello from loop"
            ai_msg = MagicMock()
            ai_msg.type = "ai"
            ai_msg.content = "Hi"
            ai_msg.tool_calls = []

            async def run_in_loop():
                return updater.update_memory([msg, ai_msg])

            result = asyncio.run(run_in_loop())

        assert result is False


class TestRunAsyncUpdateSync:
    def test_closes_unawaited_awaitable_when_bridge_fails_before_handoff(self):
        class CloseableAwaitable:
            def __init__(self):
                self.closed = False

            def __await__(self):
                pytest.fail("awaitable should not have been awaited")
                yield

            def close(self):
                self.closed = True

        awaitable = CloseableAwaitable()

        with patch(
            "deerflow.agents.memory.updater._SYNC_MEMORY_UPDATER_EXECUTOR.submit",
            side_effect=RuntimeError("executor down"),
        ):

            async def run_in_loop():
                return _run_async_update_sync(awaitable)

            result = asyncio.run(run_in_loop())

        assert result is False
        assert awaitable.closed is True


class TestFactDeduplicationCaseInsensitive:
    """Tests that fact deduplication is case-insensitive."""

    def test_duplicate_fact_different_case_not_stored(self):
        updater = MemoryUpdater()
        current_memory = _make_memory(
            facts=[
                {
                    "id": "fact_1",
                    "content": "User prefers Python",
                    "category": "preference",
                    "confidence": 0.9,
                    "createdAt": "2026-01-01T00:00:00Z",
                    "source": "thread-a",
                },
            ]
        )
        # Same fact with different casing should be treated as duplicate
        update_data = {
            "factsToRemove": [],
            "newFacts": [
                {"content": "user prefers python", "category": "preference", "confidence": 0.95},
            ],
        }

        with patch(
            "deerflow.agents.memory.updater.get_memory_config",
            return_value=_memory_config(max_facts=100, fact_confidence_threshold=0.7),
        ):
            result = updater._apply_updates(current_memory, update_data, thread_id="thread-b")

        # Should still have only 1 fact (duplicate rejected)
        assert len(result["facts"]) == 1
        assert result["facts"][0]["content"] == "User prefers Python"

    def test_unique_fact_different_case_and_content_stored(self):
        updater = MemoryUpdater()
        current_memory = _make_memory(
            facts=[
                {
                    "id": "fact_1",
                    "content": "User prefers Python",
                    "category": "preference",
                    "confidence": 0.9,
                    "createdAt": "2026-01-01T00:00:00Z",
                    "source": "thread-a",
                },
            ]
        )
        update_data = {
            "factsToRemove": [],
            "newFacts": [
                {"content": "User prefers Go", "category": "preference", "confidence": 0.85},
            ],
        }

        with patch(
            "deerflow.agents.memory.updater.get_memory_config",
            return_value=_memory_config(max_facts=100, fact_confidence_threshold=0.7),
        ):
            result = updater._apply_updates(current_memory, update_data, thread_id="thread-b")

        assert len(result["facts"]) == 2


class TestReinforcementHint:
    """Tests that reinforcement_detected injects the correct hint into the prompt."""

    @staticmethod
    def _make_mock_model(json_response: str):
        model = MagicMock()
        response = MagicMock()
        response.content = f"```json\n{json_response}\n```"
        model.ainvoke = AsyncMock(return_value=response)
        return model

    def test_reinforcement_hint_injected_when_detected(self):
        updater = MemoryUpdater()
        valid_json = '{"user": {}, "history": {}, "newFacts": [], "factsToRemove": []}'
        model = self._make_mock_model(valid_json)

        with (
            patch.object(updater, "_get_model", return_value=model),
            patch("deerflow.agents.memory.updater.get_memory_config", return_value=_memory_config(enabled=True)),
            patch("deerflow.agents.memory.updater.get_memory_data", return_value=_make_memory()),
            patch("deerflow.agents.memory.updater.get_memory_storage", return_value=MagicMock(save=MagicMock(return_value=True))),
        ):
            msg = MagicMock()
            msg.type = "human"
            msg.content = "Yes, exactly! That's what I needed."
            ai_msg = MagicMock()
            ai_msg.type = "ai"
            ai_msg.content = "Great to hear!"
            ai_msg.tool_calls = []

            result = updater.update_memory([msg, ai_msg], reinforcement_detected=True)

        assert result is True
        prompt = model.ainvoke.await_args.args[0]
        assert "Positive reinforcement signals were detected" in prompt

    def test_reinforcement_hint_absent_when_not_detected(self):
        updater = MemoryUpdater()
        valid_json = '{"user": {}, "history": {}, "newFacts": [], "factsToRemove": []}'
        model = self._make_mock_model(valid_json)

        with (
            patch.object(updater, "_get_model", return_value=model),
            patch("deerflow.agents.memory.updater.get_memory_config", return_value=_memory_config(enabled=True)),
            patch("deerflow.agents.memory.updater.get_memory_data", return_value=_make_memory()),
            patch("deerflow.agents.memory.updater.get_memory_storage", return_value=MagicMock(save=MagicMock(return_value=True))),
        ):
            msg = MagicMock()
            msg.type = "human"
            msg.content = "Tell me more."
            ai_msg = MagicMock()
            ai_msg.type = "ai"
            ai_msg.content = "Sure."
            ai_msg.tool_calls = []

            result = updater.update_memory([msg, ai_msg], reinforcement_detected=False)

        assert result is True
        prompt = model.ainvoke.await_args.args[0]
        assert "Positive reinforcement signals were detected" not in prompt

    def test_both_hints_present_when_both_detected(self):
        updater = MemoryUpdater()
        valid_json = '{"user": {}, "history": {}, "newFacts": [], "factsToRemove": []}'
        model = self._make_mock_model(valid_json)

        with (
            patch.object(updater, "_get_model", return_value=model),
            patch("deerflow.agents.memory.updater.get_memory_config", return_value=_memory_config(enabled=True)),
            patch("deerflow.agents.memory.updater.get_memory_data", return_value=_make_memory()),
            patch("deerflow.agents.memory.updater.get_memory_storage", return_value=MagicMock(save=MagicMock(return_value=True))),
        ):
            msg = MagicMock()
            msg.type = "human"
            msg.content = "No wait, that's wrong. Actually yes, exactly right."
            ai_msg = MagicMock()
            ai_msg.type = "ai"
            ai_msg.content = "Got it."
            ai_msg.tool_calls = []

            result = updater.update_memory([msg, ai_msg], correction_detected=True, reinforcement_detected=True)

        assert result is True
        prompt = model.ainvoke.await_args.args[0]
        assert "Explicit correction signals were detected" in prompt
        assert "Positive reinforcement signals were detected" in prompt


class TestFinalizeCacheIsolation:
    """_finalize_update must not mutate the cached memory object."""

    def test_deepcopy_prevents_cache_corruption_on_save_failure(self):
        """If save() fails, the in-memory snapshot used by _finalize_update
        must remain independent of any object the storage layer may still hold in
        its cache.  The deepcopy in _finalize_update achieves this — the object
        passed to _apply_updates is always a fresh copy, never the cache reference.
        """
        updater = MemoryUpdater()
        original_memory = _make_memory(facts=[{"id": "fact_orig", "content": "original", "category": "context", "confidence": 0.9, "createdAt": "2024-01-01T00:00:00Z", "source": "t1"}])

        import json as _json

        new_fact_json = _json.dumps(
            {
                "user": {},
                "history": {},
                "newFacts": [{"content": "new fact", "category": "context", "confidence": 0.9}],
                "factsToRemove": [],
            }
        )
        mock_response = MagicMock()
        mock_response.content = new_fact_json
        mock_model = AsyncMock()
        mock_model.ainvoke = AsyncMock(return_value=mock_response)

        saved_objects: list[dict] = []
        save_mock = MagicMock(side_effect=lambda m, a=None: saved_objects.append(m) or False)  # always fails

        with (
            patch.object(updater, "_get_model", return_value=mock_model),
            patch("deerflow.agents.memory.updater.get_memory_config", return_value=_memory_config(enabled=True, fact_confidence_threshold=0.7)),
            patch("deerflow.agents.memory.updater.get_memory_data", return_value=original_memory),
            patch("deerflow.agents.memory.updater.get_memory_storage", return_value=MagicMock(save=save_mock)),
        ):
            msg = MagicMock()
            msg.type = "human"
            msg.content = "hello"
            ai_msg = MagicMock()
            ai_msg.type = "ai"
            ai_msg.content = "world"
            ai_msg.tool_calls = []
            updater.update_memory([msg, ai_msg], thread_id="t1")

        # original_memory must not have been mutated — deepcopy isolates the mutation
        assert len(original_memory["facts"]) == 1, "original_memory must not be mutated by _apply_updates"
        assert original_memory["facts"][0]["content"] == "original"
