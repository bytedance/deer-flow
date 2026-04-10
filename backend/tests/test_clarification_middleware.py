"""Tests for ClarificationMiddleware.

Covers:
- Options type coercion (JSON string normalization)
- clarification_enabled flag (interrupt vs auto-respond)
"""

import json
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from deerflow.agents.middlewares.clarification_middleware import (
    _AUTO_RESPONSE,
    ClarificationMiddleware,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def middleware():
    return ClarificationMiddleware()


def _make_request(tool_name: str = "ask_clarification", question: str = "Which stock?") -> MagicMock:
    """Build a mock ToolCallRequest."""
    req = MagicMock()
    req.tool_call = {
        "name": tool_name,
        "id": "call_abc123",
        "args": {
            "question": question,
            "clarification_type": "missing_info",
        },
    }
    return req


# ---------------------------------------------------------------------------
# Options type coercion tests
# ---------------------------------------------------------------------------

class TestFormatClarificationMessage:
    """Tests for _format_clarification_message options handling."""

    def test_options_as_native_list(self, middleware):
        """Normal case: options is already a list."""
        args = {
            "question": "Which env?",
            "clarification_type": "approach_choice",
            "options": ["dev", "staging", "prod"],
        }
        result = middleware._format_clarification_message(args)
        assert "1. dev" in result
        assert "2. staging" in result
        assert "3. prod" in result

    def test_options_as_json_string(self, middleware):
        """Bug case (#1995): model serializes options as a JSON string."""
        args = {
            "question": "Which env?",
            "clarification_type": "approach_choice",
            "options": json.dumps(["dev", "staging", "prod"]),
        }
        result = middleware._format_clarification_message(args)
        assert "1. dev" in result
        assert "2. staging" in result
        assert "3. prod" in result
        # Must NOT contain per-character output
        assert "1. [" not in result
        assert '2. "' not in result

    def test_options_as_json_string_scalar(self, middleware):
        """JSON string decoding to a non-list scalar is treated as one option."""
        args = {
            "question": "Which env?",
            "clarification_type": "approach_choice",
            "options": json.dumps("development"),
        }
        result = middleware._format_clarification_message(args)
        assert "1. development" in result
        # Must be a single option, not per-character iteration.
        assert "2." not in result

    def test_options_as_plain_string(self, middleware):
        """Edge case: options is a non-JSON string, treated as single option."""
        args = {
            "question": "Which env?",
            "clarification_type": "approach_choice",
            "options": "just one option",
        }
        result = middleware._format_clarification_message(args)
        assert "1. just one option" in result

    def test_options_none(self, middleware):
        """Options is None — no options section rendered."""
        args = {
            "question": "Tell me more",
            "clarification_type": "missing_info",
            "options": None,
        }
        result = middleware._format_clarification_message(args)
        assert "1." not in result

    def test_options_empty_list(self, middleware):
        """Options is an empty list — no options section rendered."""
        args = {
            "question": "Tell me more",
            "clarification_type": "missing_info",
            "options": [],
        }
        result = middleware._format_clarification_message(args)
        assert "1." not in result

    def test_options_missing(self, middleware):
        """Options key is absent — defaults to empty list."""
        args = {
            "question": "Tell me more",
            "clarification_type": "missing_info",
        }
        result = middleware._format_clarification_message(args)
        assert "1." not in result

    def test_context_included(self, middleware):
        """Context is rendered before the question."""
        args = {
            "question": "Which env?",
            "clarification_type": "approach_choice",
            "context": "Need target env for config",
            "options": ["dev", "prod"],
        }
        result = middleware._format_clarification_message(args)
        assert "Need target env for config" in result
        assert "Which env?" in result
        assert "1. dev" in result

    def test_json_string_with_mixed_types(self, middleware):
        """JSON string containing non-string elements still works."""
        args = {
            "question": "Pick one",
            "clarification_type": "approach_choice",
            "options": json.dumps(["Option A", 2, True, None]),
        }
        result = middleware._format_clarification_message(args)
        assert "1. Option A" in result
        assert "2. 2" in result
        assert "3. True" in result
        assert "4. None" in result


# ---------------------------------------------------------------------------
# clarification_enabled flag tests
# ---------------------------------------------------------------------------

class TestClarificationMiddlewareEnabled:
    """Tests with clarification_enabled=True (default / interactive mode)."""

    def test_default_is_enabled(self):
        mw = ClarificationMiddleware()
        assert mw.enabled is True

    def test_interrupt_returns_command(self):
        mw = ClarificationMiddleware(enabled=True)
        handler = MagicMock()
        result = mw.wrap_tool_call(_make_request(), handler)

        assert isinstance(result, Command)
        handler.assert_not_called()

    def test_interrupt_command_goes_to_end(self):
        mw = ClarificationMiddleware(enabled=True)
        result = mw.wrap_tool_call(_make_request(), MagicMock())

        assert result.goto == "__end__"

    def test_interrupt_includes_tool_message(self):
        mw = ClarificationMiddleware(enabled=True)
        result = mw.wrap_tool_call(_make_request(question="Which ticker?"), MagicMock())

        messages = result.update["messages"]
        assert len(messages) == 1
        assert isinstance(messages[0], ToolMessage)
        assert "Which ticker?" in messages[0].content

    def test_non_clarification_tool_passes_through(self):
        mw = ClarificationMiddleware(enabled=True)
        handler = MagicMock(return_value=ToolMessage(content="ok", tool_call_id="x", name="web_search"))
        req = _make_request(tool_name="web_search")

        result = mw.wrap_tool_call(req, handler)

        handler.assert_called_once_with(req)
        assert isinstance(result, ToolMessage)
        assert result.content == "ok"


class TestClarificationMiddlewareDisabled:
    """Tests with clarification_enabled=False (headless / API mode)."""

    def test_auto_responds_with_tool_message(self):
        mw = ClarificationMiddleware(enabled=False)
        handler = MagicMock()
        result = mw.wrap_tool_call(_make_request(), handler)

        assert isinstance(result, ToolMessage)
        assert not isinstance(result, Command)
        handler.assert_not_called()

    def test_auto_response_content(self):
        mw = ClarificationMiddleware(enabled=False)
        result = mw.wrap_tool_call(_make_request(), MagicMock())

        assert result.content == _AUTO_RESPONSE
        assert "best judgment" in result.content

    def test_auto_response_preserves_tool_call_id(self):
        mw = ClarificationMiddleware(enabled=False)
        result = mw.wrap_tool_call(_make_request(), MagicMock())

        assert result.tool_call_id == "call_abc123"
        assert result.name == "ask_clarification"

    def test_non_clarification_tool_still_passes_through(self):
        mw = ClarificationMiddleware(enabled=False)
        handler = MagicMock(return_value=ToolMessage(content="ok", tool_call_id="x", name="bash"))
        req = _make_request(tool_name="bash")

        mw.wrap_tool_call(req, handler)

        handler.assert_called_once_with(req)


class TestClarificationMiddlewareAsync:
    """Verify async wrappers match sync behaviour."""

    def test_enabled_interrupts_async(self):
        import asyncio

        async def _run():
            mw = ClarificationMiddleware(enabled=True)
            return await mw.awrap_tool_call(_make_request(), MagicMock())

        result = asyncio.run(_run())
        assert isinstance(result, Command)
        assert result.goto == "__end__"

    def test_disabled_auto_responds_async(self):
        import asyncio

        async def _run():
            mw = ClarificationMiddleware(enabled=False)
            return await mw.awrap_tool_call(_make_request(), MagicMock())

        result = asyncio.run(_run())
        assert isinstance(result, ToolMessage)
        assert result.content == _AUTO_RESPONSE
