"""Tests for DanglingToolCallMiddleware: fixes incomplete tool call message history."""

from __future__ import annotations

from unittest.mock import MagicMock

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.agents.middlewares.dangling_tool_call_middleware import DanglingToolCallMiddleware


def _ai_msg(content: str = "", tool_calls: list | None = None) -> AIMessage:
    """Helper to create AIMessage with optional tool_calls."""
    tc = tool_calls or []
    return AIMessage(content=content, tool_calls=tc)


def _tool_msg(tool_call_id: str, content: str = "result", name: str = "tool") -> ToolMessage:
    """Helper to create ToolMessage with specific tool_call_id."""
    return ToolMessage(content=content, tool_call_id=tool_call_id, name=name)


class TestBuildPatchedMessages:
    """Tests for DanglingToolCallMiddleware._build_patched_messages()."""

    def setup_method(self) -> None:
        self.mw = DanglingToolCallMiddleware()

    def test_no_dangling_returns_none(self) -> None:
        """When all tool calls have matching ToolMessages, return None."""
        messages = [
            HumanMessage(content="hi"),
            _ai_msg(tool_calls=[{"id": "tc1", "name": "bash", "args": {}}]),
            _tool_msg("tc1"),
        ]
        assert self.mw._build_patched_messages(messages) is None

    def test_single_dangling_inserts_placeholder(self) -> None:
        """A single dangling tool call gets a placeholder ToolMessage."""
        messages = [
            HumanMessage(content="hi"),
            _ai_msg(tool_calls=[{"id": "tc1", "name": "bash", "args": {}}]),
        ]
        result = self.mw._build_patched_messages(messages)
        assert result is not None
        assert len(result) == 3  # human + ai + placeholder
        placeholder = result[2]
        assert isinstance(placeholder, ToolMessage)
        assert placeholder.tool_call_id == "tc1"
        assert placeholder.status == "error"
        assert "interrupted" in placeholder.content.lower()

    def test_multiple_dangling_on_one_ai_message(self) -> None:
        """Multiple dangling tool calls on one AIMessage get individual placeholders."""
        messages = [
            _ai_msg(tool_calls=[
                {"id": "tc1", "name": "bash", "args": {}},
                {"id": "tc2", "name": "read_file", "args": {}},
            ]),
        ]
        result = self.mw._build_patched_messages(messages)
        assert result is not None
        placeholders = [m for m in result if isinstance(m, ToolMessage)]
        assert len(placeholders) == 2
        assert {p.tool_call_id for p in placeholders} == {"tc1", "tc2"}

    def test_dangling_across_ai_messages(self) -> None:
        """Dangling calls across multiple AIMessages all get patched."""
        messages = [
            _ai_msg(tool_calls=[{"id": "tc1", "name": "bash", "args": {}}]),
            _ai_msg(tool_calls=[{"id": "tc2", "name": "ls", "args": {}}]),
        ]
        result = self.mw._build_patched_messages(messages)
        assert result is not None
        placeholders = [m for m in result if isinstance(m, ToolMessage)]
        assert len(placeholders) == 2

    def test_no_duplicates_for_already_handled(self) -> None:
        """Tool calls already matched to ToolMessages are not patched."""
        messages = [
            _ai_msg(tool_calls=[
                {"id": "tc1", "name": "bash", "args": {}},
                {"id": "tc2", "name": "ls", "args": {}},
            ]),
            _tool_msg("tc1"),
            # tc2 is dangling
        ]
        result = self.mw._build_patched_messages(messages)
        assert result is not None
        placeholders = [m for m in result if isinstance(m, ToolMessage) and m.status == "error"]
        assert len(placeholders) == 1
        assert placeholders[0].tool_call_id == "tc2"

    def test_placeholder_has_correct_name(self) -> None:
        """Placeholder preserves the tool name from the tool call."""
        messages = [
            _ai_msg(tool_calls=[{"id": "tc1", "name": "bash", "args": {}}]),
        ]
        result = self.mw._build_patched_messages(messages)
        placeholder = [m for m in result if isinstance(m, ToolMessage)][0]
        assert placeholder.name == "bash"

    def test_empty_messages(self) -> None:
        """No messages means no patches needed."""
        assert self.mw._build_patched_messages([]) is None

    def test_no_ai_messages(self) -> None:
        """Only human messages need no patching."""
        messages = [HumanMessage(content="hello")]
        assert self.mw._build_patched_messages(messages) is None

    def test_ai_without_tool_calls(self) -> None:
        """AI messages without tool_calls need no patching."""
        messages = [_ai_msg(content="Hello!")]
        assert self.mw._build_patched_messages(messages) is None


class TestWrapModelCall:
    """Tests for DanglingToolCallMiddleware.wrap_model_call()."""

    def setup_method(self) -> None:
        self.mw = DanglingToolCallMiddleware()

    def test_no_patches_passes_unmodified(self) -> None:
        """When no patches needed, handler receives original request."""
        request = MagicMock()
        request.messages = [HumanMessage(content="hi")]
        handler = MagicMock(return_value="response")

        result = self.mw.wrap_model_call(request, handler)

        handler.assert_called_once_with(request)
        assert result == "response"

    def test_with_patches_passes_modified_request(self) -> None:
        """When patches are needed, handler receives patched request."""
        request = MagicMock()
        request.messages = [
            _ai_msg(tool_calls=[{"id": "tc1", "name": "bash", "args": {}}]),
        ]
        patched_request = MagicMock()
        request.override.return_value = patched_request
        handler = MagicMock(return_value="response")

        result = self.mw.wrap_model_call(request, handler)

        request.override.assert_called_once()
        handler.assert_called_once_with(patched_request)
        assert result == "response"
