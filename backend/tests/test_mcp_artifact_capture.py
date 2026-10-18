"""MCP resource links must reach the persistent artifact registry through the graph."""

from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from _agent_e2e_helpers import build_single_tool_call_model
from langchain.agents import create_agent
from langchain_core.messages import ToolMessage
from langchain_mcp_adapters.tools import load_mcp_tools
from mcp.types import CallToolResult, ListToolsResult, ResourceLink, Tool

from deerflow.agents.middlewares.artifact_capture_middleware import ArtifactCaptureMiddleware
from deerflow.agents.thread_state import ThreadState
from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.config.paths import Paths
from deerflow.mcp.session_pool import MCPSessionPool
from deerflow.mcp.tools import _RawServerDiscovery, _wrap_discovered_server_tools


@pytest_asyncio.fixture
async def session_pool():
    pool = MCPSessionPool()
    try:
        yield pool
    finally:
        await pool.close_all()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "transport,mime,suffix",
    [
        ("stdio", "application/pdf", "pdf"),
        ("stdio", "image/png", "png"),
        ("streamable_http", "image/png", "png"),
    ],
)
async def test_resource_link_captured_by_agent_graph(transport, mime, suffix, monkeypatch, tmp_path, session_pool):
    url = f"https://example.com/report.{suffix}"
    calls = []

    class Session:
        async def initialize(self):
            pass

        async def list_tools(self, **kwargs):
            return ListToolsResult(
                tools=[
                    Tool(
                        name="export",
                        description="Export a report",
                        inputSchema={"type": "object", "properties": {}},
                    )
                ]
            )

        async def call_tool(self, name, arguments, **kwargs):
            calls.append((name, arguments))
            return CallToolResult(
                content=[
                    ResourceLink(
                        type="resource_link",
                        name="report",
                        uri=url,
                        mimeType=mime,
                    )
                ]
            )

    @asynccontextmanager
    async def fake_session(*args, **kwargs):
        yield Session()

    # Replace only the external MCP session and the filesystem base directory.
    # Discovery, pooling/call protection, tool execution, and capture are real.
    monkeypatch.setattr("langchain_mcp_adapters.tools.create_session", fake_session)
    monkeypatch.setattr("langchain_mcp_adapters.sessions.create_session", fake_session)
    monkeypatch.setattr("deerflow.mcp.tools.get_paths", lambda: Paths(tmp_path))
    connection = {"transport": "stdio", "command": "offline-mcp-fixture"} if transport == "stdio" else {"transport": "streamable_http", "url": "https://example.com/mcp"}
    discovered = await load_mcp_tools(
        None,
        connection=connection,
        server_name="reports",
        tool_name_prefix=True,
    )
    wrapped = _wrap_discovered_server_tools(
        ExtensionsConfig(),
        "reports",
        connection,
        _RawServerDiscovery(discovered, []),
        tool_name_prefix=True,
        session_init_timeout=None,
        pool=session_pool,
        binding=None,
        ownership_domain="deployment",
        connection_scope="deployment",
    )
    model = build_single_tool_call_model(tool_name="reports_export", tool_args={}, tool_call_id="export-1")
    graph = create_agent(
        model=model,
        tools=list(wrapped.tools),
        middleware=[ArtifactCaptureMiddleware()],
        state_schema=ThreadState,
        context_schema=dict,
    )
    state = await graph.ainvoke(
        {"messages": [("user", "Export a report")]},
        context={"thread_id": "report-thread", "thread_incarnation": "fixture-incarnation"},
    )
    (message,) = [m for m in state["messages"] if isinstance(m, ToolMessage)]
    assert calls == [("export", {})]
    assert message.status == "success"
    if mime.startswith("image/"):
        assert message.content[0]["type"] == "image"
        assert message.content[0]["url"] == url
    entries = state.get("tool_artifacts", [])
    (entry,) = entries
    assert entry["real_ref"] == url
    assert entry["artifact_type"] == ("image" if mime.startswith("image/") else "file")
    assert entry["mime_type"] == mime
    assert entry["tool_name"] == "reports_export"
