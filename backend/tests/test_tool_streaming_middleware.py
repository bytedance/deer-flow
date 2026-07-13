"""Tests for ToolStreamingMiddleware."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call

import pytest
from langchain_core.messages import ToolMessage

from deerflow.agents.middlewares.tool_streaming_middleware import (
    TOOL_OUTPUT_CHUNK_EVENT,
    ToolStreamingMiddleware,
    _build_error_chunk,
    _build_final_chunk,
    _build_start_chunk,
    _extract_content,
)
from deerflow.config.tool_streaming_config import ToolStreamingConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(**overrides) -> ToolStreamingConfig:
    kwargs = {"enabled": True}
    kwargs.update(overrides)
    return ToolStreamingConfig(**kwargs)


def _make_tool_request(tool_name: str = "bash", tool_call_id: str = "tc-bash") -> SimpleNamespace:
    return SimpleNamespace(
        tool_call={"name": tool_name, "id": tool_call_id},
    )


def _make_tool_message(
    content: str = "command output",
    *,
    tool_name: str = "bash",
    tool_call_id: str = "tc-bash",
    status: str = "success",
) -> ToolMessage:
    return ToolMessage(
        content=content,
        tool_call_id=tool_call_id,
        name=tool_name,
        status=status,
    )


def _writer_mock() -> MagicMock:
    return MagicMock()


# ---------------------------------------------------------------------------
# _build_start_chunk
# ---------------------------------------------------------------------------


class TestBuildStartChunk:
    def test_structure(self):
        chunk = _build_start_chunk("tc-1", "bash")
        assert chunk["type"] == TOOL_OUTPUT_CHUNK_EVENT
        assert chunk["tool_call_id"] == "tc-1"
        assert chunk["tool_name"] == "bash"
        assert chunk["chunk"] == ""
        assert chunk["is_partial"] is True
        assert chunk["is_final"] is False

    def test_different_tool_name(self):
        chunk = _build_start_chunk("tc-2", "web_search")
        assert chunk["tool_name"] == "web_search"


# ---------------------------------------------------------------------------
# _build_final_chunk
# ---------------------------------------------------------------------------


class TestBuildFinalChunk:
    def test_structure(self):
        chunk = _build_final_chunk("tc-1", "bash", "hello world")
        assert chunk["type"] == TOOL_OUTPUT_CHUNK_EVENT
        assert chunk["tool_call_id"] == "tc-1"
        assert chunk["tool_name"] == "bash"
        assert chunk["chunk"] == "hello world"
        assert chunk["is_partial"] is False
        assert chunk["is_final"] is True

    def test_empty_content(self):
        chunk = _build_final_chunk("tc-1", "bash", "")
        assert chunk["chunk"] == ""


# ---------------------------------------------------------------------------
# _build_error_chunk
# ---------------------------------------------------------------------------


class TestBuildErrorChunk:
    def test_structure(self):
        chunk = _build_error_chunk("tc-1", "bash", "command not found")
        assert chunk["type"] == TOOL_OUTPUT_CHUNK_EVENT
        assert chunk["tool_call_id"] == "tc-1"
        assert chunk["tool_name"] == "bash"
        assert chunk["chunk"] == "command not found"
        assert chunk["is_partial"] is False
        assert chunk["is_final"] is True
        assert chunk["error"] is True

    def test_long_error_truncated(self):
        """Truncation is the caller's responsibility (done in awrap_tool_call).
        _build_error_chunk passes the string through as-is."""
        long_error = "x" * 600
        chunk = _build_error_chunk("tc-1", "bash", long_error)
        assert len(chunk["chunk"]) == 600


# ---------------------------------------------------------------------------
# _extract_content
# ---------------------------------------------------------------------------


class TestExtractContent:
    def test_string_content(self):
        msg = ToolMessage(content="hello", tool_call_id="tc", name="bash")
        assert _extract_content(msg) == "hello"

    def test_list_content(self):
        msg = ToolMessage(
            content=[{"text": "part1"}, {"text": "part2"}],
            tool_call_id="tc",
            name="bash",
        )
        assert _extract_content(msg) == "part1part2"

    def test_empty_content(self):
        msg = ToolMessage(content="", tool_call_id="tc", name="bash")
        assert _extract_content(msg) == ""

    def test_non_string_content(self):
        msg = ToolMessage(content=42, tool_call_id="tc", name="bash")
        assert _extract_content(msg) == "42"

    def test_non_tool_message(self):
        from langgraph.types import Command

        cmd = Command(goto="some_node")
        assert _extract_content(cmd) == ""


# ---------------------------------------------------------------------------
# ToolStreamingMiddleware — disabled
# ---------------------------------------------------------------------------


class TestDisabledMiddleware:
    @pytest.mark.asyncio
    async def test_passes_through_when_disabled(self):
        mw = ToolStreamingMiddleware(config=_make_config(enabled=False))
        request = _make_tool_request()
        msg = _make_tool_message()
        handler = AsyncMock(return_value=msg)
        result = await mw.awrap_tool_call(request, handler)
        assert result is msg
        handler.assert_awaited_once()

    def test_sync_passes_through_when_disabled(self):
        mw = ToolStreamingMiddleware(config=_make_config(enabled=False))
        request = _make_tool_request()
        msg = _make_tool_message()
        handler = MagicMock(return_value=msg)
        result = mw.wrap_tool_call(request, handler)
        assert result is msg


# ---------------------------------------------------------------------------
# ToolStreamingMiddleware — enabled, no stream writer
# ---------------------------------------------------------------------------


class TestEnabledNoStreamWriter:
    @pytest.mark.asyncio
    async def test_silent_degrade_when_writer_unavailable(self, monkeypatch):
        """When get_stream_writer() returns None, the middleware passes through
        without emitting any chunks — tool execution is unaffected."""
        mw = ToolStreamingMiddleware(config=_make_config(enabled=True))
        request = _make_tool_request()
        msg = _make_tool_message()
        handler = AsyncMock(return_value=msg)

        # Force get_stream_writer to return None
        def _none_writer():
            return None

        monkeypatch.setattr(
            "deerflow.agents.middlewares.tool_streaming_middleware._get_stream_writer",
            _none_writer,
        )

        result = await mw.awrap_tool_call(request, handler)
        assert result is msg


# ---------------------------------------------------------------------------
# ToolStreamingMiddleware — enabled, with stream writer
# ---------------------------------------------------------------------------


class TestEnabledWithStreamWriter:
    @pytest.mark.asyncio
    async def test_emits_start_and_final_chunks(self, monkeypatch):
        writer = _writer_mock()
        monkeypatch.setattr(
            "deerflow.agents.middlewares.tool_streaming_middleware._get_stream_writer",
            lambda: writer,
        )

        mw = ToolStreamingMiddleware(config=_make_config(enabled=True))
        request = _make_tool_request(tool_name="bash", tool_call_id="tc-bash")
        msg = _make_tool_message(content="hello world")
        handler = AsyncMock(return_value=msg)

        result = await mw.awrap_tool_call(request, handler)
        assert result is msg

        # Verify start chunk
        assert writer.call_count == 2
        first_call = writer.call_args_list[0]
        event_name, start_data = first_call[0][0]
        assert event_name == TOOL_OUTPUT_CHUNK_EVENT
        assert start_data["is_partial"] is True
        assert start_data["is_final"] is False
        assert start_data["tool_call_id"] == "tc-bash"
        assert start_data["tool_name"] == "bash"

        # Verify final chunk
        second_call = writer.call_args_list[1]
        event_name, final_data = second_call[0][0]
        assert event_name == TOOL_OUTPUT_CHUNK_EVENT
        assert final_data["is_partial"] is False
        assert final_data["is_final"] is True
        assert final_data["chunk"] == "hello world"

    @pytest.mark.asyncio
    async def test_emits_error_chunk_on_exception(self, monkeypatch):
        writer = _writer_mock()
        monkeypatch.setattr(
            "deerflow.agents.middlewares.tool_streaming_middleware._get_stream_writer",
            lambda: writer,
        )

        mw = ToolStreamingMiddleware(config=_make_config(enabled=True))
        request = _make_tool_request()
        handler = AsyncMock(side_effect=RuntimeError("command failed"))

        with pytest.raises(RuntimeError, match="command failed"):
            await mw.awrap_tool_call(request, handler)

        # Start + error chunks
        assert writer.call_count == 2
        first_call = writer.call_args_list[0]
        event_name, start_data = first_call[0][0]
        assert start_data["is_partial"] is True

        second_call = writer.call_args_list[1]
        event_name, error_data = second_call[0][0]
        assert error_data["is_final"] is True
        assert error_data["error"] is True
        assert "command failed" in error_data["chunk"]

    @pytest.mark.asyncio
    async def test_error_chunk_truncated(self, monkeypatch):
        """Long error messages are truncated to 500 chars before emission."""
        writer = _writer_mock()
        monkeypatch.setattr(
            "deerflow.agents.middlewares.tool_streaming_middleware._get_stream_writer",
            lambda: writer,
        )

        mw = ToolStreamingMiddleware(config=_make_config(enabled=True))
        request = _make_tool_request()
        handler = AsyncMock(side_effect=RuntimeError("x" * 600))

        with pytest.raises(RuntimeError):
            await mw.awrap_tool_call(request, handler)

        # First call: start chunk, second: error chunk
        _, error_data = writer.call_args_list[1][0][0]
        assert len(error_data["chunk"]) == 500
        assert error_data["chunk"].endswith("...")

    @pytest.mark.asyncio
    async def test_writer_exception_is_silent(self, monkeypatch):
        """If the writer itself raises, execution continues normally."""
        writer = MagicMock(side_effect=RuntimeError("stream broken"))
        monkeypatch.setattr(
            "deerflow.agents.middlewares.tool_streaming_middleware._get_stream_writer",
            lambda: writer,
        )

        mw = ToolStreamingMiddleware(config=_make_config(enabled=True))
        request = _make_tool_request()
        msg = _make_tool_message()
        handler = AsyncMock(return_value=msg)

        # Should NOT raise — writer failures are silently swallowed
        result = await mw.awrap_tool_call(request, handler)
        assert result is msg

    @pytest.mark.asyncio
    async def test_different_tools_get_correct_chunks(self, monkeypatch):
        writer = _writer_mock()
        monkeypatch.setattr(
            "deerflow.agents.middlewares.tool_streaming_middleware._get_stream_writer",
            lambda: writer,
        )

        mw = ToolStreamingMiddleware(config=_make_config(enabled=True))

        for tool_name in ["bash", "web_search", "read_file"]:
            writer.reset_mock()
            request = _make_tool_request(
                tool_name=tool_name, tool_call_id=f"tc-{tool_name}"
            )
            msg = _make_tool_message(
                content=f"output from {tool_name}",
                tool_name=tool_name,
                tool_call_id=f"tc-{tool_name}",
            )
            handler = AsyncMock(return_value=msg)

            await mw.awrap_tool_call(request, handler)

            _, final_data = writer.call_args_list[1][0][0]
            assert final_data["tool_name"] == tool_name
            assert final_data["chunk"] == f"output from {tool_name}"


# ---------------------------------------------------------------------------
# Sync path
# ---------------------------------------------------------------------------


class TestSyncPath:
    def test_sync_passes_through(self):
        """Sync wrap_tool_call is always a pass-through — no streaming for sync tools."""
        mw = ToolStreamingMiddleware(config=_make_config(enabled=True))
        request = _make_tool_request()
        msg = _make_tool_message()
        handler = MagicMock(return_value=msg)
        result = mw.wrap_tool_call(request, handler)
        assert result is msg


# ---------------------------------------------------------------------------
# Config-driven toggles
# ---------------------------------------------------------------------------


class TestConfigToggles:
    @pytest.mark.asyncio
    async def test_default_config_disabled(self):
        """Default config has enabled=False."""
        default = ToolStreamingConfig()
        assert default.enabled is False
        assert default.min_chunk_size == 64
        assert default.max_buffer_seconds == 0.1

    @pytest.mark.asyncio
    async def test_from_config_enabled_false(self, monkeypatch):
        writer = _writer_mock()
        monkeypatch.setattr(
            "deerflow.agents.middlewares.tool_streaming_middleware._get_stream_writer",
            lambda: writer,
        )

        mw = ToolStreamingMiddleware(config=_make_config(enabled=False))
        request = _make_tool_request()
        msg = _make_tool_message()
        handler = AsyncMock(return_value=msg)

        await mw.awrap_tool_call(request, handler)
        writer.assert_not_called()

    @pytest.mark.asyncio
    async def test_from_config_enabled_true(self, monkeypatch):
        writer = _writer_mock()
        monkeypatch.setattr(
            "deerflow.agents.middlewares.tool_streaming_middleware._get_stream_writer",
            lambda: writer,
        )

        mw = ToolStreamingMiddleware(config=_make_config(enabled=True))
        request = _make_tool_request()
        msg = _make_tool_message()
        handler = AsyncMock(return_value=msg)

        await mw.awrap_tool_call(request, handler)
        assert writer.call_count == 2  # start + final


# ---------------------------------------------------------------------------
# ToolStreamingConfig field validation
# ---------------------------------------------------------------------------


class TestStreamingConfigValidation:
    def test_min_chunk_size_default(self):
        config = ToolStreamingConfig()
        assert config.min_chunk_size == 64

    def test_max_buffer_seconds_default(self):
        config = ToolStreamingConfig()
        assert config.max_buffer_seconds == 0.1

    def test_min_chunk_size_custom(self):
        config = ToolStreamingConfig(min_chunk_size=128)
        assert config.min_chunk_size == 128

    def test_max_buffer_seconds_custom(self):
        config = ToolStreamingConfig(max_buffer_seconds=0.5)
        assert config.max_buffer_seconds == 0.5
