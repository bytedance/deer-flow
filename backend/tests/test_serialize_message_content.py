"""Regression tests for ToolMessage content normalization in serialization.

Ensures that structured content (list-of-blocks) is properly extracted to
plain text, preventing raw Python repr strings from reaching the UI.

See: https://github.com/bytedance/deer-flow/issues/1149
"""

from langchain_core.messages import ToolMessage

from deerflow.client import DeerFlowClient

# ---------------------------------------------------------------------------
# _serialize_message
# ---------------------------------------------------------------------------


class TestSerializeToolMessageContent:
    """DeerFlowClient._serialize_message should normalize ToolMessage content."""

    def test_string_content(self):
        msg = ToolMessage(content="ok", tool_call_id="tc1", name="search")
        result = DeerFlowClient._serialize_message(msg)
        assert result["content"] == "ok"
        assert result["type"] == "tool"

    def test_list_of_blocks_content(self):
        """List-of-blocks should be extracted, not repr'd."""
        msg = ToolMessage(
            content=[{"type": "text", "text": "hello world"}],
            tool_call_id="tc1",
            name="search",
        )
        result = DeerFlowClient._serialize_message(msg)
        assert result["content"] == "hello world"
        # Must NOT contain Python repr artifacts
        assert "[" not in result["content"]
        assert "{" not in result["content"]

    def test_multiple_text_blocks(self):
        """Multiple full text blocks should be joined with newlines."""
        msg = ToolMessage(
            content=[
                {"type": "text", "text": "line 1"},
                {"type": "text", "text": "line 2"},
            ],
            tool_call_id="tc1",
            name="search",
        )
        result = DeerFlowClient._serialize_message(msg)
        assert result["content"] == "line 1\nline 2"

    def test_string_chunks_are_joined_without_newlines(self):
        """Chunked string payloads should not get artificial separators."""
        msg = ToolMessage(
            content=["{\"a\"", ": \"b\"}"] ,
            tool_call_id="tc1",
            name="search",
        )
        result = DeerFlowClient._serialize_message(msg)
        assert result["content"] == '{"a": "b"}'

    def test_mixed_string_chunks_and_blocks(self):
        """String chunks stay contiguous, but text blocks remain separated."""
        msg = ToolMessage(
            content=["prefix", "-continued", {"type": "text", "text": "block text"}],
            tool_call_id="tc1",
            name="search",
        )
        result = DeerFlowClient._serialize_message(msg)
        assert result["content"] == "prefix-continued\nblock text"

    def test_mixed_blocks_with_non_text(self):
        """Non-text blocks (e.g. image) should be skipped gracefully."""
        msg = ToolMessage(
            content=[
                {"type": "text", "text": "found results"},
                {"type": "image_url", "image_url": {"url": "http://img.png"}},
            ],
            tool_call_id="tc1",
            name="view_image",
        )
        result = DeerFlowClient._serialize_message(msg)
        assert result["content"] == "found results"

    def test_empty_list_content(self):
        msg = ToolMessage(content=[], tool_call_id="tc1", name="search")
        result = DeerFlowClient._serialize_message(msg)
        assert result["content"] == ""

    def test_plain_string_in_list(self):
        """Bare strings inside a list should be kept."""
        msg = ToolMessage(
            content=["plain text block"],
            tool_call_id="tc1",
            name="search",
        )
        result = DeerFlowClient._serialize_message(msg)
        assert result["content"] == "plain text block"

    def test_unknown_content_type_falls_back(self):
        """Unexpected types should not crash — return str()."""
        msg = ToolMessage(content=42, tool_call_id="tc1", name="calc")
        result = DeerFlowClient._serialize_message(msg)
        # int → not str, not list → falls to str()
        assert result["content"] == "42"


# ---------------------------------------------------------------------------
# _extract_text (already existed, but verify it also covers ToolMessage paths)
# ---------------------------------------------------------------------------


class TestExtractText:
    """DeerFlowClient._extract_text should handle all content shapes."""

    def test_string_passthrough(self):
        assert DeerFlowClient._extract_text("hello") == "hello"

    def test_list_text_blocks(self):
        assert DeerFlowClient._extract_text(
            [{"type": "text", "text": "hi"}]
        ) == "hi"

    def test_empty_list(self):
        assert DeerFlowClient._extract_text([]) == ""

    def test_fallback_non_iterable(self):
        assert DeerFlowClient._extract_text(123) == "123"
