"""Tests for ClarificationMiddleware."""

from unittest.mock import MagicMock

from langgraph.types import Command

from src.agents.middlewares.clarification_middleware import ClarificationMiddleware


class TestClarificationMiddleware:
    def setup_method(self):
        self.middleware = ClarificationMiddleware()

    def test_format_clarification_simple_question(self):
        args = {"question": "What language?", "clarification_type": "missing_info"}
        result = self.middleware._format_clarification_message(args)
        assert "What language?" in result
        assert "❓" in result

    def test_format_clarification_with_context(self):
        args = {
            "question": "Which approach?",
            "clarification_type": "approach_choice",
            "context": "There are two ways to do this.",
        }
        result = self.middleware._format_clarification_message(args)
        assert "There are two ways" in result
        assert "Which approach?" in result
        assert "🔀" in result

    def test_format_clarification_with_options(self):
        args = {
            "question": "Pick one",
            "clarification_type": "missing_info",
            "options": ["Option A", "Option B", "Option C"],
        }
        result = self.middleware._format_clarification_message(args)
        assert "1. Option A" in result
        assert "2. Option B" in result
        assert "3. Option C" in result

    def test_wrap_tool_call_passes_through_non_clarification(self):
        request = MagicMock()
        request.tool_call = {"name": "web_search", "args": {"query": "hello"}}
        handler = MagicMock(return_value="result")

        result = self.middleware.wrap_tool_call(request, handler)
        handler.assert_called_once_with(request)
        assert result == "result"

    def test_wrap_tool_call_intercepts_clarification(self):
        request = MagicMock()
        request.tool_call = {
            "name": "ask_clarification",
            "id": "call_123",
            "args": {"question": "What do you mean?", "clarification_type": "ambiguous_requirement"},
        }
        handler = MagicMock()

        result = self.middleware.wrap_tool_call(request, handler)
        handler.assert_not_called()
        assert isinstance(result, Command)

    def test_handle_clarification_returns_end_command(self):
        request = MagicMock()
        request.tool_call = {
            "name": "ask_clarification",
            "id": "call_456",
            "args": {"question": "Clarify?", "clarification_type": "missing_info"},
        }

        result = self.middleware._handle_clarification(request)
        assert isinstance(result, Command)
        assert result.goto == "__end__"
        messages = result.update.get("messages", [])
        assert len(messages) == 1
        assert messages[0].name == "ask_clarification"
        assert "Clarify?" in messages[0].content

    def test_type_icons(self):
        type_to_icon = {
            "missing_info": "❓",
            "ambiguous_requirement": "🤔",
            "approach_choice": "🔀",
            "risk_confirmation": "⚠️",
            "suggestion": "💡",
        }
        for ctype, icon in type_to_icon.items():
            args = {"question": "Q", "clarification_type": ctype}
            result = self.middleware._format_clarification_message(args)
            assert icon in result, f"Expected {icon} for type {ctype}"
