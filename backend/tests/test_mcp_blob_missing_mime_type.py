"""Empty MCP blobs and missing MIME types must preserve the tool result."""

import base64
import sys

import pytest
from _agent_e2e_helpers import build_single_tool_call_model
from langchain.agents import create_agent
from langchain_core.messages import ToolMessage
from mcp.types import BlobResourceContents, CallToolResult, EmbeddedResource, TextContent

from deerflow.mcp.tools import _convert_call_tool_result

BLOB = base64.b64encode(b"binary payload").decode("ascii")


def _result(mime_type: str | None, *, with_text: bool = True) -> CallToolResult:
    content = [TextContent(type="text", text="here is your report")] if with_text else []
    content.append(
        EmbeddedResource(
            type="resource",
            resource=BlobResourceContents(uri="file:///tmp/report.bin", blob=BLOB, mimeType=mime_type),
        )
    )
    return CallToolResult(content=content, isError=False)


def test_blob_without_mime_type_degrades_to_octet_stream():
    lc_content, _artifact = _convert_call_tool_result(_result(None))

    assert [block["type"] for block in lc_content] == ["text", "file"]
    assert lc_content[0]["text"] == "here is your report"
    assert lc_content[1]["mime_type"] == "application/octet-stream"
    assert lc_content[1]["base64"] == BLOB


def test_text_blocks_survive_the_fallback():
    lc_content, _artifact = _convert_call_tool_result(_result(None))

    assert [block["type"] for block in lc_content] == ["text", "file"]
    assert lc_content[0]["text"] == "here is your report"
    assert lc_content[1]["mime_type"] == "application/octet-stream"


def test_declared_non_image_mime_type_is_preserved():
    lc_content, _artifact = _convert_call_tool_result(_result("application/pdf"))

    assert lc_content[1]["type"] == "file"
    assert lc_content[1]["mime_type"] == "application/pdf"


def test_declared_image_mime_type_still_becomes_an_image_block():
    lc_content, _artifact = _convert_call_tool_result(_result("image/png"))

    assert [block["type"] for block in lc_content] == ["text", "image"]
    assert lc_content[1]["mime_type"] == "image/png"


@pytest.mark.parametrize("mime_type", [None, "text/plain", "image/png"])
@pytest.mark.parametrize("with_text", [False, True])
def test_empty_embedded_resource_keeps_successful_result(mime_type, with_text):
    result = _result(mime_type, with_text=with_text)
    result.content[-1].resource.blob = ""

    content, _artifact = _convert_call_tool_result(result)

    assert all(block["type"] == "text" for block in content)
    assert "empty" in content[-1]["text"].lower()
    assert (mime_type or "application/octet-stream") in content[-1]["text"]
    assert "file:///tmp" not in str(content)
    if with_text:
        assert content[0]["text"] == "here is your report"


@pytest.mark.asyncio
async def test_empty_resource_survives_real_stdio_tool_call(tmp_path, monkeypatch):
    from deerflow.agents.middlewares.tool_error_handling_middleware import ToolErrorHandlingMiddleware
    from deerflow.config.extensions_config import ExtensionsConfig
    from deerflow.config.paths import Paths
    from deerflow.mcp.session_pool import MCPSessionPool
    from deerflow.mcp.tools import get_mcp_tools

    server = tmp_path / "empty_resource_server.py"
    server.write_text(
        """import asyncio
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import BlobResourceContents, CallToolResult, EmbeddedResource, TextContent, Tool

server = Server('empty-resource')
@server.list_tools()
async def tools():
    return [Tool(name='read_empty', description='Read a zero-byte file', inputSchema={'type': 'object', 'properties': {}})]
@server.call_tool()
async def call(name, arguments):
    return CallToolResult(content=[TextContent(type='text', text='Read completed'), EmbeddedResource(type='resource', resource=BlobResourceContents(uri='file:///empty.txt', blob='', mimeType='text/plain'))])
async def main():
    async with stdio_server() as streams:
        await server.run(*streams, server.create_initialization_options())
asyncio.run(main())
""",
        encoding="utf-8",
        newline="\n",
    )
    monkeypatch.setattr("deerflow.mcp.tools.get_paths", lambda: Paths(tmp_path / "home"))
    config = ExtensionsConfig(mcp_servers={"files": {"type": "stdio", "command": sys.executable, "args": [str(server)]}})
    pool = MCPSessionPool()
    try:
        tools = await get_mcp_tools(config, session_pool=pool)
        assert [tool.name for tool in tools] == ["files_read_empty"]
        graph = create_agent(model=build_single_tool_call_model(tool_name="files_read_empty", tool_args={}), tools=tools, middleware=[ToolErrorHandlingMiddleware()], context_schema=dict)
        state = await graph.ainvoke({"messages": [("user", "Read the empty file")]}, context={"thread_id": "empty-resource-thread", "thread_incarnation": "fixture"})
    finally:
        await pool.close_all()

    (result,) = [message for message in state["messages"] if isinstance(message, ToolMessage)]
    assert result.status == "success"
    assert result.content[0]["text"] == "Read completed"
    assert "empty" in result.content[-1]["text"].lower()
    assert state["messages"][-1].content == "done"
