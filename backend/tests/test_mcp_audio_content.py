"""MCP content handling keeps binary payloads out of model-visible errors."""

import asyncio
import base64
import io
import json
import wave
from contextlib import asynccontextmanager

import httpx
import pytest
from _agent_e2e_helpers import build_single_tool_call_model
from langchain.agents import create_agent
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import ToolMessage
from langchain_mcp_adapters.tools import load_mcp_tools
from langgraph.types import Command
from mcp.types import AudioContent, BlobResourceContents, CallToolResult, EmbeddedResource, ImageContent, ListToolsResult, ResourceLink, TextContent, TextResourceContents, Tool

from deerflow.agents.middlewares.tool_error_handling_middleware import ToolErrorHandlingMiddleware
from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.config.paths import Paths
from deerflow.mcp.client import build_server_params
from deerflow.mcp.session_pool import MCPSessionPool
from deerflow.mcp.tools import _convert_call_tool_result, _RawServerDiscovery, _wrap_discovered_server_tools, get_mcp_tools


@pytest.fixture
def audio_content():
    """A valid, synthetic WAV; no provider or user audio is involved."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x00\x00" * 1600)
    return AudioContent(type="audio", data=base64.b64encode(buffer.getvalue()).decode("ascii"), mimeType="audio/wav")


@pytest.mark.parametrize("is_error", [False, True])
@pytest.mark.parametrize("with_text", [False, True])
def test_audio_conversion_fails_without_stringifying_payload(audio_content, is_error, with_text):
    content = [TextContent(type="text", text="Generated audio")] if with_text else []
    content.append(audio_content)

    with pytest.raises(NotImplementedError, match="AudioContent.*not.*supported") as exc:
        _convert_call_tool_result(CallToolResult(content=content, isError=is_error))

    assert f"Received audio with mime type: {audio_content.mimeType}" in str(exc.value)
    assert audio_content.data not in str(exc.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["stdio", "streamable_http"])
async def test_audio_tool_reports_error_without_payload_in_agent_messages(transport, audio_content, monkeypatch, tmp_path):
    calls = []
    model_inputs = []

    class CaptureModelInputs(BaseCallbackHandler):
        def on_chat_model_start(self, serialized, messages, **kwargs):
            model_inputs.extend(messages)

    class Session:
        async def initialize(self):
            pass

        async def list_tools(self, **kwargs):
            return ListToolsResult(tools=[Tool(name="speak", description="Generate speech", inputSchema={"type": "object", "properties": {}})])

        async def call_tool(self, name, arguments, **kwargs):
            calls.append((name, arguments))
            return CallToolResult(content=[TextContent(type="text", text="Generated audio"), audio_content])

    @asynccontextmanager
    async def fake_session(*args, **kwargs):
        yield Session()

    # Stub only the external session and filesystem root. Discovery, wrapping,
    # pooling, graph execution, result conversion, and error handling stay real.
    monkeypatch.setattr("langchain_mcp_adapters.tools.create_session", fake_session)
    monkeypatch.setattr("langchain_mcp_adapters.sessions.create_session", fake_session)
    monkeypatch.setattr("deerflow.mcp.tools.get_paths", lambda: Paths(tmp_path))
    connection = {"transport": "stdio", "command": "offline-audio-fixture"} if transport == "stdio" else {"transport": transport, "url": "https://example.com/mcp"}
    discovered = await load_mcp_tools(None, connection=connection, server_name="speech", tool_name_prefix=True)
    pool = MCPSessionPool()
    try:
        wrapped = _wrap_discovered_server_tools(
            ExtensionsConfig(),
            "speech",
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
            model=build_single_tool_call_model(tool_name="speech_speak", tool_args={}),
            tools=list(wrapped.tools),
            middleware=[ToolErrorHandlingMiddleware()],
            context_schema=dict,
        )
        state = await graph.ainvoke(
            {"messages": [("user", "Generate speech")]},
            config={"callbacks": [CaptureModelInputs()]},
            context={"thread_id": "audio-thread", "thread_incarnation": "audio-fixture"},
        )
    finally:
        await pool.close_all()

    assert calls == [("speak", {})]
    (result,) = [message for message in state["messages"] if isinstance(message, ToolMessage)]
    assert result.status == "error"
    assert "AudioContent" in result.content
    assert "not yet supported" in result.content
    assert f"Received audio with mime type: {audio_content.mimeType}" in result.content
    assert len(model_inputs) == 2
    assert any(isinstance(message, ToolMessage) and message.status == "error" for message in model_inputs[-1])
    for message in [*state["messages"], *model_inputs[-1]]:
        assert audio_content.data not in message.model_dump_json()
    assert state["messages"][-1].content == "done"


@pytest.fixture
def network_mcp_tools(monkeypatch, tmp_path):
    """Replace only HTTP transport; discovery, SDK and interceptors stay real."""

    @asynccontextmanager
    async def load(transport, result, *, prefix=True, interceptor=None):
        calls, clients = [], []

        def factory(headers=None, timeout=None, auth=None):
            events = asyncio.Queue()

            class Events(httpx.AsyncByteStream):
                async def __aiter__(self):
                    yield b"event: endpoint\ndata: /messages\n\n"
                    while True:
                        yield await events.get()

            async def respond(request):
                if request.method == "GET":
                    if transport == "sse":
                        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=Events())
                    return httpx.Response(405)
                body = json.loads(request.content)
                method = body["method"]
                if method == "initialize":
                    data = {"protocolVersion": body["params"]["protocolVersion"], "capabilities": {"tools": {}}, "serverInfo": {"name": "offline-content", "version": "1"}}
                elif method == "tools/list":
                    data = {"tools": [{"name": "export", "description": "Export a report", "inputSchema": {"type": "object", "properties": {}}}]}
                elif method == "tools/call":
                    calls.append(body["params"])
                    data = result.model_dump(mode="json", by_alias=True, exclude_none=True)
                else:
                    assert method == "notifications/initialized"
                    return httpx.Response(202)
                response = {"jsonrpc": "2.0", "id": body["id"], "result": data}
                if transport == "sse":
                    await events.put(f"event: message\ndata: {json.dumps(response)}\n\n".encode())
                    return httpx.Response(202)
                return httpx.Response(200, json=response)

            client = httpx.AsyncClient(transport=httpx.MockTransport(respond), headers=headers, timeout=timeout, auth=auth, trust_env=False)
            clients.append(client)
            return client

        def params(name, config):
            connection = build_server_params(name, config)
            connection["httpx_client_factory"] = factory
            return connection

        payload = {"mcpServers": {"reports": {"type": transport, "url": "https://mcp.invalid/mcp", "tool_name_prefix": prefix}}}
        if interceptor is not None:
            payload["mcpInterceptors"] = ["offline_interceptors:build"]
            monkeypatch.setattr("deerflow.mcp.tools.resolve_variable", lambda _path: lambda: interceptor)
        monkeypatch.setattr("deerflow.mcp.client.build_server_params", params)
        monkeypatch.setattr("deerflow.mcp.tools.get_paths", lambda: Paths(tmp_path))
        pool = MCPSessionPool()
        try:
            tools = await get_mcp_tools(ExtensionsConfig.model_validate(payload), session_pool=pool)
            assert len(tools) == 1
            yield tools[0], calls
        finally:
            await pool.close_all()
            assert clients and all(client.is_closed for client in clients)

    return load


def _non_text_error_content(kind, data):
    if kind == "image":
        return [ImageContent(type="image", data=data, mimeType="image/png")]
    if kind == "blob":
        return [EmbeddedResource(type="resource", resource=BlobResourceContents(uri="file:///report.pdf", blob=data, mimeType="application/pdf"))]
    if kind == "audio":
        return [AudioContent(type="audio", data=data, mimeType="audio/wav")]
    if kind == "link":
        return [ResourceLink(type="resource_link", name="report", uri=f"data:application/pdf;base64,{data}", mimeType="application/pdf")]
    assert kind == "empty"
    return []


@pytest.mark.asyncio
@pytest.mark.parametrize("transport,prefix", [("http", True), ("http", False), ("sse", True), ("sse", False)])
@pytest.mark.parametrize(
    "kind,blank_blocks",
    [
        pytest.param("image", [], id="image"),
        pytest.param("blob", [], id="blob"),
        pytest.param("audio", [], id="audio"),
        pytest.param("link", [], id="link"),
        pytest.param("empty", [], id="empty"),
        pytest.param("image", [TextContent(type="text", text="")], id="image-with-empty-text"),
        pytest.param(
            "image",
            [EmbeddedResource(type="resource", resource=TextResourceContents(uri="file:///error.txt", text=" \n\t"))],
            id="image-with-blank-resource",
        ),
        pytest.param("empty", [TextContent(type="text", text=" \n")], id="blank-text-only"),
    ],
)
async def test_network_mcp_error_payload_never_reaches_agent_messages(network_mcp_tools, transport, prefix, kind, blank_blocks, caplog):
    data = base64.b64encode(b"offline binary payload " * 5000).decode("ascii")
    non_text_blocks = _non_text_error_content(kind, data)
    result = CallToolResult(content=[*blank_blocks, *non_text_blocks], isError=True, structuredContent={"blob": data})
    model_inputs = []

    class CaptureModelInputs(BaseCallbackHandler):
        def on_chat_model_start(self, serialized, messages, **kwargs):
            model_inputs.extend(messages)

    async with network_mcp_tools(transport, result, prefix=prefix) as (tool, calls):
        graph = create_agent(model=build_single_tool_call_model(tool_name=tool.name, tool_args={}), tools=[tool], middleware=[ToolErrorHandlingMiddleware()], context_schema=dict)
        state = await asyncio.wait_for(
            graph.ainvoke({"messages": [("user", "Export a report")]}, config={"callbacks": [CaptureModelInputs()]}, context={"thread_id": "error-thread", "thread_incarnation": "fixture"}),
            timeout=10,
        )

    assert len(calls) == 1 and calls[0]["name"] == "export" and calls[0]["arguments"] == {}
    (tool_message,) = [message for message in state["messages"] if isinstance(message, ToolMessage)]
    assert tool_message.status == "error"
    assert len(model_inputs) == 2
    assert any(isinstance(message, ToolMessage) and message.status == "error" for message in model_inputs[-1])
    for message in [*state["messages"], *model_inputs[-1]]:
        assert data[:80] not in message.model_dump_json()
    assert data[:80] not in caplog.text
    assert f"{len(non_text_blocks)} non-text content block" in tool_message.content
    assert len(tool_message.content) < 500
    assert state["messages"][-1].content == "done"


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["http", "sse"])
async def test_network_mcp_error_preserves_text_and_embedded_text(network_mcp_tools, transport):
    result = CallToolResult(
        content=[
            TextContent(type="text", text="Export failed"),
            ImageContent(type="image", data="cGF5bG9hZA==", mimeType="image/png"),
            EmbeddedResource(type="resource", resource=TextResourceContents(uri="file:///error.txt", text="Try another format")),
        ],
        isError=True,
    )
    async with network_mcp_tools(transport, result) as (tool, calls):
        from langchain_core.tools import ToolException

        with pytest.raises(ToolException) as error:
            await tool.ainvoke({})
        assert str(error.value) == "Export failed\nTry another format"
        assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["http", "sse"])
@pytest.mark.parametrize("kind", ["image", "blob"])
async def test_network_mcp_success_preserves_multimodal_content_and_artifact(network_mcp_tools, transport, kind):
    data = base64.b64encode(b"successful binary payload").decode("ascii")
    result = CallToolResult(content=_non_text_error_content(kind, data), structuredContent={"exported": True})
    async with network_mcp_tools(transport, result) as (tool, calls):
        message = await tool.ainvoke({"type": "tool_call", "name": tool.name, "args": {}, "id": "export-1"})
        assert message.status == "success"
        (block,) = message.content
        assert block["type"] == ("image" if kind == "image" else "file")
        assert block["base64"] == data
        assert message.artifact == {"structured_content": {"exported": True}}
        assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["http", "sse"])
@pytest.mark.parametrize("kind", ["message", "command", "recovered"])
async def test_network_mcp_custom_interceptor_controls_final_result(network_mcp_tools, transport, kind):
    result = CallToolResult(content=_non_text_error_content("image", "cGF5bG9hZA=="), isError=True)
    message = ToolMessage(content="Recovered by interceptor", tool_call_id="export-1", name="reports_export")
    replacement = Command(update={"messages": [message]}) if kind == "command" else message

    async def interceptor(request, handler):
        if kind == "recovered":
            raw = await handler(request)
            assert raw.isError and raw.content == result.content
            return raw.model_copy(update={"isError": False, "content": [TextContent(type="text", text="Recovered by interceptor")]})
        return replacement

    async with network_mcp_tools(transport, result, interceptor=interceptor) as (tool, calls):
        actual = await tool.ainvoke({"type": "tool_call", "name": tool.name, "args": {}, "id": "export-1"})
        if kind == "recovered":
            assert actual.status == "success"
            assert actual.content[0]["text"] == "Recovered by interceptor"
            assert len(calls) == 1
        else:
            assert actual is replacement
            assert calls == []
