"""Every SSE response sends ``Cache-Control: no-cache, no-transform``.

Compressing proxies (Next's rewrite proxy behind ``pnpm start``, and others)
buffer a response they compress, so a plain ``no-cache`` stream reaches the
browser in bursts. ``no-transform`` asks them to leave the body alone. These
tests pin the header on all five SSE routes, keep ``Content-Location`` on the
two routes that create a run, and fail if a route goes back to a literal
header dict.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest
from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient

from app.gateway.routers import runs, thread_runs
from app.gateway.sse_headers import SSE_CACHE_CONTROL, sse_response_headers
from deerflow.runtime import RunManager, RunStatus
from deerflow.runtime.stream_bridge import MemoryStreamBridge

THREAD_ID = "thread-sse-headers"
ROUTERS_DIR = Path(__file__).resolve().parents[1] / "app" / "gateway" / "routers"


async def _one_frame(*_args, **_kwargs):
    yield "event: end\ndata: null\n\n"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, str]:
    mgr = RunManager()

    async def _seed():
        record = await mgr.create(THREAD_ID)
        await mgr.set_status(record.run_id, RunStatus.success)
        return record

    record = asyncio.run(_seed())

    async def _start_run(*_args, **_kwargs):
        return record

    for module in (thread_runs, runs):
        monkeypatch.setattr(module, "sse_consumer", _one_frame)
        monkeypatch.setattr(module, "start_run", _start_run)

    app = make_authed_test_app()
    app.include_router(thread_runs.router)
    app.include_router(runs.router)
    app.state.run_manager = mgr
    app.state.stream_bridge = MemoryStreamBridge()
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client, record.run_id


def _stream(test_client: TestClient, method: str, url: str, **kwargs):
    with test_client.stream(method, url, **kwargs) as response:
        body = "".join(response.iter_text())
        return response, body


def _assert_sse_headers(response) -> None:
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache, no-transform"
    assert response.headers["x-accel-buffering"] == "no"
    assert response.headers["connection"] == "keep-alive"


def test_helper_shape():
    assert SSE_CACHE_CONTROL == "no-cache, no-transform"
    assert sse_response_headers() == {
        "Cache-Control": "no-cache, no-transform",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    assert sse_response_headers(content_location="/api/threads/t/runs/r")["Content-Location"] == "/api/threads/t/runs/r"


def test_thread_run_create_stream_headers(client):
    test_client, run_id = client
    response, body = _stream(test_client, "POST", f"/api/threads/{THREAD_ID}/runs/stream", json={"input": {}})
    _assert_sse_headers(response)
    assert response.headers["content-location"] == f"/api/threads/{THREAD_ID}/runs/{run_id}"
    assert "event: end" in body


def test_stateless_create_stream_headers(client):
    test_client, run_id = client
    response, body = _stream(
        test_client,
        "POST",
        "/api/runs/stream",
        json={"input": {}, "config": {"configurable": {"thread_id": THREAD_ID}}},
    )
    _assert_sse_headers(response)
    assert response.headers["content-location"] == f"/api/threads/{THREAD_ID}/runs/{run_id}"
    assert "event: end" in body


def test_join_headers(client):
    test_client, run_id = client
    response, body = _stream(test_client, "GET", f"/api/threads/{THREAD_ID}/runs/{run_id}/join")
    _assert_sse_headers(response)
    assert "content-location" not in response.headers
    assert "event: end" in body


@pytest.mark.parametrize("method", ("GET", "POST"))
def test_existing_run_stream_headers(client, method: str):
    test_client, run_id = client
    response, body = _stream(test_client, method, f"/api/threads/{THREAD_ID}/runs/{run_id}/stream")
    _assert_sse_headers(response)
    assert "content-location" not in response.headers
    assert "event: end" in body


def test_no_literal_no_cache_header_left_in_routers():
    pattern = re.compile(r"""["']Cache-Control["']\s*:\s*["']no-cache["']""")
    offenders = [str(path.relative_to(ROUTERS_DIR)) for path in sorted(ROUTERS_DIR.rglob("*.py")) if pattern.search(path.read_text(encoding="utf-8"))]
    assert offenders == []


def test_every_event_stream_route_uses_the_helper():
    for path in sorted(ROUTERS_DIR.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        streams = source.count('media_type="text/event-stream"')
        assert source.count("headers=sse_response_headers(") == streams, path.name
