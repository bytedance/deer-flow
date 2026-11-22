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
from types import SimpleNamespace

import anyio
import pytest

from app.gateway.services import sse_consumer
from deerflow.runtime import END_SENTINEL, HEARTBEAT_SENTINEL, DisconnectMode, RunRecord, RunStatus


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


class _TwoEventBridge:
    """Yields twice so the request can disconnect on the second poll."""

    def subscribe(self, run_id, last_event_id=None):
        async def _gen():
            yield SimpleNamespace(event="message", data='{"step": 1}', id="1")
            yield SimpleNamespace(event="message", data='{"step": 2}', id="2")

        return _gen()


class _HeartbeatBridge:
    def subscribe(self, run_id, last_event_id=None):
        async def _gen():
            yield HEARTBEAT_SENTINEL

        return _gen()


class _FailingBridge:
    """Fails before yielding: the client remains connected."""

    def subscribe(self, run_id, last_event_id=None):
        async def _gen():
            raise RuntimeError("stream bridge unavailable")
            yield

        return _gen()


class _BlockingBridge:
    def __init__(self):
        self.subscribed = asyncio.Event()

    def subscribe(self, run_id, last_event_id=None):
        async def _gen():
            self.subscribed.set()
            await asyncio.Event().wait()
            yield

        return _gen()


class _ExhaustedBridge:
    def subscribe(self, run_id, last_event_id=None):
        async def _gen():
            if False:
                yield

        return _gen()


class _EndBridge:
    def subscribe(self, run_id, last_event_id=None):
        async def _gen():
            yield END_SENTINEL

        return _gen()


class _CancelRecorder:
    """Stands in for the RunManager: records cancel calls, mutates nothing."""

    def __init__(self):
        self.cancelled: list[str] = []

    async def cancel(self, run_id, action="interrupt"):
        self.cancelled.append(run_id)


class _DrainingCancelRecorder(_CancelRecorder):
    async def cancel(self, run_id, action="interrupt"):
        await asyncio.sleep(0)
        self.cancelled.append(run_id)


class _StubRequest:
    """Minimal request: headers for Last-Event-ID, never-disconnected client
    (the disconnect under test happens between events, via generator close)."""

    def __init__(self):
        self.headers = {}

    async def is_disconnected(self) -> bool:
        return False


class _PollingDisconnectRequest(_StubRequest):
    def __init__(self, *, disconnect_after: int):
        super().__init__()
        self._disconnect_after = disconnect_after
        self._polls = 0

    async def is_disconnected(self) -> bool:
        self._polls += 1
        return self._polls > self._disconnect_after


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


def test_creator_stream_poll_disconnect_applies_cancel_policy():
    """The primary request-poll arm must mark the disconnect before breaking."""

    async def scenario():
        recorder = _CancelRecorder()
        request = _PollingDisconnectRequest(disconnect_after=1)
        consumer = sse_consumer(_TwoEventBridge(), _running_record(), request, recorder)
        first_frame = await anext(consumer)
        assert "event: message\n" in first_frame
        assert "id: 1\n" in first_frame
        with pytest.raises(StopAsyncIteration):
            await anext(consumer)
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


def test_creator_stream_bridge_failure_does_not_apply_disconnect_policy():
    """A server-side subscription failure is not a client disconnect."""

    async def scenario():
        recorder = _CancelRecorder()
        consumer = sse_consumer(_FailingBridge(), _running_record(), _request(), recorder)
        with pytest.raises(RuntimeError, match="stream bridge unavailable"):
            await anext(consumer)
        return recorder.cancelled

    assert asyncio.run(scenario()) == []


def test_creator_stream_request_cancellation_applies_disconnect_policy():
    """Cancelling the hosting request task retains creator disconnect semantics."""

    async def scenario():
        bridge = _BlockingBridge()
        recorder = _CancelRecorder()
        consumer = sse_consumer(bridge, _running_record(), _request(), recorder)
        next_frame = asyncio.create_task(anext(consumer))
        await bridge.subscribed.wait()

        next_frame.cancel()
        try:
            await next_frame
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("cancelled request task must propagate cancellation")
        return recorder.cancelled

    assert asyncio.run(scenario()) == ["run-1"]


def test_creator_stream_anyio_cancel_scope_drains_disconnect_policy():
    """Level cancellation cannot interrupt the owned run-cancel operation."""

    async def scenario():
        bridge = _BlockingBridge()
        recorder = _DrainingCancelRecorder()
        consumer = sse_consumer(bridge, _running_record(), _request(), recorder)

        with anyio.CancelScope() as scope:
            scope.cancel()
            await anext(consumer)

        return recorder.cancelled

    assert anyio.run(scenario) == ["run-1"]


def test_creator_stream_unexpected_exhaustion_does_not_cancel():
    """A subscription ending without END is a server error, not disconnect."""

    async def scenario():
        recorder = _CancelRecorder()
        consumer = sse_consumer(_ExhaustedBridge(), _running_record(), _request(), recorder)
        with pytest.raises(RuntimeError, match="ended before a terminal event"):
            await anext(consumer)
        return recorder.cancelled

    assert asyncio.run(scenario()) == []


def test_creator_stream_close_after_end_does_not_cancel():
    """Closing after a terminal frame cannot reinterpret END as disconnect."""

    async def scenario():
        recorder = _CancelRecorder()
        consumer = sse_consumer(_EndBridge(), _running_record(), _request(), recorder)
        assert await anext(consumer) == "event: end\ndata: null\n\n"
        await consumer.aclose()
        return recorder.cancelled

    assert asyncio.run(scenario()) == []


def test_creator_stream_close_after_orphan_recovery_end_does_not_cancel(monkeypatch):
    """A synthetic orphan terminal frame owns the same local invariant as END."""

    async def scenario():
        recorder = _CancelRecorder()

        async def orphan_recovered(record, run_mgr, bridge):
            return "recovered"

        monkeypatch.setattr(
            "app.gateway.services._orphan_recovery_observed_after_heartbeat",
            orphan_recovered,
        )
        consumer = sse_consumer(_HeartbeatBridge(), _running_record(), _request(), recorder)
        assert await anext(consumer) == "event: end\ndata: null\n\n"
        await consumer.aclose()
        return recorder.cancelled

    assert asyncio.run(scenario()) == []


def test_join_and_create_routes_apply_observer_vs_creator_disconnect_policies(monkeypatch):
    """Behavioral verification across the real route handlers:
    - join_run, stream_existing_run (POST without action), and join_existing_run_stream (GET)
      behave as observers and never cancel the running run on disconnect;
    - stream_run and stateless_stream keep the creator cancel-on-disconnect policy;
    - stream_run emits a missing-stream gap frame only when record.idempotency_reused is True.
    """
    from app.gateway.routers import runs as runs_router
    from app.gateway.routers import thread_runs
    from app.gateway.run_models import RunCreateRequest

    class _RouteRunManager(_CancelRecorder):
        def __init__(self, rec: RunRecord):
            super().__init__()
            self._rec = rec

        async def get(self, run_id: str):
            return self._rec if run_id == self._rec.run_id else None

    class _MissingStreamBridge:
        supports_cross_process = False

        def subscribe(self, run_id, last_event_id=None):
            return None

    def _route_req():
        req = _StubRequest()
        req._deerflow_test_bypass_auth = True
        req.state = SimpleNamespace()
        return req

    async def _noop_scope(*args, **kwargs):
        return None

    monkeypatch.setattr(thread_runs, "_require_run_visible_to_scope", _noop_scope)
    monkeypatch.setattr(thread_runs, "_scope_http_run_idempotency_key", lambda req, tid, key: key)

    async def exercise_observer_routes():
        for call in (
            lambda req: thread_runs.join_run("t1", "run-1", req),
            lambda req: thread_runs.stream_existing_run("t1", "run-1", req, action=None, wait=0),
            lambda req: thread_runs.join_existing_run_stream("t1", "run-1", req),
        ):
            mgr = _RouteRunManager(_running_record())
            monkeypatch.setattr(thread_runs, "get_run_manager", lambda _r, m=mgr: m)
            monkeypatch.setattr(thread_runs, "get_stream_bridge", lambda _r: _StubBridge())
            resp = await call(_route_req())
            await _drive_disconnect(resp.body_iterator)
            assert mgr.cancelled == []

    asyncio.run(exercise_observer_routes())

    async def exercise_creator_routes():
        for router_mod, call in (
            (thread_runs, lambda req: thread_runs.stream_run("t1", RunCreateRequest(), req, idempotency_key=None)),
            (runs_router, lambda req: runs_router.stateless_stream(RunCreateRequest(), req)),
        ):
            rec = _running_record()
            mgr = _RouteRunManager(rec)

            async def fake_start_run(*args, r=rec, **kwargs):
                return r

            monkeypatch.setattr(router_mod, "get_run_manager", lambda _r, m=mgr: m)
            monkeypatch.setattr(router_mod, "get_stream_bridge", lambda _r: _StubBridge())
            monkeypatch.setattr(router_mod, "start_run", fake_start_run)
            resp = await call(_route_req())
            await _drive_disconnect(resp.body_iterator)
            assert mgr.cancelled == ["run-1"]

    asyncio.run(exercise_creator_routes())

    async def exercise_missing_stream_gap_policy():
        async def _stream_missing(_b, _r):
            return True

        monkeypatch.setattr("app.gateway.services._terminal_record_stream_missing", _stream_missing)
        for reused, expected_prefix in ((False, "event: end\n"), (True, "event: gap\n")):
            rec = RunRecord(
                run_id="run-done",
                thread_id="t1",
                assistant_id=None,
                status=RunStatus.success,
                on_disconnect=DisconnectMode.cancel,
                idempotency_reused=reused,
            )
            mgr = _RouteRunManager(rec)

            async def fake_start_run(*args, r=rec, **kwargs):
                return r

            monkeypatch.setattr(thread_runs, "get_run_manager", lambda _r, m=mgr: m)
            monkeypatch.setattr(thread_runs, "get_stream_bridge", lambda _r: _MissingStreamBridge())
            monkeypatch.setattr(thread_runs, "start_run", fake_start_run)
            resp = await thread_runs.stream_run("t1", RunCreateRequest(), _route_req(), idempotency_key="k1")
            frames = [frame async for frame in resp.body_iterator]
            assert frames[0].startswith(expected_prefix), (reused, frames)

    asyncio.run(exercise_missing_stream_gap_policy())
