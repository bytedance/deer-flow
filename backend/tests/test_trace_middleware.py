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
