"""Search and fetch providers send a configured key without surrounding whitespace.

A key read from a file keeps its trailing newline: a Kubernetes Secret created
with ``kubectl create secret --from-file`` and mounted through ``envFrom`` is
the usual source. These providers put the raw value into an HTTP header, which
the transport refuses, and the refusal quotes the whole header:
``Illegal header value b'Bearer <key>\\n'`` from h11, or ``... in header value:
'<key>\\n'`` from requests. The providers returned that message as the tool
result, so the key reached the model, the checkpointed conversation and, for
some of them, the error log.

Every provider here now resolves its key through
``provider_credentials.resolve_api_key``, as the other bundled providers already
strip theirs. The tests run each one over a real loopback HTTP server, so the
transport's own header validation is in the loop: the request must arrive with
the stripped key, and nothing the provider returns or logs may contain the key.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from types import SimpleNamespace

import httpx
import pytest

KEY = "sk-provider-test-4f7c2a91"
RAW_KEY = f"{KEY}\r\n"


class _Recorder:
    def __init__(self) -> None:
        self.headers: list[dict[str, str]] = []


@pytest.fixture
def backend():
    """A loopback HTTP server that records request headers and answers ``{}``."""
    recorder = _Recorder()

    class Handler(BaseHTTPRequestHandler):
        def _answer(self) -> None:
            self.rfile.read(int(self.headers.get("content-length") or 0))
            recorder.headers.append({name.lower(): value for name, value in self.headers.items()})
            body = b"{}"
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        do_GET = do_POST = _answer

        def log_message(self, *args) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield SimpleNamespace(url=f"http://127.0.0.1:{server.server_port}", recorder=recorder)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


class _LoopbackTransport(httpx.AsyncHTTPTransport):
    """Send every request to the loopback server through the real httpcore/h11 stack."""

    def __init__(self, base_url: str) -> None:
        super().__init__()
        self._base = httpx.URL(base_url)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        request.url = request.url.copy_with(scheme=self._base.scheme, host=self._base.host, port=self._base.port)
        return await super().handle_async_request(request)


@pytest.fixture
def loopback_httpx(backend, monkeypatch):
    """Route clients built with a fixed provider host (``r.jina.ai``, InfoQuest, Tavily) to the loopback server."""
    original = httpx.AsyncClient

    def client(*args, **kwargs):
        kwargs.pop("transport", None)
        return original(*args, transport=_LoopbackTransport(backend.url), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)
    return backend


def _app_config(extra: dict | None):
    return SimpleNamespace(get_tool_config=lambda name: SimpleNamespace(model_extra=dict(extra)) if extra is not None else None)


async def _outcome(call: Callable[[], Awaitable[object]]) -> str:
    """The provider's result, or the text ToolErrorHandlingMiddleware would build from its exception."""
    try:
        return str(await call())
    except Exception as exc:  # noqa: BLE001 - the middleware turns any tool exception into a ToolMessage
        return f"{type(exc).__name__}: {exc}"


async def _groundroute(source: str, backend, monkeypatch) -> str:
    from deerflow.community.groundroute import tools

    monkeypatch.setattr(tools, "_GROUNDROUTE_ENDPOINT", f"{backend.url}/v1/search")
    monkeypatch.setattr(tools, "get_app_config", lambda: _app_config({"api_key": RAW_KEY} if source == "config" else {}))
    if source == "env":
        monkeypatch.setenv("GROUNDROUTE_API_KEY", RAW_KEY)
    return await _outcome(lambda: tools.web_search_tool.ainvoke({"query": "q"}))


async def _infoquest(source: str, backend, monkeypatch) -> str:
    from deerflow.community.infoquest.infoquest_client import InfoQuestClient

    monkeypatch.setenv("INFOQUEST_API_KEY", RAW_KEY)
    return await _outcome(lambda: InfoQuestClient().web_search("q"))


async def _tavily(source: str, backend, monkeypatch) -> str:
    from deerflow.community.tavily import tools

    monkeypatch.setattr(tools, "get_app_config", lambda: _app_config({"api_key": RAW_KEY} if source == "config" else {}))
    if source == "env":
        monkeypatch.setenv("TAVILY_API_KEY", RAW_KEY)
    return await _outcome(lambda: tools.web_search_tool.ainvoke({"query": "q"}))


async def _exa(source: str, backend, monkeypatch) -> str:
    from deerflow.community.exa import tools

    monkeypatch.setattr(tools, "get_app_config", lambda: _app_config({"base_url": backend.url, **({"api_key": RAW_KEY} if source == "config" else {})}))
    if source == "env":
        monkeypatch.setenv("EXA_API_KEY", RAW_KEY)
    return await _outcome(lambda: asyncio.to_thread(tools.web_search_tool.invoke, {"query": "q"}))


async def _jina(source: str, backend, monkeypatch) -> str:
    from deerflow.community.jina_ai.jina_client import JinaClient

    monkeypatch.setenv("JINA_API_KEY", RAW_KEY)
    return await _outcome(lambda: JinaClient().crawl("https://example.com"))


async def _firecrawl(source: str, backend, monkeypatch) -> str:
    from deerflow.community.firecrawl import tools

    extra = {"base_url": backend.url, "network_isolation_confirmed": True, **({"api_key": RAW_KEY} if source == "config" else {})}
    monkeypatch.setattr(tools, "get_app_config", lambda: _app_config(extra))
    if source == "env":
        monkeypatch.setenv("FIRECRAWL_API_KEY", RAW_KEY)
    return await _outcome(lambda: tools.web_search_tool.ainvoke({"query": "q"}))


async def _fastcrw(source: str, backend, monkeypatch) -> str:
    from deerflow.community.fastcrw import tools

    monkeypatch.setattr(tools, "get_app_config", lambda: _app_config({"base_url": backend.url, **({"api_key": RAW_KEY} if source == "config" else {})}))
    if source == "env":
        monkeypatch.setenv("CRW_API_KEY", RAW_KEY)
    return await _outcome(lambda: asyncio.to_thread(tools.web_search_tool.invoke, {"query": "q"}))


async def _crawl4ai(source: str, backend, monkeypatch) -> str:
    from deerflow.community.crawl4ai import tools

    monkeypatch.setattr(tools, "get_app_config", lambda: _app_config({"base_url": backend.url, "network_isolation_confirmed": True, "token": RAW_KEY}))
    # The fetch target is screened by DNS; it never leaves the loopback server here.
    monkeypatch.setattr(tools, "validate_public_http_url", lambda url, **kwargs: None)
    return await _outcome(lambda: tools.web_fetch_tool.ainvoke({"url": "https://example.com"}))


# provider, key source, call, header that carries the key, its expected value
CASES = [
    ("groundroute", "config", _groundroute, "authorization", f"Bearer {KEY}"),
    ("groundroute", "env", _groundroute, "authorization", f"Bearer {KEY}"),
    ("infoquest", "env", _infoquest, "authorization", f"Bearer {KEY}"),
    ("tavily", "config", _tavily, "authorization", f"Bearer {KEY}"),
    ("tavily", "env", _tavily, "authorization", f"Bearer {KEY}"),
    ("exa", "config", _exa, "x-api-key", KEY),
    ("exa", "env", _exa, "x-api-key", KEY),
    ("jina", "env", _jina, "authorization", f"Bearer {KEY}"),
    ("firecrawl", "config", _firecrawl, "authorization", f"Bearer {KEY}"),
    ("firecrawl", "env", _firecrawl, "authorization", f"Bearer {KEY}"),
    ("fastcrw", "config", _fastcrw, "authorization", f"Bearer {KEY}"),
    ("fastcrw", "env", _fastcrw, "authorization", f"Bearer {KEY}"),
    ("crawl4ai", "config", _crawl4ai, "authorization", f"Bearer {KEY}"),
]


@pytest.mark.anyio
@pytest.mark.parametrize(("provider", "source", "call", "header", "expected"), CASES, ids=[f"{case[0]}-{case[1]}" for case in CASES])
async def test_key_with_trailing_newline_is_sent_stripped_and_never_echoed(provider, source, call, header, expected, loopback_httpx, monkeypatch, caplog):
    backend = loopback_httpx
    for name in ("GROUNDROUTE_API_KEY", "INFOQUEST_API_KEY", "TAVILY_API_KEY", "EXA_API_KEY", "EXA_BASE_URL", "JINA_API_KEY", "FIRECRAWL_API_KEY", "CRW_API_KEY", "CRW_API_URL"):
        monkeypatch.delenv(name, raising=False)
    caplog.set_level(logging.DEBUG)

    result = await call(source, backend, monkeypatch)

    sent = [request.get(header) for request in backend.recorder.headers]
    assert sent and set(sent) == {expected}, f"{provider} never sent its key cleanly; it returned {result!r}"
    assert KEY not in result
    assert KEY not in caplog.text


@pytest.mark.anyio
@pytest.mark.parametrize("tool_name", ["web_search", "web_fetch"])
@pytest.mark.parametrize("configured", [{"api_key": ""}, {"api_key": " \n"}, {}], ids=["empty", "blank", "absent"])
async def test_fastcrw_without_its_own_key_never_sends_the_firecrawl_key(configured, tool_name, backend, monkeypatch, caplog):
    """fastCRW builds the Firecrawl SDK client, which reads FIRECRAWL_API_KEY when it gets no key.

    Only the SDK's v2 client honours the ``""`` sentinel; running both tools pins
    that search and scrape still reach it rather than the v1 client.
    """
    from deerflow.community.fastcrw import tools

    firecrawl_key = "fc-other-provider-key-93b1"
    monkeypatch.delenv("CRW_API_KEY", raising=False)
    monkeypatch.delenv("CRW_API_URL", raising=False)
    monkeypatch.setenv("FIRECRAWL_API_KEY", firecrawl_key)
    monkeypatch.setattr(tools, "get_app_config", lambda: _app_config({"base_url": backend.url, "network_isolation_confirmed": True, **configured}))
    monkeypatch.setattr(tools, "validate_public_http_url", lambda url, **kwargs: None)
    caplog.set_level(logging.DEBUG)

    if tool_name == "web_search":
        result = await _outcome(lambda: asyncio.to_thread(tools.web_search_tool.invoke, {"query": "q"}))
    else:
        result = await _outcome(lambda: asyncio.to_thread(tools.web_fetch_tool.invoke, {"url": "https://example.com"}))

    assert backend.recorder.headers, f"fastCRW never reached its endpoint; it returned {result!r}"
    assert all("authorization" not in request for request in backend.recorder.headers)
    assert firecrawl_key not in result
    assert firecrawl_key not in caplog.text


BLANK_ENV_CASES = [
    ("tavily", "TAVILY_API_KEY", _tavily),
    ("exa", "EXA_API_KEY", _exa),
    ("firecrawl", "FIRECRAWL_API_KEY", _firecrawl),
]


@pytest.mark.anyio
@pytest.mark.parametrize(("provider", "env_name", "call"), BLANK_ENV_CASES, ids=[case[0] for case in BLANK_ENV_CASES])
async def test_blank_environment_key_is_never_handed_back_to_the_sdk(provider, env_name, call, loopback_httpx, monkeypatch):
    """These SDKs re-read their variable unstripped when given no key; a blank one must act as missing."""
    backend = loopback_httpx
    monkeypatch.setenv(env_name, " \r\n")

    result = await call("none", backend, monkeypatch)

    assert "header value" not in result, f"{provider} handed the raw variable back to its SDK: {result!r}"
    assert all(request.get("authorization", "").strip() == "" and "x-api-key" not in request for request in backend.recorder.headers)
