"""Comprehensive tests for ToolOutputBudgetMiddleware.

Covers: pass-through, disk externalization, fallback truncation, UTF-8
boundaries, Command results, model-request history patching, config
variations, exempt tools, per-tool overrides, edge cases, and both
sync/async code paths.
"""

from __future__ import annotations

import os
import tempfile
from types import SimpleNamespace

import pytest
from langchain.agents.middleware.types import ModelRequest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.types import Command

from deerflow.agents.middlewares.tool_output_budget_middleware import (
    ToolOutputBudgetMiddleware,
    _build_fallback,
    _build_preview,
    _effective_trigger,
    _externalize,
    _message_text,
    _needs_budget,
    _patch_model_messages,
    _sanitize_tool_name,
    _snap_to_line_boundary,
    _tool_message_over_budget,
)
from deerflow.config.app_config import AppConfig
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.config.tool_output_config import ToolOutputConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(tool_name: str = "remote_executor", tool_call_id: str = "tc-1", outputs_path: str | None = None) -> SimpleNamespace:
    thread_data = {"outputs_path": outputs_path} if outputs_path else None
    state = {"thread_data": thread_data} if thread_data else {}
    runtime = SimpleNamespace(state=state)
    return SimpleNamespace(
        tool_call={"name": tool_name, "id": tool_call_id},
        runtime=runtime,
    )


def _tm(content: str = "ok", name: str = "tool", tool_call_id: str = "tc-1") -> ToolMessage:
    return ToolMessage(content=content, name=name, tool_call_id=tool_call_id)


# ===========================================================================
# Unit tests for helper functions
# ===========================================================================


class TestMessageText:
    def test_string_content(self):
        assert _message_text("hello") == "hello"

    def test_none_content(self):
        assert _message_text(None) is None

    def test_list_of_strings(self):
        assert _message_text(["a", "b"]) == "a\nb"

    def test_list_of_text_dicts(self):
        assert _message_text([{"text": "x"}, {"text": "y"}]) == "x\ny"

    def test_list_with_image_returns_none(self):
        assert _message_text([{"type": "image", "data": "..."}]) is None

    def test_empty_list(self):
        assert _message_text([]) is None

    def test_non_string_non_list(self):
        assert _message_text(42) is None


class TestSnapToLineBoundary:
    def test_snaps_to_newline(self):
        text = "line1\nline2\nline3"
        pos = 14  # inside "line3"
        result = _snap_to_line_boundary(text, pos)
        assert text[result - 1] == "\n"

    def test_no_snap_when_no_newline_in_range(self):
        text = "abcdefghij"
        assert _snap_to_line_boundary(text, 8) == 8

    def test_zero_pos(self):
        assert _snap_to_line_boundary("abc", 0) == 0

    def test_pos_beyond_length(self):
        assert _snap_to_line_boundary("abc", 10) == 10


class TestExternalize:
    def test_writes_file_and_returns_virtual_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _externalize(
                "full content here",
                tool_name="bash",
                tool_call_id="tc-1",
                outputs_path=tmpdir,
                storage_subdir=".tool-results",
            )
            assert path is not None
            assert path.startswith("/mnt/user-data/outputs/.tool-results/bash-")
            assert path.endswith(".log")

            # Verify actual file on disk
            storage_dir = os.path.join(tmpdir, ".tool-results")
            files = os.listdir(storage_dir)
            assert len(files) == 1
            with open(os.path.join(storage_dir, files[0]), encoding="utf-8") as f:
                assert f.read() == "full content here"

    def test_returns_none_on_invalid_path(self):
        path = _externalize(
            "data",
            tool_name="test",
            tool_call_id="tc-1",
            outputs_path="/nonexistent/path/that/should/not/exist",
            storage_subdir=".tool-results",
        )
        assert path is None

    def test_txt_extension_for_unknown_tool(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _externalize(
                "data",
                tool_name="unknown_tool",
                tool_call_id="tc-1",
                outputs_path=tmpdir,
                storage_subdir=".tool-results",
            )
            assert path is not None
            assert path.endswith(".txt")


class TestSanitizeToolName:
    def test_strips_path_separators(self):
        assert _sanitize_tool_name("../../etc/passwd") == "passwd"

    def test_strips_backslashes(self):
        result = _sanitize_tool_name("..\\..\\windows\\system32")
        assert ".." not in result
        assert "/" not in result

    def test_normal_name_unchanged(self):
        assert _sanitize_tool_name("bash") == "bash"

    def test_empty_becomes_unknown(self):
        assert _sanitize_tool_name("") == "unknown"

    def test_dots_only_becomes_unknown(self):
        assert _sanitize_tool_name("..") == "unknown"


class TestExternalizePathTraversal:
    def test_traversal_tool_name_is_sanitized(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _externalize(
                "data",
                tool_name="../../etc/passwd",
                tool_call_id="tc-1",
                outputs_path=tmpdir,
                storage_subdir=".tool-results",
            )
            assert path is not None
            assert "passwd-" in path
            assert "../" not in path

    def test_absolute_storage_subdir_rejected(self):
        path = _externalize(
            "data",
            tool_name="tool",
            tool_call_id="tc-1",
            outputs_path="/tmp",
            storage_subdir="/etc/evil",
        )
        assert path is None

    def test_traversal_storage_subdir_rejected(self):
        path = _externalize(
            "data",
            tool_name="tool",
            tool_call_id="tc-1",
            outputs_path="/tmp",
            storage_subdir="../../../etc",
        )
        assert path is None


class TestNeedsBudget:
    def test_small_output_does_not_need_budget(self):
        config = ToolOutputConfig(externalize_min_chars=1000)
        msg = _tm("small", name="tool")
        assert _needs_budget(msg, config) is False

    def test_large_output_needs_budget(self):
        config = ToolOutputConfig(externalize_min_chars=50)
        msg = _tm("x" * 100, name="tool")
        assert _needs_budget(msg, config) is True

    def test_exempt_tool_does_not_need_budget(self):
        config = ToolOutputConfig(externalize_min_chars=10)
        msg = _tm("x" * 100, name="read_file")
        assert _needs_budget(msg, config) is False

    def test_multimodal_does_not_need_budget(self):
        config = ToolOutputConfig(externalize_min_chars=10)
        msg = ToolMessage(content=[{"type": "image", "data": "x" * 100}], name="tool", tool_call_id="tc-1")
        assert _needs_budget(msg, config) is False


class TestBuildPreview:
    def test_contains_head_and_tail_and_reference(self):
        content = "HEAD_" + "x" * 5000 + "_TAIL"
        preview = _build_preview(
            content,
            tool_name="bash",
            virtual_path="/mnt/test/bash-abc.log",
            head_chars=100,
            tail_chars=50,
        )
        assert preview.startswith("HEAD_")
        assert "_TAIL" in preview
        assert "/mnt/test/bash-abc.log" in preview
        assert "read_file" in preview
        assert "start_line and end_line" in preview

    def test_reports_total_chars(self):
        content = "a" * 10000
        preview = _build_preview(
            content,
            tool_name="web_search",
            virtual_path="/mnt/test/file.txt",
            head_chars=200,
            tail_chars=100,
        )
        assert "10000 chars" in preview


class TestBuildFallback:
    def test_short_content_unchanged(self):
        assert _build_fallback("short", tool_name="t", max_chars=100, head_chars=50, tail_chars=50) == "short"

    def test_zero_max_disables(self):
        content = "a" * 1000
        assert _build_fallback(content, tool_name="t", max_chars=0, head_chars=50, tail_chars=50) == content

    def test_truncates_long_content(self):
        content = "H" * 5000 + "M" * 20000 + "T" * 5000
        result = _build_fallback(content, tool_name="bash", max_chars=12000, head_chars=6000, tail_chars=3000)
        assert len(result) < len(content)
        assert "omitted from bash output" in result
        assert "Persistent storage unavailable" in result

    def test_preserves_head_and_tail(self):
        content = "HEADSTART" + "x" * 50000 + "TAILEND"
        result = _build_fallback(content, tool_name="t", max_chars=20000, head_chars=10000, tail_chars=5000)
        assert result.startswith("HEADSTART")
        assert "TAILEND" in result

    def test_result_never_exceeds_max_chars(self):
        """The marker itself has non-zero length; total must still respect max_chars."""
        for max_chars in [200, 500, 1000, 5000, 20000]:
            content = "x" * 50000
            result = _build_fallback(content, tool_name="long_tool_name", max_chars=max_chars, head_chars=max_chars // 2, tail_chars=max_chars // 4)
            assert len(result) <= max_chars, f"max_chars={max_chars}: got {len(result)}"

    def test_very_small_max_chars_does_not_crash(self):
        content = "x" * 1000
        result = _build_fallback(content, tool_name="t", max_chars=50, head_chars=20, tail_chars=10)
        assert len(result) <= 50


# ===========================================================================
# Middleware integration tests — wrap_tool_call
# ===========================================================================


class TestWrapToolCallPassThrough:
    def test_small_output_passes_through(self):
        mw = ToolOutputBudgetMiddleware(config=ToolOutputConfig(externalize_min_chars=1000))
        msg = _tm("small output", name="bash")
        result = mw.wrap_tool_call(_make_request(), lambda _: msg)
        assert result is msg

    def test_disabled_middleware_passes_through(self):
        mw = ToolOutputBudgetMiddleware(config=ToolOutputConfig(enabled=False, externalize_min_chars=10, fallback_max_chars=20))
        msg = _tm("x" * 50000, name="bash")
        result = mw.wrap_tool_call(_make_request(), lambda _: msg)
        assert result is msg


class TestWrapToolCallExternalize:
    def test_oversized_output_externalized_to_disk(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ToolOutputConfig(externalize_min_chars=100, preview_head_chars=50, preview_tail_chars=30)
            mw = ToolOutputBudgetMiddleware(config=config)
            content = "x" * 500
            msg = _tm(content, name="remote_executor")
            req = _make_request(outputs_path=tmpdir)

            result = mw.wrap_tool_call(req, lambda _: msg)

            assert isinstance(result, ToolMessage)
            assert result is not msg
            assert "Full remote_executor output saved to" in result.content
            assert "read_file" in result.content
            assert result.tool_call_id == "tc-1"

            # Verify file was written
            storage_dir = os.path.join(tmpdir, ".tool-results")
            assert os.path.isdir(storage_dir)
            files = os.listdir(storage_dir)
            assert len(files) == 1
            with open(os.path.join(storage_dir, files[0]), encoding="utf-8") as f:
                assert f.read() == content

    def test_preview_contains_head_and_tail(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ToolOutputConfig(externalize_min_chars=50, preview_head_chars=20, preview_tail_chars=10)
            mw = ToolOutputBudgetMiddleware(config=config)
            content = "HEADPART_" + "m" * 200 + "_TAILPART"
            msg = _tm(content, name="web_search")
            req = _make_request(outputs_path=tmpdir)

            result = mw.wrap_tool_call(req, lambda _: msg)

            assert result.content.startswith("HEADPART_")
            assert "_TAILPART" in result.content


class TestWrapToolCallFallback:
    def test_fallback_when_no_outputs_path(self):
        config = ToolOutputConfig(
            externalize_min_chars=50,
            fallback_max_chars=200,
            fallback_head_chars=80,
            fallback_tail_chars=40,
        )
        mw = ToolOutputBudgetMiddleware(config=config)
        content = "x" * 500
        msg = _tm(content, name="mcp_tool")
        req = _make_request(outputs_path=None)

        result = mw.wrap_tool_call(req, lambda _: msg)

        assert isinstance(result, ToolMessage)
        assert result is not msg
        assert "omitted from mcp_tool output" in result.content
        assert "Persistent storage unavailable" in result.content
        assert len(result.content) < len(content)

    def test_fallback_when_disk_write_fails(self):
        config = ToolOutputConfig(
            externalize_min_chars=50,
            fallback_max_chars=200,
            fallback_head_chars=80,
            fallback_tail_chars=40,
        )
        mw = ToolOutputBudgetMiddleware(config=config)
        content = "x" * 500
        msg = _tm(content, name="tool")
        req = _make_request(outputs_path="/nonexistent/impossible/path")

        result = mw.wrap_tool_call(req, lambda _: msg)

        assert isinstance(result, ToolMessage)
        assert "omitted from tool output" in result.content


class TestWrapToolCallExemption:
    def test_read_file_exempt(self):
        config = ToolOutputConfig(externalize_min_chars=10, fallback_max_chars=50)
        mw = ToolOutputBudgetMiddleware(config=config)
        content = "x" * 100
        msg = _tm(content, name="read_file")

        result = mw.wrap_tool_call(_make_request(tool_name="read_file"), lambda _: msg)

        assert result is msg

    def test_read_file_tool_exempt(self):
        config = ToolOutputConfig(externalize_min_chars=10, fallback_max_chars=50)
        mw = ToolOutputBudgetMiddleware(config=config)
        content = "x" * 100
        msg = _tm(content, name="read_file_tool")

        result = mw.wrap_tool_call(_make_request(tool_name="read_file_tool"), lambda _: msg)

        assert result is msg

    def test_custom_exempt_tool(self):
        config = ToolOutputConfig(externalize_min_chars=10, fallback_max_chars=50, exempt_tools=["my_tool"])
        mw = ToolOutputBudgetMiddleware(config=config)
        content = "x" * 100
        msg = _tm(content, name="my_tool")

        result = mw.wrap_tool_call(_make_request(tool_name="my_tool"), lambda _: msg)

        assert result is msg


class TestWrapToolCallPerToolOverride:
    def test_per_tool_threshold(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ToolOutputConfig(
                externalize_min_chars=50000,  # global: high
                tool_overrides={"sensitive_tool": 100},  # override: low
            )
            mw = ToolOutputBudgetMiddleware(config=config)
            content = "x" * 500
            msg = _tm(content, name="sensitive_tool")
            req = _make_request(tool_name="sensitive_tool", outputs_path=tmpdir)

            result = mw.wrap_tool_call(req, lambda _: msg)

            assert result is not msg
            assert "Full sensitive_tool output saved to" in result.content

    def test_per_tool_zero_disables_externalization(self):
        config = ToolOutputConfig(
            externalize_min_chars=50,
            tool_overrides={"bash": 0},
            fallback_max_chars=200,
            fallback_head_chars=80,
            fallback_tail_chars=40,
        )
        mw = ToolOutputBudgetMiddleware(config=config)
        content = "x" * 500
        msg = _tm(content, name="bash")
        # Even with outputs_path, externalization disabled for bash
        req = _make_request(tool_name="bash", outputs_path="/tmp/test")

        result = mw.wrap_tool_call(req, lambda _: msg)

        assert isinstance(result, ToolMessage)
        # Should use fallback instead of externalization
        assert "Persistent storage unavailable" in result.content or "omitted" in result.content


class TestWrapToolCallCommand:
    def test_command_messages_are_patched(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ToolOutputConfig(externalize_min_chars=50, preview_head_chars=20, preview_tail_chars=10)
            mw = ToolOutputBudgetMiddleware(config=config)
            tool_msg = _tm("x" * 200, name="present_files")
            command = Command(update={"messages": [tool_msg], "artifacts": ["/mnt/report.html"]})
            req = _make_request(tool_name="present_files", outputs_path=tmpdir)

            result = mw.wrap_tool_call(req, lambda _: command)

            assert isinstance(result, Command)
            assert result is not command
            assert result.update["artifacts"] == ["/mnt/report.html"]
            new_msg = result.update["messages"][0]
            assert isinstance(new_msg, ToolMessage)
            assert "Full present_files output saved to" in new_msg.content

    def test_command_without_messages_unchanged(self):
        config = ToolOutputConfig(externalize_min_chars=10)
        mw = ToolOutputBudgetMiddleware(config=config)
        command = Command(update={"key": "value"})
        result = mw.wrap_tool_call(_make_request(), lambda _: command)
        assert result is command


class TestWrapToolCallEdgeCases:
    def test_none_content_passes_through(self):
        config = ToolOutputConfig(externalize_min_chars=10, fallback_max_chars=20)
        mw = ToolOutputBudgetMiddleware(config=config)
        msg = ToolMessage(content=None, name="tool", tool_call_id="tc-1")

        result = mw.wrap_tool_call(_make_request(), lambda _: msg)

        assert result is msg

    def test_empty_string_passes_through(self):
        config = ToolOutputConfig(externalize_min_chars=10, fallback_max_chars=20)
        mw = ToolOutputBudgetMiddleware(config=config)
        msg = _tm("", name="tool")

        result = mw.wrap_tool_call(_make_request(), lambda _: msg)

        assert result is msg

    def test_multimodal_content_skipped(self):
        config = ToolOutputConfig(externalize_min_chars=10, fallback_max_chars=20)
        mw = ToolOutputBudgetMiddleware(config=config)
        content = [{"type": "image", "data": "x" * 100}]
        msg = ToolMessage(content=content, name="tool", tool_call_id="tc-1")

        result = mw.wrap_tool_call(_make_request(), lambda _: msg)

        assert result is msg

    def test_exactly_at_threshold_passes_through(self):
        config = ToolOutputConfig(externalize_min_chars=100, fallback_max_chars=100)
        mw = ToolOutputBudgetMiddleware(config=config)
        msg = _tm("x" * 100, name="tool")

        result = mw.wrap_tool_call(_make_request(), lambda _: msg)

        assert result is msg

    def test_one_char_over_threshold_triggers(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ToolOutputConfig(externalize_min_chars=100)
            mw = ToolOutputBudgetMiddleware(config=config)
            msg = _tm("x" * 101, name="tool")
            req = _make_request(outputs_path=tmpdir)

            result = mw.wrap_tool_call(req, lambda _: msg)

            assert result is not msg

    def test_chinese_content_preserved(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ToolOutputConfig(externalize_min_chars=50, preview_head_chars=20, preview_tail_chars=10)
            mw = ToolOutputBudgetMiddleware(config=config)
            content = "你好世界" * 50
            msg = _tm(content, name="tool")
            req = _make_request(outputs_path=tmpdir)

            result = mw.wrap_tool_call(req, lambda _: msg)

            assert isinstance(result, ToolMessage)
            # File should contain the full Chinese content
            storage_dir = os.path.join(tmpdir, ".tool-results")
            files = os.listdir(storage_dir)
            with open(os.path.join(storage_dir, files[0]), encoding="utf-8") as f:
                assert f.read() == content

    def test_no_runtime_state_uses_fallback(self):
        config = ToolOutputConfig(
            externalize_min_chars=50,
            fallback_max_chars=500,
            fallback_head_chars=100,
            fallback_tail_chars=50,
        )
        mw = ToolOutputBudgetMiddleware(config=config)
        content = "x" * 1000
        msg = _tm(content, name="tool")
        req = SimpleNamespace(
            tool_call={"name": "tool", "id": "tc-1"},
            runtime=None,
        )

        result = mw.wrap_tool_call(req, lambda _: msg)

        assert isinstance(result, ToolMessage)
        assert "omitted" in result.content
        assert len(result.content) <= 500


# ===========================================================================
# MCP content_and_artifact format tests
# ===========================================================================


class TestMCPContentAndArtifact:
    """MCP tools return content as list of content blocks, not plain strings."""

    def test_text_content_blocks_are_budgeted(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ToolOutputConfig(externalize_min_chars=50, preview_head_chars=20, preview_tail_chars=10)
            mw = ToolOutputBudgetMiddleware(config=config)
            content = [{"type": "text", "text": "x" * 200}]
            msg = ToolMessage(content=content, name="mcp_tool", tool_call_id="tc-mcp")
            req = _make_request(tool_name="mcp_tool", outputs_path=tmpdir)

            result = mw.wrap_tool_call(req, lambda _: msg)

            assert result is not msg
            assert isinstance(result.content, str)
            assert "Full mcp_tool output saved to" in result.content
            assert result.tool_call_id == "tc-mcp"

    def test_multiple_text_blocks_joined_and_budgeted(self):
        config = ToolOutputConfig(externalize_min_chars=50, fallback_max_chars=500, fallback_head_chars=100, fallback_tail_chars=50)
        mw = ToolOutputBudgetMiddleware(config=config)
        content = [{"type": "text", "text": "a" * 300}, {"type": "text", "text": "b" * 300}]
        msg = ToolMessage(content=content, name="mcp_tool", tool_call_id="tc-mcp2")
        req = _make_request(tool_name="mcp_tool")

        result = mw.wrap_tool_call(req, lambda _: msg)

        assert result is not msg
        assert "omitted" in result.content

    def test_image_content_blocks_are_skipped(self):
        config = ToolOutputConfig(externalize_min_chars=10, fallback_max_chars=20)
        mw = ToolOutputBudgetMiddleware(config=config)
        content = [{"type": "image", "data": "base64data" * 100}]
        msg = ToolMessage(content=content, name="mcp_tool", tool_call_id="tc-img")
        req = _make_request(tool_name="mcp_tool")

        result = mw.wrap_tool_call(req, lambda _: msg)

        assert result is msg

    def test_mixed_text_and_image_blocks_are_skipped(self):
        config = ToolOutputConfig(externalize_min_chars=10)
        mw = ToolOutputBudgetMiddleware(config=config)
        content = [{"type": "text", "text": "x" * 100}, {"type": "image", "data": "base64"}]
        msg = ToolMessage(content=content, name="mcp_tool", tool_call_id="tc-mix")
        req = _make_request(tool_name="mcp_tool")

        result = mw.wrap_tool_call(req, lambda _: msg)

        assert result is msg

    def test_small_text_blocks_pass_through(self):
        config = ToolOutputConfig(externalize_min_chars=1000)
        mw = ToolOutputBudgetMiddleware(config=config)
        content = [{"type": "text", "text": "small result"}]
        msg = ToolMessage(content=content, name="mcp_tool", tool_call_id="tc-sm")
        req = _make_request(tool_name="mcp_tool")

        result = mw.wrap_tool_call(req, lambda _: msg)

        assert result is msg


# ===========================================================================
# Async path tests
# ===========================================================================


class TestAsyncPaths:
    @pytest.mark.anyio
    async def test_async_tool_call_externalized(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ToolOutputConfig(externalize_min_chars=50, preview_head_chars=20, preview_tail_chars=10)
            mw = ToolOutputBudgetMiddleware(config=config)
            content = "x" * 200
            msg = _tm(content, name="async_tool")
            req = _make_request(tool_name="async_tool", outputs_path=tmpdir)

            async def handler(_):
                return msg

            result = await mw.awrap_tool_call(req, handler)

            assert isinstance(result, ToolMessage)
            assert result is not msg
            assert "Full async_tool output saved to" in result.content

    @pytest.mark.anyio
    async def test_async_model_call_patches_history(self):
        config = ToolOutputConfig(fallback_max_chars=500, fallback_head_chars=100, fallback_tail_chars=50)
        mw = ToolOutputBudgetMiddleware(config=config)
        oversized = _tm("h" * 1000, name="tool", tool_call_id="tc-h")
        request = ModelRequest(model=None, messages=[oversized], tools=[], state={})
        captured: dict[str, ModelRequest] = {}

        async def handler(req):
            captured["request"] = req
            return []

        await mw.awrap_model_call(request, handler)

        forwarded = captured["request"]
        assert forwarded is not request
        msg = forwarded.messages[0]
        assert isinstance(msg, ToolMessage)
        assert "omitted" in msg.content


# ===========================================================================
# wrap_model_call — historical message patching
# ===========================================================================


class TestWrapModelCall:
    def test_oversized_historical_messages_truncated(self):
        config = ToolOutputConfig(fallback_max_chars=500, fallback_head_chars=100, fallback_tail_chars=50)
        mw = ToolOutputBudgetMiddleware(config=config)
        oversized = _tm("q" * 1000, name="tool", tool_call_id="tc-q")
        request = ModelRequest(model=None, messages=[oversized], tools=[], state={})
        captured: dict[str, ModelRequest] = {}

        def handler(req):
            captured["request"] = req
            return []

        mw.wrap_model_call(request, handler)

        forwarded = captured["request"]
        assert forwarded is not request
        msg = forwarded.messages[0]
        assert isinstance(msg, ToolMessage)
        assert "omitted" in msg.content
        assert len(msg.content) < len(oversized.content) + 150

    def test_small_historical_messages_unchanged(self):
        config = ToolOutputConfig(fallback_max_chars=1000)
        mw = ToolOutputBudgetMiddleware(config=config)
        small = _tm("small", name="tool")
        request = ModelRequest(model=None, messages=[small], tools=[], state={})
        captured: dict[str, ModelRequest] = {}

        def handler(req):
            captured["request"] = req
            return []

        mw.wrap_model_call(request, handler)

        assert captured["request"] is request

    def test_exempt_tools_in_history_unchanged(self):
        config = ToolOutputConfig(fallback_max_chars=50)
        mw = ToolOutputBudgetMiddleware(config=config)
        read_msg = _tm("x" * 200, name="read_file", tool_call_id="tc-r")
        request = ModelRequest(model=None, messages=[read_msg], tools=[], state={})
        captured: dict[str, ModelRequest] = {}

        def handler(req):
            captured["request"] = req
            return []

        mw.wrap_model_call(request, handler)

        assert captured["request"] is request

    def test_non_tool_messages_preserved(self):
        config = ToolOutputConfig(fallback_max_chars=500, fallback_head_chars=100, fallback_tail_chars=50)
        mw = ToolOutputBudgetMiddleware(config=config)
        human = HumanMessage(content="x" * 200)
        ai = AIMessage(content="y" * 200)
        oversized_tool = _tm("z" * 1000, name="tool")
        request = ModelRequest(model=None, messages=[human, ai, oversized_tool], tools=[], state={})
        captured: dict[str, ModelRequest] = {}

        def handler(req):
            captured["request"] = req
            return []

        mw.wrap_model_call(request, handler)

        msgs = captured["request"].messages
        assert msgs[0] is human
        assert msgs[1] is ai
        assert isinstance(msgs[2], ToolMessage)
        assert "omitted" in msgs[2].content


# ===========================================================================
# Config integration
# ===========================================================================


class TestFromAppConfig:
    def test_from_app_config_with_tool_output(self):
        config = AppConfig(
            sandbox=SandboxConfig(use="test"),
            tool_output={"externalize_min_chars": 5000, "preview_head_chars": 500},
        )
        mw = ToolOutputBudgetMiddleware.from_app_config(config)
        assert mw._config.externalize_min_chars == 5000
        assert mw._config.preview_head_chars == 500

    def test_from_app_config_defaults(self):
        config = AppConfig(sandbox=SandboxConfig(use="test"))
        mw = ToolOutputBudgetMiddleware.from_app_config(config)
        assert mw._config.externalize_min_chars == 12000


class TestPatchModelMessages:
    def test_returns_none_when_no_changes(self):
        config = ToolOutputConfig(fallback_max_chars=1000)
        messages = [_tm("short", name="tool")]
        assert _patch_model_messages(messages, config) is None

    def test_patches_oversized_messages(self):
        config = ToolOutputConfig(fallback_max_chars=500, fallback_head_chars=100, fallback_tail_chars=50)
        messages = [_tm("x" * 1000, name="tool")]
        result = _patch_model_messages(messages, config)
        assert result is not None
        assert len(result) == 1
        assert "omitted" in result[0].content


# ===========================================================================
# Pre-scan helpers (_effective_trigger / _tool_message_over_budget / _needs_budget)
# These guard the fast-path optimization — a false negative here is a real bug
# (budgeting silently skipped), so per-tool overrides must be honored.
# ===========================================================================


class TestPreScanHelpers:
    def test_effective_trigger_uses_global_externalize(self):
        config = ToolOutputConfig(externalize_min_chars=12000, fallback_max_chars=30000)
        # smallest of the two thresholds wins
        assert _effective_trigger("any_tool", config) == 12000

    def test_effective_trigger_respects_per_tool_override(self):
        config = ToolOutputConfig(externalize_min_chars=50000, fallback_max_chars=0, tool_overrides={"sensitive": 100})
        assert _effective_trigger("sensitive", config) == 100
        # other tools fall back to the (high) global
        assert _effective_trigger("other", config) == 50000

    def test_effective_trigger_per_tool_zero_falls_to_fallback(self):
        config = ToolOutputConfig(externalize_min_chars=50, tool_overrides={"bash": 0}, fallback_max_chars=200)
        # externalize disabled for bash → only fallback can trigger
        assert _effective_trigger("bash", config) == 200

    def test_effective_trigger_returns_negative_when_fully_disabled(self):
        config = ToolOutputConfig(externalize_min_chars=0, fallback_max_chars=0)
        assert _effective_trigger("any", config) == -1

    def test_pre_scan_does_not_short_circuit_per_tool_override(self):
        """Regression: pre-scan must honor per-tool overrides, not just global threshold."""
        config = ToolOutputConfig(externalize_min_chars=50000, fallback_max_chars=0, tool_overrides={"sensitive": 100})
        msg = _tm("x" * 500, name="sensitive")
        # 500 < global 50000 but > per-tool 100 → must still be flagged
        assert _tool_message_over_budget(msg, config) is True
        assert _needs_budget(msg, config) is True

    def test_exempt_tool_never_over_budget(self):
        config = ToolOutputConfig(externalize_min_chars=10, fallback_max_chars=20, exempt_tools=["read_file"])
        msg = _tm("x" * 1000, name="read_file")
        assert _tool_message_over_budget(msg, config) is False

    def test_model_call_pre_scan_skips_when_nothing_oversized(self):
        """_patch_model_messages returns None (no list rebuild) when all messages are small."""
        config = ToolOutputConfig(externalize_min_chars=12000, fallback_max_chars=30000)
        messages = [_tm("small", name="tool"), HumanMessage(content="hi"), _tm("also small", name="bash")]
        assert _patch_model_messages(messages, config) is None


# ===========================================================================
# Middleware ordering in the chain
# ===========================================================================


class TestMiddlewareChainIntegration:
    def test_budget_middleware_is_first_in_chain(self):
        from deerflow.agents.middlewares.tool_error_handling_middleware import build_subagent_runtime_middlewares

        app_config = AppConfig(sandbox=SandboxConfig(use="test"))
        middlewares = build_subagent_runtime_middlewares(app_config=app_config, lazy_init=False)

        assert isinstance(middlewares[0], ToolOutputBudgetMiddleware)

    def test_budget_middleware_in_lead_chain(self):
        from deerflow.agents.middlewares.tool_error_handling_middleware import build_lead_runtime_middlewares

        app_config = AppConfig(sandbox=SandboxConfig(use="test"))
        middlewares = build_lead_runtime_middlewares(app_config=app_config, lazy_init=False)

        assert isinstance(middlewares[0], ToolOutputBudgetMiddleware)


# ===========================================================================
# Config version bump
# ===========================================================================


class TestConfigVersion:
    def test_config_version_bumped(self):
        import yaml

        example_path = os.path.join(os.path.dirname(__file__), "..", "..", "config.example.yaml")
        if os.path.exists(example_path):
            with open(example_path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            assert data.get("config_version", 0) >= 11

    def test_config_example_has_tool_output_section(self):
        import yaml

        example_path = os.path.join(os.path.dirname(__file__), "..", "..", "config.example.yaml")
        if os.path.exists(example_path):
            with open(example_path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            assert "tool_output" in data
            tool_output = data["tool_output"]
            assert tool_output["enabled"] is True
            assert tool_output["externalize_min_chars"] == 12000
            assert "read_file" in tool_output["exempt_tools"]
