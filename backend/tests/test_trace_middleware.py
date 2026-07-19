from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.responses import Response, StreamingResponse
from starlette.testclient import TestClient

from app.gateway.trace_middleware import TraceMiddleware, resolve_trace_enabled
from deerflow.trace_context import (
    TRACE_ID_HEADER,
    get_current_trace_id,
    is_trace_id_from_request_header,
)


def _make_app(*, enabled: bool) -> FastAPI:
    app = FastAPI()
    app.add_middleware(TraceMiddleware, enabled=enabled)

    @app.get("/plain")
    async def plain() -> dict[str, str | None]:
        return {"trace_id": get_current_trace_id()}

    @app.get("/header-flag")
    async def header_flag() -> dict[str, bool]:
        return {"from_header": is_trace_id_from_request_header()}

    @app.get("/stream")
    async def stream() -> StreamingResponse:
        async def body():
            yield f"trace={get_current_trace_id()}".encode()

        return StreamingResponse(body(), media_type="text/plain")

    @app.get("/pre-set")
    async def pre_set() -> Response:
        return Response("ok", headers={TRACE_ID_HEADER: "downstream"})

    return app


def test_trace_header_absent_when_disabled() -> None:
    client = TestClient(_make_app(enabled=False))

    response = client.get("/plain")

    assert TRACE_ID_HEADER not in response.headers
    assert response.json() == {"trace_id": None}


def test_trace_header_inherits_inbound_value_and_binds_context() -> None:
    client = TestClient(_make_app(enabled=True))

    response = client.get("/plain", headers={TRACE_ID_HEADER: "trace-from-upstream"})

    assert response.headers[TRACE_ID_HEADER] == "trace-from-upstream"
    assert response.json() == {"trace_id": "trace-from-upstream"}


def test_trace_header_generated_when_missing() -> None:
    client = TestClient(_make_app(enabled=True))

    response = client.get("/plain")

    trace_id = response.headers[TRACE_ID_HEADER]
    assert trace_id
    assert response.json() == {"trace_id": trace_id}


def test_trace_header_added_to_streaming_response_without_consuming_body() -> None:
    client = TestClient(_make_app(enabled=True))

    response = client.get("/stream", headers={TRACE_ID_HEADER: "stream-trace"})

    assert response.headers[TRACE_ID_HEADER] == "stream-trace"
    assert response.text == "trace=stream-trace"


def test_trace_header_overwrites_duplicate_downstream_value() -> None:
    client = TestClient(_make_app(enabled=True))

    response = client.get("/pre-set", headers={TRACE_ID_HEADER: "canonical-trace"})

    assert response.headers[TRACE_ID_HEADER] == "canonical-trace"
    assert response.headers.get_list(TRACE_ID_HEADER) == ["canonical-trace"]


def test_trace_header_marks_inbound_header_flag() -> None:
    client = TestClient(_make_app(enabled=True))

    with_header = client.get("/header-flag", headers={TRACE_ID_HEADER: "trace-from-upstream"})
    without_header = client.get("/header-flag")

    assert with_header.json() == {"from_header": True}
    assert without_header.json() == {"from_header": False}


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
    client = TestClient(_make_app(enabled=True))

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
    client = TestClient(_make_app(enabled=True))

    crafted_bytes = b"trace\x9fid"
    crafted_decoded = crafted_bytes.decode("latin-1")
    response = client.get("/plain", headers={TRACE_ID_HEADER: crafted_bytes})

    assert response.status_code == 200
    returned = response.headers[TRACE_ID_HEADER]
    assert returned != crafted_decoded
    assert all(0x20 <= ord(ch) <= 0x7E for ch in returned), returned


def test_enabled_is_a_startup_snapshot_not_a_live_read() -> None:
    """`logging` is startup-only (see reload_boundary.STARTUP_ONLY_FIELDS), so
    the middleware must capture the flag by value at construction time. A
    later mutation of the source object must not flip request-time behavior,
    otherwise the response `X-Trace-Id` would drift out of sync with the
    log formatter installed once by `configure_logging()` at startup.
    """
    source = {"enabled": True}
    app = FastAPI()
    app.add_middleware(TraceMiddleware, enabled=source["enabled"])

    @app.get("/plain")
    async def plain() -> dict[str, str | None]:
        return {"trace_id": get_current_trace_id()}

    client = TestClient(app)

    source["enabled"] = False  # would matter if the middleware read live
    response = client.get("/plain")

    assert TRACE_ID_HEADER in response.headers
    assert response.json()["trace_id"] is not None


def test_resolve_trace_enabled_walks_nested_config() -> None:
    config = SimpleNamespace(logging=SimpleNamespace(enhance=SimpleNamespace(enabled=True)))
    assert resolve_trace_enabled(config) is True

    config_off = SimpleNamespace(logging=SimpleNamespace(enhance=SimpleNamespace(enabled=False)))
    assert resolve_trace_enabled(config_off) is False


def test_resolve_trace_enabled_defaults_to_false_when_fields_missing() -> None:
    assert resolve_trace_enabled(SimpleNamespace()) is False
    assert resolve_trace_enabled(SimpleNamespace(logging=None)) is False
    assert resolve_trace_enabled(SimpleNamespace(logging=SimpleNamespace(enhance=None))) is False


def test_gateway_app_construction_trace_flag_defaults_false_when_config_missing(monkeypatch) -> None:
    import app.gateway.app as gateway_app

    def missing_config():
        raise FileNotFoundError("no config")

    monkeypatch.setattr(gateway_app, "get_app_config", missing_config)

    assert gateway_app._resolve_trace_enabled_for_app_construction() is False


def test_gateway_app_construction_trace_flag_uses_config_snapshot(monkeypatch) -> None:
    import app.gateway.app as gateway_app

    config = SimpleNamespace(logging=SimpleNamespace(enhance=SimpleNamespace(enabled=True)))
    monkeypatch.setattr(gateway_app, "get_app_config", lambda: config)

    assert gateway_app._resolve_trace_enabled_for_app_construction() is True
