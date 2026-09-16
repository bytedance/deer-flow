from __future__ import annotations

import asyncio
import json
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import pytest
import uvicorn
from mcp.server.fastmcp import FastMCP

from app.gateway.routers.mcp import McpServerConfigResponse, _mask_server_config
from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.mcp.client import build_server_params
from deerflow.mcp.tools import get_mcp_tools

_IDENTITY_HEADERS = {
    "x-openviking-account",
    "x-openviking-user",
    "x-openviking-actor-peer",
}


class _RequestCapture:
    def __init__(self, app) -> None:
        self._app = app
        self.headers: list[dict[str, str]] = []
        self.methods: list[str] = []

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        messages = []
        body = bytearray()
        while True:
            message = await receive()
            messages.append(message)
            body.extend(message.get("body", b""))
            if not message.get("more_body", False):
                break

        self.headers.append({key.decode("latin-1").lower(): value.decode("latin-1") for key, value in scope.get("headers", [])})
        if body:
            payload = json.loads(body)
            requests = payload if isinstance(payload, list) else [payload]
            self.methods.extend(request["method"] for request in requests if isinstance(request, dict) and "method" in request)

        message_iterator = iter(messages)

        async def replay_receive():
            return next(message_iterator, {"type": "http.disconnect"})

        await self._app(scope, replay_receive, send)


@asynccontextmanager
async def _openviking_mcp_server() -> AsyncIterator[tuple[str, _RequestCapture, list[str]]]:
    calls: list[str] = []
    mcp = FastMCP("OpenViking test server", stateless_http=True, json_response=True)

    @mcp.tool(name="find")
    async def find(query: str) -> dict[str, list[str]]:
        calls.append(query)
        return {"matches": [query]}

    @mcp.tool(name="forget")
    async def forget(uri: str) -> dict[str, str]:
        return {"forgotten": uri}

    capture = _RequestCapture(mcp.streamable_http_app())
    server_socket = socket.socket()
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind(("127.0.0.1", 0))
    server_socket.listen()
    server_socket.setblocking(False)
    port = server_socket.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(
            capture,
            log_level="error",
            lifespan="on",
        )
    )
    server_task = asyncio.create_task(server.serve(sockets=[server_socket]))

    try:
        for _ in range(500):
            if server.started:
                break
            if server_task.done():
                await server_task
            await asyncio.sleep(0.01)
        else:
            raise TimeoutError("Timed out starting the test MCP server")

        yield f"http://127.0.0.1:{port}/mcp", capture, calls
    finally:
        server.should_exit = True
        await server_task
        server_socket.close()


def _write_openviking_extensions_config(path: Path, url: str) -> None:
    example_path = Path(__file__).resolve().parents[2] / "extensions_config.example.json"
    example = json.loads(example_path.read_text(encoding="utf-8"))
    openviking = deepcopy(example["mcpServers"]["openviking"])
    openviking["enabled"] = True
    openviking["url"] = url
    path.write_text(
        json.dumps({"mcpServers": {"openviking": openviking}}),
        encoding="utf-8",
    )


def test_openviking_mcp_config_resolves_headers_omits_identity_and_masks_secrets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    api_key = "openviking-user-test-secret"
    monkeypatch.setenv("OPENVIKING_API_KEY", api_key)
    config_path = tmp_path / "extensions_config.json"
    _write_openviking_extensions_config(config_path, "http://127.0.0.1:1933/mcp")

    extensions = ExtensionsConfig.from_file(str(config_path))
    server = extensions.mcp_servers["openviking"]
    params = build_server_params("openviking", server)
    masked = _mask_server_config(McpServerConfigResponse.model_validate(server.model_dump()))

    assert params["headers"] == {"X-API-Key": api_key}
    assert _IDENTITY_HEADERS.isdisjoint({name.lower() for name in params["headers"]})
    assert masked.headers == {"X-API-Key": "***"}
    assert server.tools == {}
    assert api_key not in masked.model_dump_json()
    assert api_key not in caplog.text


@pytest.mark.asyncio
async def test_openviking_http_mcp_discovers_exposes_and_calls_native_tools(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    api_key = "openviking-user-test-secret"
    monkeypatch.setenv("OPENVIKING_API_KEY", api_key)

    async with _openviking_mcp_server() as (url, capture, calls):
        config_path = tmp_path / "extensions_config.json"
        _write_openviking_extensions_config(config_path, url)
        extensions = ExtensionsConfig.from_file(str(config_path))

        with patch("deerflow.mcp.tools.ExtensionsConfig.from_file", return_value=extensions):
            tools = await get_mcp_tools()

        assert {tool.name for tool in tools} == {"openviking_find", "openviking_forget"}
        find_tool = next(tool for tool in tools if tool.name == "openviking_find")
        result = await find_tool.ainvoke({"query": "needle"})

    assert calls == ["needle"]
    assert any(block.get("type") == "text" and "needle" in block.get("text", "") for block in result)
    assert {"initialize", "notifications/initialized", "tools/list", "tools/call"} <= set(capture.methods)
    assert capture.headers
    for headers in capture.headers:
        assert headers["x-api-key"] == api_key
        assert _IDENTITY_HEADERS.isdisjoint(headers)
    assert api_key not in caplog.text
