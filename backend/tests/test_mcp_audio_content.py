"""Unsupported MCP audio must not become model-visible base64 text."""

import base64
import io
import wave
from contextlib import asynccontextmanager

import pytest
from _agent_e2e_helpers import build_single_tool_call_model
from langchain.agents import create_agent
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import ToolMessage
from langchain_mcp_adapters.tools import load_mcp_tools
from mcp.types import AudioContent, CallToolResult, ListToolsResult, TextContent, Tool

from deerflow.agents.middlewares.tool_error_handling_middleware import ToolErrorHandlingMiddleware
from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.config.paths import Paths
from deerflow.mcp.session_pool import MCPSessionPool
from deerflow.mcp.tools import _convert_call_tool_result, _RawServerDiscovery, _wrap_discovered_server_tools


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
