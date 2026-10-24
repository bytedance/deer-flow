"""Invalid Browserless timeout settings must retain usable HTTP timeouts."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from types import SimpleNamespace

import httpx
import pytest
import yaml

from deerflow.community.browserless import browserless_client, tools


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name", ["web_fetch", "web_capture"])
@pytest.mark.parametrize("key", ["timeout_s", "timeout"])
@pytest.mark.parametrize("value", ["0", "-1", ".nan", ".inf", "-.inf", '"NaN"', '"Infinity"', "true", "false", "", "null", "{}", "[]", '"typo"'])
async def test_invalid_timeout_uses_default_in_http_request(monkeypatch, tmp_path, caplog, tool_name, key, value):
    cfg = yaml.safe_load(f"{key}: {value}\nallow_private_addresses: true\nnetwork_isolation_confirmed: true")
    monkeypatch.setattr(tools, "_get_tool_config", lambda name: cfg)
    monkeypatch.delenv("BROWSERLESS_TOKEN", raising=False)
    requests = []

    def respond(request):
        requests.append(request)
        if request.url.path == "/screenshot":
            return httpx.Response(200, content=b"screenshot", headers={"Content-Type": "image/png"})
        return httpx.Response(200, text="<html><body><article><p>A healthy rendered page.</p></article></body></html>")

    client_type = httpx.AsyncClient
    monkeypatch.setattr(browserless_client, "httpx", SimpleNamespace(AsyncClient=lambda **kwargs: client_type(transport=httpx.MockTransport(respond), **kwargs)))

    if tool_name == "web_fetch":
        result = await tools.web_fetch_tool.ainvoke({"url": "http://127.0.0.1/page"})
        assert not result.startswith("Error:")
    else:
        runtime = SimpleNamespace(context={"thread_id": "timeout-test"}, state={"thread_data": {"outputs_path": str(tmp_path)}})
        result = await tools.web_capture_tool.coroutine(url="http://127.0.0.1/page", runtime=runtime, tool_call_id="capture", filename="page.png")
        assert result.update["artifacts"] == ["/mnt/user-data/outputs/page.png"]
        assert (tmp_path / "page.png").read_bytes() == b"screenshot"

    assert len(requests) == 1
    assert requests[0].extensions["timeout"] == dict.fromkeys(["connect", "read", "write", "pool"], 30.0)
    assert any(record.name == tools.__name__ and "invalid timeout" in record.message for record in caplog.records)


@pytest.mark.parametrize("value", [0.25, 45, "2.5", " 60 "])
def test_positive_finite_timeouts_are_preserved(value):
    assert tools._get_browserless_client(cfg={"timeout_s": value}).timeout_s == float(value)


def test_missing_timeout_uses_default_without_warning(caplog):
    assert tools._get_browserless_client(cfg={}).timeout_s == 30.0
    assert not any(record.name == tools.__name__ and "invalid timeout" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_negative_timeout_does_not_abort_a_healthy_local_backend(monkeypatch):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            content = b"<html>A healthy rendered page.</html>"
            self.send_response(200)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, *args):
            pass

    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setenv("no_proxy", "127.0.0.1")
    monkeypatch.delenv("BROWSERLESS_TOKEN", raising=False)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = tools._get_browserless_client(cfg={"base_url": f"http://127.0.0.1:{server.server_port}", "timeout_s": -1})
        assert await client.fetch_html("https://example.com") == "<html>A healthy rendered page.</html>"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
