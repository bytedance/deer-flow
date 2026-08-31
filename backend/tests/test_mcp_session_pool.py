"""Tests for the MCP persistent-session pool."""

import asyncio
import gc
import logging
import stat
import sys
import threading
import weakref
from unittest.mock import AsyncMock, MagicMock, patch

import anyio
import pytest
from mcp.shared.exceptions import McpError
from mcp.types import CONNECTION_CLOSED, CallToolResult, ErrorData, TextContent

from deerflow.mcp.session_pool import MCPSessionPool, call_pooled_session_tool, get_session_pool, reset_session_pool


@pytest.fixture(autouse=True)
def _reset_pool():
    reset_session_pool()
    yield
    reset_session_pool()


# ---------------------------------------------------------------------------
# MCPSessionPool unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_session_creates_new():
    """First call for a key creates a new session."""
    pool = MCPSessionPool()

    mock_session = AsyncMock()
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("langchain_mcp_adapters.sessions.create_session", return_value=mock_cm):
        session = await pool.get_session("server", "thread-1", {"transport": "stdio", "command": "x", "args": []})

    assert session is mock_session
    mock_session.initialize.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_session_reuses_existing():
    """Second call for the same key returns the cached session."""
    pool = MCPSessionPool()

    mock_session = AsyncMock()
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("langchain_mcp_adapters.sessions.create_session", return_value=mock_cm):
        s1 = await pool.get_session("server", "thread-1", {"transport": "stdio", "command": "x", "args": []})
        s2 = await pool.get_session("server", "thread-1", {"transport": "stdio", "command": "x", "args": []})

    assert s1 is s2
    # Only one session should have been created.
    assert mock_cm.__aenter__.await_count == 1


@pytest.mark.asyncio
async def test_different_scope_creates_different_session():
    """Different scope keys get different sessions."""
    pool = MCPSessionPool()

    sessions = [AsyncMock(), AsyncMock()]
    idx = 0

    class CmFactory:
        def __init__(self):
            self.enter_count = 0

        async def __aenter__(self):
            nonlocal idx
            s = sessions[idx]
            idx += 1
            self.enter_count += 1
            return s

        async def __aexit__(self, *args):
            return False

    with patch("langchain_mcp_adapters.sessions.create_session", side_effect=lambda *a, **kw: CmFactory()):
        s1 = await pool.get_session("server", "thread-1", {"transport": "stdio", "command": "x", "args": []})
        s2 = await pool.get_session("server", "thread-2", {"transport": "stdio", "command": "x", "args": []})

    assert s1 is not s2
    assert s1 is sessions[0]
    assert s2 is sessions[1]


@pytest.mark.asyncio
async def test_lru_eviction():
    """Oldest entries are evicted when the pool is full."""
    pool = MCPSessionPool()
    pool.MAX_SESSIONS = 2

    class CmFactory:
        def __init__(self):
            self.closed = False

        async def __aenter__(self):
            return AsyncMock()

        async def __aexit__(self, *args):
            self.closed = True
            return False

    cms: list[CmFactory] = []

    def make_cm(*a, **kw):
        cm = CmFactory()
        cms.append(cm)
        return cm

    with patch("langchain_mcp_adapters.sessions.create_session", side_effect=make_cm):
        await pool.get_session("s", "t1", {"transport": "stdio", "command": "x", "args": []})
        await pool.get_session("s", "t2", {"transport": "stdio", "command": "x", "args": []})
        # Pool is full (2). Adding t3 should evict t1.
        await pool.get_session("s", "t3", {"transport": "stdio", "command": "x", "args": []})

    assert cms[0].closed is True
    assert cms[1].closed is False
    assert cms[2].closed is False


@pytest.mark.asyncio
async def test_close_scope():
    """close_scope shuts down sessions for a specific scope key."""
    pool = MCPSessionPool()

    class CmFactory:
        def __init__(self):
            self.closed = False

        async def __aenter__(self):
            return AsyncMock()

        async def __aexit__(self, *args):
            self.closed = True
            return False

    cms: list[CmFactory] = []

    def make_cm(*a, **kw):
        cm = CmFactory()
        cms.append(cm)
        return cm

    with patch("langchain_mcp_adapters.sessions.create_session", side_effect=make_cm):
        await pool.get_session("s", "t1", {"transport": "stdio", "command": "x", "args": []})
        await pool.get_session("s", "t2", {"transport": "stdio", "command": "x", "args": []})

    await pool.close_scope("t1")

    assert cms[0].closed is True
    assert cms[1].closed is False

    # t2 session still exists.
    assert ("s", "t2") in pool._entries


@pytest.mark.asyncio
async def test_close_session_only_evicts_the_exact_server_scope_pair():
    pool = MCPSessionPool()

    class CmFactory:
        def __init__(self):
            self.closed = False

        async def __aenter__(self):
            return AsyncMock()

        async def __aexit__(self, *args):
            self.closed = True
            return False

    cms: list[CmFactory] = []

    def make_cm(*_args, **_kwargs):
        cm = CmFactory()
        cms.append(cm)
        return cm

    with patch("langchain_mcp_adapters.sessions.create_session", side_effect=make_cm):
        await pool.get_session("s1", "t1", {"transport": "stdio", "command": "x", "args": []})
        await pool.get_session("s2", "t1", {"transport": "stdio", "command": "x", "args": []})
        await pool.get_session("s1", "t2", {"transport": "stdio", "command": "x", "args": []})

    await pool.close_session("s1", "t1")

    assert cms[0].closed is True
    assert cms[1].closed is False
    assert cms[2].closed is False
    assert set(pool._entries) == {("s2", "t1"), ("s1", "t2")}


@pytest.mark.asyncio
async def test_close_all():
    """close_all shuts down every session."""
    pool = MCPSessionPool()

    class CmFactory:
        def __init__(self):
            self.closed = False

        async def __aenter__(self):
            return AsyncMock()

        async def __aexit__(self, *args):
            self.closed = True
            return False

    cms: list[CmFactory] = []

    def make_cm(*a, **kw):
        cm = CmFactory()
        cms.append(cm)
        return cm

    with patch("langchain_mcp_adapters.sessions.create_session", side_effect=make_cm):
        await pool.get_session("s1", "t1", {"transport": "stdio", "command": "x", "args": []})
        await pool.get_session("s2", "t2", {"transport": "stdio", "command": "x", "args": []})

    await pool.close_all()

    assert all(cm.closed for cm in cms)
    assert len(pool._entries) == 0


# ---------------------------------------------------------------------------
# Singleton helpers
# ---------------------------------------------------------------------------


def test_get_session_pool_singleton():
    """get_session_pool returns the same instance."""
    p1 = get_session_pool()
    p2 = get_session_pool()
    assert p1 is p2


def test_reset_session_pool():
    """reset_session_pool clears the singleton."""
    p1 = get_session_pool()
    reset_session_pool()
    p2 = get_session_pool()
    assert p1 is not p2


# ---------------------------------------------------------------------------
# Integration: _make_session_pool_tool uses the pool
# ---------------------------------------------------------------------------


def _make_test_pool_tool(*, pool, call_tool, tool_interceptors=None):
    from langchain_core.tools import StructuredTool
    from pydantic import BaseModel, Field

    from deerflow.mcp.tools import _make_session_pool_tool

    class Args(BaseModel):
        value: int = Field(..., description="value")

    original_tool = StructuredTool(
        name="srv_act",
        description="test",
        args_schema=Args,
        coroutine=AsyncMock(),
        response_format="content_and_artifact",
    )
    session = AsyncMock()
    if isinstance(call_tool, BaseException):
        session.call_tool = AsyncMock(side_effect=call_tool)
    else:
        session.call_tool = AsyncMock(return_value=call_tool)
    pool.get_session = AsyncMock(return_value=session)
    pool.close_session_if_current = AsyncMock()

    with patch("deerflow.mcp.tools.get_session_pool", return_value=pool):
        wrapped = _make_session_pool_tool(
            original_tool,
            "srv",
            {"transport": "stdio", "command": "x", "args": []},
            tool_interceptors=tool_interceptors,
        )
    return wrapped, session


@pytest.mark.asyncio
async def test_session_pool_tool_reconnects_after_real_stdio_process_disconnect(tmp_path):
    """A dead stdio subprocess must not poison later calls in the same scope."""
    from langchain_core.tools import StructuredTool
    from pydantic import BaseModel

    from deerflow.config.paths import Paths
    from deerflow.mcp.tools import _make_session_pool_tool

    server = """
import os
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

marker = Path(sys.argv[1])
mcp = FastMCP("crash-once")

@mcp.tool()
def crash_once() -> str:
    if not marker.exists():
        marker.write_text("crashed")
        os._exit(17)
    return "recovered"

mcp.run(transport="stdio")
"""

    class Args(BaseModel):
        pass

    original_tool = StructuredTool(
        name="crash_crash_once",
        description="crash once",
        args_schema=Args,
        coroutine=AsyncMock(),
        response_format="content_and_artifact",
    )
    marker = tmp_path / "crashed"
    connection = {
        "transport": "stdio",
        "command": sys.executable,
        "args": ["-c", server, str(marker)],
    }
    runtime = MagicMock()
    runtime.context = {"thread_id": "thread", "user_id": "user"}
    runtime.config = {}

    with patch("deerflow.mcp.tools.get_paths", return_value=Paths(tmp_path)):
        wrapped = _make_session_pool_tool(original_tool, "crash", connection)
        with pytest.raises(McpError, match="Connection closed") as exc_info:
            await wrapped.coroutine(runtime=runtime)

        assert exc_info.value.error.code == CONNECTION_CLOSED
        assert ("crash", "user:thread") not in get_session_pool()._entries

        content, _artifact = await wrapped.coroutine(runtime=runtime)

    assert content[0]["text"] == "recovered"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "transport_error",
    [
        anyio.ClosedResourceError(),
        anyio.BrokenResourceError(),
        anyio.EndOfStream(),
    ],
)
async def test_session_pool_tool_evicts_session_after_transport_disconnect(tmp_path, transport_error):
    """Low-level closed-stream signals evict the exact pooled session."""
    from deerflow.config.paths import Paths

    pool = MagicMock()
    wrapped, session = _make_test_pool_tool(pool=pool, call_tool=transport_error)

    with (
        patch("deerflow.mcp.tools.get_paths", return_value=Paths(tmp_path)),
        pytest.raises(type(transport_error)),
    ):
        await wrapped.coroutine(value=1)

    pool.close_session_if_current.assert_awaited_once_with("srv", "test-user-autouse:default", session)


@pytest.mark.asyncio
async def test_session_pool_tool_evicts_connection_closed_through_interceptor(tmp_path):
    """A passthrough interceptor must retain transport-failure recovery."""
    from deerflow.config.paths import Paths

    async def passthrough(request, handler):
        return await handler(request)

    error = McpError(ErrorData(code=CONNECTION_CLOSED, message="Connection closed"))
    pool = MagicMock()
    wrapped, session = _make_test_pool_tool(
        pool=pool,
        call_tool=error,
        tool_interceptors=[passthrough],
    )

    with (
        patch("deerflow.mcp.tools.get_paths", return_value=Paths(tmp_path)),
        pytest.raises(McpError, match="Connection closed"),
    ):
        await wrapped.coroutine(value=1)

    pool.close_session_if_current.assert_awaited_once_with("srv", "test-user-autouse:default", session)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        McpError(ErrorData(code=408, message="request timed out")),
        McpError(ErrorData(code=CONNECTION_CLOSED, message="server-specific failure")),
    ],
)
async def test_session_pool_tool_keeps_session_after_nonfatal_mcp_error(tmp_path, error):
    """Protocol errors such as timeouts do not prove that the session is dead."""
    from deerflow.config.paths import Paths

    pool = MagicMock()
    wrapped, _session = _make_test_pool_tool(pool=pool, call_tool=error)

    with (
        patch("deerflow.mcp.tools.get_paths", return_value=Paths(tmp_path)),
        pytest.raises(McpError, match=str(error)),
    ):
        await wrapped.coroutine(value=1)

    pool.close_session_if_current.assert_not_awaited()


@pytest.mark.asyncio
async def test_session_pool_tool_preserves_disconnect_error_when_eviction_fails(tmp_path):
    """Cleanup failure must not replace the transport error seen by the caller."""
    from deerflow.config.paths import Paths

    error = anyio.ClosedResourceError()
    pool = MagicMock()
    wrapped, session = _make_test_pool_tool(pool=pool, call_tool=error)
    pool.close_session_if_current.side_effect = RuntimeError("cleanup failed")

    with (
        patch("deerflow.mcp.tools.get_paths", return_value=Paths(tmp_path)),
        pytest.raises(anyio.ClosedResourceError) as exc_info,
    ):
        await wrapped.coroutine(value=1)

    assert exc_info.value is error
    pool.close_session_if_current.assert_awaited_once_with("srv", "test-user-autouse:default", session)


@pytest.mark.asyncio
async def test_session_pool_disconnect_cleanup_survives_caller_cancellation():
    """A cancelled caller cannot interrupt disconnected-session teardown."""
    cleanup_started = asyncio.Event()
    release_cleanup = asyncio.Event()
    cleanup_finished = asyncio.Event()

    async def close_session_if_current(*_args):
        cleanup_started.set()
        await release_cleanup.wait()
        cleanup_finished.set()
        return True

    session = AsyncMock()
    session.call_tool = AsyncMock(side_effect=anyio.ClosedResourceError())
    pool = MagicMock()
    pool.close_session_if_current = close_session_if_current

    call = asyncio.create_task(
        call_pooled_session_tool(
            session,
            pool,
            server_name="srv",
            scope_key="scope",
            tool_name="act",
            arguments={},
            call_kwargs={},
        )
    )
    await cleanup_started.wait()
    call.cancel()
    await asyncio.sleep(0)
    call.cancel()
    release_cleanup.set()

    with pytest.raises(asyncio.CancelledError):
        await call
    assert cleanup_finished.is_set()


@pytest.mark.asyncio
async def test_session_pool_tool_keeps_session_after_tool_error_result(tmp_path):
    """An MCP tool-level error is a valid response from a live session."""
    from langchain_core.tools import ToolException

    from deerflow.config.paths import Paths

    result = CallToolResult(
        content=[TextContent(type="text", text="invalid input")],
        isError=True,
    )
    pool = MagicMock()
    wrapped, _session = _make_test_pool_tool(pool=pool, call_tool=result)

    with (
        patch("deerflow.mcp.tools.get_paths", return_value=Paths(tmp_path)),
        pytest.raises(ToolException, match="invalid input"),
    ):
        await wrapped.coroutine(value=1)

    pool.close_session_if_current.assert_not_awaited()


@pytest.mark.asyncio
async def test_session_pool_tool_keeps_session_after_interceptor_error(tmp_path):
    """Interceptor failures happen outside the transport and must not evict it."""
    from deerflow.config.paths import Paths

    async def failing_interceptor(_request, _handler):
        raise RuntimeError("interceptor failed")

    pool = MagicMock()
    wrapped, session = _make_test_pool_tool(
        pool=pool,
        call_tool=CallToolResult(content=[], isError=False),
        tool_interceptors=[failing_interceptor],
    )

    with (
        patch("deerflow.mcp.tools.get_paths", return_value=Paths(tmp_path)),
        pytest.raises(RuntimeError, match="interceptor failed"),
    ):
        await wrapped.coroutine(value=1)

    session.call_tool.assert_not_awaited()
    pool.close_session_if_current.assert_not_awaited()


@pytest.mark.asyncio
async def test_late_disconnect_from_old_session_does_not_evict_replacement(tmp_path):
    """Concurrent late failures must not close a replacement for the same key."""
    from langchain_core.tools import StructuredTool
    from pydantic import BaseModel, Field

    from deerflow.config.paths import Paths
    from deerflow.mcp.tools import _make_session_pool_tool

    first_failure = asyncio.Event()
    late_failure = asyncio.Event()
    both_started = asyncio.Event()
    call_count = 0

    async def old_call_tool(_name, arguments, **_kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            both_started.set()
        await (first_failure if arguments["value"] == 1 else late_failure).wait()
        raise anyio.ClosedResourceError

    old_session = AsyncMock()
    old_session.call_tool = AsyncMock(side_effect=old_call_tool)
    replacement = AsyncMock()
    replacement.call_tool = AsyncMock(return_value=CallToolResult(content=[], isError=False))
    sessions = iter([old_session, replacement])

    def create_session(*_args, **_kwargs):
        session = next(sessions)
        context_manager = MagicMock()
        context_manager.__aenter__ = AsyncMock(return_value=session)
        context_manager.__aexit__ = AsyncMock(return_value=False)
        return context_manager

    class Args(BaseModel):
        value: int = Field(..., description="value")

    original_tool = StructuredTool(
        name="srv_act",
        description="test",
        args_schema=Args,
        coroutine=AsyncMock(),
        response_format="content_and_artifact",
    )
    pool = get_session_pool()

    with (
        patch("deerflow.mcp.tools.get_paths", return_value=Paths(tmp_path)),
        patch("langchain_mcp_adapters.sessions.create_session", side_effect=create_session),
    ):
        wrapped = _make_session_pool_tool(
            original_tool,
            "srv",
            {"transport": "stdio", "command": "x", "args": []},
        )
        first_call = asyncio.create_task(wrapped.coroutine(value=1))
        late_call = asyncio.create_task(wrapped.coroutine(value=2))
        await asyncio.wait_for(both_started.wait(), timeout=1)

        first_failure.set()
        with pytest.raises(anyio.ClosedResourceError):
            await first_call

        await wrapped.coroutine(value=3)
        late_failure.set()
        with pytest.raises(anyio.ClosedResourceError):
            await late_call

    assert pool._entries[("srv", "test-user-autouse:default")][0] is replacement
    await pool.close_all()


@pytest.mark.asyncio
async def test_session_pool_tool_wrapping():
    """The wrapper tool delegates to a pool-managed session."""
    # Build a dummy StructuredTool (as returned by langchain-mcp-adapters).
    from langchain_core.tools import StructuredTool
    from pydantic import BaseModel, Field

    from deerflow.mcp.tools import _make_session_pool_tool

    class Args(BaseModel):
        url: str = Field(..., description="url")

    original_tool = StructuredTool(
        name="playwright_navigate",
        description="Navigate browser",
        args_schema=Args,
        coroutine=AsyncMock(),
        response_format="content_and_artifact",
    )

    mock_session = AsyncMock()
    mock_session.call_tool = AsyncMock(return_value=MagicMock(content=[], isError=False, structuredContent=None))
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    connection = {"transport": "stdio", "command": "pw", "args": []}

    with patch("langchain_mcp_adapters.sessions.create_session", return_value=mock_cm):
        wrapped = _make_session_pool_tool(original_tool, "playwright", connection)

        # Simulate a tool call with a runtime context containing thread_id.
        mock_runtime = MagicMock()
        mock_runtime.context = {"thread_id": "thread-42"}
        mock_runtime.config = {}

        await wrapped.coroutine(runtime=mock_runtime, url="https://example.com")

    mock_session.call_tool.assert_awaited_once_with("navigate", {"url": "https://example.com"})


@pytest.mark.asyncio
async def test_session_pool_tool_pins_cwd_and_temp_env(tmp_path):
    """Stdio MCP subprocesses should write relative and temp outputs under user-data."""
    from langchain_core.tools import StructuredTool
    from pydantic import BaseModel, Field

    from deerflow.config.paths import Paths
    from deerflow.constants import MCP_TMP_SUBDIR
    from deerflow.mcp.tools import _make_session_pool_tool

    class Args(BaseModel):
        url: str = Field(..., description="url")

    original_tool = StructuredTool(
        name="playwright_navigate",
        description="Navigate browser",
        args_schema=Args,
        coroutine=AsyncMock(),
        response_format="content_and_artifact",
    )

    mock_session = AsyncMock()
    mock_session.call_tool = AsyncMock(return_value=MagicMock(content=[], isError=False, structuredContent=None))
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    paths = Paths(tmp_path)
    connection = {"transport": "stdio", "command": "pw", "args": [], "env": {"KEEP": "1"}}
    mock_runtime = MagicMock()
    mock_runtime.context = {"thread_id": "thread-42", "user_id": "user-7"}
    mock_runtime.config = {}

    with (
        patch("deerflow.mcp.tools.get_paths", return_value=paths),
        patch("langchain_mcp_adapters.sessions.create_session", return_value=mock_cm) as create_session,
    ):
        wrapped = _make_session_pool_tool(original_tool, "playwright", connection)
        await wrapped.coroutine(runtime=mock_runtime, url="https://example.com")

    session_connection = create_session.call_args.args[0]
    workspace = paths.sandbox_work_dir("thread-42", user_id="user-7")
    tmp_dir = workspace / MCP_TMP_SUBDIR

    assert session_connection["cwd"] == str(workspace)
    assert session_connection["env"]["KEEP"] == "1"
    assert session_connection["env"]["TMPDIR"] == str(tmp_dir)
    assert session_connection["env"]["TMP"] == str(tmp_dir)
    assert session_connection["env"]["TEMP"] == str(tmp_dir)
    assert tmp_dir.is_dir()
    assert stat.S_IMODE(tmp_dir.stat().st_mode) == 0o700


@pytest.mark.asyncio
async def test_session_pool_tool_does_not_override_explicit_tmpdir(tmp_path):
    """An operator-provided TMPDIR must win over our injected default."""
    from langchain_core.tools import StructuredTool
    from pydantic import BaseModel, Field

    from deerflow.config.paths import Paths
    from deerflow.constants import MCP_TMP_SUBDIR
    from deerflow.mcp.tools import _make_session_pool_tool

    class Args(BaseModel):
        url: str = Field(..., description="url")

    original_tool = StructuredTool(
        name="playwright_navigate",
        description="Navigate browser",
        args_schema=Args,
        coroutine=AsyncMock(),
        response_format="content_and_artifact",
    )

    mock_session = AsyncMock()
    mock_session.call_tool = AsyncMock(return_value=MagicMock(content=[], isError=False, structuredContent=None))
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    paths = Paths(tmp_path)
    connection = {"transport": "stdio", "command": "pw", "args": [], "env": {"TMPDIR": "/operator/tmp"}}
    mock_runtime = MagicMock()
    mock_runtime.context = {"thread_id": "thread-42", "user_id": "user-7"}
    mock_runtime.config = {}

    with (
        patch("deerflow.mcp.tools.get_paths", return_value=paths),
        patch("langchain_mcp_adapters.sessions.create_session", return_value=mock_cm) as create_session,
    ):
        wrapped = _make_session_pool_tool(original_tool, "playwright", connection)
        await wrapped.coroutine(runtime=mock_runtime, url="https://example.com")

    session_connection = create_session.call_args.args[0]
    # Operator-provided TMPDIR is preserved; TMP/TEMP still get our default.
    assert session_connection["env"]["TMPDIR"] == "/operator/tmp"
    assert session_connection["env"]["TMP"].endswith(MCP_TMP_SUBDIR)


@pytest.mark.asyncio
async def test_session_pool_tool_does_not_override_explicit_cwd(tmp_path):
    """An operator-provided cwd must win over our injected workspace default."""
    from langchain_core.tools import StructuredTool
    from pydantic import BaseModel, Field

    from deerflow.config.paths import Paths
    from deerflow.constants import MCP_TMP_SUBDIR
    from deerflow.mcp.tools import _make_session_pool_tool

    class Args(BaseModel):
        url: str = Field(..., description="url")

    original_tool = StructuredTool(
        name="playwright_navigate",
        description="Navigate browser",
        args_schema=Args,
        coroutine=AsyncMock(),
        response_format="content_and_artifact",
    )

    mock_session = AsyncMock()
    mock_session.call_tool = AsyncMock(return_value=MagicMock(content=[], isError=False, structuredContent=None))
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    operator_cwd = str(tmp_path / "operator-cwd")
    paths = Paths(tmp_path)
    connection = {"transport": "stdio", "command": "pw", "args": [], "cwd": operator_cwd}
    mock_runtime = MagicMock()
    mock_runtime.context = {"thread_id": "thread-42", "user_id": "user-7"}
    mock_runtime.config = {}

    with (
        patch("deerflow.mcp.tools.get_paths", return_value=paths),
        patch("langchain_mcp_adapters.sessions.create_session", return_value=mock_cm) as create_session,
    ):
        wrapped = _make_session_pool_tool(original_tool, "playwright", connection)
        await wrapped.coroutine(runtime=mock_runtime, url="https://example.com")

    session_connection = create_session.call_args.args[0]
    workspace = paths.sandbox_work_dir("thread-42", user_id="user-7")
    tmp_dir = workspace / MCP_TMP_SUBDIR

    assert session_connection["cwd"] == operator_cwd
    assert session_connection["env"]["TMPDIR"] == str(tmp_dir)


@pytest.mark.asyncio
async def test_session_pool_tool_skips_fs_work_for_non_stdio_transport(tmp_path):
    """SSE/HTTP transports must not get a pinned cwd/temp env or workspace dirs."""
    from langchain_core.tools import StructuredTool
    from pydantic import BaseModel, Field

    from deerflow.config.paths import Paths
    from deerflow.mcp.tools import _make_session_pool_tool

    class Args(BaseModel):
        url: str = Field(..., description="url")

    original_tool = StructuredTool(
        name="srv_act",
        description="test",
        args_schema=Args,
        coroutine=AsyncMock(),
        response_format="content_and_artifact",
    )

    mock_session = AsyncMock()
    mock_session.call_tool = AsyncMock(return_value=MagicMock(content=[], isError=False, structuredContent=None))
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    paths = Paths(tmp_path)
    connection = {"transport": "sse", "url": "http://localhost:9000/sse", "env": {"KEEP": "1"}}
    mock_runtime = MagicMock()
    mock_runtime.context = {"thread_id": "thread-42", "user_id": "user-7"}
    mock_runtime.config = {}

    with (
        patch("deerflow.mcp.tools.get_paths", return_value=paths) as get_paths,
        patch("langchain_mcp_adapters.sessions.create_session", return_value=mock_cm) as create_session,
    ):
        wrapped = _make_session_pool_tool(original_tool, "srv", connection)
        await wrapped.coroutine(runtime=mock_runtime, url="https://example.com")

    session_connection = create_session.call_args.args[0]
    assert "cwd" not in session_connection
    assert session_connection["env"] == {"KEEP": "1"}
    # No filesystem work at all: get_paths() is never consulted and no thread
    # workspace directory is created for non-stdio transports.
    get_paths.assert_not_called()
    assert not paths.sandbox_work_dir("thread-42", user_id="user-7").exists()


@pytest.mark.asyncio
async def test_session_pool_tool_skips_after_walk_when_no_text_content(tmp_path):
    """With no text content to rewrite, the post-call snapshot diff must be skipped."""
    from langchain_core.tools import StructuredTool
    from pydantic import BaseModel, Field

    from deerflow.config.paths import Paths
    from deerflow.mcp.tools import _make_session_pool_tool

    class Args(BaseModel):
        url: str = Field(..., description="url")

    original_tool = StructuredTool(
        name="playwright_navigate",
        description="Navigate browser",
        args_schema=Args,
        coroutine=AsyncMock(),
        response_format="content_and_artifact",
    )

    # An image-only result carries no text, so bare-filename correlation has
    # nothing to do and the second recursive walk should not run.
    from mcp.types import ImageContent

    image_result = MagicMock(content=[ImageContent(type="image", data="QUJD", mimeType="image/png")], isError=False, structuredContent=None)
    mock_session = AsyncMock()
    mock_session.call_tool = AsyncMock(return_value=image_result)
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    paths = Paths(tmp_path)
    connection = {"transport": "stdio", "command": "pw", "args": []}
    mock_runtime = MagicMock()
    mock_runtime.context = {"thread_id": "thread-42", "user_id": "user-7"}
    mock_runtime.config = {}

    with (
        patch("deerflow.mcp.tools.get_paths", return_value=paths),
        patch("langchain_mcp_adapters.sessions.create_session", return_value=mock_cm),
        patch("deerflow.mcp.tools._changed_workspace_files") as changed_files,
    ):
        wrapped = _make_session_pool_tool(original_tool, "playwright", connection)
        await wrapped.coroutine(runtime=mock_runtime, url="https://example.com")

    changed_files.assert_not_called()


@pytest.mark.asyncio
async def test_session_pool_tool_runs_after_walk_when_text_content_present(tmp_path):
    """A text result must trigger the post-call snapshot diff for path rewriting."""
    from langchain_core.tools import StructuredTool
    from pydantic import BaseModel, Field

    from deerflow.config.paths import Paths
    from deerflow.mcp.tools import _make_session_pool_tool

    class Args(BaseModel):
        url: str = Field(..., description="url")

    original_tool = StructuredTool(
        name="playwright_navigate",
        description="Navigate browser",
        args_schema=Args,
        coroutine=AsyncMock(),
        response_format="content_and_artifact",
    )

    from mcp.types import TextContent

    text_result = MagicMock(content=[TextContent(type="text", text="Saved as shot.png")], isError=False, structuredContent=None)
    mock_session = AsyncMock()
    mock_session.call_tool = AsyncMock(return_value=text_result)
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    paths = Paths(tmp_path)
    connection = {"transport": "stdio", "command": "pw", "args": []}
    mock_runtime = MagicMock()
    mock_runtime.context = {"thread_id": "thread-42", "user_id": "user-7"}
    mock_runtime.config = {}

    with (
        patch("deerflow.mcp.tools.get_paths", return_value=paths),
        patch("langchain_mcp_adapters.sessions.create_session", return_value=mock_cm),
        patch("deerflow.mcp.tools._changed_workspace_files", return_value=[]) as changed_files,
    ):
        wrapped = _make_session_pool_tool(original_tool, "playwright", connection)
        await wrapped.coroutine(runtime=mock_runtime, url="https://example.com")

    changed_files.assert_called_once()


@pytest.mark.asyncio
async def test_session_pool_tool_forwards_interceptor_headers():
    """Regression for PR #3294: when an interceptor sets ``request.headers``, the
    pooled stdio call must forward them via ``meta={"headers": ...}`` so downstream
    MCP servers can read auth/context headers.
    """
    from langchain_core.tools import StructuredTool
    from pydantic import BaseModel, Field

    from deerflow.mcp.tools import _make_session_pool_tool

    class Args(BaseModel):
        x: int = Field(..., description="x")

    original_tool = StructuredTool(
        name="srv_act",
        description="test",
        args_schema=Args,
        coroutine=AsyncMock(),
        response_format="content_and_artifact",
    )

    mock_session = AsyncMock()
    mock_session.call_tool = AsyncMock(return_value=MagicMock(content=[], isError=False, structuredContent=None))
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    async def header_interceptor(request, handler):
        return await handler(request.override(headers={"X-User-Id": "u-42"}))

    with patch("langchain_mcp_adapters.sessions.create_session", return_value=mock_cm):
        wrapped = _make_session_pool_tool(
            original_tool,
            "srv",
            {"transport": "stdio", "command": "x", "args": []},
            tool_interceptors=[header_interceptor],
        )
        await wrapped.coroutine(runtime=None, x=1)

    mock_session.call_tool.assert_awaited_once_with("act", {"x": 1}, meta={"headers": {"X-User-Id": "u-42"}})


@pytest.mark.asyncio
async def test_session_pool_interceptor_reads_request_scoped_secret():
    """Interceptors can read request-scoped secrets from LangGraph context."""
    from langchain_core.tools import StructuredTool
    from pydantic import BaseModel, Field

    from deerflow.mcp.tools import _make_session_pool_tool

    class Args(BaseModel):
        x: int = Field(..., description="x")

    original_tool = StructuredTool(
        name="srv_act",
        description="test",
        args_schema=Args,
        coroutine=AsyncMock(),
        response_format="content_and_artifact",
    )

    mock_session = AsyncMock()
    mock_session.call_tool = AsyncMock(return_value=MagicMock(content=[], isError=False, structuredContent=None))
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    async def secret_header_interceptor(request, handler):
        from langgraph.config import get_config

        secrets = (get_config().get("context") or {}).get("secrets") or {}
        return await handler(request.override(headers={"Authorization": f"Bearer {secrets['MCP_AUTH_TOKEN']}"}))

    with (
        patch("langchain_mcp_adapters.sessions.create_session", return_value=mock_cm),
        patch(
            "langgraph.config.get_config",
            return_value={"context": {"secrets": {"MCP_AUTH_TOKEN": "nested-secret"}}},
        ),
    ):
        wrapped = _make_session_pool_tool(
            original_tool,
            "srv",
            {"transport": "stdio", "command": "x", "args": []},
            tool_interceptors=[secret_header_interceptor],
        )
        await wrapped.coroutine(runtime=None, x=1)

    mock_session.call_tool.assert_awaited_once_with(
        "act",
        {"x": 1},
        meta={"headers": {"Authorization": "Bearer nested-secret"}},
    )


@pytest.mark.asyncio
async def test_session_pool_tool_no_headers_omits_meta():
    """When no interceptor sets headers, the pooled call must not pass a ``meta``
    kwarg (falls back to the plain two-argument ``call_tool``).
    """
    from langchain_core.tools import StructuredTool
    from pydantic import BaseModel, Field

    from deerflow.mcp.tools import _make_session_pool_tool

    class Args(BaseModel):
        x: int = Field(..., description="x")

    original_tool = StructuredTool(
        name="srv_act",
        description="test",
        args_schema=Args,
        coroutine=AsyncMock(),
        response_format="content_and_artifact",
    )

    mock_session = AsyncMock()
    mock_session.call_tool = AsyncMock(return_value=MagicMock(content=[], isError=False, structuredContent=None))
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    async def passthrough_interceptor(request, handler):
        return await handler(request)

    with patch("langchain_mcp_adapters.sessions.create_session", return_value=mock_cm):
        wrapped = _make_session_pool_tool(
            original_tool,
            "srv",
            {"transport": "stdio", "command": "x", "args": []},
            tool_interceptors=[passthrough_interceptor],
        )
        await wrapped.coroutine(runtime=None, x=1)

    mock_session.call_tool.assert_awaited_once_with("act", {"x": 1})


@pytest.mark.asyncio
async def test_session_pool_tool_ignores_unsupported_header_type(caplog):
    """Defensive path: non-mapping truthy headers should be ignored safely."""
    from langchain_core.tools import StructuredTool
    from pydantic import BaseModel, Field

    from deerflow.mcp.tools import _make_session_pool_tool

    class Args(BaseModel):
        x: int = Field(..., description="x")

    class TruthyHeaders:
        def __bool__(self) -> bool:
            return True

    original_tool = StructuredTool(
        name="srv_act",
        description="test",
        args_schema=Args,
        coroutine=AsyncMock(),
        response_format="content_and_artifact",
    )

    mock_session = AsyncMock()
    mock_session.call_tool = AsyncMock(return_value=MagicMock(content=[], isError=False, structuredContent=None))
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    async def invalid_header_interceptor(request, handler):
        return await handler(request.override(headers=TruthyHeaders()))

    with patch("langchain_mcp_adapters.sessions.create_session", return_value=mock_cm):
        wrapped = _make_session_pool_tool(
            original_tool,
            "srv",
            {"transport": "stdio", "command": "x", "args": []},
            tool_interceptors=[invalid_header_interceptor],
        )
        await wrapped.coroutine(runtime=None, x=1)

    mock_session.call_tool.assert_awaited_once_with("act", {"x": 1})
    assert "unsupported type" in caplog.text


@pytest.mark.asyncio
async def test_session_pool_tool_extracts_thread_id():
    """Thread ID is extracted from runtime.config when not in context."""
    from langchain_core.tools import StructuredTool
    from pydantic import BaseModel, Field

    from deerflow.mcp.tools import _make_session_pool_tool

    class Args(BaseModel):
        x: int = Field(..., description="x")

    original_tool = StructuredTool(
        name="server_tool",
        description="test",
        args_schema=Args,
        coroutine=AsyncMock(),
        response_format="content_and_artifact",
    )

    mock_session = AsyncMock()
    mock_session.call_tool = AsyncMock(return_value=MagicMock(content=[], isError=False, structuredContent=None))
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("langchain_mcp_adapters.sessions.create_session", return_value=mock_cm):
        wrapped = _make_session_pool_tool(original_tool, "server", {"transport": "stdio", "command": "x", "args": []})

        mock_runtime = MagicMock()
        mock_runtime.context = {}
        mock_runtime.config = {"configurable": {"thread_id": "from-config"}}

        await wrapped.coroutine(runtime=mock_runtime, x=1)

    # Verify the session was created with the correct scope key.
    # The scope key is "{user_id}:{thread_id}"; the autouse fixture sets
    # the effective user to "test-user-autouse".
    pool = get_session_pool()
    assert ("server", "test-user-autouse:from-config") in pool._entries


@pytest.mark.asyncio
async def test_session_pool_tool_default_scope():
    """When no thread_id is available, 'default' is used as scope key."""
    from langchain_core.tools import StructuredTool
    from pydantic import BaseModel, Field

    from deerflow.mcp.tools import _make_session_pool_tool

    class Args(BaseModel):
        x: int = Field(..., description="x")

    original_tool = StructuredTool(
        name="server_tool",
        description="test",
        args_schema=Args,
        coroutine=AsyncMock(),
        response_format="content_and_artifact",
    )

    mock_session = AsyncMock()
    mock_session.call_tool = AsyncMock(return_value=MagicMock(content=[], isError=False, structuredContent=None))
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("langchain_mcp_adapters.sessions.create_session", return_value=mock_cm):
        wrapped = _make_session_pool_tool(original_tool, "server", {"transport": "stdio", "command": "x", "args": []})

        # No thread_id in runtime at all.
        await wrapped.coroutine(runtime=None, x=1)

    pool = get_session_pool()
    assert ("server", "test-user-autouse:default") in pool._entries


@pytest.mark.asyncio
async def test_session_pool_tool_get_config_fallback():
    """When runtime is None, get_config() provides thread_id as fallback."""
    from langchain_core.tools import StructuredTool
    from pydantic import BaseModel, Field

    from deerflow.mcp.tools import _make_session_pool_tool

    class Args(BaseModel):
        x: int = Field(..., description="x")

    original_tool = StructuredTool(
        name="server_tool",
        description="test",
        args_schema=Args,
        coroutine=AsyncMock(),
        response_format="content_and_artifact",
    )

    mock_session = AsyncMock()
    mock_session.call_tool = AsyncMock(return_value=MagicMock(content=[], isError=False, structuredContent=None))
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    fake_config = {"configurable": {"thread_id": "from-langgraph-config"}}

    with (
        patch("langchain_mcp_adapters.sessions.create_session", return_value=mock_cm),
        patch("deerflow.mcp.tools.get_config", return_value=fake_config),
    ):
        wrapped = _make_session_pool_tool(original_tool, "server", {"transport": "stdio", "command": "x", "args": []})

        # runtime=None — get_config() fallback should provide thread_id
        await wrapped.coroutine(runtime=None, x=1)

    pool = get_session_pool()
    assert ("server", "test-user-autouse:from-langgraph-config") in pool._entries


def test_session_pool_tool_sync_wrapper_path_is_safe():
    """Sync wrapper (tool.func) invocation doesn't crash on cross-loop access."""
    from langchain_core.tools import StructuredTool
    from pydantic import BaseModel, Field

    from deerflow.mcp.tools import _make_session_pool_tool
    from deerflow.tools.sync import make_sync_tool_wrapper

    class Args(BaseModel):
        url: str = Field(..., description="url")

    original_tool = StructuredTool(
        name="playwright_navigate",
        description="Navigate browser",
        args_schema=Args,
        coroutine=AsyncMock(),
        response_format="content_and_artifact",
    )

    mock_session = AsyncMock()
    mock_session.call_tool = AsyncMock(return_value=MagicMock(content=[], isError=False, structuredContent=None))
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    connection = {"transport": "stdio", "command": "pw", "args": []}

    with patch("langchain_mcp_adapters.sessions.create_session", return_value=mock_cm):
        wrapped = _make_session_pool_tool(original_tool, "playwright", connection)
        # Attach the sync wrapper exactly as get_mcp_tools() does.
        wrapped.func = make_sync_tool_wrapper(wrapped.coroutine, wrapped.name)

        # Call via the sync path (asyncio.run in a worker thread).
        # runtime is not supplied so _extract_thread_id falls back to "default".
        wrapped.func(url="https://example.com")

    mock_session.call_tool.assert_called_once_with("navigate", {"url": "https://example.com"})


# ---------------------------------------------------------------------------
# get_mcp_tools: HTTP transport should NOT be pooled
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_transport_tools_not_pooled():
    """HTTP/SSE transport tools should NOT be wrapped with the session pool."""
    from langchain_core.tools import StructuredTool
    from pydantic import BaseModel, Field

    from deerflow.mcp.tools import get_mcp_tools

    class Args(BaseModel):
        query: str = Field(..., description="query")

    http_tool = StructuredTool(
        name="myserver_search",
        description="Search tool",
        args_schema=Args,
        coroutine=AsyncMock(),
        response_format="content_and_artifact",
    )

    stdio_tool = StructuredTool(
        name="playwright_navigate",
        description="Navigate browser",
        args_schema=Args,
        coroutine=AsyncMock(),
        response_format="content_and_artifact",
    )

    mock_session = AsyncMock()
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    extensions_config = MagicMock()
    extensions_config.get_enabled_mcp_servers.return_value = {
        "myserver": MagicMock(type="http", url="http://localhost:8000/mcp", headers=None, command=None, args=[], env=None),
        "playwright": MagicMock(type="stdio", command="npx", args=["-y", "@anthropic/mcp-server-playwright"], env=None, url=None, headers=None),
    }
    extensions_config.model_extra = {}

    servers_config = {
        "myserver": {"transport": "http", "url": "http://localhost:8000/mcp"},
        "playwright": {"transport": "stdio", "command": "npx", "args": ["-y", "@anthropic/mcp-server-playwright"]},
    }

    with (
        patch("deerflow.mcp.tools.ExtensionsConfig.from_file", return_value=extensions_config),
        patch("deerflow.mcp.tools.build_servers_config", return_value=servers_config),
        patch("deerflow.mcp.tools.get_initial_oauth_headers", return_value={}),
        patch("deerflow.mcp.tools.build_oauth_tool_interceptor", return_value=None),
        patch("langchain_mcp_adapters.client.MultiServerMCPClient") as MockClient,
        patch("langchain_mcp_adapters.sessions.create_session", return_value=mock_cm),
    ):
        mock_client_instance = MockClient.return_value

        async def get_tools_for_server(*, server_name: str | None = None):
            if server_name == "myserver":
                return [http_tool]
            if server_name == "playwright":
                return [stdio_tool]
            raise AssertionError(f"unexpected server_name: {server_name}")

        mock_client_instance.get_tools = AsyncMock(side_effect=get_tools_for_server)

        tools = await get_mcp_tools()

    pool = get_session_pool()
    # Tool discovery is lazy: no pooled sessions are created until a wrapped tool is invoked.
    assert list(pool._entries.keys()) == []

    # Verify the HTTP tool was NOT wrapped with the pool (it's the original tool).
    http_tools = [t for t in tools if t.name == "myserver_search"]
    assert len(http_tools) == 1
    assert http_tools[0].coroutine is http_tool.coroutine

    # Verify the stdio tool WAS wrapped with the pool.
    stdio_tools = [t for t in tools if t.name == "playwright_navigate"]
    assert len(stdio_tools) == 1
    assert stdio_tools[0].coroutine is not stdio_tool.coroutine


@pytest.mark.asyncio
async def test_non_stdio_tool_call_timeout_warns_that_it_is_ignored(caplog):
    """HTTP/SSE servers should not silently ignore stdio-only tool_call_timeout."""
    from langchain_core.tools import StructuredTool
    from pydantic import BaseModel, Field

    from deerflow.config.extensions_config import McpServerConfig
    from deerflow.mcp.tools import get_mcp_tools

    class Args(BaseModel):
        query: str = Field(..., description="query")

    http_tool = StructuredTool(
        name="remote_search",
        description="Search tool",
        args_schema=Args,
        coroutine=AsyncMock(),
        response_format="content_and_artifact",
    )

    server_cfg = McpServerConfig(
        type="http",
        url="https://example.com/mcp",
        tool_call_timeout=30.0,
    )
    extensions_config = MagicMock()
    extensions_config.get_enabled_mcp_servers.return_value = {"remote": server_cfg}
    extensions_config.mcp_servers = {"remote": server_cfg}
    extensions_config.model_extra = {}

    servers_config = {
        "remote": {"transport": "http", "url": "https://example.com/mcp"},
    }

    with (
        patch("deerflow.mcp.tools.ExtensionsConfig.from_file", return_value=extensions_config),
        patch("deerflow.mcp.tools.build_servers_config", return_value=servers_config),
        patch("deerflow.mcp.tools.get_initial_oauth_headers", return_value={}),
        patch("deerflow.mcp.tools.build_oauth_tool_interceptor", return_value=None),
        patch("langchain_mcp_adapters.client.MultiServerMCPClient") as MockClient,
        caplog.at_level(logging.WARNING, logger="deerflow.mcp.tools"),
    ):
        mock_client_instance = MockClient.return_value
        mock_client_instance.get_tools = AsyncMock(return_value=[http_tool])

        tools = await get_mcp_tools()

    assert tools == [http_tool]
    assert any(record.levelno == logging.WARNING and "remote" in record.getMessage() and "tool_call_timeout" in record.getMessage() and "stdio" in record.getMessage() for record in caplog.records)


# ---------------------------------------------------------------------------
# Regression for PR #3843: tool_call_timeout must not leak into connection dict
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stdio_tool_call_timeout_does_not_raise_typeerror():
    """A stdio server with tool_call_timeout must load tools without TypeError.

    The timeout must be read from McpServerConfig (extensions_config), NOT from
    the connection dict that langchain's create_session receives.  If it leaks
    into the connection dict, _create_stdio_session() raises TypeError.
    Regression for PR #3843 P1 bug.
    """
    from langchain_core.tools import StructuredTool
    from pydantic import BaseModel, Field

    from deerflow.config.extensions_config import McpServerConfig
    from deerflow.mcp.tools import get_mcp_tools

    class Args(BaseModel):
        query: str = Field(..., description="query")

    stdio_tool = StructuredTool(
        name="biomcp_search",
        description="Search biomedical data",
        args_schema=Args,
        coroutine=AsyncMock(),
        response_format="content_and_artifact",
    )

    mock_session = AsyncMock()
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    # Use real McpServerConfig so tool_call_timeout is a real field value,
    # not a MagicMock that might accidentally work.
    server_cfg = McpServerConfig(
        type="stdio",
        command="biomcp",
        args=["serve"],
        tool_call_timeout=60.0,
    )

    extensions_config = MagicMock()
    extensions_config.get_enabled_mcp_servers.return_value = {"biomcp": server_cfg}
    extensions_config.mcp_servers = {"biomcp": server_cfg}
    extensions_config.model_extra = {}

    # Connection dict must NOT contain tool_call_timeout — this is the key assertion.
    servers_config = {
        "biomcp": {"transport": "stdio", "command": "biomcp", "args": ["serve"]},
    }

    with (
        patch("deerflow.mcp.tools.ExtensionsConfig.from_file", return_value=extensions_config),
        patch("deerflow.mcp.tools.build_servers_config", return_value=servers_config),
        patch("deerflow.mcp.tools.get_initial_oauth_headers", return_value={}),
        patch("deerflow.mcp.tools.build_oauth_tool_interceptor", return_value=None),
        patch("langchain_mcp_adapters.client.MultiServerMCPClient") as MockClient,
        patch("langchain_mcp_adapters.sessions.create_session", return_value=mock_cm),
    ):
        mock_client_instance = MockClient.return_value
        mock_client_instance.get_tools = AsyncMock(return_value=[stdio_tool])

        # This must NOT raise TypeError from _create_stdio_session()
        tools = await get_mcp_tools()

    assert len(tools) == 1
    # The tool should be wrapped with session pool (it's stdio)
    assert tools[0].coroutine is not stdio_tool.coroutine

    # Verify the connection dict passed to the pool does NOT contain tool_call_timeout
    assert "tool_call_timeout" not in servers_config["biomcp"]


# ---------------------------------------------------------------------------
# Regression for #3379: cancel scope must be exited in the entering task
# ---------------------------------------------------------------------------


class _CancelScopeCm:
    """Fake session context manager that mimics anyio's cancel-scope rule.

    ``ClientSession`` is built on an anyio task group, which requires the cancel
    scope to be exited from the *same asyncio task* that entered it. This fake
    records the task that runs ``__aenter__`` and raises the exact RuntimeError
    anyio would raise if ``__aexit__`` runs in a different task — reproducing the
    crash reported in GitHub issue #3379.
    """

    def __init__(self) -> None:
        self.enter_task: object | None = None
        self.closed = False

    async def __aenter__(self):
        self.enter_task = asyncio.current_task()
        return AsyncMock()

    async def __aexit__(self, *args):
        if asyncio.current_task() is not self.enter_task:
            raise RuntimeError("Attempted to exit cancel scope in a different task than it was entered in")
        self.closed = True
        return False


async def _get_session_in_own_task(pool, *args):
    """Create a pooled session from a *dedicated* child task.

    In production every stdio session is entered from its own short-lived task
    (the sync-tool path runs each call through a fresh ``asyncio.run``). This
    helper reproduces that so the close paths are exercised from a *different*
    task than the one that entered the session — the exact condition that
    triggered #3379.
    """
    return await asyncio.create_task(pool.get_session(*args))


@pytest.mark.asyncio
async def test_close_all_does_not_cross_tasks():
    """close_all must not raise the cross-task cancel-scope RuntimeError (#3379)."""
    pool = MCPSessionPool()
    cms: list[_CancelScopeCm] = []

    def make_cm(*a, **kw):
        cm = _CancelScopeCm()
        cms.append(cm)
        return cm

    with patch("langchain_mcp_adapters.sessions.create_session", side_effect=make_cm):
        await _get_session_in_own_task(pool, "s1", "t1", {"transport": "stdio", "command": "x", "args": []})
        await _get_session_in_own_task(pool, "s2", "t2", {"transport": "stdio", "command": "x", "args": []})

    # close_all runs in this task, which is *not* the task that entered either
    # session. The owner task must perform __aexit__ so each CM closes cleanly.
    await pool.close_all()

    assert all(cm.closed for cm in cms)
    assert len(pool._entries) == 0


@pytest.mark.asyncio
async def test_close_scope_does_not_cross_tasks():
    """close_scope must respect the same-task cancel-scope rule (#3379)."""
    pool = MCPSessionPool()
    cms: list[_CancelScopeCm] = []

    def make_cm(*a, **kw):
        cm = _CancelScopeCm()
        cms.append(cm)
        return cm

    with patch("langchain_mcp_adapters.sessions.create_session", side_effect=make_cm):
        await _get_session_in_own_task(pool, "s", "t1", {"transport": "stdio", "command": "x", "args": []})
        await _get_session_in_own_task(pool, "s", "t2", {"transport": "stdio", "command": "x", "args": []})

    await pool.close_scope("t1")

    assert cms[0].closed is True
    assert cms[1].closed is False
    assert ("s", "t2") in pool._entries


@pytest.mark.asyncio
async def test_lru_eviction_does_not_cross_tasks():
    """LRU eviction must close the victim without a cross-task RuntimeError (#3379)."""
    pool = MCPSessionPool()
    pool.MAX_SESSIONS = 2
    cms: list[_CancelScopeCm] = []

    def make_cm(*a, **kw):
        cm = _CancelScopeCm()
        cms.append(cm)
        return cm

    with patch("langchain_mcp_adapters.sessions.create_session", side_effect=make_cm):
        await _get_session_in_own_task(pool, "s", "t1", {"transport": "stdio", "command": "x", "args": []})
        await _get_session_in_own_task(pool, "s", "t2", {"transport": "stdio", "command": "x", "args": []})
        # Adding t3 evicts t1 — its own owner task must run __aexit__, even
        # though the eviction is driven from t3's get_session call.
        await _get_session_in_own_task(pool, "s", "t3", {"transport": "stdio", "command": "x", "args": []})

    assert cms[0].closed is True
    assert cms[1].closed is False
    assert cms[2].closed is False


def test_close_all_sync_across_loops_does_not_cross_tasks():
    """close_all_sync, the path hit by the sync tool wrapper, must close sessions
    created in earlier (now-finished) asyncio.run loops without crashing (#3379).
    """
    pool = MCPSessionPool()
    cms: list[_CancelScopeCm] = []

    def make_cm(*a, **kw):
        cm = _CancelScopeCm()
        cms.append(cm)
        return cm

    with patch("langchain_mcp_adapters.sessions.create_session", side_effect=make_cm):
        # Simulate the sync-tool path: a session created inside one short-lived
        # event loop, then a second one in a different loop.
        asyncio.run(pool.get_session("s", "t1", {"transport": "stdio", "command": "x", "args": []}))
        asyncio.run(pool.get_session("s", "t2", {"transport": "stdio", "command": "x", "args": []}))

    # The owning loops are already closed; close_all_sync must not raise.
    pool.close_all_sync()

    assert len(pool._entries) == 0


def test_get_session_replaces_session_from_closed_loop():
    """A pooled session whose owning loop has closed is evicted and recreated."""
    pool = MCPSessionPool()
    cms: list[_CancelScopeCm] = []

    def make_cm(*a, **kw):
        cm = _CancelScopeCm()
        cms.append(cm)
        return cm

    with patch("langchain_mcp_adapters.sessions.create_session", side_effect=make_cm):
        # First session created in a throwaway loop that is torn down by
        # asyncio.run (mirrors the sync-tool path). asyncio.run cancels the
        # pending owner task and runs its __aexit__ on the same loop.
        asyncio.run(pool.get_session("s", "t1", {"transport": "stdio", "command": "x", "args": []}))
        assert ("s", "t1") in pool._entries

        # Now request the same key from a fresh loop: the stale entry (closed
        # loop) must be evicted and replaced with a fresh session.
        session = asyncio.run(pool.get_session("s", "t1", {"transport": "stdio", "command": "x", "args": []}))

    assert session is not None
    assert len(cms) == 2
    assert pool._entries[("s", "t1")][0] is session


class _BlockingInitCm:
    """Fake session CM whose ``initialize`` blocks until released.

    Lets a test cancel ``get_session`` while the owner task is still
    initializing, reproducing the caller-cancellation window.
    """

    def __init__(self, gate: asyncio.Event) -> None:
        self._gate = gate
        self.entered = False
        self.closed = False

    async def __aenter__(self):
        self.entered = True
        session = MagicMock()
        session.initialize = self._initialize
        return session

    async def _initialize(self):
        await self._gate.wait()

    async def __aexit__(self, *args):
        self.closed = True
        return False


@pytest.mark.asyncio
async def test_get_session_cancelled_while_initializing_does_not_leak():
    """Cancelling get_session mid-init must not leak the owner task/session (#3379 CR).

    The session is not registered yet, so if cancellation skipped the cleanup
    the owner task would block forever on close_evt.wait() and the CM's
    __aexit__ would never run — an unreachable, unclosable session.
    """
    pool = MCPSessionPool()
    gate = asyncio.Event()
    cms: list[_BlockingInitCm] = []

    def make_cm(*a, **kw):
        cm = _BlockingInitCm(gate)
        cms.append(cm)
        return cm

    with patch("langchain_mcp_adapters.sessions.create_session", side_effect=make_cm):
        call = asyncio.create_task(pool.get_session("s", "t1", {"transport": "stdio", "command": "x", "args": []}))
        # Let the owner task enter the CM and reach the blocking initialize().
        await asyncio.sleep(0.01)
        call.cancel()
        with pytest.raises(asyncio.CancelledError):
            await call

        # Release initialize() so the owner task can finish its shutdown path.
        gate.set()
        # Give the owner task a chance to run __aexit__ and complete.
        for _ in range(10):
            if cms and cms[0].closed:
                break
            await asyncio.sleep(0.01)

    assert len(cms) == 1
    assert cms[0].entered is True
    assert cms[0].closed is True, "owner task must run __aexit__ after cancellation"
    assert len(pool._entries) == 0

    current = asyncio.current_task()
    leaked = [t for t in asyncio.all_tasks() if t is not current and not t.done() and "_run_session" in str(t.get_coro())]
    assert not leaked, "owner task must not be left pending after cancellation"


@pytest.mark.asyncio
async def test_get_session_cancelled_during_eviction_teardown_does_not_leak():
    """Cancelling get_session while it awaits an evicted session's teardown
    must not orphan the just-created owner task.

    The in-flight record and owner task are published before the Phase-2
    eviction awaits, so a caller cancelled there — routine, since both
    production call sites wrap get_session in asyncio.wait_for(
    session_init_timeout) — would otherwise leak the owner: it finishes
    initialize(), publishes ready, and blocks on close_evt forever, invisible
    to LRU eviction, which only scans _entries.
    """
    pool = MCPSessionPool()
    pool.MAX_SESSIONS = 1

    # A pre-registered LRU victim whose teardown hangs (wedged server): the
    # creator parks in Phase 2 awaiting it, so the cancel below is guaranteed
    # to land between publishing the in-flight record and Phase 3.
    victim_hang = asyncio.Event()

    async def victim_owner() -> None:
        await victim_hang.wait()

    loop = asyncio.get_running_loop()
    victim_task = asyncio.create_task(victim_owner())
    pool._entries[("victim", "scope")] = (MagicMock(), loop, victim_task, asyncio.Event())

    gate = asyncio.Event()
    cms: list[_BlockingInitCm] = []
    call: asyncio.Task | None = None

    def make_cm(*args, **kwargs):
        cm = _BlockingInitCm(gate)
        cms.append(cm)
        return cm

    try:
        with patch("langchain_mcp_adapters.sessions.create_session", side_effect=make_cm):
            call = asyncio.create_task(pool.get_session("srv", "scope-2", {"transport": "stdio", "command": "x", "args": []}))
            # The creator publishes its in-flight record before awaiting the
            # hung victim, so this is deterministic.
            for _ in range(100):
                if ("srv", "scope-2") in pool._inflight:
                    break
                await asyncio.sleep(0.01)
            assert ("srv", "scope-2") in pool._inflight
            await asyncio.sleep(0.02)

            call.cancel()
            # On the bug, the caller's cancellation is swallowed by the
            # eviction teardown and the task never finishes; the shield keeps
            # the timeout from cancelling it so the hang is observable.
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(asyncio.shield(call), timeout=5.0)

        # The orphaned owner must have been torn down: its __aexit__ ran even
        # though initialize() was never released.
        for _ in range(50):
            if cms and cms[0].closed:
                break
            await asyncio.sleep(0.01)
        assert cms, "owner task must have been created"
        assert cms[0].closed, "owner must run __aexit__ after Phase-2 cancellation"
        assert ("srv", "scope-2") not in pool._inflight

        current = asyncio.current_task()
        leaked = [t for t in asyncio.all_tasks() if t is not current and not t.done() and "_run_session" in str(t.get_coro())]
        assert not leaked, "owner task must not be left pending after Phase-2 cancellation"
    finally:
        if call is not None and not call.done():
            call.cancel()
        victim_hang.set()
        victim_task.cancel()
        try:
            await victim_task
        except BaseException:
            pass


@pytest.mark.asyncio
async def test_cancelled_creator_does_not_close_session_held_by_joiner():
    """Cancelling the creator must not close a session a joiner already holds.

    Reproduces the review race deterministically: MAX_SESSIONS=1, the creator
    parks in Phase 2 awaiting a hung LRU victim while its owner finishes
    initialize(); a second caller for the same key then receives the session.
    Cancelling the creator afterwards must leave that session open and
    registered — once the creation committed, the session is pool property
    (LRU eviction / close_* own it), never the cancelled caller's (#5008
    review).
    """
    pool = MCPSessionPool()
    pool.MAX_SESSIONS = 1

    # A pre-registered LRU victim whose teardown hangs: the creator parks in
    # Phase 2 awaiting it, so the cancel below lands while the creator is
    # between publishing the in-flight record and awaiting ready.
    victim_hang = asyncio.Event()

    async def victim_owner() -> None:
        await victim_hang.wait()

    loop = asyncio.get_running_loop()
    victim_task = asyncio.create_task(victim_owner())
    pool._entries[("victim", "scope")] = (MagicMock(), loop, victim_task, asyncio.Event())

    gate = asyncio.Event()
    cms: list[_BlockingInitCm] = []
    creator: asyncio.Task | None = None

    def make_cm(*args, **kwargs):
        cm = _BlockingInitCm(gate)
        cms.append(cm)
        return cm

    try:
        with patch("langchain_mcp_adapters.sessions.create_session", side_effect=make_cm):
            conn = {"transport": "stdio", "command": "x", "args": []}
            creator = asyncio.create_task(pool.get_session("srv", "scope-2", conn))
            # The creator publishes its in-flight record before awaiting the
            # hung victim, so this is deterministic.
            for _ in range(100):
                if ("srv", "scope-2") in pool._inflight:
                    break
                await asyncio.sleep(0.01)
            assert ("srv", "scope-2") in pool._inflight

            # The owner finishes initialize() and commits while its creator is
            # still parked on the victim's teardown. The second caller then
            # receives the initialized session (Phase 2b before this fix, the
            # _entries fast path after) — either way it now holds it.
            gate.set()
            joiner = asyncio.create_task(pool.get_session("srv", "scope-2", conn))
            session = await asyncio.wait_for(asyncio.shield(joiner), timeout=5.0)
            assert cms, "owner task must have been created"

            # On the bug, this unwind unconditionally shut the owner down even
            # though a joiner held the session: __aexit__ ran underneath it.
            creator.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(asyncio.shield(creator), timeout=5.0)

            await asyncio.sleep(0.02)
            assert not cms[0].closed, "cancelling the creator must not close a session already handed to a caller"
            assert ("srv", "scope-2") in pool._entries, "committed session must stay registered after creator cancellation"
            assert pool._entries[("srv", "scope-2")][0] is session, "the joiner's session must be the registered one"
            assert ("srv", "scope-2") not in pool._inflight

        # Cleanup: close the pool so the parked owner finishes deterministically.
        await pool.close_all()
        for _ in range(100):
            if cms[0].closed:
                break
            await asyncio.sleep(0.01)
        assert cms[0].closed, "owner must still tear down through the pool close paths"

        current = asyncio.current_task()
        leaked = [t for t in asyncio.all_tasks() if t is not current and not t.done() and "_run_session" in str(t.get_coro())]
        assert not leaked, "owner task must not be left pending after cleanup"
    finally:
        if creator is not None and not creator.done():
            creator.cancel()
        victim_hang.set()
        victim_task.cancel()
        try:
            await victim_task
        except BaseException:
            pass


@pytest.mark.asyncio
async def test_joiner_follows_creation_outcome_when_creator_is_cancelled():
    """A joiner must follow the creation's outcome, never hold an orphan.

    If the creator is cancelled while the shared owner is still initializing,
    the creation is aborted before it commits: the joiner fails with the same
    cancellation instead of receiving (or hanging on) a session whose teardown
    is already underway. Drift guard for the outcome-gated join semantics.
    """
    pool = MCPSessionPool()
    gate = asyncio.Event()
    cms: list[_BlockingInitCm] = []

    def make_cm(*a, **kw):
        cm = _BlockingInitCm(gate)
        cms.append(cm)
        return cm

    with patch("langchain_mcp_adapters.sessions.create_session", side_effect=make_cm):
        conn = {"transport": "stdio", "command": "x", "args": []}
        creator = asyncio.create_task(pool.get_session("s", "same", conn))
        for _ in range(100):
            if ("s", "same") in pool._inflight:
                break
            await asyncio.sleep(0.01)
        assert ("s", "same") in pool._inflight

        # Second caller joins the in-flight creation instead of duplicating it.
        joiner = asyncio.create_task(pool.get_session("s", "same", conn))
        await asyncio.sleep(0.01)

        # The creator is cancelled mid-init: the creation aborts, and the
        # joiner must observe that outcome rather than succeed or hang.
        creator.cancel()
        with pytest.raises(asyncio.CancelledError):
            await creator
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(asyncio.shield(joiner), timeout=5.0)

    assert len(cms) == 1, "the joiner must not have created a duplicate session"
    for _ in range(100):
        if cms[0].closed:
            break
        await asyncio.sleep(0.01)
    assert cms[0].closed, "aborted creation must still run its __aexit__"
    assert len(pool._entries) == 0
    assert len(pool._inflight) == 0

    current = asyncio.current_task()
    leaked = [t for t in asyncio.all_tasks() if t is not current and not t.done() and "_run_session" in str(t.get_coro())]
    assert not leaked, "owner task must not be left pending after the creation aborted"


@pytest.mark.asyncio
async def test_eviction_teardown_completes_normally_then_session_is_returned():
    """Non-cancelled path: eviction teardown runs to completion and the caller
    proceeds to Phase 3 unchanged — guards the Phase-2 try/except against
    happy-path drift."""
    pool = MCPSessionPool()
    pool.MAX_SESSIONS = 1

    class CmFactory:
        def __init__(self):
            self.closed = False

        async def __aenter__(self):
            return AsyncMock()

        async def __aexit__(self, *args):
            self.closed = True
            return False

    cms: list[CmFactory] = []

    def make_cm(*a, **kw):
        cm = CmFactory()
        cms.append(cm)
        return cm

    with patch("langchain_mcp_adapters.sessions.create_session", side_effect=make_cm):
        first = await pool.get_session("s", "t1", {"transport": "stdio", "command": "x", "args": []})
        # Pool is full (1): this call evicts t1 through Phase 2 and then
        # returns the fresh session through Phase 3/4.
        second = await pool.get_session("s", "t2", {"transport": "stdio", "command": "x", "args": []})

    assert first is not second
    assert cms[0].closed, "evicted owner must complete teardown before the caller proceeds"
    assert ("s", "t2") in pool._entries
    assert ("s", "t1") not in pool._entries


@pytest.mark.asyncio
async def test_close_scope_does_not_cancel_owner_already_unwinding_in_aexit():
    """A failed in-flight owner is already running __aexit__ in its own task;
    the close paths must not cancel it — the cancel would interrupt that
    in-task cleanup and the exit would never finish."""
    pool = MCPSessionPool()
    cms: list[_InitFailCm] = []

    def make_cm(*args, **kwargs):
        cm = _InitFailCm()
        cms.append(cm)
        return cm

    with patch("langchain_mcp_adapters.sessions.create_session", side_effect=make_cm):
        call = asyncio.create_task(pool.get_session("s", "t1", {"transport": "stdio", "command": "x", "args": []}))
        # Wait until the owner failed initialize() and entered its slow __aexit__.
        for _ in range(100):
            if cms and cms[0].exit_started:
                break
            await asyncio.sleep(0.01)
        assert cms and cms[0].exit_started, "owner must reach its slow __aexit__ first"

        await pool.close_scope("t1")

        with pytest.raises(RuntimeError):
            await call

    assert cms[0].closed is True, "close_scope must not cancel an owner already unwinding in __aexit__"


@pytest.mark.asyncio
async def test_cancelling_close_scope_does_not_strand_other_removed_owners():
    """Cancelling close_scope mid-teardown must not strand the other owners it
    already removed from the registry: every removed owner gets its close
    signal before any teardown is awaited."""
    pool = MCPSessionPool()
    loop = asyncio.get_running_loop()

    first_hang = asyncio.Event()  # first owner's slow teardown stand-in
    first_close = asyncio.Event()
    second_close = asyncio.Event()
    second_done = asyncio.Event()

    async def first_owner() -> None:
        await first_close.wait()
        await first_hang.wait()

    async def second_owner() -> None:
        await second_close.wait()
        second_done.set()

    first_task = asyncio.create_task(first_owner())
    second_task = asyncio.create_task(second_owner())
    pool._entries[("s1", "scope")] = (MagicMock(), loop, first_task, first_close)
    pool._entries[("s2", "scope")] = (MagicMock(), loop, second_task, second_close)

    closer = asyncio.create_task(pool.close_scope("scope"))
    # Let the closer reach its teardown await (both signals are already out).
    for _ in range(100):
        if first_close.is_set() and second_close.is_set():
            break
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.02)

    closer.cancel()
    with pytest.raises(asyncio.CancelledError):
        await closer

    assert second_close.is_set(), "every removed owner must be signalled before teardown awaits"
    for _ in range(100):
        if second_done.is_set():
            break
        await asyncio.sleep(0.01)
    assert second_done.is_set(), "the second owner must finish its own teardown"

    first_hang.set()
    first_task.cancel()
    try:
        await first_task
    except BaseException:
        pass


@pytest.mark.asyncio
async def test_owner_mid_aexit_survives_gc_after_closer_cancellation():
    """The reaper spawned for a cancelled closer must be strongly retained.

    The event loop holds only weak references to tasks, so an unheld reaper —
    and transitively the owner it awaits, mid-``__aexit__`` — can be
    garbage-collected before the teardown completes once the registry entry
    is gone (#5008 review). The closer scenario runs in its own dropped task
    so no harness frame (including the caught CancelledError's traceback)
    keeps the teardown alive."""
    pool = MCPSessionPool()

    class GcProneCm:
        def __init__(self):
            self.entered = False
            self.exit_started = False
            self.closed = False

        async def __aenter__(self):
            self.entered = True
            session = MagicMock()
            session.initialize = self._initialize
            return session

        async def _initialize(self):
            return None

        async def __aexit__(self, *args):
            self.exit_started = True
            # An orphaned future: nothing external references it, so the
            # awaiting owner forms a collectable cycle once no strong root
            # holds the reaper.
            await asyncio.get_running_loop().create_future()
            self.closed = True

    holder: dict[str, GcProneCm] = {}

    def make_cm(*args, **kwargs):
        cm = GcProneCm()
        holder["cm"] = cm
        return cm

    async def scenario() -> None:
        closer = asyncio.create_task(pool.close_scope("t1"))
        for _ in range(200):
            cm = cm_weak()
            if cm is not None and cm.exit_started:
                break
            await asyncio.sleep(0.01)
        closer.cancel()
        try:
            await closer
        except asyncio.CancelledError:
            pass

    with patch("langchain_mcp_adapters.sessions.create_session", side_effect=make_cm):
        await pool.get_session("s", "t1", {"transport": "stdio", "command": "x", "args": []})

    cm_weak = weakref.ref(holder["cm"])
    holder.clear()

    scen = asyncio.create_task(scenario())
    await scen
    del scen

    # Drop every remaining strong root and force collection: the registry
    # entry is gone (close_scope popped it), the scenario task and its
    # frames are gone, and the only thing that may keep the teardown alive
    # is the retained reaper.
    gc.collect()

    assert cm_weak() is not None, "owner mid-__aexit__ must survive GC while teardown is pending"

    # Cleanup: cancel the surviving owner/reaper tasks.
    for t in [t for t in asyncio.all_tasks() if t is not asyncio.current_task() and ("_run_session" in str(t.get_coro()) or "_reap" in str(t.get_coro()))]:
        t.cancel()
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_queued_cancel_rechecks_failure_on_owning_loop():
    """A cancellation queued from another loop must recheck the owner's failure
    state ON the owning loop, immediately before cancelling.

    Reproduces the time-of-check/time-of-use window: the guard snapshot is
    taken while the owner has not failed yet, the queued cancellation is
    delivered (delayed here deterministically) only after the owner failed and
    parked inside ``__aexit__`` — delivering it must be a no-op, not an
    interruption of that cleanup (#5008 review)."""
    pool = MCPSessionPool()
    loop2 = asyncio.new_event_loop()
    thread2 = threading.Thread(target=loop2.run_forever, daemon=True)
    thread2.start()

    class _DelayedLoop:
        """Wraps the foreign loop; while holding, callbacks queue locally.

        ``is_running()`` reports False so the pool's await phase takes its
        harmless idle-loop branch instead of needing a real loop handle.
        """

        def __init__(self, wrapped: asyncio.AbstractEventLoop) -> None:
            self._wrapped = wrapped
            self.hold = False
            self._held: list[tuple] = []

        def is_closed(self) -> bool:
            return self._wrapped.is_closed()

        def is_running(self) -> bool:
            return False

        def call_soon_threadsafe(self, callback, *args) -> None:
            if self.hold:
                self._held.append((callback, args))
            else:
                self._wrapped.call_soon_threadsafe(callback, *args)

        def flush(self) -> None:
            held, self._held = self._held, []
            for callback, args in held:
                self._wrapped.call_soon_threadsafe(callback, *args)

    class _GatedAexitCm:
        def __init__(self):
            self.exit_started = False
            self.closed = False

        async def __aexit__(self, *args):
            self.exit_started = True
            await gate2.wait()
            self.closed = True

    cm = _GatedAexitCm()
    holder: dict[str, object] = {}

    def _spawn() -> None:
        ready2 = loop2.create_future()
        release2 = asyncio.Event()
        close_evt2 = asyncio.Event()

        async def owner() -> None:
            try:
                await release2.wait()
                raise RuntimeError("init boom")
            except BaseException as exc:
                if not ready2.done():
                    ready2.set_exception(exc)
            finally:
                await cm.__aexit__(None, None, None)

        task2 = asyncio.ensure_future(owner())
        holder.update(ready=ready2, task=task2, close_evt=close_evt2, release=release2, gate=asyncio.Event())

    gate2 = None
    loop2.call_soon_threadsafe(_spawn)
    for _ in range(200):
        if "task" in holder:
            break
        await asyncio.sleep(0.005)
    assert "task" in holder, "foreign owner must be spawned"
    gate2 = holder["gate"]

    proxy = _DelayedLoop(loop2)
    pool._inflight[("s", "t1")] = (proxy, holder["ready"], holder["task"], holder["close_evt"])

    # Snapshot moment: the owner has NOT failed yet. close_scope's signal phase
    # queues the (guarded) cancellation into the holding proxy; its await phase
    # takes the idle branch and returns.
    proxy.hold = True
    await pool.close_scope("t1")
    assert pool._inflight == {}

    # The owner now fails on its own loop and parks inside the gated __aexit__.
    loop2.call_soon_threadsafe(holder["release"].set)
    for _ in range(400):
        if cm.exit_started:
            break
        await asyncio.sleep(0.005)
    assert cm.exit_started, "owner must enter its gated __aexit__ before the cancel is delivered"

    # Deliver the held cancellation — this is the stale-snapshot catch-up the
    # on-owning-loop recheck must neutralize.
    proxy.hold = False
    proxy.flush()

    # Let the exit finish: the delivered cancel must have been skipped.
    loop2.call_soon_threadsafe(gate2.set)
    for _ in range(400):
        if cm.closed:
            break
        await asyncio.sleep(0.005)
    assert cm.closed, "queued cancel must not interrupt an owner already unwinding in __aexit__"

    loop2.call_soon_threadsafe(loop2.stop)
    thread2.join(timeout=2)
    loop2.close()


class _InitFailCm:
    """Fake session CM whose ``initialize`` fails, with a slow ``__aexit__``.

    The slow __aexit__ lets a test observe whether cleanup is allowed to run to
    completion (closed=True) or is interrupted by a stray cancellation.
    """

    def __init__(self) -> None:
        self.entered = False
        self.exit_started = False
        self.closed = False

    async def __aenter__(self):
        self.entered = True
        session = MagicMock()
        session.initialize = self._initialize
        return session

    async def _initialize(self):
        raise RuntimeError("init boom")

    async def __aexit__(self, *args):
        self.exit_started = True
        # Yield control so a buggy double-cancel would interrupt us here.
        await asyncio.sleep(0.02)
        self.closed = True
        return False


@pytest.mark.asyncio
async def test_get_session_init_failure_runs_full_cleanup():
    """On initialize() failure the owner task's __aexit__ must complete (#3379 CR P1).

    The caller must NOT cancel the owner task on a reported failure, otherwise
    the in-progress __aexit__ cleanup gets interrupted and leaks resources.
    """
    pool = MCPSessionPool()
    cms: list[_InitFailCm] = []

    def make_cm(*a, **kw):
        cm = _InitFailCm()
        cms.append(cm)
        return cm

    with patch("langchain_mcp_adapters.sessions.create_session", side_effect=make_cm):
        with pytest.raises(RuntimeError, match="init boom"):
            await pool.get_session("s", "t1", {"transport": "stdio", "command": "x", "args": []})

    assert len(cms) == 1
    assert cms[0].entered is True
    assert cms[0].exit_started is True
    assert cms[0].closed is True, "__aexit__ must run to completion, not be interrupted"
    assert len(pool._entries) == 0
    assert len(pool._inflight) == 0


@pytest.mark.asyncio
async def test_concurrent_get_session_same_key_creates_single_session():
    """Concurrent get_session for the same key must share one session (#3379 CR P1)."""
    pool = MCPSessionPool()
    gate = asyncio.Event()
    cms: list[_BlockingInitCm] = []

    def make_cm(*a, **kw):
        cm = _BlockingInitCm(gate)
        cms.append(cm)
        return cm

    with patch("langchain_mcp_adapters.sessions.create_session", side_effect=make_cm):
        conn = {"transport": "stdio", "command": "x", "args": []}
        t1 = asyncio.create_task(pool.get_session("s", "same", conn))
        t2 = asyncio.create_task(pool.get_session("s", "same", conn))
        # Let both calls pass Phase 1 and reach the (gated) initialize().
        await asyncio.sleep(0.02)
        gate.set()
        s1, s2 = await asyncio.gather(t1, t2)

    # Only one CM/session created, both callers got the same object.
    assert len(cms) == 1, "concurrent same-key calls must not create duplicate sessions"
    assert s1 is s2
    assert len(pool._entries) == 1
    assert len(pool._inflight) == 0


@pytest.mark.asyncio
async def test_close_all_during_in_flight_creation_does_not_resurrect_session():
    """close_all while a creation is in-flight must not leave a live session (#3379 CR P1).

    The in-flight record must be removed and its owner task torn down, so when
    the (blocked) creator finishes initializing it does NOT register the session
    back into _entries — otherwise the pool resurrects an unclosable session.
    """
    pool = MCPSessionPool()
    gate = asyncio.Event()
    cms: list[_BlockingInitCm] = []

    def make_cm(*a, **kw):
        cm = _BlockingInitCm(gate)
        cms.append(cm)
        return cm

    with patch("langchain_mcp_adapters.sessions.create_session", side_effect=make_cm):
        conn = {"transport": "stdio", "command": "x", "args": []}
        call = asyncio.create_task(pool.get_session("s", "t1", conn))
        # Let the owner task enter the CM and reach the blocking initialize().
        await asyncio.sleep(0.01)
        assert ("s", "t1") in pool._inflight

        # Close everything while the creation is still in-flight.
        await pool.close_all()

        # The in-flight creation must be gone, not promoted to an entry.
        assert len(pool._inflight) == 0
        assert len(pool._entries) == 0

        # Even if the gate is released afterwards, nothing must come back.
        gate.set()
        with pytest.raises(asyncio.CancelledError):
            await call

    assert len(pool._entries) == 0
    assert len(pool._inflight) == 0
    assert cms[0].closed is True, "in-flight session's __aexit__ must run on teardown"

    current = asyncio.current_task()
    leaked = [t for t in asyncio.all_tasks() if t is not current and not t.done() and "_run_session" in str(t.get_coro())]
    assert not leaked, "in-flight owner task must not leak after close_all"


def test_get_session_cross_loop_in_flight_does_not_raise_assertion():
    """A same-key request from another loop must not hit the in-flight assertion (#3379 CR P1).

    Loop A starts (and leaves running) an in-flight creation, then loop B
    requests the same key. The stale in-flight record (owned by loop A) must be
    dropped and loop B must become a fresh creator — never fall through to an
    AssertionError.
    """
    pool = MCPSessionPool()
    cms: list[_CancelScopeCm] = []

    def make_cm(*a, **kw):
        cm = _CancelScopeCm()
        cms.append(cm)
        return cm

    conn = {"transport": "stdio", "command": "x", "args": []}
    results: list[object] = []
    errors: list[BaseException] = []

    def run_in_own_loop():
        try:
            results.append(asyncio.run(pool.get_session("s", "t1", conn)))
        except BaseException as e:  # noqa: BLE001 - capture for assertion
            errors.append(e)

    with patch("langchain_mcp_adapters.sessions.create_session", side_effect=make_cm):
        # First loop creates and registers an entry, then its loop is torn down
        # by asyncio.run, leaving a stale (closed-loop) record behind.
        t1 = threading.Thread(target=run_in_own_loop)
        t1.start()
        t1.join()

        # Second loop requests the same key. It must evict the stale record and
        # create a fresh session instead of raising AssertionError.
        t2 = threading.Thread(target=run_in_own_loop)
        t2.start()
        t2.join()

    assert not errors, f"cross-loop same-key request must not raise: {errors}"
    assert len(results) == 2
    assert all(r is not None for r in results)


def test_cross_loop_preempting_blocked_in_flight_does_not_hang_owner():
    """A foreign-loop request must not leave a still-initializing owner hung (#3379 CR P1).

    Loop A starts a creation that blocks inside initialize() (the in-flight
    record stays live). Loop B then requests the same key. B must tear A's owner
    down — cancelling it, because close_evt alone cannot wake a task blocked in
    initialize() — so that A's get_session unwinds instead of hanging forever.
    """
    pool = MCPSessionPool()
    conn = {"transport": "stdio", "command": "x", "args": []}
    first_gate = threading.Event()
    entered = threading.Event()
    results: list[tuple[str, object]] = []
    errors: list[tuple[str, BaseException]] = []
    closed: list[str] = []

    class _BlockingForeverCm:
        async def __aenter__(self):
            session = MagicMock()
            session.initialize = self._initialize
            entered.set()
            return session

        async def _initialize(self):
            # Block until released, simulating a slow/stuck server handshake.
            while not first_gate.is_set():
                await asyncio.sleep(0.005)

        async def __aexit__(self, *args):
            closed.append("blocking")
            return False

    class _FastCm:
        async def __aenter__(self):
            session = MagicMock()

            async def init():
                return None

            session.initialize = init
            return session

        async def __aexit__(self, *args):
            return False

    cms: list[object] = [_BlockingForeverCm(), _FastCm()]

    def make_cm(*a, **kw):
        return cms.pop(0)

    def run_get(name):
        try:
            results.append((name, asyncio.run(pool.get_session("s", "t1", conn))))
        except BaseException as e:  # noqa: BLE001 - capture for assertion
            errors.append((name, e))

    with patch("langchain_mcp_adapters.sessions.create_session", side_effect=make_cm):
        ta = threading.Thread(target=run_get, args=("A",))
        ta.start()
        assert entered.wait(2), "owner A must enter the CM and start initializing"

        tb = threading.Thread(target=run_get, args=("B",))
        tb.start()
        tb.join(3)

        # B must complete without depending on A's blocked initialize().
        assert not tb.is_alive(), "foreign-loop request B must not hang"
        # A must already be unwound (cancelled), not waiting on the dead gate.
        ta.join(3)
        assert not ta.is_alive(), "preempted owner A must not hang forever"

    assert [n for n, _ in results] == ["B"], "only B produces a usable session"
    assert any(isinstance(e, asyncio.CancelledError) for _, e in errors), "preempted A must unwind via CancelledError"
    assert "blocking" in closed, "preempted owner's __aexit__ must run on teardown"


@pytest.mark.asyncio
async def test_close_all_sync_from_running_loop_does_not_wait_on_itself():
    """close_all_sync must not block on the current running loop (#3379 CR P1).

    When called from code already executing inside the owner loop's thread,
    close_all_sync cannot synchronously wait for that loop to run the shutdown
    coroutine. It must signal the owner task and return promptly, then the owner
    task closes itself once the loop regains control.
    """
    pool = MCPSessionPool()
    pool.SESSION_CLOSE_TIMEOUT = 0.2
    conn = {"transport": "stdio", "command": "x", "args": []}

    cm = _CloseTrackingCm()

    def make_cm(*a, **kw):
        return cm

    with patch("langchain_mcp_adapters.sessions.create_session", side_effect=make_cm):
        await pool.get_session("s", "t1", conn)
        start = asyncio.get_running_loop().time()
        pool.close_all_sync()
        elapsed = asyncio.get_running_loop().time() - start

        assert elapsed < 0.1, "close_all_sync must not stall until timeout on the current loop"
        assert len(pool._entries) == 0
        assert len(pool._inflight) == 0
        assert cm.closed is False, "owner task has not run yet while close_all_sync is still executing"

        for _ in range(10):
            if cm.closed:
                break
            await asyncio.sleep(0.01)

    assert cm.closed is True, "owner task must close itself after the loop regains control"


# ---------------------------------------------------------------------------
# reset_mcp_tools_cache deadlock regression
# ---------------------------------------------------------------------------


class _CloseTrackingCm:
    """A create_session() context manager that records when __aexit__ runs."""

    def __init__(self) -> None:
        self.closed = False

    async def __aenter__(self):
        session = MagicMock()

        async def init():
            return None

        session.initialize = init
        return session

    async def __aexit__(self, *args):
        self.closed = True
        return False


def test_reset_mcp_tools_cache_from_running_loop_is_bounded():
    """reset_mcp_tools_cache() must not deadlock when called from inside a
    running loop that owns sessions (#3392 CR blocker).

    The previous implementation spun up a worker thread running
    ``asyncio.run(pool.close_all())`` and blocked the loop thread on
    ``.result()``. close_all() then routed teardown of the current loop's
    sessions back onto that blocked loop via run_coroutine_threadsafe(...),
    so neither side could make progress. This test drives the exact scenario
    on a daemon thread and asserts the call returns within a bounded time.
    """
    from deerflow.mcp.cache import reset_mcp_tools_cache
    from deerflow.mcp.session_pool import get_session_pool

    conn = {"transport": "stdio", "command": "x", "args": []}
    cm = _CloseTrackingCm()
    done = threading.Event()

    async def scenario():
        pool = get_session_pool()
        # Entry owned by THIS loop — the deadlock-prone case.
        await pool.get_session("s", "t1", conn)
        # Synchronous call: asyncio.get_running_loop() succeeds inside it, so
        # it takes the "running loop" branch in reset_mcp_tools_cache().
        reset_mcp_tools_cache()
        # Signal-only teardown completes once the loop regains control.
        await asyncio.sleep(0.05)

    def run():
        asyncio.run(scenario())
        done.set()

    t = threading.Thread(target=run, daemon=True)
    with patch("langchain_mcp_adapters.sessions.create_session", return_value=cm):
        t.start()
        t.join(timeout=5)

    assert done.is_set(), "reset_mcp_tools_cache() deadlocked inside a running loop"
    assert cm.closed is True, "owner task must run __aexit__ once the loop regains control"


# ---------------------------------------------------------------------------
# get_mcp_tools: routing when one server name is a prefix of another
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mcp_tools_routed_to_source_server_with_prefix_overlap():
    """Regression: tools must be routed to the server that produced them, not the first
    server whose name is a string prefix of the (prefixed) tool name.

    With `tool_name_prefix=True`, a tool from server `web_scraper` is named
    `web_scraper_search`. When a server `web` is also configured, prefix-matching the tool
    name picks `web` first (`"web_scraper_search".startswith("web_")`), mis-routing the
    tool and stripping it to the wrong original name. Routing by the source grouping fixes it.
    """
    from langchain_core.tools import StructuredTool
    from pydantic import BaseModel, Field

    from deerflow.mcp.tools import get_mcp_tools

    class Args(BaseModel):
        query: str = Field(..., description="query")

    web_tool = StructuredTool(
        name="web_open",
        description="d",
        args_schema=Args,
        coroutine=AsyncMock(),
        response_format="content_and_artifact",
    )
    scraper_tool = StructuredTool(
        name="web_scraper_search",
        description="d",
        args_schema=Args,
        coroutine=AsyncMock(),
        response_format="content_and_artifact",
    )

    extensions_config = MagicMock()
    extensions_config.model_extra = {}

    # `web` is inserted before `web_scraper`, so a first-prefix-match mis-routes
    # `web_scraper_search` to `web`.
    servers_config = {
        "web": {"transport": "stdio", "command": "npx", "args": ["web"]},
        "web_scraper": {"transport": "stdio", "command": "npx", "args": ["scraper"]},
    }

    routed: list[tuple[str, str]] = []

    def fake_wrap(tool, server_name, connection, interceptors, tool_call_timeout=None, session_init_timeout=None, tool_name_prefix=True):
        routed.append((tool.name, server_name))
        return tool

    async def get_tools_for_server(*, server_name: str | None = None):
        if server_name == "web":
            return [web_tool]
        if server_name == "web_scraper":
            return [scraper_tool]
        raise AssertionError(f"unexpected server_name: {server_name}")

    with (
        patch("deerflow.mcp.tools.ExtensionsConfig.from_file", return_value=extensions_config),
        patch("deerflow.mcp.tools.build_servers_config", return_value=servers_config),
        patch("deerflow.mcp.tools.get_initial_oauth_headers", return_value={}),
        patch("deerflow.mcp.tools.build_oauth_tool_interceptor", return_value=None),
        patch("langchain_mcp_adapters.client.MultiServerMCPClient") as MockClient,
        patch("deerflow.mcp.tools._make_session_pool_tool", side_effect=fake_wrap),
    ):
        MockClient.return_value.get_tools = AsyncMock(side_effect=get_tools_for_server)
        await get_mcp_tools()

    routing = dict(routed)
    assert routing["web_scraper_search"] == "web_scraper", f"tool mis-routed to {routing.get('web_scraper_search')!r}, expected 'web_scraper'"
    assert routing["web_open"] == "web"
