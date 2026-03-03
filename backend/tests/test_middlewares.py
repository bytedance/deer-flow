"""Tests for remaining middlewares: usage tracking, memory, title, clarification, view image, subagent limit, uploads, phase filter."""

from __future__ import annotations

import threading
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.agents.middlewares.clarification_middleware import ClarificationMiddleware
from src.agents.middlewares.phase_filter_middleware import (
    ExecutionPhase,
    _detect_phase,
)
from src.agents.middlewares.subagent_limit_middleware import (
    SubagentLimitMiddleware,
    _clamp_subagent_limit,
)
from src.agents.middlewares.usage_tracking_middleware import (
    UsageTrackingMiddleware,
    add_subagent_usage,
    drain_subagent_usage,
    _pending_subagent_usage,
    _pending_lock,
)
from src.agents.middlewares.view_image_middleware import ViewImageMiddleware


def _make_runtime(context: dict | None = None) -> SimpleNamespace:
    """Create a lightweight runtime mock."""
    return SimpleNamespace(context=context or {})


# ---------------------------------------------------------------------------
# UsageTrackingMiddleware — add/drain helpers
# ---------------------------------------------------------------------------
class TestUsageTrackingHelpers:
    """Tests for add_subagent_usage and drain_subagent_usage."""

    def setup_method(self) -> None:
        with _pending_lock:
            _pending_subagent_usage.clear()

    def teardown_method(self) -> None:
        with _pending_lock:
            _pending_subagent_usage.clear()

    def test_add_subagent_usage(self) -> None:
        add_subagent_usage("t1", {"input_tokens": 10, "output_tokens": 5})
        with _pending_lock:
            assert _pending_subagent_usage["t1"]["input_tokens"] == 10
            assert _pending_subagent_usage["t1"]["output_tokens"] == 5

    def test_add_accumulates(self) -> None:
        add_subagent_usage("t1", {"input_tokens": 10, "output_tokens": 5})
        add_subagent_usage("t1", {"input_tokens": 20, "output_tokens": 15})
        with _pending_lock:
            assert _pending_subagent_usage["t1"]["input_tokens"] == 30
            assert _pending_subagent_usage["t1"]["output_tokens"] == 20

    def test_add_none_usage_noop(self) -> None:
        add_subagent_usage("t1", None)
        with _pending_lock:
            assert "t1" not in _pending_subagent_usage

    def test_add_empty_thread_id_noop(self) -> None:
        add_subagent_usage("", {"input_tokens": 10, "output_tokens": 5})
        with _pending_lock:
            assert "" not in _pending_subagent_usage

    def test_drain_returns_and_removes(self) -> None:
        add_subagent_usage("t1", {"input_tokens": 10, "output_tokens": 5})
        result = drain_subagent_usage("t1")
        assert result == {"input_tokens": 10, "output_tokens": 5}
        assert drain_subagent_usage("t1") is None

    def test_drain_unknown_thread(self) -> None:
        assert drain_subagent_usage("unknown") is None

    def test_drain_empty_thread_id(self) -> None:
        assert drain_subagent_usage("") is None


class TestUsageTrackingMiddleware:
    """Tests for UsageTrackingMiddleware._extract_and_emit."""

    def setup_method(self) -> None:
        with _pending_lock:
            _pending_subagent_usage.clear()

    def teardown_method(self) -> None:
        with _pending_lock:
            _pending_subagent_usage.clear()

    def test_extracts_usage_from_ai_message(self) -> None:
        mw = UsageTrackingMiddleware()
        ai_msg = AIMessage(content="hi")
        ai_msg.usage_metadata = {"input_tokens": 100, "output_tokens": 50}

        state: dict[str, Any] = {"messages": [ai_msg]}
        runtime = _make_runtime(context={"thread_id": "t1"})

        with patch("src.agents.middlewares.usage_tracking_middleware.get_stream_writer", side_effect=Exception):
            result = mw._extract_and_emit(state, runtime)

        assert result is not None
        assert result["token_usage"]["input_tokens"] == 100
        assert result["token_usage"]["output_tokens"] == 50

    def test_returns_none_for_no_messages(self) -> None:
        mw = UsageTrackingMiddleware()
        state: dict[str, Any] = {"messages": []}
        runtime = _make_runtime()
        assert mw._extract_and_emit(state, runtime) is None

    def test_returns_none_for_non_ai_message(self) -> None:
        mw = UsageTrackingMiddleware()
        state: dict[str, Any] = {"messages": [HumanMessage(content="hi")]}
        runtime = _make_runtime()
        assert mw._extract_and_emit(state, runtime) is None

    def test_returns_none_for_no_usage(self) -> None:
        mw = UsageTrackingMiddleware()
        ai_msg = AIMessage(content="hi")
        state: dict[str, Any] = {"messages": [ai_msg]}
        runtime = _make_runtime()
        assert mw._extract_and_emit(state, runtime) is None

    def test_drains_subagent_usage(self) -> None:
        mw = UsageTrackingMiddleware()
        add_subagent_usage("t1", {"input_tokens": 50, "output_tokens": 25})

        ai_msg = AIMessage(content="hi")
        ai_msg.usage_metadata = {"input_tokens": 100, "output_tokens": 50}

        state: dict[str, Any] = {"messages": [ai_msg]}
        runtime = _make_runtime(context={"thread_id": "t1"})

        with patch("src.agents.middlewares.usage_tracking_middleware.get_stream_writer", side_effect=Exception):
            result = mw._extract_and_emit(state, runtime)

        assert result["token_usage"]["input_tokens"] == 150
        assert result["token_usage"]["output_tokens"] == 75


# ---------------------------------------------------------------------------
# ClarificationMiddleware
# ---------------------------------------------------------------------------
class TestClarificationMiddleware:
    """Tests for ClarificationMiddleware."""

    def test_is_chinese_true(self) -> None:
        mw = ClarificationMiddleware()
        assert mw._is_chinese("你好") is True

    def test_is_chinese_false(self) -> None:
        mw = ClarificationMiddleware()
        assert mw._is_chinese("Hello world") is False

    def test_format_with_options(self) -> None:
        mw = ClarificationMiddleware()
        msg = mw._format_clarification_message({
            "question": "Which approach?",
            "clarification_type": "approach_choice",
            "options": ["Option A", "Option B"],
        })
        assert "Which approach?" in msg
        assert "Option A" in msg
        assert "Option B" in msg

    def test_format_with_context(self) -> None:
        mw = ClarificationMiddleware()
        msg = mw._format_clarification_message({
            "question": "What size?",
            "context": "You requested a T-shirt",
            "clarification_type": "missing_info",
        })
        assert "You requested a T-shirt" in msg
        assert "What size?" in msg

    def test_wrap_tool_call_non_clarification(self) -> None:
        mw = ClarificationMiddleware()
        request = MagicMock()
        request.tool_call = {"name": "bash", "id": "tc1", "args": {}}
        handler = MagicMock(return_value=ToolMessage(content="ok", tool_call_id="tc1"))

        result = mw.wrap_tool_call(request, handler)
        handler.assert_called_once_with(request)
        assert isinstance(result, ToolMessage)

    def test_wrap_tool_call_clarification(self) -> None:
        mw = ClarificationMiddleware()
        request = MagicMock()
        request.tool_call = {
            "name": "ask_clarification",
            "id": "tc1",
            "args": {"question": "Are you sure?"},
        }
        handler = MagicMock()

        from langgraph.types import Command

        result = mw.wrap_tool_call(request, handler)
        handler.assert_not_called()
        assert isinstance(result, Command)


# ---------------------------------------------------------------------------
# ViewImageMiddleware
# ---------------------------------------------------------------------------
class TestViewImageMiddleware:
    """Tests for ViewImageMiddleware helper methods."""

    def test_has_view_image_tool_true(self) -> None:
        mw = ViewImageMiddleware()
        msg = AIMessage(content="", tool_calls=[{"name": "view_image", "id": "tc1", "args": {}}])
        assert mw._has_view_image_tool(msg) is True

    def test_has_view_image_tool_false(self) -> None:
        mw = ViewImageMiddleware()
        msg = AIMessage(content="", tool_calls=[{"name": "bash", "id": "tc1", "args": {}}])
        assert mw._has_view_image_tool(msg) is False

    def test_has_view_image_tool_no_calls(self) -> None:
        mw = ViewImageMiddleware()
        msg = AIMessage(content="hello")
        assert mw._has_view_image_tool(msg) is False

    def test_all_tools_completed_true(self) -> None:
        mw = ViewImageMiddleware()
        ai_msg = AIMessage(content="", tool_calls=[{"name": "view_image", "id": "tc1", "args": {}}])
        tool_msg = ToolMessage(content="result", tool_call_id="tc1")
        messages = [ai_msg, tool_msg]
        assert mw._all_tools_completed(messages, ai_msg) is True

    def test_all_tools_completed_false(self) -> None:
        mw = ViewImageMiddleware()
        ai_msg = AIMessage(content="", tool_calls=[
            {"name": "view_image", "id": "tc1", "args": {}},
            {"name": "view_image", "id": "tc2", "args": {}},
        ])
        tool_msg = ToolMessage(content="result", tool_call_id="tc1")
        messages = [ai_msg, tool_msg]
        assert mw._all_tools_completed(messages, ai_msg) is False

    def test_create_image_details_message_empty(self) -> None:
        mw = ViewImageMiddleware()
        state: dict[str, Any] = {"viewed_images": {}}
        content = mw._create_image_details_message(state)
        assert content == ["No images have been viewed."]

    def test_create_image_details_message_with_images(self) -> None:
        mw = ViewImageMiddleware()
        state: dict[str, Any] = {
            "viewed_images": {
                "/path/img.png": {"mime_type": "image/png", "base64": "abc123"},
            }
        }
        content = mw._create_image_details_message(state)
        assert any("img.png" in str(block) for block in content)
        assert any("image_url" in str(block) for block in content)


# ---------------------------------------------------------------------------
# SubagentLimitMiddleware
# ---------------------------------------------------------------------------
class TestSubagentLimitMiddleware:
    """Tests for SubagentLimitMiddleware."""

    def test_clamp_below_min(self) -> None:
        assert _clamp_subagent_limit(1) == 2

    def test_clamp_above_max(self) -> None:
        assert _clamp_subagent_limit(10) == 4

    def test_clamp_within_range(self) -> None:
        assert _clamp_subagent_limit(3) == 3

    def test_no_truncation_below_limit(self) -> None:
        mw = SubagentLimitMiddleware(max_concurrent=3)
        ai_msg = AIMessage(content="", tool_calls=[
            {"name": "task", "id": "tc1", "args": {}},
            {"name": "task", "id": "tc2", "args": {}},
        ])
        state: dict[str, Any] = {"messages": [ai_msg]}
        result = mw._truncate_task_calls(state)
        assert result is None

    def test_truncation_above_limit(self) -> None:
        mw = SubagentLimitMiddleware(max_concurrent=2)
        ai_msg = AIMessage(content="", tool_calls=[
            {"name": "task", "id": "tc1", "args": {}},
            {"name": "task", "id": "tc2", "args": {}},
            {"name": "task", "id": "tc3", "args": {}},
            {"name": "bash", "id": "tc4", "args": {}},
        ])
        state: dict[str, Any] = {"messages": [ai_msg]}
        result = mw._truncate_task_calls(state)
        assert result is not None
        updated_msg = result["messages"][0]
        task_calls = [tc for tc in updated_msg.tool_calls if tc["name"] == "task"]
        assert len(task_calls) == 2
        # Non-task calls should be preserved
        bash_calls = [tc for tc in updated_msg.tool_calls if tc["name"] == "bash"]
        assert len(bash_calls) == 1

    def test_no_truncation_for_non_task(self) -> None:
        mw = SubagentLimitMiddleware(max_concurrent=2)
        ai_msg = AIMessage(content="", tool_calls=[
            {"name": "bash", "id": "tc1", "args": {}},
            {"name": "bash", "id": "tc2", "args": {}},
            {"name": "bash", "id": "tc3", "args": {}},
        ])
        state: dict[str, Any] = {"messages": [ai_msg]}
        result = mw._truncate_task_calls(state)
        assert result is None

    def test_no_messages(self) -> None:
        mw = SubagentLimitMiddleware()
        state: dict[str, Any] = {"messages": []}
        assert mw._truncate_task_calls(state) is None

    def test_non_ai_last_message(self) -> None:
        mw = SubagentLimitMiddleware()
        state: dict[str, Any] = {"messages": [HumanMessage(content="hi")]}
        assert mw._truncate_task_calls(state) is None


# ---------------------------------------------------------------------------
# PhaseFilterMiddleware — _detect_phase
# ---------------------------------------------------------------------------
class TestDetectPhase:
    """Tests for _detect_phase()."""

    def test_empty_messages(self) -> None:
        assert _detect_phase({"messages": []}) == ExecutionPhase.PLANNING

    def test_no_ai_messages(self) -> None:
        state: dict[str, Any] = {"messages": [HumanMessage(content="hi")]}
        assert _detect_phase(state) == ExecutionPhase.PLANNING

    def test_read_tools_detected_as_planning(self) -> None:
        ai_msg = AIMessage(content="", tool_calls=[{"name": "read_file", "id": "tc1", "args": {}}])
        state: dict[str, Any] = {"messages": [ai_msg]}
        assert _detect_phase(state) == ExecutionPhase.PLANNING

    def test_write_tools_detected_as_execution(self) -> None:
        ai_msg = AIMessage(content="", tool_calls=[{"name": "bash", "id": "tc1", "args": {}}])
        state: dict[str, Any] = {"messages": [ai_msg]}
        assert _detect_phase(state) == ExecutionPhase.EXECUTION

    def test_present_files_detected_as_review(self) -> None:
        ai_msg = AIMessage(content="", tool_calls=[{"name": "present_files", "id": "tc1", "args": {}}])
        state: dict[str, Any] = {"messages": [ai_msg]}
        assert _detect_phase(state) == ExecutionPhase.REVIEW

    def test_many_ai_messages_defaults_to_execution(self) -> None:
        msgs = [AIMessage(content=f"msg{i}") for i in range(5)]
        state: dict[str, Any] = {"messages": msgs}
        assert _detect_phase(state) == ExecutionPhase.EXECUTION


# ---------------------------------------------------------------------------
# MemoryMiddleware — _filter_messages_for_memory
# ---------------------------------------------------------------------------
class TestFilterMessagesForMemory:
    """Tests for _filter_messages_for_memory()."""

    def test_keeps_human_and_final_ai(self) -> None:
        from src.agents.middlewares.memory_middleware import _filter_messages_for_memory

        messages = [
            HumanMessage(content="hi"),
            AIMessage(content="hello"),
        ]
        result = _filter_messages_for_memory(messages)
        assert len(result) == 2

    def test_filters_tool_messages(self) -> None:
        from src.agents.middlewares.memory_middleware import _filter_messages_for_memory

        messages = [
            HumanMessage(content="hi"),
            AIMessage(content="", tool_calls=[{"name": "bash", "id": "tc1", "args": {}}]),
            ToolMessage(content="output", tool_call_id="tc1"),
            AIMessage(content="Here's the result"),
        ]
        result = _filter_messages_for_memory(messages)
        assert len(result) == 2
        assert result[0].content == "hi"
        assert result[1].content == "Here's the result"

    def test_empty_messages(self) -> None:
        from src.agents.middlewares.memory_middleware import _filter_messages_for_memory

        assert _filter_messages_for_memory([]) == []


# ---------------------------------------------------------------------------
# TitleMiddleware — _should_generate_title
# ---------------------------------------------------------------------------
class TestTitleMiddleware:
    """Tests for TitleMiddleware._should_generate_title."""

    @patch("src.agents.middlewares.title_middleware.get_title_config")
    def test_disabled(self, mock_config) -> None:
        from src.agents.middlewares.title_middleware import TitleMiddleware

        mock_config.return_value = MagicMock(enabled=False)
        mw = TitleMiddleware()
        state: dict[str, Any] = {"messages": [HumanMessage(content="hi"), AIMessage(content="hello")]}
        assert mw._should_generate_title(state) is False

    @patch("src.agents.middlewares.title_middleware.get_title_config")
    def test_already_has_title(self, mock_config) -> None:
        from src.agents.middlewares.title_middleware import TitleMiddleware

        mock_config.return_value = MagicMock(enabled=True)
        mw = TitleMiddleware()
        state: dict[str, Any] = {
            "messages": [HumanMessage(content="hi"), AIMessage(content="hello")],
            "title": "Existing Title",
        }
        assert mw._should_generate_title(state) is False

    @patch("src.agents.middlewares.title_middleware.get_title_config")
    def test_first_exchange(self, mock_config) -> None:
        from src.agents.middlewares.title_middleware import TitleMiddleware

        mock_config.return_value = MagicMock(enabled=True)
        mw = TitleMiddleware()
        state: dict[str, Any] = {
            "messages": [HumanMessage(content="hi"), AIMessage(content="hello")],
        }
        assert mw._should_generate_title(state) is True

    @patch("src.agents.middlewares.title_middleware.get_title_config")
    def test_not_enough_messages(self, mock_config) -> None:
        from src.agents.middlewares.title_middleware import TitleMiddleware

        mock_config.return_value = MagicMock(enabled=True)
        mw = TitleMiddleware()
        state: dict[str, Any] = {"messages": [HumanMessage(content="hi")]}
        assert mw._should_generate_title(state) is False
