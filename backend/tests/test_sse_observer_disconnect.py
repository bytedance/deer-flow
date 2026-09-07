"""Observer joins must not apply the creator's cancel-on-disconnect policy.

Review round 5 (PR #5041): every consumer of ``sse_consumer`` used to apply
the record's ``on_disconnect=cancel`` policy in its ``finally`` block, so a
read-only stream observer could cancel a locally-owned running run just by
closing the SSE connection. The fix separates creator streams
(``apply_on_disconnect=True``, the default) from join/observer streams
(``False``). These tests drive a real generator close — the same machinery
Starlette runs when a client drops the connection — against the production
consumer.
"""

import asyncio
import inspect
from types import SimpleNamespace

from app.gateway.services import sse_consumer
from deerflow.runtime import DisconnectMode, RunRecord, RunStatus


def _running_record() -> RunRecord:
    return RunRecord(
        run_id="run-1",
        thread_id="t1",
        assistant_id=None,
        status=RunStatus.running,
        on_disconnect=DisconnectMode.cancel,
    )


class _StubBridge:
    """Yields one event, then parks until the consumer closes the generator."""

    def subscribe(self, run_id, last_event_id=None):
        async def _gen():
            yield SimpleNamespace(event="message", data="{}", id="1")
            await asyncio.Event().wait()

        return _gen()


class _CancelRecorder:
    """Stands in for the RunManager: records cancel calls, mutates nothing."""

    def __init__(self):
        self.cancelled: list[str] = []

    async def cancel(self, run_id, action="interrupt"):
        self.cancelled.append(run_id)


class _StubRequest:
    """Minimal request: headers for Last-Event-ID, never-disconnected client
    (the disconnect under test happens between events, via generator close)."""

    def __init__(self):
        self.headers = {}

    async def is_disconnected(self) -> bool:
        return False


def _request() -> _StubRequest:
    return _StubRequest()


async def _drive_disconnect(consumer) -> None:
    """Start the generator (it yields one frame), then close it — a real
    disconnect of the response stream, running the ``finally`` block."""
    await consumer.__anext__()
    await consumer.aclose()


def test_creator_stream_disconnect_applies_cancel_policy():
    """The stream returned by the creating endpoint keeps the creator's
    cancel-on-disconnect semantics."""

    async def scenario():
        recorder = _CancelRecorder()
        consumer = sse_consumer(_StubBridge(), _running_record(), _request(), recorder)
        await _drive_disconnect(consumer)
        return recorder.cancelled

    assert asyncio.run(scenario()) == ["run-1"]


def test_observer_join_disconnect_does_not_cancel():
    """A join/observer stream closing must not cancel the run — including for
    a read-only credential that never held runs:cancel."""

    async def scenario():
        recorder = _CancelRecorder()
        consumer = sse_consumer(_StubBridge(), _running_record(), _request(), recorder, apply_on_disconnect=False)
        await _drive_disconnect(consumer)
        return recorder.cancelled

    assert asyncio.run(scenario()) == []


def test_join_routes_wire_sse_consumer_as_observers():
    """Both join surfaces must be wired as observers, and the creator's
    create-and-stream endpoints must keep the creator policy (default)."""
    from app.gateway.routers import runs as runs_router
    from app.gateway.routers import thread_runs

    thread_runs_source = inspect.getsource(thread_runs)
    # join_run + the shared existing-run stream implementation
    assert thread_runs_source.count("sse_consumer(bridge, record, request, run_mgr, apply_on_disconnect=False)") == 2
    # stream_run — the creator's create-and-stream endpoint
    assert thread_runs_source.count("sse_consumer(bridge, record, request, run_mgr),") == 1

    runs_source = inspect.getsource(runs_router)
    # stateless create-and-stream — also a creator stream
    assert "sse_consumer(bridge, record, request, run_mgr, apply_on_disconnect=False)" not in runs_source
