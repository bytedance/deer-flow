"""Tests for per-call stdio MCP tool sessions (issue #3379).

Background
----------
stdio MCP transport (``stdio_client`` + ``ClientSession``) is built on
``anyio.create_task_group()``. anyio enforces a hard invariant: a cancel
scope / task group MUST be entered (``__aenter__``) and exited (``__aexit__``)
in the **same** asyncio task. The old ``MCPSessionPool`` entered a session in
the task handling one tool call and later closed it from a *different* task
(LRU eviction, ``close_all_sync`` via ``run_coroutine_threadsafe``, or the
event loop's async-generator GC finalizer), which raised
``RuntimeError: Attempted to exit cancel scope in a different task than it was
entered in`` — issue #3379.

The fix removes pooling entirely and gives stdio tools per-call sessions
(open + call + close inside one coroutine, i.e. one task), matching what
langchain-mcp-adapters does for HTTP/SSE and what the library does by default.

These tests deliberately include a REAL stdio MCP subprocess (no mocks for the
session) because the previous test suite mocked ``create_session`` with plain
``AsyncMock`` context managers that have no task group — which is precisely why
the cross-task bug was never caught.
"""

from __future__ import annotations

import asyncio
import gc
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Path to the committed minimal stdio MCP server used by the real-session test.
_STDIO_SERVER = str(Path(__file__).parent / "support" / "stdio_mcp_server.py")
_REAL_CONNECTION = {"transport": "stdio", "command": sys.executable, "args": [_STDIO_SERVER]}


def _make_args_schema():
    from pydantic import BaseModel, Field

    class Args(BaseModel):
        text: str = Field(..., description="text")

    return Args


def _stub_tool(name: str):
    from langchain_core.tools import StructuredTool

    return StructuredTool(
        name=name,
        description="test tool",
        args_schema=_make_args_schema(),
        coroutine=AsyncMock(),
        response_format="content_and_artifact",
    )


# ---------------------------------------------------------------------------
# Structural guarantee: stdio tools use a FRESH session per call (not pooled)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stdio_tool_opens_and_closes_session_per_call():
    """Each invocation must open AND close its own session in the same task.

    This is the regression lock for #3379: pooling reused one session across
    calls (open once, close from a foreign task later). Per-call sessions open
    and close within the single coroutine/task, so every call enters and exits
    the cancel scope in the same task.
    """
    from deerflow.mcp.tools import _make_per_call_mcp_tool

    enters = 0
    exits = 0

    class CountingCM:
        async def __aenter__(self):
            nonlocal enters
            enters += 1
            session = AsyncMock()
            session.call_tool = AsyncMock(return_value=MagicMock(content=[], isError=False, structuredContent=None))
            return session

        async def __aexit__(self, *args):
            nonlocal exits
            exits += 1
            return False

    with patch("langchain_mcp_adapters.sessions.create_session", side_effect=lambda *a, **kw: CountingCM()):
        wrapped = _make_per_call_mcp_tool(_stub_tool("srv_echo"), "srv", {"transport": "stdio", "command": "x", "args": []})
        await wrapped.coroutine(runtime=None, text="a")
        await wrapped.coroutine(runtime=None, text="b")

    # Two calls => two independent open/close cycles (per-call, not pooled).
    assert enters == 2, f"expected a fresh session per call, got {enters} opens"
    assert exits == 2, f"each per-call session must close in-task, got {exits} closes"


@pytest.mark.asyncio
async def test_stdio_tool_closes_session_even_on_error():
    """An MCP error must still close the per-call session (no leak)."""
    from langchain_core.tools import ToolException

    from deerflow.mcp.tools import _make_per_call_mcp_tool

    closed = False

    class CM:
        async def __aenter__(self):
            session = AsyncMock()
            session.call_tool = AsyncMock(return_value=MagicMock(content=[{"type": "text", "text": "boom"}], isError=True, structuredContent=None))
            return session

        async def __aexit__(self, *args):
            nonlocal closed
            closed = True
            return False

    with patch("langchain_mcp_adapters.sessions.create_session", side_effect=lambda *a, **kw: CM()):
        wrapped = _make_per_call_mcp_tool(_stub_tool("srv_echo"), "srv", {"transport": "stdio", "command": "x", "args": []})
        with pytest.raises(ToolException):
            await wrapped.coroutine(runtime=None, text="a")

    assert closed is True, "session must be closed even when the tool call errors"


# ---------------------------------------------------------------------------
# Interceptor header forwarding (preserve PR #3294 behavior for stdio)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stdio_tool_forwards_interceptor_headers():
    """Interceptor-set headers are forwarded to stdio calls via ``meta``."""
    from deerflow.mcp.tools import _make_per_call_mcp_tool

    session = AsyncMock()
    session.call_tool = AsyncMock(return_value=MagicMock(content=[], isError=False, structuredContent=None))
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)

    async def header_interceptor(request, handler):
        return await handler(request.override(headers={"X-User-Id": "u-42"}))

    with patch("langchain_mcp_adapters.sessions.create_session", return_value=cm):
        wrapped = _make_per_call_mcp_tool(
            _stub_tool("srv_act"),
            "srv",
            {"transport": "stdio", "command": "x", "args": []},
            tool_interceptors=[header_interceptor],
        )
        await wrapped.coroutine(runtime=None, text="x")

    session.call_tool.assert_awaited_once_with("act", {"text": "x"}, meta={"headers": {"X-User-Id": "u-42"}})


@pytest.mark.asyncio
async def test_stdio_tool_no_headers_omits_meta():
    """Without interceptor headers, no ``meta`` kwarg is passed."""
    from deerflow.mcp.tools import _make_per_call_mcp_tool

    session = AsyncMock()
    session.call_tool = AsyncMock(return_value=MagicMock(content=[], isError=False, structuredContent=None))
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)

    async def passthrough(request, handler):
        return await handler(request)

    with patch("langchain_mcp_adapters.sessions.create_session", return_value=cm):
        wrapped = _make_per_call_mcp_tool(
            _stub_tool("srv_act"),
            "srv",
            {"transport": "stdio", "command": "x", "args": []},
            tool_interceptors=[passthrough],
        )
        await wrapped.coroutine(runtime=None, text="x")

    session.call_tool.assert_awaited_once_with("act", {"text": "x"})


# ---------------------------------------------------------------------------
# Sync-wrapper path (DeerFlowClient streams synchronously)
# ---------------------------------------------------------------------------


def test_stdio_tool_sync_wrapper_path_is_safe():
    """Sync invocation (asyncio.run in a worker thread) opens+closes in one task."""
    from deerflow.mcp.tools import _make_per_call_mcp_tool
    from deerflow.tools.sync import make_sync_tool_wrapper

    session = AsyncMock()
    session.call_tool = AsyncMock(return_value=MagicMock(content=[], isError=False, structuredContent=None))
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)

    with patch("langchain_mcp_adapters.sessions.create_session", return_value=cm):
        wrapped = _make_per_call_mcp_tool(_stub_tool("srv_echo"), "srv", {"transport": "stdio", "command": "x", "args": []})
        wrapped.func = make_sync_tool_wrapper(wrapped.coroutine, wrapped.name)
        wrapped.func(text="hello")

    session.call_tool.assert_called_once_with("echo", {"text": "hello"})


# ---------------------------------------------------------------------------
# get_mcp_tools: HTTP/SSE returned as-is, stdio wrapped per-call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_transport_tools_not_wrapped_stdio_is():
    """HTTP/SSE tools are returned unchanged; stdio tools get the per-call wrapper."""
    from deerflow.mcp.tools import get_mcp_tools

    http_tool = _stub_tool("myserver_search")
    stdio_tool = _stub_tool("playwright_navigate")

    extensions_config = MagicMock()
    extensions_config.model_extra = {}

    servers_config = {
        "myserver": {"transport": "http", "url": "http://localhost:8000/mcp"},
        "playwright": {"transport": "stdio", "command": "npx", "args": ["-y", "@playwright/mcp"]},
    }

    with (
        patch("deerflow.mcp.tools.ExtensionsConfig.from_file", return_value=extensions_config),
        patch("deerflow.mcp.tools.build_servers_config", return_value=servers_config),
        patch("deerflow.mcp.tools.get_initial_oauth_headers", return_value={}),
        patch("deerflow.mcp.tools.build_oauth_tool_interceptor", return_value=None),
        patch("langchain_mcp_adapters.client.MultiServerMCPClient") as MockClient,
    ):
        MockClient.return_value.get_tools = AsyncMock(return_value=[http_tool, stdio_tool])
        tools = await get_mcp_tools()

    http = next(t for t in tools if t.name == "myserver_search")
    stdio = next(t for t in tools if t.name == "playwright_navigate")
    assert http.coroutine is http_tool.coroutine, "HTTP tool must be returned unchanged"
    assert stdio.coroutine is not stdio_tool.coroutine, "stdio tool must be wrapped per-call"


def test_session_pool_module_is_removed():
    """The cross-task session pool must be gone (locks the #3379 fix)."""
    with pytest.raises(ModuleNotFoundError):
        __import__("deerflow.mcp.session_pool")


# ---------------------------------------------------------------------------
# REAL stdio session — the cross-task safety guard (no mocks)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_real_stdio_tool_is_cross_task_safe():
    """Invoke a REAL stdio MCP tool from multiple distinct tasks + force GC.

    LangGraph runs parallel tool calls via ``asyncio.gather`` (each coroutine
    becomes its own Task). With per-call sessions, every call opens and closes
    its session inside its own task, so no cancel-scope-cross-task RuntimeError
    is raised and the async-gen finalizer has nothing to clean up across tasks.

    This is the test the old, mock-only suite could not express.
    """
    from deerflow.mcp.tools import _make_per_call_mcp_tool

    loop = asyncio.get_running_loop()
    unhandled: list[dict] = []
    loop.set_exception_handler(lambda _l, ctx: unhandled.append(ctx))

    wrapped = _make_per_call_mcp_tool(_stub_tool("repro_echo"), "repro", _REAL_CONNECTION)

    async def call(text: str) -> str:
        result, _artifact = await asyncio.wait_for(wrapped.coroutine(runtime=None, text=text), timeout=30)
        # content blocks -> first text
        return result[0]["text"] if result else ""

    # Distinct tasks, exactly like LangGraph's parallel tool execution.
    outputs = await asyncio.gather(call("one"), call("two"), call("three"))
    assert outputs == ["echo: one", "echo: two", "echo: three"]

    # Force finalization of any lingering async generators; give the loop a tick.
    gc.collect()
    await asyncio.sleep(0.3)

    cancel_scope_errors = [ctx for ctx in unhandled if "cancel scope" in str(ctx.get("exception") or ctx.get("message", ""))]
    assert not cancel_scope_errors, f"cross-task cancel-scope error leaked: {cancel_scope_errors}"
