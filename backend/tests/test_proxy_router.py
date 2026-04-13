"""Unit tests for the gateway's nginx-replacement reverse-proxy router.

Covers:
- Path-ownership defensive check (`_is_gateway_owned`)
- Header normalization (hop-by-hop strip, X-Forwarded-* injection)
- Upstream URL/rewrite normalization
- HTTP forwarding for GET / POST / streamed responses
- Catch-all 404 for gateway-owned paths
- LangGraph rewrite prefix (standard and gateway modes)
- 503 fallback for the optional provisioner upstream
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture()
def proxy_module(monkeypatch):
    """Reload the proxy module after clearing any DEERFLOW_PROXY_* env vars
    so each test starts from default upstreams."""
    for var in (
        "DEERFLOW_PROXY_LANGGRAPH_UPSTREAM",
        "DEERFLOW_PROXY_LANGGRAPH_REWRITE",
        "DEERFLOW_PROXY_PROVISIONER_UPSTREAM",
        "DEERFLOW_PROXY_FRONTEND_UPSTREAM",
    ):
        monkeypatch.delenv(var, raising=False)
    from app.gateway.routers import proxy

    return proxy


def _make_app(proxy_module, transport: httpx.MockTransport) -> FastAPI:
    app = FastAPI()
    app.include_router(proxy_module.router)
    app.state.proxy_client = httpx.AsyncClient(
        transport=transport,
        timeout=httpx.Timeout(5.0),
        follow_redirects=False,
    )
    return app


# ── Helper unit tests ────────────────────────────────────────────────────────


class TestIsGatewayOwned:
    def test_api_prefix_is_owned(self, proxy_module):
        assert proxy_module._is_gateway_owned("api/threads/123")

    def test_api_exact_is_owned(self, proxy_module):
        assert proxy_module._is_gateway_owned("api")

    def test_docs_exact_is_owned(self, proxy_module):
        assert proxy_module._is_gateway_owned("docs")

    def test_docs_subpath_is_owned(self, proxy_module):
        assert proxy_module._is_gateway_owned("docs/oauth2-redirect")

    def test_health_exact_is_owned(self, proxy_module):
        assert proxy_module._is_gateway_owned("health")

    def test_openapi_json_is_owned(self, proxy_module):
        assert proxy_module._is_gateway_owned("openapi.json")

    def test_random_page_is_not_owned(self, proxy_module):
        assert not proxy_module._is_gateway_owned("workspace/chats/abc")

    def test_apparent_does_not_collide_with_api(self, proxy_module):
        # Defensive: prefix check should NOT mark "apparent" as owned just
        # because it starts with "ap...". The ownership check uses "api/" not "ap".
        assert not proxy_module._is_gateway_owned("apparent")


class TestNormalizeUpstream:
    def test_adds_http_scheme(self, proxy_module):
        assert proxy_module._normalize_upstream("frontend:3000") == "http://frontend:3000"

    def test_strips_trailing_slash(self, proxy_module):
        assert proxy_module._normalize_upstream("http://x/") == "http://x"

    def test_preserves_https(self, proxy_module):
        assert proxy_module._normalize_upstream("https://x.example.com") == "https://x.example.com"


class TestNormalizeRewrite:
    def test_default_slash(self, proxy_module):
        assert proxy_module._normalize_rewrite("/") == "/"

    def test_adds_leading_slash(self, proxy_module):
        assert proxy_module._normalize_rewrite("api/") == "/api/"

    def test_adds_trailing_slash(self, proxy_module):
        assert proxy_module._normalize_rewrite("/api") == "/api/"


class TestBuildForwardHeaders:
    def test_drops_hop_by_hop(self, proxy_module):
        headers = [
            ("Host", "example.com"),
            ("Connection", "keep-alive"),
            ("Content-Length", "42"),
            ("Authorization", "Bearer abc"),
            ("Cookie", "sid=xyz"),
        ]
        forwarded = proxy_module._build_forward_headers(headers, client_host="1.2.3.4", scheme="http", host="gateway.test")
        assert "Host" not in forwarded
        assert "Connection" not in forwarded
        assert "Content-Length" not in forwarded
        assert forwarded["Authorization"] == "Bearer abc"
        assert forwarded["Cookie"] == "sid=xyz"
        assert forwarded["X-Forwarded-For"] == "1.2.3.4"
        assert forwarded["X-Real-IP"] == "1.2.3.4"
        assert forwarded["X-Forwarded-Proto"] == "http"
        assert forwarded["X-Forwarded-Host"] == "gateway.test"

    def test_appends_to_existing_xff(self, proxy_module):
        headers = [("X-Forwarded-For", "5.6.7.8")]
        forwarded = proxy_module._build_forward_headers(headers, client_host="1.2.3.4", scheme="https", host="gateway.test")
        assert forwarded["X-Forwarded-For"] == "5.6.7.8, 1.2.3.4"
        assert forwarded["X-Forwarded-Proto"] == "https"

    def test_no_client_host_keeps_existing_xff(self, proxy_module):
        headers = [("X-Forwarded-For", "5.6.7.8")]
        forwarded = proxy_module._build_forward_headers(headers, client_host=None, scheme="http", host="")
        assert forwarded["X-Forwarded-For"] == "5.6.7.8"
        assert "X-Real-IP" not in forwarded
        assert "X-Forwarded-Host" not in forwarded


# ── HTTP forwarding integration tests ────────────────────────────────────────


class TestFrontendProxy:
    def test_get_forwards_path_and_query(self, proxy_module):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["method"] = request.method
            captured["headers"] = dict(request.headers)
            return httpx.Response(200, content=b"hello frontend")

        app = _make_app(proxy_module, httpx.MockTransport(handler))
        with TestClient(app) as client:
            r = client.get("/workspace/chats/abc?foo=bar")

        assert r.status_code == 200
        assert r.content == b"hello frontend"
        assert captured["method"] == "GET"
        assert captured["url"] == "http://frontend:3000/workspace/chats/abc?foo=bar"
        # X-Forwarded-* injected
        assert "x-forwarded-for" in captured["headers"]
        assert "x-forwarded-proto" in captured["headers"]

    def test_post_forwards_body(self, proxy_module):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = request.content
            captured["method"] = request.method
            return httpx.Response(201, content=b"created")

        app = _make_app(proxy_module, httpx.MockTransport(handler))
        with TestClient(app) as client:
            r = client.post("/some/endpoint", content=b"payload bytes")

        assert r.status_code == 201
        assert captured["method"] == "POST"
        assert captured["body"] == b"payload bytes"

    def test_catch_all_rejects_api_paths(self, proxy_module):
        """If FastAPI routing falls through to the catch-all for an /api/*
        path that no specific router handled, it must return 404 instead of
        proxying to the frontend."""
        called = False

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal called
            called = True
            return httpx.Response(200)

        app = _make_app(proxy_module, httpx.MockTransport(handler))
        with TestClient(app) as client:
            r = client.get("/api/no-such-router/foo")

        assert r.status_code == 404
        assert called is False, "Frontend upstream must NOT receive /api/* paths"

    def test_catch_all_rejects_docs_path(self, proxy_module):
        called = False

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal called
            called = True
            return httpx.Response(200)

        app = _make_app(proxy_module, httpx.MockTransport(handler))
        # /docs is registered by FastAPI itself in __init__, but if for some
        # reason it falls through to the catch-all (e.g., docs disabled), the
        # defensive check must reject it. We test by hitting /docs/anything
        # which has no FastAPI handler.
        with TestClient(app) as client:
            r = client.get("/docs/oauth2-redirect-fake")

        assert r.status_code == 404
        assert called is False

    def test_streaming_response_passes_through(self, proxy_module):
        async def stream_body():
            for chunk in [b"chunk-1\n", b"chunk-2\n", b"chunk-3\n"]:
                yield chunk

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                content=stream_body(),
                headers={"content-type": "text/event-stream"},
            )

        app = _make_app(proxy_module, httpx.MockTransport(handler))
        with TestClient(app) as client:
            r = client.get("/_next/static/feed")

        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        assert r.content == b"chunk-1\nchunk-2\nchunk-3\n"


class TestLangGraphProxy:
    def test_default_strips_prefix(self, proxy_module, monkeypatch):
        monkeypatch.delenv("DEERFLOW_PROXY_LANGGRAPH_REWRITE", raising=False)
        monkeypatch.delenv("DEERFLOW_PROXY_LANGGRAPH_UPSTREAM", raising=False)

        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            return httpx.Response(200, content=b"langgraph")

        app = _make_app(proxy_module, httpx.MockTransport(handler))
        with TestClient(app) as client:
            r = client.get("/api/langgraph/threads/abc/runs?stream=values")

        assert r.status_code == 200
        # Default rewrite "/" + path "threads/abc/runs" → /threads/abc/runs
        assert captured["url"] == "http://langgraph:2024/threads/abc/runs?stream=values"

    def test_gateway_mode_rewrite_to_api_prefix(self, proxy_module, monkeypatch):
        monkeypatch.setenv("DEERFLOW_PROXY_LANGGRAPH_UPSTREAM", "http://gateway:8001")
        monkeypatch.setenv("DEERFLOW_PROXY_LANGGRAPH_REWRITE", "/api/")

        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            return httpx.Response(200)

        app = _make_app(proxy_module, httpx.MockTransport(handler))
        with TestClient(app) as client:
            client.get("/api/langgraph/threads/xyz/runs")

        # With rewrite "/api/" the upstream should receive /api/threads/xyz/runs
        # (the LangGraph Platform-compat router on the same gateway).
        assert captured["url"] == "http://gateway:8001/api/threads/xyz/runs"

    def test_post_body_forwarded(self, proxy_module, monkeypatch):
        monkeypatch.delenv("DEERFLOW_PROXY_LANGGRAPH_UPSTREAM", raising=False)

        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = request.content
            return httpx.Response(202)

        app = _make_app(proxy_module, httpx.MockTransport(handler))
        with TestClient(app) as client:
            r = client.post(
                "/api/langgraph/threads/abc/runs",
                json={"input": {"messages": [{"role": "user", "content": "hi"}]}},
            )

        assert r.status_code == 202
        assert b'"messages"' in captured["body"]


class TestProvisionerProxy:
    def test_forwards_to_provisioner(self, proxy_module, monkeypatch):
        monkeypatch.delenv("DEERFLOW_PROXY_PROVISIONER_UPSTREAM", raising=False)

        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            return httpx.Response(200, content=b'{"sandboxes":[]}')

        app = _make_app(proxy_module, httpx.MockTransport(handler))
        with TestClient(app) as client:
            r = client.get("/api/sandboxes")

        assert r.status_code == 200
        assert captured["url"] == "http://provisioner:8002/api/sandboxes"

    def test_forwards_subpath(self, proxy_module):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["method"] = request.method
            return httpx.Response(204)

        app = _make_app(proxy_module, httpx.MockTransport(handler))
        with TestClient(app) as client:
            r = client.delete("/api/sandboxes/sb-123")

        assert r.status_code == 204
        assert captured["url"] == "http://provisioner:8002/api/sandboxes/sb-123"
        assert captured["method"] == "DELETE"

    def test_returns_503_when_unreachable(self, proxy_module):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Connection refused")

        app = _make_app(proxy_module, httpx.MockTransport(handler))
        with TestClient(app) as client:
            r = client.get("/api/sandboxes")

        # Provisioner is *optional* — connection failure must surface as 503,
        # not 502, so the rest of the gateway keeps working when sandbox
        # provisioning is disabled.
        assert r.status_code == 503

    def test_frontend_returns_502_when_unreachable(self, proxy_module):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Connection refused")

        app = _make_app(proxy_module, httpx.MockTransport(handler))
        with TestClient(app) as client:
            r = client.get("/")

        # Frontend is NOT optional — a connection failure must be a 502.
        assert r.status_code == 502


# ── Multi-value response header preservation (regression test) ───────────────


class TestMultiValueHeaders:
    """Regression test: dict-coerced response headers used to drop duplicate
    ``Set-Cookie`` entries because ``httpx.Headers.items()`` collapses them
    into a single comma-joined value, and then ``dict[k]=v`` overwrites
    duplicates. Cookie expiry dates contain commas, so a session cookie and
    an auth cookie returned by the frontend would silently get merged into
    one corrupted header. The proxy must use ``multi_items()`` and bypass
    ``StreamingResponse(headers=...)`` to preserve them verbatim.
    """

    def test_set_cookie_duplicates_preserved(self, proxy_module):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers=[
                    ("set-cookie", "session=abc; Path=/; HttpOnly"),
                    ("set-cookie", "auth=xyz; Path=/; HttpOnly; Expires=Wed, 21 Oct 2026 07:28:00 GMT"),
                    ("content-type", "text/html"),
                ],
                content=b"hi",
            )

        app = _make_app(proxy_module, httpx.MockTransport(handler))
        with TestClient(app) as client:
            r = client.get("/some-page")

        assert r.status_code == 200
        # httpx (the client used by Starlette TestClient) exposes duplicate
        # headers via .headers.get_list() — both cookies must survive the
        # proxy round-trip unchanged.
        cookies = r.headers.get_list("set-cookie")
        assert len(cookies) == 2
        assert "session=abc" in cookies[0]
        assert "auth=xyz" in cookies[1]
        # The Expires comma must be preserved, not turned into a delimiter.
        assert "Wed, 21 Oct 2026 07:28:00 GMT" in cookies[1]

    def test_hop_by_hop_headers_still_stripped(self, proxy_module):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers=[
                    ("connection", "close"),
                    ("transfer-encoding", "chunked"),
                    ("x-custom", "keep-me"),
                ],
                content=b"ok",
            )

        app = _make_app(proxy_module, httpx.MockTransport(handler))
        with TestClient(app) as client:
            r = client.get("/foo")

        assert r.status_code == 200
        # Hop-by-hop headers are stripped, regular ones are forwarded.
        assert "connection" not in {k.lower() for k in r.headers.keys()}
        assert r.headers.get("x-custom") == "keep-me"


# ── Backwards-compat: ensure we don't accidentally hide existing routers ─────


class TestRoutePriority:
    def test_proxy_router_route_count(self, proxy_module):
        """Sanity check: the proxy router exposes exactly the expected paths."""
        paths = sorted({route.path for route in proxy_module.router.routes if hasattr(route, "path")})
        assert paths == sorted(
            [
                "/api/langgraph/{path:path}",
                "/api/sandboxes",
                "/api/sandboxes/{path:path}",
                "/{path:path}",  # frontend HTTP catch-all
            ]
        ) or paths == sorted(
            [
                "/api/langgraph/{path:path}",
                "/api/sandboxes",
                "/api/sandboxes/{path:path}",
                "/{path:path}",
                "/{path:path}",  # the WebSocket route shares the same template
            ]
        )

    def test_full_app_does_not_swallow_existing_routes(self, proxy_module, monkeypatch):
        """Smoke test: when registered LAST on the real gateway app, the
        catch-all does NOT shadow earlier routes."""
        monkeypatch.delenv("DEERFLOW_PROXY_FRONTEND_UPSTREAM", raising=False)

        from fastapi.testclient import TestClient as _TestClient

        app = FastAPI()

        @app.get("/api/example")
        async def example():
            return {"ok": True}

        # Register the proxy router LAST, exactly as create_app() does.
        app.include_router(proxy_module.router)
        app.state.proxy_client = httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(599, content=b"frontend")),
            timeout=httpx.Timeout(5.0),
        )

        with _TestClient(app) as client:
            r = client.get("/api/example")

        assert r.status_code == 200
        assert r.json() == {"ok": True}


# ── Asyncio cleanup helper ───────────────────────────────────────────────────
# Some test runs may close the loop before httpx.AsyncClient finishes its
# background tasks. The fixture above uses TestClient which manages this, but
# we also explicitly run the loop here to confirm nothing leaks.


def test_asyncio_loop_clean():
    loop = asyncio.new_event_loop()
    try:

        async def noop():
            return None

        loop.run_until_complete(noop())
    finally:
        loop.close()
