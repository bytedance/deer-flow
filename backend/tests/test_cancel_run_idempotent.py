"""Tests for idempotent cancel — issue #3055.

When a run is cancelled multiple times concurrently (e.g. the user clicks
Stop repeatedly), only the first call transitions the run to ``interrupted``.
Subsequent calls that race in after status is already ``interrupted`` must
return 202, not 409.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient

from app.gateway.routers import thread_runs
from deerflow.runtime import RunManager, RunStatus

THREAD_ID = "thread-1"


def _make_app(run_manager: RunManager) -> TestClient:
    app = make_authed_test_app()
    app.include_router(thread_runs.router)
    app.state.run_manager = run_manager

    # Stub required app.state attrs that cancel_run doesn't actually use
    app.state.checkpointer = MagicMock()
    app.state.thread_store = MagicMock()
    app.state.thread_store.check_access = AsyncMock(return_value=True)
    app.state.run_store = MagicMock()
    app.state.run_event_store = MagicMock()
    app.state.stream_bridge = MagicMock()
    app.state.feedback_repo = MagicMock()
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.anyio
async def test_double_cancel_returns_202_not_409():
    """Second cancel on an already-interrupted run must be 202, not 409."""
    mgr = RunManager()
    record = await mgr.create(THREAD_ID)
    run_id = record.run_id
    await mgr.set_status(run_id, RunStatus.running)

    # Simulate first cancel: transitions to interrupted
    await mgr.cancel(run_id)
    assert record.status == RunStatus.interrupted

    # Second cancel via the HTTP endpoint should be idempotent → 202
    client = _make_app(mgr)
    resp = client.post(f"/api/threads/{THREAD_ID}/runs/{run_id}/cancel")
    assert resp.status_code == 202, f"Expected 202, got {resp.status_code}: {resp.text}"


@pytest.mark.anyio
async def test_cancel_already_cleaned_up_returns_404():
    """Cancelling a run whose record is fully gone (post-cleanup) returns 404.

    The idempotent-202 path only fires when the record exists at the time
    of the initial get() but is gone/interrupted by the time cancel() runs
    (in-flight race).  When the record is absent before the request even
    arrives, 404 is the correct response.
    """
    mgr = RunManager()
    record = await mgr.create(THREAD_ID)
    run_id = record.run_id
    await mgr.set_status(run_id, RunStatus.running)
    await mgr.cancel(run_id)
    await mgr.cleanup(run_id, delay=0)
    assert mgr.get(run_id) is None

    client = _make_app(mgr)
    resp = client.post(f"/api/threads/{THREAD_ID}/runs/{run_id}/cancel")
    assert resp.status_code == 404, f"Expected 404, got {resp.status_code}: {resp.text}"


@pytest.mark.anyio
async def test_cancel_completed_run_returns_409():
    """Cancelling a run that finished successfully must still return 409."""
    mgr = RunManager()
    record = await mgr.create(THREAD_ID)
    run_id = record.run_id
    await mgr.set_status(run_id, RunStatus.success)

    client = _make_app(mgr)
    resp = client.post(f"/api/threads/{THREAD_ID}/runs/{run_id}/cancel")
    assert resp.status_code == 409, f"Expected 409, got {resp.status_code}: {resp.text}"
