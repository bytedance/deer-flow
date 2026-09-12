"""Tests for the read-before-write gate (issue #3857, output layer)."""

import hashlib
import posixpath
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _make_request(name, args, messages=(), tool_call_id="call-1"):
    runtime = MagicMock()
    runtime.context = {"thread_id": "t-test"}
    return ToolCallRequest(
        tool_call={"name": name, "args": args, "id": tool_call_id},
        tool=None,
        state={"messages": list(messages)},
        runtime=runtime,
    )


def _read_marked_message(path, content, tool_call_id="r1"):
    msg = ToolMessage(content=content[:20], tool_call_id=tool_call_id, name="read_file")
    msg.additional_kwargs["deerflow_read_mark"] = {"path": path, "hash": _sha(content)}
    return msg


def _middleware(files: dict[str, str]):
    from deerflow.agents.middlewares.read_before_write_middleware import ReadBeforeWriteMiddleware

    def reader(_runtime, path):
        normalized = posixpath.normpath(path)
        if normalized not in files:
            raise FileNotFoundError(path)
        value = files[normalized]
        if isinstance(value, Exception):
            raise value
        return value

    return ReadBeforeWriteMiddleware(content_reader=reader)


class TestReadCurrentFileContent:
    def test_reads_via_sandbox_with_resolution(self):
        from deerflow.sandbox import tools as sandbox_tools

        sandbox = MagicMock()
        sandbox.read_file.return_value = "hello"
        runtime = MagicMock()
        with (
            patch.object(sandbox_tools, "ensure_sandbox_initialized", return_value=sandbox),
            patch.object(sandbox_tools, "ensure_thread_directories_exist"),
            patch.object(sandbox_tools, "is_local_sandbox", return_value=False),
        ):
            assert sandbox_tools.read_current_file_content(runtime, "/mnt/user-data/outputs/report.md") == "hello"
        sandbox.read_file.assert_called_once_with("/mnt/user-data/outputs/report.md")

    def test_propagates_file_not_found(self):
        from deerflow.sandbox import tools as sandbox_tools

        sandbox = MagicMock()
        sandbox.read_file.side_effect = FileNotFoundError()
        with (
            patch.object(sandbox_tools, "ensure_sandbox_initialized", return_value=sandbox),
            patch.object(sandbox_tools, "ensure_thread_directories_exist"),
            patch.object(sandbox_tools, "is_local_sandbox", return_value=False),
        ):
            with pytest.raises(FileNotFoundError):
                sandbox_tools.read_current_file_content(MagicMock(), "/mnt/user-data/outputs/missing.md")


class TestReadMarkStamping:
    def test_read_file_success_stamps_mark(self):
        mw = _middleware({"/mnt/user-data/outputs/report.md": "v1"})
        request = _make_request("read_file", {"description": "d", "path": "/mnt/user-data/outputs/report.md"})
        handler = MagicMock(return_value=ToolMessage(content="v1", tool_call_id="call-1", name="read_file"))
        result = mw.wrap_tool_call(request, handler)
        mark = result.additional_kwargs["deerflow_read_mark"]
        assert mark == {"path": "/mnt/user-data/outputs/report.md", "hash": _sha("v1")}

    def test_ranged_read_stamps_full_file_hash(self):
        mw = _middleware({"/mnt/user-data/outputs/report.md": "line1\nline2\nline3"})
        request = _make_request(
            "read_file",
            {"description": "d", "path": "/mnt/user-data/outputs/report.md", "start_line": 3, "end_line": 3},
        )
        handler = MagicMock(return_value=ToolMessage(content="line3", tool_call_id="call-1", name="read_file"))
        result = mw.wrap_tool_call(request, handler)
        assert result.additional_kwargs["deerflow_read_mark"]["hash"] == _sha("line1\nline2\nline3")

    def test_error_tool_message_gets_no_mark(self):
        mw = _middleware({"/mnt/user-data/outputs/report.md": "v1"})
        request = _make_request("read_file", {"description": "d", "path": "/mnt/user-data/outputs/report.md"})
        handler = MagicMock(return_value=ToolMessage(content="boom", tool_call_id="call-1", name="read_file", status="error"))
        result = mw.wrap_tool_call(request, handler)
        assert "deerflow_read_mark" not in result.additional_kwargs

    def test_reader_failure_means_no_mark(self):
        mw = _middleware({"/mnt/user-data/outputs/report.md": RuntimeError("sandbox down")})
        request = _make_request("read_file", {"description": "d", "path": "/mnt/user-data/outputs/report.md"})
        handler = MagicMock(return_value=ToolMessage(content="v1", tool_call_id="call-1", name="read_file"))
        result = mw.wrap_tool_call(request, handler)
        assert "deerflow_read_mark" not in result.additional_kwargs

    def test_non_file_tools_untouched(self):
        mw = _middleware({})
        request = _make_request("bash", {"description": "d", "command": "ls"})
        sentinel = ToolMessage(content="ok", tool_call_id="call-1", name="bash")
        handler = MagicMock(return_value=sentinel)
        assert mw.wrap_tool_call(request, handler) is sentinel


class TestWriteGate:
    PATH = "/mnt/user-data/outputs/report.md"

    def test_new_file_write_allowed(self):
        mw = _middleware({})  # file does not exist
        request = _make_request("write_file", {"description": "d", "path": self.PATH, "content": "v1"})
        handler = MagicMock(return_value=ToolMessage(content="OK", tool_call_id="call-1", name="write_file"))
        result = mw.wrap_tool_call(request, handler)
        handler.assert_called_once()
        assert result.status != "error"

    def test_overwrite_existing_without_read_blocked(self):
        mw = _middleware({self.PATH: "v1"})
        request = _make_request("write_file", {"description": "d", "path": self.PATH, "content": "v2"})
        handler = MagicMock()
        result = mw.wrap_tool_call(request, handler)
        handler.assert_not_called()
        assert isinstance(result, ToolMessage)
        assert result.status == "error"
        assert result.tool_call_id == "call-1"
        assert "read" in result.content.lower()

    def test_append_without_read_blocked(self):
        mw = _middleware({self.PATH: "v1"})
        request = _make_request("write_file", {"description": "d", "path": self.PATH, "content": "more", "append": True})
        handler = MagicMock()
        result = mw.wrap_tool_call(request, handler)
        handler.assert_not_called()
        assert result.status == "error"

    def test_str_replace_without_read_blocked(self):
        mw = _middleware({self.PATH: "v1"})
        request = _make_request("str_replace", {"description": "d", "path": self.PATH, "old_str": "v1", "new_str": "v2"})
        handler = MagicMock()
        result = mw.wrap_tool_call(request, handler)
        handler.assert_not_called()
        assert result.status == "error"

    def test_str_replace_missing_file_passes_through(self):
        mw = _middleware({})
        request = _make_request("str_replace", {"description": "d", "path": self.PATH, "old_str": "a", "new_str": "b"})
        native_error = ToolMessage(content="Error: File not found", tool_call_id="call-1", name="str_replace", status="error")
        handler = MagicMock(return_value=native_error)
        assert mw.wrap_tool_call(request, handler) is native_error

    def test_fresh_mark_allows_write(self):
        mw = _middleware({self.PATH: "v1"})
        messages = [HumanMessage("hi"), AIMessage(""), _read_marked_message(self.PATH, "v1")]
        request = _make_request("write_file", {"description": "d", "path": self.PATH, "content": "v2"}, messages)
        handler = MagicMock(return_value=ToolMessage(content="OK", tool_call_id="call-1", name="write_file"))
        result = mw.wrap_tool_call(request, handler)
        handler.assert_called_once()
        assert result.status != "error"

    def test_stale_mark_after_modification_blocked(self):
        mw = _middleware({self.PATH: "v2"})  # file changed since the read of v1
        messages = [_read_marked_message(self.PATH, "v1")]
        request = _make_request("write_file", {"description": "d", "path": self.PATH, "content": "v3", "append": True}, messages)
        handler = MagicMock()
        result = mw.wrap_tool_call(request, handler)
        handler.assert_not_called()
        assert result.status == "error"

    def test_newest_mark_wins(self):
        mw = _middleware({self.PATH: "v2"})
        messages = [_read_marked_message(self.PATH, "v1", "r1"), _read_marked_message(self.PATH, "v2", "r2")]
        request = _make_request("write_file", {"description": "d", "path": self.PATH, "content": "v3"}, messages)
        handler = MagicMock(return_value=ToolMessage(content="OK", tool_call_id="call-1", name="write_file"))
        result = mw.wrap_tool_call(request, handler)
        handler.assert_called_once()
        assert result.status != "error"

    def test_mark_removed_by_summarization_blocks(self):
        mw = _middleware({self.PATH: "v1"})
        messages = [HumanMessage("Here is a summary of the conversation to date: ...", name="summary")]
        request = _make_request("write_file", {"description": "d", "path": self.PATH, "content": "v2"}, messages)
        handler = MagicMock()
        result = mw.wrap_tool_call(request, handler)
        handler.assert_not_called()
        assert result.status == "error"

    def test_gate_read_failure_fails_open(self):
        mw = _middleware({self.PATH: RuntimeError("sandbox hiccup")})
        request = _make_request("write_file", {"description": "d", "path": self.PATH, "content": "v2"})
        handler = MagicMock(return_value=ToolMessage(content="OK", tool_call_id="call-1", name="write_file"))
        result = mw.wrap_tool_call(request, handler)
        handler.assert_called_once()
        assert result.status != "error"

    def test_normalized_path_matching(self):
        mw = _middleware({self.PATH: "v1"})
        messages = [_read_marked_message(self.PATH, "v1")]
        request = _make_request("write_file", {"description": "d", "path": "/mnt/user-data/outputs/../outputs/report.md", "content": "v2"}, messages)
        handler = MagicMock(return_value=ToolMessage(content="OK", tool_call_id="call-1", name="write_file"))
        result = mw.wrap_tool_call(request, handler)
        handler.assert_called_once()
        assert result.status != "error"

    def test_blocked_write_has_deerflow_tool_meta(self):
        from deerflow.agents.middlewares.tool_result_meta import TOOL_META_KEY

        mw = _middleware({self.PATH: "v1"})
        request = _make_request("write_file", {"description": "d", "path": self.PATH, "content": "v2"})
        result = mw.wrap_tool_call(request, MagicMock())
        meta = (result.additional_kwargs or {}).get(TOOL_META_KEY)
        assert meta is not None, "blocked write must carry deerflow_tool_meta"
        assert meta["recoverable_by_model"] is True


class TestAsyncPaths:
    PATH = "/mnt/user-data/outputs/report.md"

    def test_async_block(self):
        import asyncio

        mw = _middleware({self.PATH: "v1"})
        request = _make_request("write_file", {"description": "d", "path": self.PATH, "content": "v2"})

        async def handler(_request):
            raise AssertionError("handler must not run when blocked")

        result = asyncio.run(mw.awrap_tool_call(request, handler))
        assert result.status == "error"

    def test_async_blocked_write_has_deerflow_tool_meta(self):
        import asyncio

        from deerflow.agents.middlewares.tool_result_meta import TOOL_META_KEY

        mw = _middleware({self.PATH: "v1"})
        request = _make_request("write_file", {"description": "d", "path": self.PATH, "content": "v2"})

        async def handler(_request):
            raise AssertionError("handler must not run when blocked")

        result = asyncio.run(mw.awrap_tool_call(request, handler))
        meta = (result.additional_kwargs or {}).get(TOOL_META_KEY)
        assert meta is not None, "async blocked write must carry deerflow_tool_meta"
        assert meta["recoverable_by_model"] is True

    def test_async_read_stamps_mark(self):
        import asyncio

        mw = _middleware({self.PATH: "v1"})
        request = _make_request("read_file", {"description": "d", "path": self.PATH})

        async def handler(_request):
            return ToolMessage(content="v1", tool_call_id="call-1", name="read_file")

        result = asyncio.run(mw.awrap_tool_call(request, handler))
        assert result.additional_kwargs["deerflow_read_mark"]["hash"] == _sha("v1")

    def test_async_allowed_write_calls_handler(self):
        import asyncio

        mw = _middleware({self.PATH: "v1"})
        messages = [_read_marked_message(self.PATH, "v1")]
        request = _make_request("write_file", {"description": "d", "path": self.PATH, "content": "v2"}, messages)

        async def handler(_request):
            return ToolMessage(content="OK", tool_call_id="call-1", name="write_file")

        result = asyncio.run(mw.awrap_tool_call(request, handler))
        assert result.status != "error"


def _wiring_app_config(**overrides):
    from deerflow.config.app_config import AppConfig
    from deerflow.config.sandbox_config import SandboxConfig

    return AppConfig(sandbox=SandboxConfig(use="test"), **overrides)


class TestChainWiring:
    def test_enabled_by_default_in_runtime_chain(self):
        from deerflow.agents.middlewares.read_before_write_middleware import ReadBeforeWriteMiddleware
        from deerflow.agents.middlewares.sandbox_audit_middleware import SandboxAuditMiddleware
        from deerflow.agents.middlewares.tool_error_handling_middleware import ToolErrorHandlingMiddleware, build_lead_runtime_middlewares

        middlewares = build_lead_runtime_middlewares(app_config=_wiring_app_config())
        types = [type(m) for m in middlewares]
        assert ReadBeforeWriteMiddleware in types
        assert types.index(SandboxAuditMiddleware) < types.index(ReadBeforeWriteMiddleware) < types.index(ToolErrorHandlingMiddleware)

    def test_disabled_removes_middleware(self):
        from deerflow.agents.middlewares.read_before_write_middleware import ReadBeforeWriteMiddleware
        from deerflow.agents.middlewares.tool_error_handling_middleware import build_lead_runtime_middlewares
        from deerflow.config.read_before_write_config import ReadBeforeWriteConfig

        app_config = _wiring_app_config(read_before_write=ReadBeforeWriteConfig(enabled=False))
        middlewares = build_lead_runtime_middlewares(app_config=app_config)
        assert ReadBeforeWriteMiddleware not in [type(m) for m in middlewares]

    def test_subagents_get_the_gate_too(self):
        from deerflow.agents.middlewares.read_before_write_middleware import ReadBeforeWriteMiddleware
        from deerflow.agents.middlewares.tool_error_handling_middleware import build_subagent_runtime_middlewares

        middlewares = build_subagent_runtime_middlewares(app_config=_wiring_app_config())
        assert ReadBeforeWriteMiddleware in [type(m) for m in middlewares]


class TestErrorStringSandboxes:
    """AIO/E2B sandboxes report read failures as "Error: ..." strings, not exceptions."""

    PATH = "/mnt/user-data/outputs/report.md"

    def _error_string_middleware(self, files):
        from deerflow.agents.middlewares.read_before_write_middleware import ReadBeforeWriteMiddleware

        def reader(_runtime, path):
            normalized = posixpath.normpath(path)
            if normalized not in files:
                return f"Error: can't read file {path}: file not found"
            return files[normalized]

        return ReadBeforeWriteMiddleware(content_reader=reader)

    def test_new_file_creation_not_blocked(self):
        mw = self._error_string_middleware({})
        request = _make_request("write_file", {"description": "d", "path": self.PATH, "content": "v1"})
        handler = MagicMock(return_value=ToolMessage(content="OK", tool_call_id="call-1", name="write_file"))
        result = mw.wrap_tool_call(request, handler)
        handler.assert_called_once()
        assert result.status != "error"

    def test_no_mark_when_reread_returns_error_string(self):
        mw = self._error_string_middleware({})
        request = _make_request("read_file", {"description": "d", "path": self.PATH})
        handler = MagicMock(return_value=ToolMessage(content="v1", tool_call_id="call-1", name="read_file"))
        result = mw.wrap_tool_call(request, handler)
        assert "deerflow_read_mark" not in result.additional_kwargs

    def test_existing_file_still_gated(self):
        mw = self._error_string_middleware({self.PATH: "v1"})
        request = _make_request("write_file", {"description": "d", "path": self.PATH, "content": "v2"})
        handler = MagicMock()
        result = mw.wrap_tool_call(request, handler)
        handler.assert_not_called()
        assert result.status == "error"

    def test_existing_file_read_still_marked_and_write_allowed(self):
        mw = self._error_string_middleware({self.PATH: "v1"})
        read_request = _make_request("read_file", {"description": "d", "path": self.PATH})
        read_handler = MagicMock(return_value=ToolMessage(content="v1", tool_call_id="r1", name="read_file"))
        read_result = mw.wrap_tool_call(read_request, read_handler)
        assert read_result.additional_kwargs["deerflow_read_mark"]["hash"] == _sha("v1")

        write_request = _make_request("write_file", {"description": "d", "path": self.PATH, "content": "v2"}, [read_result])
        write_handler = MagicMock(return_value=ToolMessage(content="OK", tool_call_id="call-1", name="write_file"))
        result = mw.wrap_tool_call(write_request, write_handler)
        write_handler.assert_called_once()
        assert result.status != "error"


class TestSamePathSerialization:
    """LangGraph runs one AIMessage's tool calls concurrently; the gate must not
    let two same-turn writes pass on one stale mark (issue #3912 review)."""

    PATH = "/mnt/user-data/outputs/report.md"

    def test_parallel_appends_exactly_one_lands(self):
        import asyncio

        files = {self.PATH: "v1"}
        mw = _middleware(files)
        messages = [_read_marked_message(self.PATH, "v1")]

        def make_handler(suffix):
            async def handler(_request):
                await asyncio.sleep(0.02)
                files[self.PATH] = files[self.PATH] + suffix
                return ToolMessage(content="OK", tool_call_id="call-1", name="write_file")

            return handler

        async def run():
            return await asyncio.gather(
                mw.awrap_tool_call(
                    _make_request("write_file", {"description": "d", "path": self.PATH, "content": "A", "append": True}, messages),
                    make_handler("A"),
                ),
                mw.awrap_tool_call(
                    _make_request("write_file", {"description": "d", "path": self.PATH, "content": "B", "append": True}, messages),
                    make_handler("B"),
                ),
            )

        results = asyncio.run(run())
        assert sorted(r.status for r in results) == ["error", "success"]
        assert files[self.PATH] in ("v1A", "v1B")

    def test_read_mark_matches_content_shown_to_model(self):
        import asyncio

        files = {self.PATH: "v1"}
        mw = _middleware(files)
        write_messages = [_read_marked_message(self.PATH, "v1")]

        async def read_handler(_request):
            snapshot = files[self.PATH]
            await asyncio.sleep(0.03)
            return ToolMessage(content=snapshot, tool_call_id="r-call", name="read_file")

        async def write_handler(_request):
            files[self.PATH] = "v2"
            return ToolMessage(content="OK", tool_call_id="w-call", name="write_file")

        async def run():
            read_task = asyncio.create_task(mw.awrap_tool_call(_make_request("read_file", {"description": "d", "path": self.PATH}), read_handler))
            await asyncio.sleep(0.01)
            write_task = asyncio.create_task(
                mw.awrap_tool_call(
                    _make_request("write_file", {"description": "d", "path": self.PATH, "content": "v2"}, write_messages),
                    write_handler,
                )
            )
            return await asyncio.gather(read_task, write_task)

        read_result, _write_result = asyncio.run(run())
        mark = read_result.additional_kwargs.get("deerflow_read_mark")
        assert mark is not None
        assert mark["hash"] == _sha(read_result.content)


class TestBlockedPayloadElision:
    """Model-bound requests drop the dead payload of gate-blocked writes; state stays intact."""

    PATH = "/mnt/user-data/outputs/report.md"

    @staticmethod
    def _config(**overrides):
        from deerflow.config.read_before_write_config import ReadBeforeWriteConfig

        return ReadBeforeWriteConfig(**overrides)

    def _middleware(self, files=None, **config_overrides):
        from deerflow.agents.middlewares.read_before_write_middleware import ReadBeforeWriteMiddleware

        files = {self.PATH: "v1"} if files is None else files

        def reader(_runtime, path):
            normalized = posixpath.normpath(path)
            if normalized not in files:
                raise FileNotFoundError(path)
            return files[normalized]

        return ReadBeforeWriteMiddleware(content_reader=reader, config=self._config(**config_overrides))

    @staticmethod
    def _model_request(messages):
        from langchain.agents.middleware.types import ModelRequest

        return ModelRequest(model=None, messages=list(messages), tools=[], state={"messages": list(messages)}, runtime=MagicMock())

    def _blocked_turn(self, mw, name, args, tool_call_id="call-1"):
        """Run a gated call against an unread file; return ``(AIMessage, blocked ToolMessage)``."""
        ai = AIMessage(content="", tool_calls=[{"name": name, "id": tool_call_id, "args": dict(args)}])
        request = _make_request(name, dict(args), [HumanMessage(content="go"), ai], tool_call_id=tool_call_id)
        blocked = mw.wrap_tool_call(request, MagicMock(side_effect=AssertionError("handler must not run when blocked")))
        assert blocked.status == "error"
        return ai, blocked

    @staticmethod
    def _captured(handler):
        return handler.call_args[0][0]

    def test_blocked_result_carries_write_block_marker(self):
        from deerflow.agents.middlewares.read_before_write_middleware import WRITE_BLOCK_KEY

        mw = self._middleware()
        _ai, blocked = self._blocked_turn(mw, "write_file", {"description": "d", "path": self.PATH, "content": "v2"})
        assert blocked.additional_kwargs[WRITE_BLOCK_KEY] == {"path": self.PATH, "tool": "write_file"}

    def test_allowed_write_result_has_no_marker(self):
        from deerflow.agents.middlewares.read_before_write_middleware import WRITE_BLOCK_KEY

        mw = self._middleware()
        messages = [_read_marked_message(self.PATH, "v1")]
        request = _make_request("write_file", {"description": "d", "path": self.PATH, "content": "v2"}, messages)
        handler = MagicMock(return_value=ToolMessage(content="OK", tool_call_id="call-1", name="write_file"))
        result = mw.wrap_tool_call(request, handler)
        assert WRITE_BLOCK_KEY not in result.additional_kwargs

    def test_elides_blocked_write_file_content_in_model_request(self):
        mw = self._middleware()
        payload = "x" * 5000
        ai, blocked = self._blocked_turn(mw, "write_file", {"description": "d", "path": self.PATH, "content": payload})
        human = HumanMessage(content="go")
        request = self._model_request([human, ai, blocked])
        handler = MagicMock(return_value=AIMessage(content="ok"))

        mw.wrap_model_call(request, handler)

        captured = self._captured(handler)
        assert captured is not request
        rewritten = captured.messages[1]
        assert rewritten is not ai
        args = rewritten.tool_calls[0]["args"]
        assert args["path"] == self.PATH
        assert args["description"] == "d"
        assert args["content"].startswith("[payload elided: 5000 chars")
        assert "read-before-write" in args["content"]
        assert payload not in args["content"]
        # Untouched neighbours are passed through by identity; the stored history is never rewritten.
        assert captured.messages[0] is human
        assert captured.messages[2] is blocked
        assert request.messages[1] is ai
        assert request.state["messages"][1] is ai
        assert ai.tool_calls[0]["args"]["content"] == payload

    def test_successful_write_payload_is_left_alone(self):
        mw = self._middleware()
        payload = "x" * 5000
        ai = AIMessage(content="", tool_calls=[{"name": "write_file", "id": "call-1", "args": {"description": "d", "path": self.PATH, "content": payload}}])
        ok = ToolMessage(content="OK", tool_call_id="call-1", name="write_file")
        request = self._model_request([HumanMessage(content="go"), ai, ok])
        handler = MagicMock(return_value=AIMessage(content="ok"))

        mw.wrap_model_call(request, handler)

        assert self._captured(handler) is request
        assert ai.tool_calls[0]["args"]["content"] == payload

    def test_only_the_blocked_call_is_elided_when_ids_differ(self):
        mw = self._middleware()
        payload = "x" * 5000
        ai, blocked = self._blocked_turn(mw, "write_file", {"description": "d", "path": self.PATH, "content": payload}, tool_call_id="call-blocked")
        other = AIMessage(content="", tool_calls=[{"name": "write_file", "id": "call-ok", "args": {"description": "d", "path": "/mnt/user-data/outputs/new.md", "content": payload}}])
        ok = ToolMessage(content="OK", tool_call_id="call-ok", name="write_file")
        request = self._model_request([HumanMessage(content="go"), other, ok, ai, blocked])
        handler = MagicMock(return_value=AIMessage(content="ok"))

        mw.wrap_model_call(request, handler)

        captured = self._captured(handler)
        assert captured.messages[1] is other
        assert captured.messages[3].tool_calls[0]["args"]["content"].startswith("[payload elided")

    def test_rewrites_raw_tool_calls_and_tool_use_blocks_consistently(self):
        import json

        mw = self._middleware()
        payload = "y" * 5000
        args = {"description": "d", "path": self.PATH, "content": payload}
        ai = AIMessage(
            content=[
                {"type": "text", "text": "writing"},
                {"type": "tool_use", "id": "call-1", "name": "write_file", "input": dict(args), "partial_json": json.dumps(args)},
            ],
            tool_calls=[{"name": "write_file", "id": "call-1", "args": dict(args)}],
            additional_kwargs={"tool_calls": [{"id": "call-1", "type": "function", "function": {"name": "write_file", "arguments": json.dumps(args)}}]},
        )
        request = _make_request("write_file", dict(args), [HumanMessage(content="go"), ai])
        blocked = mw.wrap_tool_call(request, MagicMock())
        model_request = self._model_request([HumanMessage(content="go"), ai, blocked])
        handler = MagicMock(return_value=AIMessage(content="ok"))

        mw.wrap_model_call(model_request, handler)

        rewritten = self._captured(handler).messages[1]
        structured = rewritten.tool_calls[0]["args"]
        assert structured["content"].startswith("[payload elided")
        raw = json.loads(rewritten.additional_kwargs["tool_calls"][0]["function"]["arguments"])
        assert raw == structured
        assert rewritten.additional_kwargs["tool_calls"][0]["function"]["name"] == "write_file"
        block = rewritten.content[1]
        assert block["input"] == structured
        assert "partial_json" not in block
        assert rewritten.content[0] == {"type": "text", "text": "writing"}
        # Serialized payload must be gone from every surface the provider adapters read.
        assert payload not in json.dumps(rewritten.model_dump(), ensure_ascii=False)
        # Original objects are untouched.
        assert ai.content[1]["input"]["content"] == payload
        assert payload in ai.additional_kwargs["tool_calls"][0]["function"]["arguments"]

    def test_str_replace_elides_old_and_new_str(self):
        mw = self._middleware()
        old_str, new_str = "a" * 3000, "b" * 4000
        ai, blocked = self._blocked_turn(mw, "str_replace", {"description": "d", "path": self.PATH, "old_str": old_str, "new_str": new_str})
        request = self._model_request([HumanMessage(content="go"), ai, blocked])
        handler = MagicMock(return_value=AIMessage(content="ok"))

        mw.wrap_model_call(request, handler)

        args = self._captured(handler).messages[1].tool_calls[0]["args"]
        assert args["old_str"].startswith("[payload elided: 3000 chars")
        assert args["new_str"].startswith("[payload elided: 4000 chars")
        assert "str_replace" in args["new_str"]
        assert args["path"] == self.PATH

    def test_payload_below_min_chars_stays_visible(self):
        mw = self._middleware()
        ai, blocked = self._blocked_turn(mw, "write_file", {"description": "d", "path": self.PATH, "content": "short " * 20})
        request = self._model_request([HumanMessage(content="go"), ai, blocked])
        handler = MagicMock(return_value=AIMessage(content="ok"))

        mw.wrap_model_call(request, handler)

        assert self._captured(handler) is request

    def test_mixed_fields_only_elide_those_over_threshold(self):
        mw = self._middleware(elide_min_chars=1000)
        ai, blocked = self._blocked_turn(mw, "str_replace", {"description": "d", "path": self.PATH, "old_str": "tiny", "new_str": "n" * 1000})
        request = self._model_request([HumanMessage(content="go"), ai, blocked])
        handler = MagicMock(return_value=AIMessage(content="ok"))

        mw.wrap_model_call(request, handler)

        args = self._captured(handler).messages[1].tool_calls[0]["args"]
        assert args["old_str"] == "tiny"
        assert args["new_str"].startswith("[payload elided: 1000 chars")

    def test_min_chars_zero_elides_any_non_empty_payload(self):
        mw = self._middleware(elide_min_chars=0)
        ai, blocked = self._blocked_turn(mw, "write_file", {"description": "d", "path": self.PATH, "content": "v2"})
        empty_ai, empty_blocked = self._blocked_turn(mw, "write_file", {"description": "d", "path": self.PATH, "content": ""}, tool_call_id="call-2")
        request = self._model_request([HumanMessage(content="go"), ai, blocked, empty_ai, empty_blocked])
        handler = MagicMock(return_value=AIMessage(content="ok"))

        mw.wrap_model_call(request, handler)

        captured = self._captured(handler)
        assert captured.messages[1].tool_calls[0]["args"]["content"].startswith("[payload elided: 2 chars")
        assert captured.messages[3] is empty_ai

    def test_disabled_by_config_passes_request_through(self):
        mw = self._middleware(elide_blocked_payloads=False)
        ai, blocked = self._blocked_turn(mw, "write_file", {"description": "d", "path": self.PATH, "content": "x" * 5000})
        request = self._model_request([HumanMessage(content="go"), ai, blocked])
        handler = MagicMock(return_value=AIMessage(content="ok"))

        mw.wrap_model_call(request, handler)

        assert self._captured(handler) is request

    def test_elision_is_deterministic_across_model_calls(self):
        mw = self._middleware()
        ai, blocked = self._blocked_turn(mw, "write_file", {"description": "d", "path": self.PATH, "content": "x" * 5000})
        first, second = MagicMock(return_value=AIMessage(content="ok")), MagicMock(return_value=AIMessage(content="ok"))

        mw.wrap_model_call(self._model_request([HumanMessage(content="go"), ai, blocked]), first)
        mw.wrap_model_call(self._model_request([HumanMessage(content="go"), ai, blocked]), second)

        assert self._captured(first).messages[1].tool_calls == self._captured(second).messages[1].tool_calls

    def test_async_model_call_elides(self):
        import asyncio

        mw = self._middleware()
        ai, blocked = self._blocked_turn(mw, "write_file", {"description": "d", "path": self.PATH, "content": "x" * 5000})
        request = self._model_request([HumanMessage(content="go"), ai, blocked])
        seen = {}

        async def handler(model_request):
            seen["request"] = model_request
            return AIMessage(content="ok")

        asyncio.run(mw.awrap_model_call(request, handler))

        assert seen["request"] is not request
        assert seen["request"].messages[1].tool_calls[0]["args"]["content"].startswith("[payload elided")

    def test_release_policy_declares_config(self):
        mw = self._middleware(elide_min_chars=123)
        params = mw.release_policy_parameters()
        assert params["config"]["enabled"] is True
        assert params["config"]["elide_blocked_payloads"] is True
        assert params["config"]["elide_min_chars"] == 123

    def test_malformed_unhashable_ids_do_not_break_elision(self):
        import json

        mw = self._middleware()
        payload = "z" * 5000
        args = {"description": "d", "path": self.PATH, "content": payload}
        ai, blocked = self._blocked_turn(mw, "write_file", args)
        # A provider payload with a list-typed id must be skipped, not raise from a membership probe.
        weird = AIMessage(
            content=[{"type": "tool_use", "id": ["not", "a", "string"], "name": "write_file", "input": dict(args)}],
            tool_calls=[{"name": "write_file", "id": "call-1", "args": dict(args)}],
            additional_kwargs={"tool_calls": [{"id": ["not", "a", "string"], "type": "function", "function": {"name": "write_file", "arguments": json.dumps(args)}}]},
        )
        request = self._model_request([HumanMessage(content="go"), weird, blocked])
        handler = MagicMock(return_value=AIMessage(content="ok"))

        mw.wrap_model_call(request, handler)

        rewritten = self._captured(handler).messages[1]
        assert rewritten.tool_calls[0]["args"]["content"].startswith("[payload elided")
        assert rewritten.content[0]["input"]["content"] == payload
        assert payload in rewritten.additional_kwargs["tool_calls"][0]["function"]["arguments"]

    def test_responses_api_request_input_never_carries_the_blocked_payload(self):
        """End to end against the real OpenAI Responses input builder (reviewer probe on #5329)."""
        import json

        from langchain_openai.chat_models.base import _construct_responses_api_input

        mw = self._middleware()
        payload = "r" * 5000
        args = {"description": "d", "path": self.PATH, "content": payload}
        ai = AIMessage(
            content=[{"type": "function_call", "id": "fc_1", "call_id": "call-1", "name": "write_file", "arguments": json.dumps(args), "status": "completed"}],
            tool_calls=[{"name": "write_file", "id": "call-1", "args": dict(args)}],
            response_metadata={"output_version": "responses/v1"},
        )
        blocked = mw.wrap_tool_call(_make_request("write_file", dict(args), [HumanMessage(content="go"), ai]), MagicMock())
        request = self._model_request([HumanMessage(content="go"), ai, blocked])
        handler = MagicMock(return_value=AIMessage(content="ok"))

        mw.wrap_model_call(request, handler)

        items = _construct_responses_api_input(self._captured(handler).messages[1:2])
        calls = [item for item in items if item.get("type") == "function_call"]
        assert len(calls) == 1
        assert calls[0]["id"] == "fc_1"
        assert json.loads(calls[0]["arguments"])["content"].startswith("[payload elided: 5000 chars")
        assert payload not in json.dumps(items, ensure_ascii=False)

    def _successful_write(self, tool_call_id, path="/mnt/user-data/outputs/other.md", payload="s" * 5000):
        ai = AIMessage(content="", tool_calls=[{"name": "write_file", "id": tool_call_id, "args": {"description": "d", "path": path, "content": payload}}])
        return ai, ToolMessage(content="OK", tool_call_id=tool_call_id, name="write_file")

    @pytest.mark.parametrize("success_first", [True, False], ids=["success-before-block", "block-before-success"])
    def test_reused_call_id_only_elides_the_blocked_occurrence(self, success_first):
        """Tool-call ids repeat across turns; pairing is per occurrence, not per id (review on #5329)."""
        import json

        from langchain_openai.chat_models.base import _convert_message_to_dict

        mw = self._middleware()
        ok_ai, ok_tool = self._successful_write("call-1")
        blocked_ai, blocked = self._blocked_turn(mw, "write_file", {"description": "d", "path": self.PATH, "content": "b" * 5000}, tool_call_id="call-1")
        turns = [ok_ai, ok_tool, blocked_ai, blocked] if success_first else [blocked_ai, blocked, ok_ai, ok_tool]
        request = self._model_request([HumanMessage(content="go"), *turns])
        handler = MagicMock(return_value=AIMessage(content="ok"))

        mw.wrap_model_call(request, handler)

        captured = self._captured(handler).messages
        ok_index, blocked_index = (1, 3) if success_first else (3, 1)
        assert captured[ok_index] is ok_ai
        assert captured[blocked_index].tool_calls[0]["args"]["content"].startswith("[payload elided: 5000 chars")
        ok_wire = json.loads(_convert_message_to_dict(captured[ok_index])["tool_calls"][0]["function"]["arguments"])
        blocked_wire = json.loads(_convert_message_to_dict(captured[blocked_index])["tool_calls"][0]["function"]["arguments"])
        assert ok_wire["content"] == "s" * 5000
        assert blocked_wire["content"].startswith("[payload elided")

    def test_chained_responses_request_replays_the_rewritten_history(self):
        """With use_previous_response_id the adapter must not chain past the elided call (review on #5329)."""
        import json

        from langchain_openai import ChatOpenAI

        mw = self._middleware()
        payload = "c" * 5000
        args = {"description": "d", "path": self.PATH, "content": payload}
        ai = AIMessage(
            content=[{"type": "function_call", "id": "fc_1", "call_id": "call-1", "name": "write_file", "arguments": json.dumps(args), "status": "completed"}],
            tool_calls=[{"name": "write_file", "id": "call-1", "args": dict(args)}],
            response_metadata={"id": "resp_blocked", "output_version": "responses/v1"},
        )
        blocked = mw.wrap_tool_call(_make_request("write_file", dict(args), [HumanMessage(content="go"), ai]), MagicMock())
        request = self._model_request([HumanMessage(content="go"), ai, blocked])
        handler = MagicMock(return_value=AIMessage(content="ok"))
        model = ChatOpenAI(model="gpt-4.1", api_key="test-key", use_responses_api=True, use_previous_response_id=True)

        mw.wrap_model_call(request, handler)

        leaked = model._get_request_payload(request.messages)
        assert leaked["previous_response_id"] == "resp_blocked"
        sent = model._get_request_payload(self._captured(handler).messages)
        assert "previous_response_id" not in sent
        calls = [item for item in sent["input"] if item.get("type") == "function_call"]
        assert len(calls) == 1
        assert json.loads(calls[0]["arguments"])["content"].startswith("[payload elided: 5000 chars")
        assert payload not in json.dumps(sent, ensure_ascii=False)

    def test_unanswered_write_with_a_reused_id_is_not_labeled_blocked(self):
        """Review on #5374: an interrupted write must not inherit the blocked result of a later call that reused its id."""
        mw = self._middleware()
        draft = "d" * 5000
        interrupted = AIMessage(content="", tool_calls=[{"name": "write_file", "id": "reused", "args": {"description": "d", "path": "/mnt/user-data/outputs/other.md", "content": draft}}])
        blocked_ai, blocked = self._blocked_turn(mw, "write_file", {"description": "d", "path": self.PATH, "content": "b" * 5000}, tool_call_id="reused")
        request = self._model_request([HumanMessage(content="go"), interrupted, blocked_ai, blocked])
        handler = MagicMock(return_value=AIMessage(content="ok"))

        mw.wrap_model_call(request, handler)

        captured = self._captured(handler).messages
        assert captured[1] is interrupted
        assert captured[2].tool_calls[0]["args"]["content"].startswith("[payload elided: 5000 chars")
