import asyncio

import pytest
from fastapi import FastAPI
from fastapi.responses import Response, StreamingResponse
from starlette.testclient import TestClient

from app.gateway.csrf_middleware import CORS_EXPOSED_HEADERS
from app.gateway.trace_middleware import TraceMiddleware
from deerflow.trace_context import TRACE_ID_HEADER, get_current_trace_id


def _make_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(TraceMiddleware)

    @app.get("/plain")
    async def plain() -> dict[str, str | None]:
        return {"trace_id": get_current_trace_id()}

    @app.get("/stream")
    async def stream() -> StreamingResponse:
        async def body():
            yield f"trace={get_current_trace_id()}".encode()

        return StreamingResponse(body(), media_type="text/plain")

    @app.get("/pre-set")
    async def pre_set() -> Response:
        return Response("ok", headers={TRACE_ID_HEADER: "downstream"})

    return app


def test_every_response_carries_a_trace_id() -> None:
    """Ungated by design: downstream reads one ContextVar instead of branching
    on whether a trace id happens to exist."""
    client = TestClient(_make_app())

    response = client.get("/plain")

    assert response.headers[TRACE_ID_HEADER]
    assert response.json()["trace_id"] == response.headers[TRACE_ID_HEADER]


def test_trace_id_header_is_exposed_to_split_origin_clients() -> None:
    """Not CORS-safelisted, so a browser client on a separate origin cannot
    read the id it is meant to quote in a bug report unless it is listed."""
    assert TRACE_ID_HEADER in CORS_EXPOSED_HEADERS


def test_trace_header_inherits_inbound_value_and_binds_context() -> None:
    client = TestClient(_make_app())

    response = client.get("/plain", headers={TRACE_ID_HEADER: "trace-from-upstream"})

    assert response.headers[TRACE_ID_HEADER] == "trace-from-upstream"
    assert response.json() == {"trace_id": "trace-from-upstream"}


def test_trace_header_generated_when_missing() -> None:
    client = TestClient(_make_app())

    response = client.get("/plain")

    trace_id = response.headers[TRACE_ID_HEADER]
    assert trace_id
    assert response.json() == {"trace_id": trace_id}


def test_trace_header_added_to_streaming_response_without_consuming_body() -> None:
    client = TestClient(_make_app())

    response = client.get("/stream", headers={TRACE_ID_HEADER: "stream-trace"})

    assert response.headers[TRACE_ID_HEADER] == "stream-trace"
    assert response.text == "trace=stream-trace"


def test_trace_header_overwrites_duplicate_downstream_value() -> None:
    client = TestClient(_make_app())

    response = client.get("/pre-set", headers={TRACE_ID_HEADER: "canonical-trace"})

    assert response.headers[TRACE_ID_HEADER] == "canonical-trace"
    assert response.headers.get_list(TRACE_ID_HEADER) == ["canonical-trace"]


def test_trace_header_rejects_crafted_non_ascii_and_generates_fresh_id() -> None:
    """A caller-crafted ``X-Trace-Id`` containing codepoints > 0x7E must not
    reach the response header. Prior to tightening ``normalize_trace_id`` such
    values either forced a 500 via ``UnicodeEncodeError`` inside
    ``MutableHeaders.__setitem__`` (codepoints > 0xFF, e.g. UTF-8 CJK bytes
    latin-1-decoded to high codepoints) or silently broke the response at
    hardened intermediaries (nginx / envoy / cloudfront) for the 0x80-0xFF
    range. The middleware must fall back to a freshly generated ASCII id.

    ``httpx`` refuses to ascii-encode non-ASCII string header values on the
    client side, so we pass the header as raw bytes to mirror what an
    attacker's ``curl -H 'X-Trace-Id: 请求-1'`` would put on the wire (UTF-8
    bytes that Starlette then latin-1-decodes into codepoints > 0x7E).
    """
    client = TestClient(_make_app())

    # Raw UTF-8 bytes of "café-1"; Starlette latin-1-decodes them into
    # a string containing 0xC3, 0xA9 — both > 0x7E.
    crafted_bytes = b"caf\xc3\xa9-1"
    crafted_decoded = crafted_bytes.decode("latin-1")
    response = client.get("/plain", headers={TRACE_ID_HEADER: crafted_bytes})

    assert response.status_code == 200
    returned = response.headers[TRACE_ID_HEADER]
    assert returned != crafted_decoded
    assert all(0x20 <= ord(ch) <= 0x7E for ch in returned), returned
    assert response.json() == {"trace_id": returned}


def test_trace_header_rejects_crafted_c1_control_and_generates_fresh_id() -> None:
    """C1 controls (0x80-0x9F) latin-1-encode successfully but are stripped
    or rejected by hardened intermediaries, so they must not survive
    validation either. Sent as raw bytes to bypass the ``httpx`` client-side
    ASCII check."""
    client = TestClient(_make_app())

    crafted_bytes = b"trace\x9fid"
    crafted_decoded = crafted_bytes.decode("latin-1")
    response = client.get("/plain", headers={TRACE_ID_HEADER: crafted_bytes})

    assert response.status_code == 200
    returned = response.headers[TRACE_ID_HEADER]
    assert returned != crafted_decoded
    assert all(0x20 <= ord(ch) <= 0x7E for ch in returned), returned


def test_create_app_wires_trace_middleware_into_the_real_stack(monkeypatch) -> None:
    """Every other case here pins the middleware's behavior on a hand-built
    app; this one pins the wiring. ``create_app()`` must install
    ``TraceMiddleware`` itself — dropping that ``add_middleware`` line (or
    short-circuiting above it) would strip the header and the ambient id that
    the run-record stamp and enhanced log records derive from, while every
    hand-wired suite still passed."""
    import app.gateway.app as app_module
    import deerflow.extensions as extensions_module
    from deerflow.config.app_config import AppConfig
    from deerflow.config.sandbox_config import SandboxConfig
    from deerflow.extensions import reset_loaded_extensions
    from deerflow.extensions.registry import ExtensionRegistry

    monkeypatch.setattr(app_module, "get_app_config", lambda: AppConfig(sandbox=SandboxConfig(use="test")))
    monkeypatch.setattr(extensions_module, "load_extensions", lambda plugins: (ExtensionRegistry().build(), []))
    try:
        client = TestClient(app_module.create_app())
        response = client.get("/health", headers={TRACE_ID_HEADER: "wired-through-create-app"})
    finally:
        reset_loaded_extensions()

    assert response.status_code == 200
    assert response.headers[TRACE_ID_HEADER] == "wired-through-create-app"


def test_unhandled_exception_500_carries_trace_header() -> None:
    """Starlette's ServerErrorMiddleware sits outside every user middleware and
    emits unhandled-exception 500s through the raw send, so those responses
    never pass the header-writing wrapper -- yet the 500 for a server bug is
    exactly the response a user most needs to correlate with a log line. The
    middleware must ship its own 500 carrying the id before re-raising."""
    app = _make_app()

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("server bug")

    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/boom", headers={TRACE_ID_HEADER: "trace-from-upstream"})

    assert response.status_code == 500
    assert response.headers[TRACE_ID_HEADER] == "trace-from-upstream"
    # Byte-identical to the ServerErrorMiddleware response it replaces: an
    # explicit content-length, not server-chosen framing (chunked on HTTP/1.1,
    # close-delimited on HTTP/1.0).
    assert response.text == "Internal Server Error"
    assert response.headers["content-length"] == str(len(b"Internal Server Error"))


def test_unhandled_exception_500_carries_generated_trace_header() -> None:
    app = _make_app()

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("server bug")

    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/boom")

    assert response.status_code == 500
    returned = response.headers[TRACE_ID_HEADER]
    assert returned
    assert all(0x20 <= ord(ch) <= 0x7E for ch in returned), returned


def test_midstream_exception_propagates_without_second_response_start() -> None:
    """An exception after ``http.response.start`` keeps propagating unchanged:
    a second response start cannot be sent, and the already-written header
    stands on the one that was."""
    sent: list[dict] = []

    async def failing_app(scope, receive, send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"partial", "more_body": True})
        raise RuntimeError("mid-stream bug")

    async def record(message) -> None:
        sent.append(message)

    middleware = TraceMiddleware(failing_app)
    scope = {"type": "http", "method": "GET", "path": "/", "headers": []}

    async def scenario() -> None:
        with pytest.raises(RuntimeError, match="mid-stream bug"):
            await middleware(scope, None, record)

    asyncio.run(scenario())

    starts = [message for message in sent if message["type"] == "http.response.start"]
    assert len(starts) == 1
    assert starts[0]["status"] == 200
    header_names = {name.lower() for name, _ in starts[0]["headers"]}
    assert TRACE_ID_HEADER.lower().encode("latin-1") in header_names
