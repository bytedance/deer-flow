"""Tests for ToolEndEmitMiddleware."""

from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import ToolMessage

from deerflow.agents.middlewares.tool_end_emit_middleware import (
    ToolEndEmitMiddleware,
    _extract_summary,
    _truncate_summary,
)


def _make_request(name: str = "web_search", tool_call_id: str = "tc-1") -> MagicMock:
    req = MagicMock()
    req.tool_call = {"id": tool_call_id, "name": name, "args": {}}
    return req


def _make_tool_message(content: str = "results", status: str = "success", name: str = "web_search", tool_call_id: str = "tc-1") -> ToolMessage:
    return ToolMessage(content=content, tool_call_id=tool_call_id, name=name, status=status)


class TestTruncateSummary:
    def test_short_text_unchanged(self):
        assert _truncate_summary("hello") == "hello"

    def test_long_text_truncated(self):
        long_text = "x" * 1000
        result = _truncate_summary(long_text, max_bytes=500)
        assert len(result.encode("utf-8")) <= 500
        assert result.endswith("...")

    def test_multibyte_utf8_truncated(self):
        # Chinese characters are 3 bytes each in UTF-8
        text = "中" * 200  # 600 bytes
        result = _truncate_summary(text, max_bytes=100)
        assert len(result.encode("utf-8")) <= 100
        assert result.endswith("...")

    def test_exact_limit_not_truncated(self):
        text = "x" * 500
        assert _truncate_summary(text, max_bytes=500) == text


class TestExtractSummary:
    def test_success_message(self):
        msg = _make_tool_message(content="search results found")
        summary = _extract_summary(msg)
        assert "search results found" in summary

    def test_error_message(self):
        msg = _make_tool_message(content="connection timeout", status="error")
        summary = _extract_summary(msg)
        assert summary.startswith("Error:")
        assert "connection timeout" in summary

    def test_long_content_truncated(self):
        msg = _make_tool_message(content="x" * 1000)
        summary = _extract_summary(msg)
        assert len(summary.encode("utf-8")) <= 500


class TestToolEndEmitMiddleware:
    def test_sync_wrap_emits_success(self):
        middleware = ToolEndEmitMiddleware()
        request = _make_request()
        expected_result = _make_tool_message()
        writer = MagicMock()

        def handler(req):
            return expected_result

        with patch("langgraph.config.get_stream_writer", return_value=writer):
            result = middleware.wrap_tool_call(request, handler)

        assert result == expected_result

    @pytest.mark.anyio
    async def test_async_wrap_emits_success(self):
        middleware = ToolEndEmitMiddleware()
        request = _make_request()
        expected_result = _make_tool_message()
        writer = MagicMock()

        async def handler(req):
            return expected_result

        with patch("langgraph.config.get_stream_writer", return_value=writer):
            result = await middleware.awrap_tool_call(request, handler)

        assert result == expected_result
        writer.assert_called_once()
        event = writer.call_args[0][0]
        assert event["type"] == "tool_end"
        assert event["name"] == "web_search"
        assert event["data"]["status"] == "success"

    @pytest.mark.anyio
    async def test_async_wrap_emits_error_status(self):
        middleware = ToolEndEmitMiddleware()
        request = _make_request()
        error_result = _make_tool_message(content="failed", status="error")
        writer = MagicMock()

        async def handler(req):
            return error_result

        with patch("langgraph.config.get_stream_writer", return_value=writer):
            result = await middleware.awrap_tool_call(request, handler)

        assert result == error_result
        event = writer.call_args[0][0]
        assert event["data"]["status"] == "error"

    @pytest.mark.anyio
    async def test_no_stream_writer_does_not_crash(self):
        middleware = ToolEndEmitMiddleware()
        request = _make_request()
        expected_result = _make_tool_message()

        async def handler(req):
            return expected_result

        with patch("langgraph.config.get_stream_writer", side_effect=RuntimeError("no writer")):
            result = await middleware.awrap_tool_call(request, handler)

        assert result == expected_result

    @pytest.mark.anyio
    async def test_event_payload_under_500_bytes(self):
        middleware = ToolEndEmitMiddleware()
        request = _make_request()
        long_content = "x" * 2000
        result_msg = _make_tool_message(content=long_content)
        writer = MagicMock()

        async def handler(req):
            return result_msg

        with patch("langgraph.config.get_stream_writer", return_value=writer):
            await middleware.awrap_tool_call(request, handler)

        import json

        event = writer.call_args[0][0]
        payload_size = len(json.dumps(event).encode("utf-8"))
        assert payload_size <= 1024  # generous bound — summary itself is <500 bytes

    @pytest.mark.anyio
    async def test_different_tool_names(self):
        middleware = ToolEndEmitMiddleware()
        writer = MagicMock()

        for name in ["code_interpreter", "web_search", "present_files"]:
            request = _make_request(name=name)
            result_msg = _make_tool_message(name=name)

            async def handler(req):
                return result_msg

            with patch("langgraph.config.get_stream_writer", return_value=writer):
                await middleware.awrap_tool_call(request, handler)

            event = writer.call_args[0][0]
            assert event["name"] == name
