"""GET on the join-stream route must not carry cancel actions.

The existing-run stream path supports both GET and POST; POST's ``action``
branch cancels the run. The CSRF middleware exempts GET, while a SameSite=Lax
session cookie still accompanies a cross-site top-level safe navigation. An
attacker-induced navigation to
``GET .../runs/{run_id}/stream?action=interrupt|rollback`` was therefore a
state-changing GET that bypassed the CSRF protection guarding the POST
variant. These tests pin that GET stays a read-only join and POST keeps
cancelling.
"""

from __future__ import annotations

import asyncio

import pytest
from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient

from app.gateway.routers import thread_runs
from deerflow.runtime import RunManager, RunStatus
from deerflow.runtime.stream_bridge import MemoryStreamBridge

THREAD_ID = "thread-get-action"


def _make_seeded_run_client(run_status: RunStatus = RunStatus.running) -> tuple[TestClient, RunManager, str]:
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


def _get_run_status(mgr: RunManager, run_id: str) -> RunStatus:
    async def _read_status() -> RunStatus:
        record = await mgr.get(run_id)
        assert record is not None
        return record.status

    return asyncio.run(_read_status())


@pytest.mark.parametrize("action", ("interrupt", "rollback"))
def test_get_with_cancel_action_is_rejected(action: str):
    """GET + action=interrupt|rollback must answer 405, not cancel."""
    client, mgr, run_id = _make_seeded_run_client()
    response = client.get(f"/api/threads/{THREAD_ID}/runs/{run_id}/stream?action={action}")
    assert response.status_code == 405
    assert response.headers["allow"] == "POST"
    assert "POST" in response.json()["detail"]
    assert _get_run_status(mgr, run_id) == RunStatus.running


def test_get_with_invalid_action_has_one_validation_error():
    """The dependency must not duplicate the endpoint's query validation."""
    client, mgr, run_id = _make_seeded_run_client()

    response = client.get(f"/api/threads/{THREAD_ID}/runs/{run_id}/stream?action=invalid")

    assert response.status_code == 422
    assert len(response.json()["detail"]) == 1
    assert _get_run_status(mgr, run_id) == RunStatus.running


def test_unsupported_method_preserves_post_allow_header():
    """Splitting the handlers must not change Starlette's route precedence."""
    client, _, run_id = _make_seeded_run_client()

    response = client.put(f"/api/threads/{THREAD_ID}/runs/{run_id}/stream")

    assert response.status_code == 405
    assert response.headers["allow"] == "POST"


def test_get_with_action_is_rejected_before_owner_lookup():
    """The method gate must not reveal whether a thread metadata row exists."""
    app = make_authed_test_app(owner_check_passes=False)
    app.include_router(thread_runs.router)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get(f"/api/threads/{THREAD_ID}/runs/missing-run/stream?action=interrupt")

    assert response.status_code == 405
    assert response.headers["allow"] == "POST"
    app.state.thread_store.check_access.assert_not_awaited()


def test_get_without_action_still_joins():
    """The method guard must not break the plain read-only GET join. The
    seeded run is terminal so the SSE stream emits `end` and completes."""
    client, _, run_id = _make_seeded_run_client(run_status=RunStatus.success)
    with client.stream("GET", f"/api/threads/{THREAD_ID}/runs/{run_id}/stream") as response:
        assert response.status_code == 200
        events = [line for line in response.iter_lines() if line.startswith("event:")]

    assert events[-1].strip() == "event: end"


@pytest.mark.parametrize("action", ("interrupt", "rollback"))
def test_post_with_cancel_action_still_cancels(action: str):
    """The documented POST cancel-then-stream flow is unchanged."""
    client, mgr, run_id = _make_seeded_run_client()
    with client.stream("POST", f"/api/threads/{THREAD_ID}/runs/{run_id}/stream?action={action}") as response:
        assert response.status_code == 200

    assert _get_run_status(mgr, run_id) == RunStatus.interrupted
