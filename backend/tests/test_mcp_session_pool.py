"""Tests for the MCP persistent-session pool."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deerflow.mcp.session_pool import MCPSessionPool, get_session_pool, reset_session_pool


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
    pool = get_session_pool()
    assert ("server", "from-config") in pool._entries


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
    assert ("server", "default") in pool._entries


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
    assert ("server", "from-langgraph-config") in pool._entries


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
        mock_client_instance.get_tools = AsyncMock(return_value=[http_tool, stdio_tool])

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
