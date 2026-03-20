"""Tests for the conversation history management router (threads API)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.gateway.routers.threads import (
    ExportResponse,
    ThreadDetail,
    ThreadsListResponse,
    ThreadSummary,
    _extract_text,
    _summarise_messages,
    _to_summary,
    _truncate,
)


# ---------------------------------------------------------------------------
# Unit tests for helper functions
# ---------------------------------------------------------------------------


class TestTruncate:
    def test_short_text_unchanged(self):
        assert _truncate("hello") == "hello"

    def test_long_text_truncated(self):
        text = "a" * 200
        result = _truncate(text, max_len=50)
        assert len(result) == 50
        assert result.endswith("…")

    def test_strips_whitespace(self):
        assert _truncate("  hello  \n world  ") == "hello    world"


class TestExtractText:
    def test_string_content(self):
        assert _extract_text("hello") == "hello"

    def test_text_blocks(self):
        content = [
            {"type": "text", "text": "line 1"},
            {"type": "text", "text": "line 2"},
        ]
        assert _extract_text(content) == "line 1\nline 2"

    def test_tool_use_block(self):
        content = [
            {"type": "tool_use", "name": "search", "id": "t1", "input": {}},
        ]
        assert "[Tool: search]" in _extract_text(content)

    def test_tool_result_block(self):
        content = [
            {"type": "tool_result", "content": "some result", "tool_use_id": "t1"},
        ]
        # tool_result without "text" key — should return empty
        result = _extract_text(content)
        assert isinstance(result, str)

    def test_mixed_blocks(self):
        content = [
            {"type": "thinking", "text": "thinking..."},
            {"type": "text", "text": "actual response"},
        ]
        assert "actual response" in _extract_text(content)

    def test_plain_string_in_list(self):
        content = ["plain string"]
        assert _extract_text(content) == "plain string"

    def test_non_string_non_list(self):
        assert _extract_text(42) == "42"
        assert _extract_text(None) == "None"


class TestSummariseMessages:
    def test_empty_messages(self):
        count, preview = _summarise_messages([])
        assert count == 0
        assert preview is None

    def test_with_human_messages(self):
        messages = [
            {"type": "ai", "content": "Hi"},
            {"type": "human", "content": "Tell me about Python"},
            {"type": "ai", "content": "Python is great"},
        ]
        count, preview = _summarise_messages(messages)
        assert count == 3
        assert preview == "Tell me about Python"

    def test_no_human_messages(self):
        messages = [{"type": "ai", "content": "Hello"}]
        count, preview = _summarise_messages(messages)
        assert count == 1
        assert preview is None

    def test_preview_truncation(self):
        long_text = "x" * 200
        messages = [{"type": "human", "content": long_text}]
        _, preview = _summarise_messages(messages)
        assert preview is not None
        assert len(preview) <= 120


class TestToSummary:
    def test_basic_thread(self):
        thread_data = {
            "thread_id": "abc-123",
            "status": "idle",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-02T00:00:00Z",
            "metadata": {"title": "Test"},
            "values": {
                "messages": [
                    {"type": "human", "content": "Hello"},
                    {"type": "ai", "content": "Hi there!"},
                ],
            },
        }
        summary = _to_summary(thread_data)
        assert summary.thread_id == "abc-123"
        assert summary.status == "idle"
        assert summary.message_count == 2
        assert summary.last_message_preview == "Hello"
        assert summary.metadata == {"title": "Test"}

    def test_thread_without_values(self):
        thread_data = {"thread_id": "xyz", "status": "busy"}
        summary = _to_summary(thread_data)
        assert summary.thread_id == "xyz"
        assert summary.message_count == 0
        assert summary.last_message_preview is None


# ---------------------------------------------------------------------------
# API endpoint tests (mocked LangGraph SDK)
# ---------------------------------------------------------------------------


class TestListThreadsEndpoint:
    def test_returns_paginated_threads(self):
        """list_threads should return a paginated list of thread summaries."""
        fake_threads = [
            {
                "thread_id": "t1",
                "status": "idle",
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-02T00:00:00Z",
                "metadata": {},
                "values": {"messages": [{"type": "human", "content": "Hi"}]},
            },
            {
                "thread_id": "t2",
                "status": "idle",
                "created_at": "2026-01-03T00:00:00Z",
                "updated_at": "2026-01-04T00:00:00Z",
                "metadata": {"title": "Research"},
                "values": {"messages": []},
            },
        ]

        mock_client = MagicMock()
        mock_client.threads = MagicMock()
        mock_client.threads.search = AsyncMock(return_value=fake_threads)
        mock_client.threads.count = AsyncMock(return_value=2)

        with patch("app.gateway.routers.threads.get_client", return_value=mock_client):
            from app.gateway.routers.threads import list_threads

            result = asyncio.run(list_threads(limit=20, offset=0, status=None))

        assert isinstance(result, ThreadsListResponse)
        assert len(result.threads) == 2
        assert result.total == 2
        assert result.threads[0].thread_id == "t1"
        assert result.threads[1].thread_id == "t2"
        assert result.threads[1].metadata == {"title": "Research"}


class TestGetThreadEndpoint:
    def test_returns_full_thread(self):
        thread_data = {
            "thread_id": "t1",
            "status": "idle",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-02T00:00:00Z",
            "metadata": {"title": "Test"},
            "values": {
                "messages": [
                    {"type": "human", "content": "Hello"},
                    {"type": "ai", "content": "Hi!"},
                ],
            },
        }

        mock_client = MagicMock()
        mock_client.threads = MagicMock()
        mock_client.threads.get = AsyncMock(return_value=thread_data)

        with patch("app.gateway.routers.threads.get_client", return_value=mock_client):
            from app.gateway.routers.threads import get_thread

            result = asyncio.run(get_thread("t1"))

        assert isinstance(result, ThreadDetail)
        assert result.thread_id == "t1"
        assert result.message_count == 2
        assert len(result.messages) == 2

    def test_returns_404_for_missing_thread(self):
        mock_client = MagicMock()
        mock_client.threads = MagicMock()
        mock_client.threads.get = AsyncMock(return_value={})

        with patch("app.gateway.routers.threads.get_client", return_value=mock_client):
            from app.gateway.routers.threads import get_thread
            from fastapi import HTTPException

            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(get_thread("nonexistent"))
            assert exc_info.value.status_code == 404


class TestDeleteThreadEndpoint:
    def test_calls_delete(self):
        mock_client = MagicMock()
        mock_client.threads = MagicMock()
        mock_client.threads.delete = AsyncMock()

        with patch("app.gateway.routers.threads.get_client", return_value=mock_client):
            from app.gateway.routers.threads import delete_thread

            asyncio.run(delete_thread("t1"))

        mock_client.threads.delete.assert_called_once_with("t1")


class TestExportThreadEndpoint:
    def test_exports_as_markdown(self):
        thread_data = {
            "thread_id": "t1",
            "status": "idle",
            "metadata": {"title": "Research Q"},
            "values": {
                "messages": [
                    {"type": "human", "content": "What is Python?"},
                    {
                        "type": "ai",
                        "content": "Python is a programming language.",
                        "tool_calls": [{"name": "search", "args": {"query": "Python"}}],
                    },
                    {
                        "type": "tool",
                        "name": "search",
                        "content": "Python is...",
                        "tool_call_id": "tc1",
                    },
                ],
            },
        }

        mock_client = MagicMock()
        mock_client.threads = MagicMock()
        mock_client.threads.get = AsyncMock(return_value=thread_data)

        with patch("app.gateway.routers.threads.get_client", return_value=mock_client):
            from app.gateway.routers.threads import export_thread

            result = asyncio.run(export_thread("t1"))

        assert isinstance(result, ExportResponse)
        assert result.title == "Research Q"
        assert "## User" in result.markdown
        assert "What is Python?" in result.markdown
        assert "## Assistant" in result.markdown
        assert "Python is a programming language." in result.markdown
        assert "Tool call" in result.markdown
        assert "search" in result.markdown
        assert "### Tool" in result.markdown
