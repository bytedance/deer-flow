"""Tests for idempotent run cancellation (issue #3055).

RunManager.cancel() returns True when a run is already interrupted so that
a second cancel request from the same worker is treated as a no-op success
(202) rather than a conflict (409).  Both the POST cancel endpoint and the
POST stream endpoint share this behaviour through the same cancel() call.
"""

from __future__ import annotations

import asyncio

from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient

from app.gateway.routers import thread_runs
from deerflow.runtime import CancelOutcome, RunManager, RunStatus

THREAD_ID = "thread-cancel-test"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_app(mgr: RunManager) -> TestClient:
    app = make_authed_test_app()
    app.include_router(thread_runs.router)
    app.state.run_manager = mgr
    return TestClient(app, raise_server_exceptions=False)


def _create_interrupted_run(mgr: RunManager) -> str:
    """Create a run and cancel it, returning its run_id."""

    async def _setup():
        record = await mgr.create(THREAD_ID)
        await mgr.set_status(record.run_id, RunStatus.running)
        await mgr.cancel(record.run_id)
        return record.run_id

    return asyncio.run(_setup())


# ---------------------------------------------------------------------------
# RunManager.cancel() unit tests
# ---------------------------------------------------------------------------


class TestRunManagerCancelIdempotency:
    def test_cancel_returns_cancelled_for_already_interrupted_run(self):
        """cancel() must return CancelledOutcome.cancelled when the run is already interrupted."""

        async def run():
            mgr = RunManager()
            record = await mgr.create(THREAD_ID)
            await mgr.set_status(record.run_id, RunStatus.running)
            first = await mgr.cancel(record.run_id)
            assert first == CancelOutcome.cancelled
            second = await mgr.cancel(record.run_id)
            assert second == CancelOutcome.cancelled  # idempotent

        asyncio.run(run())

    def test_cancel_returns_not_cancellable_for_successful_run(self):
        """cancel() must return not_cancellable for runs that completed successfully."""

        async def run():
            mgr = RunManager()
            record = await mgr.create(THREAD_ID)
            await mgr.set_status(record.run_id, RunStatus.running)
            await mgr.set_status(record.run_id, RunStatus.success)
            result = await mgr.cancel(record.run_id)
            assert result == CancelOutcome.not_cancellable

        asyncio.run(run())

    def test_cancel_returns_not_active_locally_for_unknown_run(self):
        async def run():
            mgr = RunManager()
            result = await mgr.cancel("nonexistent-run-id")
            assert result == CancelOutcome.not_active_locally

        asyncio.run(run())


# ---------------------------------------------------------------------------
# POST /cancel endpoint — idempotent 202
# ---------------------------------------------------------------------------


class TestCancelRunEndpointIdempotency:
    def test_double_cancel_returns_202_not_409(self):
        """Second cancel on an already-interrupted run must return 202, not 409."""
        mgr = RunManager()
        run_id = _create_interrupted_run(mgr)
        client = _make_app(mgr)

        resp = client.post(f"/api/threads/{THREAD_ID}/runs/{run_id}/cancel")
        assert resp.status_code == 202, f"Expected 202, got {resp.status_code}: {resp.text}"

    def test_cancel_unknown_run_returns_404(self):
        mgr = RunManager()
        client = _make_app(mgr)
        resp = client.post(f"/api/threads/{THREAD_ID}/runs/no-such-run/cancel")
        assert resp.status_code == 404

    def test_cancel_successful_run_returns_409(self):
        """Successfully-completed runs cannot be cancelled — must return 409."""

        async def _setup():
            mgr = RunManager()
            record = await mgr.create(THREAD_ID)
            await mgr.set_status(record.run_id, RunStatus.running)
            await mgr.set_status(record.run_id, RunStatus.success)
            return mgr, record.run_id

        mgr, run_id = asyncio.run(_setup())
        client = _make_app(mgr)
        resp = client.post(f"/api/threads/{THREAD_ID}/runs/{run_id}/cancel")
        assert resp.status_code == 409


# ---------------------------------------------------------------------------
# POST /{thread_id}/runs/{run_id}/join (stream_existing_run) — idempotent cancel
# ---------------------------------------------------------------------------


class TestStreamExistingRunIdempotentCancel:
    def test_stream_cancel_already_interrupted_returns_not_409(self):
        """stream_existing_run with action=interrupt on an already-interrupted run
        must not raise 409 — the idempotent cancel path returns 202/SSE."""
        mgr = RunManager()
        run_id = _create_interrupted_run(mgr)
        client = _make_app(mgr)

        resp = client.post(
            f"/api/threads/{THREAD_ID}/runs/{run_id}/join",
            params={"action": "interrupt"},
        )
        assert resp.status_code != 409, f"Should not 409 on idempotent cancel, got {resp.status_code}"
