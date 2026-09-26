"""Capture real HTTP requests through DeerFlow's MCP discovery and tool calls."""

import asyncio
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest

from deerflow.mcp.tools import get_mcp_tools


@pytest.mark.asyncio
@pytest.mark.parametrize("authenticated", [False, True])
async def test_parallel_example_user_agent_reaches_tool_requests(tmp_path, monkeypatch, authenticated):
    captured = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            captured.append((self.path, request, dict(self.headers)))
            if "id" not in request:
                self.send_response(202)
                self.end_headers()
                return
            method = request["method"]
            if method == "initialize":
                result = {"protocolVersion": request["params"]["protocolVersion"], "capabilities": {"tools": {}}, "serverInfo": {"name": "capture", "version": "1.0"}}
            elif method == "tools/list":
                result = {"tools": [{"name": name, "description": name, "inputSchema": {"type": "object", "properties": {}}} for name in ("web_search", "web_fetch")]}
            else:
                assert method == "tools/call"
                result = {"content": [{"type": "text", "text": request["params"]["name"]}]}
            body = json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        example = json.loads((Path(__file__).parents[2] / "extensions_config.example.json").read_text())
        parallel = example["mcpServers"]["parallel-search"]
        parallel["enabled"] = True
        parallel["url"] = f"http://127.0.0.1:{server.server_port}/parallel"
        if authenticated:
            monkeypatch.setenv("PARALLEL_AUTHORIZATION", "Bearer test-only")
            parallel.setdefault("headers", {}).update({"Authorization": "$PARALLEL_AUTHORIZATION", "X-Caller": "test-caller"})
        config = {"mcpServers": {"parallel-search": parallel, "other": {"type": "http", "url": f"http://127.0.0.1:{server.server_port}/other", "headers": {"User-Agent": "other-project/1.0", "X-Caller": "other-caller"}}}}
        config_path = tmp_path / "extensions_config.json"
        config_path.write_text(json.dumps(config))
        monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(config_path))

        tools = {tool.name: tool for tool in await get_mcp_tools()}
        for name in ("parallel-search_web_search", "parallel-search_web_fetch", "parallel-search_web_search", "other_web_search"):
            assert await tools[name].ainvoke({})

        parallel_requests = [(request, headers) for path, request, headers in captured if path == "/parallel"]
        assert {request["method"] for request, _ in parallel_requests} >= {"initialize", "tools/list", "tools/call"}
        # HTTP tools create a fresh session per call: attribution must survive
        # discovery, reinitialization, and subsequent Search/Fetch requests.
        assert [request["params"]["name"] for request, _ in parallel_requests if request["method"] == "tools/call"] == ["web_search", "web_fetch", "web_search"]
        for _, headers in parallel_requests:
            headers = {name.lower(): value for name, value in headers.items()}
            assert headers["user-agent"] == "deer-flow"
            if authenticated:
                assert headers["authorization"] == "Bearer test-only"
                assert headers["x-caller"] == "test-caller"
            else:
                assert "authorization" not in headers
        other_requests = [headers for path, _, headers in captured if path == "/other"]
        assert other_requests
        for headers in other_requests:
            headers = {name.lower(): value for name, value in headers.items()}
            assert headers["user-agent"] == "other-project/1.0"
            assert headers["x-caller"] == "other-caller"
            assert "authorization" not in headers
    finally:
        await asyncio.to_thread(server.shutdown)
        server.server_close()
        thread.join()
