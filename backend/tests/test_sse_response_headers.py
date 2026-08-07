"""Regression tests for the public Gateway SSE response contract."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient

from app.gateway.routers import runs, thread_runs
from deerflow.runtime import END_SENTINEL, RunStatus


def _make_app(monkeypatch: pytest.MonkeyPatch):
    record = MagicMock(
        run_id="run-1",
        thread_id="thread-1",
        store_only=False,
        status=RunStatus.success,
    )
    run_manager = MagicMock()
    run_manager.get = AsyncMock(return_value=record)
    monkeypatch.setattr(thread_runs, "start_run", AsyncMock(return_value=record))
    monkeypatch.setattr(runs, "start_run", AsyncMock(return_value=record))

    bridge = MagicMock(supports_cross_process=True)
    bridge.stream_exists = AsyncMock(return_value=True)

    async def _events():
        yield END_SENTINEL

    bridge.subscribe = lambda *_args, **_kwargs: _events()

    app = make_authed_test_app()
    app.include_router(thread_runs.router)
    app.include_router(runs.router)
    app.state.run_manager = run_manager
    app.state.stream_bridge = bridge
    return app


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/api/threads/thread-1/runs/run-1/join", None),
        ("GET", "/api/threads/thread-1/runs/run-1/stream", None),
        ("POST", "/api/threads/thread-1/runs/stream", {}),
        (
            "POST",
            "/api/runs/stream",
            {"config": {"configurable": {"thread_id": "thread-1"}}},
        ),
    ],
)
def test_sse_responses_disable_intermediary_transforms_and_nginx_buffering(
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    path: str,
    body: dict | None,
):
    """Every public SSE route sends the shared anti-buffering contract."""
    with TestClient(_make_app(monkeypatch)) as client:
        response = client.request(method, path, json=body)

    assert response.status_code == 200
    directives = {part.strip() for part in response.headers["cache-control"].split(",")}
    assert directives >= {"no-cache", "no-transform"}
    assert response.headers["x-accel-buffering"] == "no"
