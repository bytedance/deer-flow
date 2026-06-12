"""Gateway-level terminal short-circuit and reconciliation tests.

Exercises the decision logic added for problems J/Q/R/T (router short-circuit)
and K/S/U (service-layer reconciliation) without a real Redis or FastAPI app.
"""

from __future__ import annotations

import pytest
from fastapi.responses import StreamingResponse

from app.gateway.routers.thread_runs import _terminal_short_circuit
from app.gateway.services import RECONCILE_INTERVAL, _reconcile_terminal_end
from deerflow.runtime.runs.manager import RunRecord
from deerflow.runtime.runs.schemas import DisconnectMode, RunStatus

RUN_ID = "11111111-2222-3333-4444-555555555555"


def _record(status: RunStatus, *, store_only: bool = False, error: str | None = None) -> RunRecord:
    return RunRecord(
        run_id=RUN_ID,
        thread_id="t-1",
        assistant_id=None,
        status=status,
        on_disconnect=DisconnectMode.continue_,
        store_only=store_only,
        error=error,
    )


class _FakeBridge:
    def __init__(self, *, retained: bool = True, events_after: bool = False, raise_on=None):
        self._retained = retained
        self._events_after = events_after
        self._raise_on = raise_on or set()

    async def has_retained_stream(self, run_id: str) -> bool:
        if "has_retained_stream" in self._raise_on:
            raise RuntimeError("probe failed")
        return self._retained

    async def has_events_after(self, run_id: str, last_event_id) -> bool:
        if "has_events_after" in self._raise_on:
            raise RuntimeError("probe failed")
        return self._events_after


class _FakeRunMgr:
    def __init__(self, record: RunRecord | None):
        self._record = record

    async def get(self, run_id: str, *, user_id=None) -> RunRecord | None:
        return self._record


# ---------------------------------------------------------------------------
# Router terminal short-circuit (problem J/Q/R/T)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_short_circuit_non_terminal_returns_none():
    bridge = _FakeBridge(retained=False)
    assert await _terminal_short_circuit(bridge, _record(RunStatus.running)) is None


@pytest.mark.anyio
async def test_short_circuit_terminal_no_retained_returns_end_response():
    bridge = _FakeBridge(retained=False)
    resp = await _terminal_short_circuit(bridge, _record(RunStatus.success))
    assert isinstance(resp, StreamingResponse)


@pytest.mark.anyio
async def test_short_circuit_terminal_with_retained_falls_through():
    bridge = _FakeBridge(retained=True)
    assert await _terminal_short_circuit(bridge, _record(RunStatus.success)) is None


@pytest.mark.anyio
async def test_short_circuit_timeout_is_terminal():
    """RunStatus.timeout must short-circuit too (problem T)."""
    bridge = _FakeBridge(retained=False)
    resp = await _terminal_short_circuit(bridge, _record(RunStatus.timeout))
    assert isinstance(resp, StreamingResponse)


@pytest.mark.anyio
async def test_short_circuit_works_for_store_only_run():
    """Short-circuit is no longer bound to store_only (problem Q/R)."""
    bridge = _FakeBridge(retained=False)
    resp = await _terminal_short_circuit(bridge, _record(RunStatus.success, store_only=True))
    assert isinstance(resp, StreamingResponse)


@pytest.mark.anyio
async def test_short_circuit_probe_failure_is_conservative():
    """A failed retained-stream probe assumes the stream may exist."""
    bridge = _FakeBridge(raise_on={"has_retained_stream"})
    assert await _terminal_short_circuit(bridge, _record(RunStatus.error)) is None


# ---------------------------------------------------------------------------
# Service-layer reconciliation (problem K/S/U)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_reconcile_running_run_returns_none():
    bridge = _FakeBridge(events_after=False)
    run_mgr = _FakeRunMgr(_record(RunStatus.running))
    result = await _reconcile_terminal_end(bridge, RUN_ID, "0-0", run_mgr, None)
    assert result is None


@pytest.mark.anyio
async def test_reconcile_terminal_drained_yields_synthetic_end():
    bridge = _FakeBridge(events_after=False)
    run_mgr = _FakeRunMgr(_record(RunStatus.success))
    result = await _reconcile_terminal_end(bridge, RUN_ID, "0-0", run_mgr, None)
    assert result is not None
    assert "event: end" in result
    assert '"status": "success"' in result


@pytest.mark.anyio
async def test_reconcile_terminal_with_pending_events_returns_none():
    """Terminal but unconsumed events remain -> keep streaming (problem U)."""
    bridge = _FakeBridge(events_after=True)
    run_mgr = _FakeRunMgr(_record(RunStatus.success))
    result = await _reconcile_terminal_end(bridge, RUN_ID, "5-0", run_mgr, None)
    assert result is None


@pytest.mark.anyio
async def test_reconcile_timeout_status_yields_synthetic_end():
    """timeout counts as terminal for reconciliation (problem T)."""
    bridge = _FakeBridge(events_after=False)
    run_mgr = _FakeRunMgr(_record(RunStatus.timeout, error="deadline"))
    result = await _reconcile_terminal_end(bridge, RUN_ID, "0-0", run_mgr, None)
    assert result is not None
    assert '"status": "timeout"' in result


@pytest.mark.anyio
async def test_reconcile_missing_record_returns_none():
    bridge = _FakeBridge(events_after=False)
    run_mgr = _FakeRunMgr(None)
    result = await _reconcile_terminal_end(bridge, RUN_ID, "0-0", run_mgr, None)
    assert result is None


@pytest.mark.anyio
async def test_reconcile_has_events_after_probe_failure_returns_none():
    bridge = _FakeBridge(raise_on={"has_events_after"})
    run_mgr = _FakeRunMgr(_record(RunStatus.success))
    result = await _reconcile_terminal_end(bridge, RUN_ID, "0-0", run_mgr, None)
    assert result is None


def test_reconcile_interval_is_thirty_seconds():
    """Reconciliation cadence is elapsed-time based, not heartbeat-count (problem S)."""
    assert RECONCILE_INTERVAL == 30.0
    # The window must dominate the heartbeat period so reconciliation is rare.
    assert RECONCILE_INTERVAL > 15.0
