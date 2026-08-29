"""GET on the join-stream route must not carry cancel actions.

``stream_existing_run`` is registered for both GET and POST, and its
``action`` branch cancels the run. The CSRF middleware exempts GET, so a
session-authenticated browser could be forced cross-site (img / script /
top-level navigation) into ``GET .../runs/{run_id}/stream?action=interrupt``
or ``?action=rollback`` — a state-changing GET that bypasses the CSRF
protection guarding the POST variant. The handler's documented contract is
cancel-then-stream on POST only; these tests pin that GET stays a read-only
join and POST keeps cancelling.
"""

from __future__ import annotations

import asyncio

from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient

from app.gateway.routers import thread_runs
from deerflow.runtime import RunManager, RunStatus
from deerflow.runtime.stream_bridge import MemoryStreamBridge

THREAD_ID = "thread-get-action"


def _make_client(run_status: RunStatus = RunStatus.running) -> tuple[TestClient, RunManager, str]:
    mgr = RunManager()

    async def _seed():
        record = await mgr.create(THREAD_ID)
        await mgr.set_status(record.run_id, run_status)
        return record.run_id

    run_id = asyncio.run(_seed())
    app = make_authed_test_app()
    app.include_router(thread_runs.router)
    app.state.run_manager = mgr
    app.state.stream_bridge = MemoryStreamBridge()
    return TestClient(app, raise_server_exceptions=False), mgr, run_id


def test_get_with_cancel_action_is_rejected():
    """GET + action=interrupt|rollback must answer 405, not cancel."""
    client, mgr, run_id = _make_client()
    for action in ("interrupt", "rollback"):
        response = client.get(f"/api/threads/{THREAD_ID}/runs/{run_id}/stream?action={action}")
        assert response.status_code == 405, action
        assert "POST" in response.json()["detail"]

    async def _status():
        record = await mgr.get(run_id)
        return record.status

    assert asyncio.run(_status()) == RunStatus.running


def test_get_without_action_still_joins():
    """The method guard must not break the plain read-only GET join. The
    seeded run is terminal so the SSE stream emits `end` and completes."""
    client, _, run_id = _make_client(run_status=RunStatus.success)
    with client.stream("GET", f"/api/threads/{THREAD_ID}/runs/{run_id}/stream") as response:
        assert response.status_code == 200


def test_post_with_cancel_action_still_cancels():
    """The documented POST cancel-then-stream flow is unchanged."""
    client, mgr, run_id = _make_client()
    with client.stream("POST", f"/api/threads/{THREAD_ID}/runs/{run_id}/stream?action=interrupt") as response:
        assert response.status_code == 200

    async def _status():
        record = await mgr.get(run_id)
        return record.status

    assert asyncio.run(_status()) in (RunStatus.interrupted, RunStatus.error)
