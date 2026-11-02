"""An MCP embedded blob without ``mimeType`` must not abort the tool call.

The MCP spec marks ``BlobResourceContents.mimeType`` optional, but
``langchain_core``'s ``create_file_block`` requires a MIME type whenever a
base64 payload is present. Passing the optional field straight through made a
spec-legal server response raise ``ValueError: mime_type is required when
using base64 data``, which discarded the whole tool result — including the
server's own text blocks.
"""

import base64
from contextlib import asynccontextmanager

import pytest
from _agent_e2e_helpers import build_single_tool_call_model
from langchain.agents import create_agent
from langchain_core.messages import ToolMessage
from langchain_mcp_adapters.tools import load_mcp_tools
from mcp.types import BlobResourceContents, CallToolResult, EmbeddedResource, ListToolsResult, TextContent, Tool

from deerflow.agents.middlewares.tool_error_handling_middleware import ToolErrorHandlingMiddleware
from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.config.paths import Paths
from deerflow.mcp.session_pool import MCPSessionPool
from deerflow.mcp.tools import _convert_call_tool_result, _RawServerDiscovery, _wrap_discovered_server_tools

BLOB = base64.b64encode(b"binary payload").decode("ascii")


def _blob_resource(*, mime_type: str | None = None) -> EmbeddedResource:
    return EmbeddedResource(
        type="resource",
        resource=BlobResourceContents(uri="file:///tmp/report.bin", blob=BLOB, mimeType=mime_type),
    )


def test_blob_without_mime_type_keeps_the_text_blocks():
    result = CallToolResult(
        content=[TextContent(type="text", text="here is your report"), _blob_resource()],
        isError=False,
    )

    content, _artifact = _convert_call_tool_result(result)

    assert [block["type"] for block in content] == ["text", "file"]
    assert content[0]["text"] == "here is your report"
    assert content[1]["base64"] == BLOB
    # The MIME type is optional in the MCP spec, so the converter supplies a
    # generic one instead of aborting the call.
    assert content[1]["mime_type"] == "application/octet-stream"


def test_blob_with_mime_type_keeps_its_declared_type():
    result = CallToolResult(
        content=[_blob_resource(mime_type="application/pdf")],
        isError=False,
    )

    content, _artifact = _convert_call_tool_result(result)

    assert content[0]["type"] == "file"
    assert content[0]["mime_type"] == "application/pdf"


def test_blob_without_mime_type_stays_a_file_block_not_an_image():
    result = CallToolResult(content=[_blob_resource()], isError=False)

    content, _artifact = _convert_call_tool_result(result)

    assert content[0]["type"] == "file"


@pytest.mark.asyncio
async def test_blob_without_mime_type_does_not_break_the_agent_turn(monkeypatch, tmp_path):
    calls = []

    class Session:
        async def initialize(self):
            pass

        async def list_tools(self, **kwargs):
            return ListToolsResult(tools=[Tool(name="docs", description="Read docs", inputSchema={"type": "object", "properties": {}})])

        async def call_tool(self, name, arguments, **kwargs):
            calls.append((name, arguments))
            return CallToolResult(content=[TextContent(type="text", text="here is your report"), _blob_resource()])

    @asynccontextmanager
    async def fake_session(*args, **kwargs):
        yield Session()

    # Stub only the external session and filesystem root. Discovery, wrapping,
    # pooling, graph execution, result conversion, and error handling stay real.
    monkeypatch.setattr("langchain_mcp_adapters.tools.create_session", fake_session)
    monkeypatch.setattr("langchain_mcp_adapters.sessions.create_session", fake_session)
    monkeypatch.setattr("deerflow.mcp.tools.get_paths", lambda: Paths(tmp_path))
    connection = {"transport": "stdio", "command": "offline-blob-fixture"}
    discovered = await load_mcp_tools(None, connection=connection, server_name="docs", tool_name_prefix=True)
    pool = MCPSessionPool()
    try:
        wrapped = _wrap_discovered_server_tools(
            ExtensionsConfig(),
            "docs",
            connection,
            _RawServerDiscovery(discovered, []),
            tool_name_prefix=True,
            session_init_timeout=None,
            pool=pool,
            binding=None,
            ownership_domain="deployment",
            connection_scope="deployment",
        )
        graph = create_agent(
            model=build_single_tool_call_model(tool_name="docs_docs", tool_args={}),
            tools=list(wrapped.tools),
            middleware=[ToolErrorHandlingMiddleware()],
            context_schema=dict,
        )
        state = await graph.ainvoke(
            {"messages": [("user", "Read the docs")]},
            config={},
            context={"thread_id": "blob-thread", "thread_incarnation": "blob-fixture"},
        )
    finally:
        await pool.close_all()

    assert calls == [("docs", {})]
    (result,) = [message for message in state["messages"] if isinstance(message, ToolMessage)]
    assert result.status == "success"
    # The server's own text block survives alongside the binary payload.
    assert [block["type"] for block in result.content] == ["text", "file"]
    assert result.content[0]["text"] == "here is your report"
    assert result.content[1]["mime_type"] == "application/octet-stream"
    assert "mime_type is required" not in result.content
