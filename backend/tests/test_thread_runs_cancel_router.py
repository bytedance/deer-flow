"""Tests for POST /api/threads/{thread_id}/runs/{run_id}/cancel."""

from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest
from _router_auth_helpers import call_unwrapped
from starlette.routing import Router as StarletteRouter

from deerflow.runtime import RunManager, RunStatus

# FastAPI in this repo still passes startup/shutdown kwargs to Starlette's
# Router, but some test environments pin an older Starlette that doesn't
# accept them. Patch only for this test module so we can import the router.
if "on_startup" not in inspect.signature(StarletteRouter.__init__).parameters:
    _ORIGINAL_ROUTER_INIT = StarletteRouter.__init__

    def _compat_router_init(
        self,
        *args,
        on_startup=None,
        on_shutdown=None,
        lifespan=None,
        **kwargs,
    ):
        return _ORIGINAL_ROUTER_INIT(self, *args, **kwargs)

    StarletteRouter.__init__ = _compat_router_init

from app.gateway.routers import thread_runs


def _make_request(run_manager: RunManager):
    """Create a minimal request-like object for direct route invocation."""
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(run_manager=run_manager)))


async def _seed_run(status: RunStatus) -> tuple[RunManager, str]:
    """Create a run record with the requested status for route tests."""
    run_manager = RunManager()

    record = await run_manager.create("thread-1", "lead_agent")
    if status is not RunStatus.pending:
        await run_manager.set_status(record.run_id, status)

    return run_manager, record.run_id


@pytest.mark.anyio
async def test_cancel_running_run_returns_202_and_marks_run_cancelled():
    """Active runs should still be cancelled immediately."""
    run_manager, run_id = await _seed_run(RunStatus.running)
    request = _make_request(run_manager)
    response = await call_unwrapped(
        thread_runs.cancel_run,
        "thread-1",
        run_id,
        request,
        action="interrupt",
    )

    assert response.status_code == 202
    assert (await run_manager.get(run_id)).status == RunStatus.cancelled


@pytest.mark.parametrize(
    ("status", "expected_status_code"),
    [
        (RunStatus.success, 202),
        (RunStatus.failed, 202),
        (RunStatus.cancelled, 202),
        (RunStatus.interrupted, 202),
        (RunStatus.success, 204),
    ],
)
@pytest.mark.anyio
async def test_cancel_terminal_run_is_idempotent(
    status: RunStatus,
    expected_status_code: int,
):
    """Cancelling an already-finished run should be treated as a no-op."""
    run_manager, run_id = await _seed_run(status)
    request = _make_request(run_manager)
    response = await call_unwrapped(
        thread_runs.cancel_run,
        "thread-1",
        run_id,
        request,
        wait=expected_status_code == 204,
        action="interrupt",
    )

    assert response.status_code == expected_status_code
    assert (await run_manager.get(run_id)).status == status
