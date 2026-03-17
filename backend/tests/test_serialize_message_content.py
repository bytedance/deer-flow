"""Regression tests for ToolMessage content normalization in _serialize_message.

When a model returns ToolMessage content as a list of content blocks
(e.g., [{"type": "text", "text": "..."}]), the serializer must extract
the plain text instead of producing a Python repr string.

Fixes: https://github.com/bytedance/deer-flow/issues/1149
"""

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from deerflow.client import DeerFlowClient


class TestSerializeMessageToolContent:
    """Ensure _serialize_message normalizes ToolMessage content."""

    def test_tool_message_string_content(self):
        msg = ToolMessage(content="result text", id="t1", tool_call_id="tc1", name="bash")
        d = DeerFlowClient._serialize_message(msg)
        assert d["type"] == "tool"
        assert d["content"] == "result text"

    def test_tool_message_list_content_blocks(self):
        """List of content blocks should be joined as plain text, not repr."""
        msg = ToolMessage(
            content=[{"type": "text", "text": "first part"}, {"type": "text", "text": "second part"}],
            id="t2",
            tool_call_id="tc2",
            name="web_search",
        )
        d = DeerFlowClient._serialize_message(msg)
        assert d["type"] == "tool"
        assert d["content"] == "first part\nsecond part"
        # Must NOT contain dict repr
        assert "[{" not in d["content"]

    def test_tool_message_mixed_list_content(self):
        """List with string and dict blocks should extract text from both."""
        msg = ToolMessage(
            content=["raw string", {"type": "text", "text": "block text"}],
            id="t3",
            tool_call_id="tc3",
            name="fetch",
        )
        d = DeerFlowClient._serialize_message(msg)
        assert d["content"] == "raw string\nblock text"

    def test_tool_message_empty_list_content(self):
        """Empty list content should produce empty string."""
        msg = ToolMessage(
            content=[],
            id="t4",
            tool_call_id="tc4",
            name="bash",
        )
        d = DeerFlowClient._serialize_message(msg)
        assert d["content"] == ""

    def test_ai_message_preserves_list_content(self):
        """AI messages pass content as-is (frontend handles parsing)."""
        msg = AIMessage(
            content=[{"type": "text", "text": "hello"}],
            id="a1",
        )
        d = DeerFlowClient._serialize_message(msg)
        assert d["type"] == "ai"
        assert isinstance(d["content"], list)

    def test_human_message_passthrough(self):
        """Human messages pass content as-is."""
        msg = HumanMessage(content="user input", id="h1")
        d = DeerFlowClient._serialize_message(msg)
        assert d["type"] == "human"
        assert d["content"] == "user input"
