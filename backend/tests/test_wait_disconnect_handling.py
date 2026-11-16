"""Regression tests for issues #3265 and #3932.

The non-streaming ``/wait`` endpoints used to ``await record.task`` with no
disconnect handling and silently swallow ``CancelledError``.  When a long
tool call (e.g. ``pip install`` inside a custom skill) kept the connection
idle long enough for an intermediate HTTP layer to time out, the handler
would return a stale checkpoint that looked like a normal completion.

The fix introduces ``wait_for_run_completion`` in ``app.gateway.services``:
it subscribes to the stream bridge until ``END_SENTINEL``, polls
``request.is_disconnected()`` on every wake-up, and honours the record's
``on_disconnect`` mode by cancelling the background run on real client
disconnect. Store-only consumers wait for the bridge's real terminal marker
instead of treating an ordinary durable terminal status as proof that all tail
events have already been published. Explicit run or scheduled-task orphan-recovery
stop reasons provide the narrow heartbeat fallback when the publisher is gone.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import anyio
import pytest
from _router_auth_helpers import call_unwrapped

from deerflow.runtime import ORPHAN_RECOVERY_STOP_REASON, CancelOutcome, RunManager, RunRecord, RunStatus
from deerflow.runtime.runs.schemas import DisconnectMode
from deerflow.runtime.stream_bridge.memory import MemoryStreamBridge

THREAD_ID = "thread-wait-3265"


@dataclass
class _FakeRequest:
    """Minimal stand-in for FastAPI ``Request`` with controllable disconnect.

    ``is_disconnected`` is awaited each iteration of the helper's loop, so the
    counter lets a test transition from "still connected" to "disconnected"
    after N polls without racing the event loop.
    """

    disconnect_after: int = 10**9  # effectively "never" by default
    headers: dict[str, str] = field(default_factory=dict)
    _polls: int = 0

    async def is_disconnected(self) -> bool:
        self._polls += 1
        return self._polls > self.disconnect_after


class _MissingStreamBridge:
    """Bridge stub that can report no retained stream for terminal records."""

    supports_cross_process = True

    def __init__(self) -> None:
        self.subscribed = False

    async def publish(self, run_id, event, data):
        return None

    async def publish_end(self, run_id):
        return None

    async def stream_exists(self, run_id: str) -> bool:
        return False

    def subscribe(self, run_id, *, last_event_id=None, heartbeat_interval=15.0):
        self.subscribed = True
        raise AssertionError("terminal missing streams should end before subscribing")

    async def cleanup(self, run_id, *, delay=0):
        return None


class _FastHeartbeatBridge(MemoryStreamBridge):
    """Memory bridge with a short heartbeat for durable-status refresh tests."""

    def subscribe(self, run_id, *, last_event_id=None, heartbeat_interval=15.0):
        return super().subscribe(
            run_id,
            last_event_id=last_event_id,
            heartbeat_interval=0.01,
        )


class _FailingBridge:
    """Fails before yielding: the client remains connected."""

    def subscribe(self, run_id, *, last_event_id=None, heartbeat_interval=15.0):
        async def _gen():
            raise RuntimeError("stream bridge unavailable")
            yield

        return _gen()


class _BlockingBridge:
    def __init__(self) -> None:
        self.subscribed = asyncio.Event()

    def subscribe(self, run_id, *, last_event_id=None, heartbeat_interval=15.0):
        async def _gen():
            self.subscribed.set()
            await asyncio.Event().wait()
            yield

        return _gen()


class _ExhaustedBridge:
    def subscribe(self, run_id, *, last_event_id=None, heartbeat_interval=15.0):
        async def _gen():
            if False:
                yield

        return _gen()


@dataclass
class _CancelRecorder:
    cancelled: list[str] = field(default_factory=list)

    async def cancel(self, run_id: str, action: str = "interrupt") -> None:
        self.cancelled.append(run_id)


@dataclass
class _DrainingCancelRecorder(_CancelRecorder):
    async def cancel(self, run_id: str, action: str = "interrupt") -> None:
        await asyncio.sleep(0)
        self.cancelled.append(run_id)


async def _create_running_record(mgr: RunManager, *, on_disconnect: DisconnectMode) -> Any:
    record = await mgr.create_or_reject(
        THREAD_ID,
        assistant_id=None,
        on_disconnect=on_disconnect,
    )
    await mgr.set_status(record.run_id, RunStatus.running)
    return record


# ---------------------------------------------------------------------------
# Helper-level unit tests
# ---------------------------------------------------------------------------


class TestWaitForRunCompletion:
    def test_returns_when_run_publishes_end(self) -> None:
        """Happy path: helper returns once the bridge publishes END_SENTINEL."""
        from app.gateway.services import wait_for_run_completion

        async def run() -> None:
            mgr = RunManager()
            bridge = MemoryStreamBridge()
            record = await _create_running_record(mgr, on_disconnect=DisconnectMode.cancel)
            request = _FakeRequest()

            async def finish_soon() -> None:
                await asyncio.sleep(0)
                await bridge.publish(record.run_id, "values", {"messages": []})
                await mgr.set_status(record.run_id, RunStatus.success)
                await bridge.publish_end(record.run_id)

            asyncio.create_task(finish_soon())
            completed = await asyncio.wait_for(
                wait_for_run_completion(bridge, record, request, mgr),
                timeout=2.0,
            )
            assert completed is True
            assert record.status == RunStatus.success

        asyncio.run(run())

    def test_gap_resumes_from_retained_tail_until_run_ends(self) -> None:
        """The internal wait path may skip payloads but must still observe END."""
        from app.gateway.services import wait_for_run_completion

        async def run() -> None:
            mgr = RunManager()
            bridge = MemoryStreamBridge(queue_maxsize=2)
            record = await _create_running_record(mgr, on_disconnect=DisconnectMode.cancel)
            request = _FakeRequest()

            async def overrun_then_finish() -> None:
                await asyncio.sleep(0)
                for step in range(4):
                    await bridge.publish(record.run_id, "values", {"step": step})
                await asyncio.sleep(0)
                await mgr.set_status(record.run_id, RunStatus.success)
                await bridge.publish_end(record.run_id)

            asyncio.create_task(overrun_then_finish())
            completed = await asyncio.wait_for(
                wait_for_run_completion(bridge, record, request, mgr),
                timeout=2.0,
            )

            assert completed is True
            assert record.status == RunStatus.success
            assert not record.abort_event.is_set()

        asyncio.run(run())

    def test_cancels_run_on_disconnect_when_cancel_mode(self) -> None:
        """on_disconnect=cancel: real disconnect must call run_mgr.cancel()."""
        from app.gateway.services import wait_for_run_completion

        async def run() -> None:
            mgr = RunManager()
            bridge = MemoryStreamBridge()
            record = await _create_running_record(mgr, on_disconnect=DisconnectMode.cancel)
            # Attach a real (idle) task so cancel() actually has something to cancel.
            sleeper = asyncio.create_task(asyncio.sleep(30))
            record.task = sleeper
            request = _FakeRequest(disconnect_after=0)  # disconnected on first poll

            async def publish_until_cancel() -> None:
                # Emit one event so subscribe wakes up immediately; helper polls
                # is_disconnected after each yield.
                await asyncio.sleep(0)
                await bridge.publish(record.run_id, "values", {"step": 1})

            asyncio.create_task(publish_until_cancel())
            completed = await asyncio.wait_for(
                wait_for_run_completion(bridge, record, request, mgr),
                timeout=2.0,
            )

            assert completed is False
            assert record.status == RunStatus.interrupted
            # Drain the cancelled sleeper so it does not linger past the test.
            try:
                await asyncio.wait_for(sleeper, timeout=1.0)
            except asyncio.CancelledError:
                pass
            assert sleeper.done()

        asyncio.run(run())

    def test_does_not_cancel_when_continue_mode(self) -> None:
        """on_disconnect=continue: disconnect must NOT cancel the run."""
        from app.gateway.services import wait_for_run_completion

        async def run() -> None:
            mgr = RunManager()
            bridge = MemoryStreamBridge()
            record = await _create_running_record(mgr, on_disconnect=DisconnectMode.continue_)
            sleeper = asyncio.create_task(asyncio.sleep(30))
            record.task = sleeper
            request = _FakeRequest(disconnect_after=0)

            async def publish_then_end() -> None:
                await asyncio.sleep(0)
                await bridge.publish(record.run_id, "values", {"step": 1})

            asyncio.create_task(publish_then_end())
            completed = await asyncio.wait_for(
                wait_for_run_completion(bridge, record, request, mgr),
                timeout=2.0,
            )

            # Disconnected before END — helper still reports incomplete so the
            # caller skips checkpoint serialization, but the run keeps going.
            assert completed is False
            assert record.status == RunStatus.running
            sleeper.cancel()

        asyncio.run(run())

    def test_bridge_failure_does_not_apply_disconnect_policy(self) -> None:
        """A server-side subscription failure is not a client disconnect."""
        from app.gateway.services import wait_for_run_completion

        async def run() -> None:
            record = RunRecord(
                run_id="run-bridge-failure",
                thread_id=THREAD_ID,
                assistant_id=None,
                status=RunStatus.running,
                on_disconnect=DisconnectMode.cancel,
            )
            recorder = _CancelRecorder()

            try:
                await wait_for_run_completion(_FailingBridge(), record, _FakeRequest(), recorder)
            except RuntimeError as exc:
                assert str(exc) == "stream bridge unavailable"
            else:
                raise AssertionError("bridge failure must propagate")

            assert recorder.cancelled == []

        asyncio.run(run())

    def test_request_task_cancellation_applies_disconnect_policy(self) -> None:
        """Cancelling the hosting request task retains disconnect semantics."""
        from app.gateway.services import wait_for_run_completion

        async def run() -> None:
            record = RunRecord(
                run_id="run-request-cancelled",
                thread_id=THREAD_ID,
                assistant_id=None,
                status=RunStatus.running,
                on_disconnect=DisconnectMode.cancel,
            )
            bridge = _BlockingBridge()
            recorder = _CancelRecorder()
            wait_task = asyncio.create_task(wait_for_run_completion(bridge, record, _FakeRequest(), recorder))
            await bridge.subscribed.wait()

            wait_task.cancel()
            try:
                await wait_task
            except asyncio.CancelledError:
                pass
            else:
                raise AssertionError("cancelled request task must propagate cancellation")

            assert recorder.cancelled == ["run-request-cancelled"]

        asyncio.run(run())

    def test_anyio_cancel_scope_drains_disconnect_policy(self) -> None:
        """Level cancellation cannot interrupt the owned run-cancel operation."""
        from app.gateway.services import wait_for_run_completion

        async def run() -> None:
            record = RunRecord(
                run_id="run-request-cancelled",
                thread_id=THREAD_ID,
                assistant_id=None,
                status=RunStatus.running,
                on_disconnect=DisconnectMode.cancel,
            )
            bridge = _BlockingBridge()
            recorder = _DrainingCancelRecorder()

            with anyio.CancelScope() as scope:
                scope.cancel()
                await wait_for_run_completion(bridge, record, _FakeRequest(), recorder)

            assert recorder.cancelled == ["run-request-cancelled"]

        anyio.run(run)

    def test_unexpected_subscription_exhaustion_does_not_cancel(self) -> None:
        """A subscription ending without END is a server error, not disconnect."""
        from app.gateway.services import wait_for_run_completion

        async def run() -> None:
            record = RunRecord(
                run_id="run-bridge-exhausted",
                thread_id=THREAD_ID,
                assistant_id=None,
                status=RunStatus.running,
                on_disconnect=DisconnectMode.cancel,
            )
            recorder = _CancelRecorder()

            try:
                await wait_for_run_completion(_ExhaustedBridge(), record, _FakeRequest(), recorder)
            except RuntimeError as exc:
                assert str(exc) == "stream bridge subscription ended before a terminal event"
            else:
                raise AssertionError("unexpected bridge exhaustion must fail")

            assert recorder.cancelled == []

        asyncio.run(run())

    def test_no_cancel_when_run_already_finished(self) -> None:
        """If the run ended (END_SENTINEL) before disconnect is observed, the
        finally block must not call cancel — the run is already terminal."""
        from app.gateway.services import wait_for_run_completion

        async def run() -> None:
            mgr = RunManager()
            bridge = MemoryStreamBridge()
            record = await _create_running_record(mgr, on_disconnect=DisconnectMode.cancel)
            # Publish END before subscribe — helper should see ended=True first
            # poll and return without ever observing the "disconnect".
            await mgr.set_status(record.run_id, RunStatus.success)
            await bridge.publish_end(record.run_id)
            request = _FakeRequest(disconnect_after=0)

            completed = await asyncio.wait_for(
                wait_for_run_completion(bridge, record, request, mgr),
                timeout=2.0,
            )

            assert completed is True
            assert record.status == RunStatus.success

        asyncio.run(run())

    def test_terminal_missing_stream_returns_complete(self) -> None:
        """A known-terminal run with cleaned-up stream should not wait forever."""
        from app.gateway.services import wait_for_run_completion

        async def run() -> None:
            mgr = RunManager()
            bridge = _MissingStreamBridge()
            record = RunRecord(
                run_id="terminal-missing-run",
                thread_id=THREAD_ID,
                assistant_id=None,
                status=RunStatus.success,
                on_disconnect=DisconnectMode.cancel,
                store_only=True,
            )
            request = _FakeRequest()

            completed = await wait_for_run_completion(bridge, record, request, mgr)

            assert completed is True
            assert bridge.subscribed is False

        asyncio.run(run())

    def test_sse_consumer_terminal_missing_stream_yields_end(self) -> None:
        """Joining a terminal store-only run with no stream should emit a terminal SSE."""
        from app.gateway.services import sse_consumer

        async def run() -> None:
            mgr = RunManager()
            bridge = _MissingStreamBridge()
            record = RunRecord(
                run_id="terminal-missing-run",
                thread_id=THREAD_ID,
                assistant_id=None,
                status=RunStatus.success,
                on_disconnect=DisconnectMode.cancel,
                store_only=True,
            )
            request = _FakeRequest()

            frames = [frame async for frame in sse_consumer(bridge, record, request, mgr)]

            assert frames == ["event: end\ndata: null\n\n"]
            assert bridge.subscribed is False

        asyncio.run(run())

    def test_sse_consumer_preserves_tail_events_after_durable_terminal_status(self) -> None:
        """A durable terminal row must not overtake delayed error and END events."""
        from app.gateway.services import sse_consumer
        from deerflow.runtime.runs.store.memory import MemoryRunStore

        async def run() -> None:
            store = MemoryRunStore()
            await store.put(
                "periodic-orphan",
                thread_id=THREAD_ID,
                status="running",
            )
            mgr = RunManager(store=store)
            record = await mgr.get("periodic-orphan")
            assert record is not None
            assert record.store_only is True
            bridge = _FastHeartbeatBridge()
            await bridge.publish(record.run_id, "values", {"step": 1})
            request = _FakeRequest()
            consumer = sse_consumer(bridge, record, request, mgr)

            first_frame = await anext(consumer)
            assert first_frame.startswith("event: values\n")

            await store.update_status(record.run_id, "error", error="lease expired")

            async def publish_tail() -> None:
                await asyncio.sleep(0.05)
                await bridge.publish(record.run_id, "error", {"message": "late error"})
                await bridge.publish_end(record.run_id)

            publisher = asyncio.create_task(publish_tail())
            tail_frames = [frame async for frame in consumer]
            await publisher

            error_index = next(index for index, frame in enumerate(tail_frames) if frame.startswith("event: error\n"))
            end_index = next(index for index, frame in enumerate(tail_frames) if frame.startswith("event: end\n"))
            assert error_index < end_index
            assert record.status == RunStatus.running

        asyncio.run(run())

    def test_wait_preserves_tail_events_after_durable_terminal_status(self) -> None:
        """The wait path must remain blocked until the real END is published."""
        from app.gateway.services import wait_for_run_completion
        from deerflow.runtime.runs.store.memory import MemoryRunStore

        async def run() -> None:
            store = MemoryRunStore()
            await store.put(
                "periodic-orphan",
                thread_id=THREAD_ID,
                status="running",
            )
            mgr = RunManager(store=store)
            record = await mgr.get("periodic-orphan")
            assert record is not None
            assert record.store_only is True
            bridge = _FastHeartbeatBridge()
            await bridge.publish(record.run_id, "values", {"step": 1})
            await store.update_status(record.run_id, "error", error="lease expired")

            wait_task = asyncio.create_task(wait_for_run_completion(bridge, record, _FakeRequest(), mgr))
            await asyncio.sleep(0.05)
            assert wait_task.done() is False

            await bridge.publish(record.run_id, "error", {"message": "late error"})
            await asyncio.sleep(0)
            assert wait_task.done() is False

            await bridge.publish_end(record.run_id)
            completed = await asyncio.wait_for(wait_task, timeout=1.0)

            assert completed is True
            assert record.status == RunStatus.running

        asyncio.run(run())

    def test_sse_consumer_uses_explicit_orphan_recovery_liveness_boundary(
        self,
    ) -> None:
        """A recovered orphan may synthesize END when its publisher is gone."""
        from app.gateway.services import sse_consumer
        from deerflow.runtime.runs.store.memory import MemoryRunStore

        async def run() -> None:
            store = MemoryRunStore()
            await store.put(
                "periodic-orphan",
                thread_id=THREAD_ID,
                status="running",
            )
            mgr = RunManager(store=store)
            record = await mgr.get("periodic-orphan")
            assert record is not None
            bridge = _FastHeartbeatBridge()
            await bridge.publish(record.run_id, "values", {"step": 1})
            consumer = sse_consumer(bridge, record, _FakeRequest(), mgr)
            assert (await anext(consumer)).startswith("event: values\n")

            await store.update_status(
                record.run_id,
                "error",
                error="lease expired",
                stop_reason=ORPHAN_RECOVERY_STOP_REASON,
            )

            end_frame = await asyncio.wait_for(anext(consumer), timeout=1.0)
            assert end_frame == "event: end\ndata: null\n\n"

        asyncio.run(run())

    def test_wait_uses_explicit_orphan_recovery_liveness_boundary(self) -> None:
        """The non-streaming consumer shares the recovered-orphan boundary."""
        from app.gateway.services import wait_for_run_completion
        from deerflow.runtime.runs.store.memory import MemoryRunStore

        async def run() -> None:
            store = MemoryRunStore()
            await store.put(
                "periodic-orphan",
                thread_id=THREAD_ID,
                status="running",
            )
            mgr = RunManager(store=store)
            record = await mgr.get("periodic-orphan")
            assert record is not None
            bridge = _FastHeartbeatBridge()
            await bridge.publish(record.run_id, "values", {"step": 1})
            await store.update_status(
                record.run_id,
                "error",
                error="lease expired",
                stop_reason=ORPHAN_RECOVERY_STOP_REASON,
            )

            completed = await asyncio.wait_for(
                wait_for_run_completion(bridge, record, _FakeRequest(), mgr),
                timeout=1.0,
            )

            assert completed is True

        asyncio.run(run())

    def test_wait_completes_after_cancel_takeover_of_crashed_owner(self) -> None:
        """A cancel takeover must wake a waiting consumer; no producer survives.

        Regression: the takeover path wrote ``error`` without the
        orphan-recovery stop reason, so ``/wait`` (and SSE joins) kept looping
        on heartbeats waiting for an END the dead owner can no longer publish.
        """
        from datetime import UTC, datetime, timedelta

        from app.gateway.services import wait_for_run_completion
        from deerflow.config.run_ownership_config import RunOwnershipConfig
        from deerflow.runtime.runs.store.memory import MemoryRunStore

        async def run() -> None:
            store = MemoryRunStore()
            grace = 10
            expired_lease = (datetime.now(UTC) - timedelta(seconds=grace + 5)).isoformat()
            await store.put(
                "takeover-wait",
                thread_id=THREAD_ID,
                status="running",
                created_at=datetime.now(UTC).isoformat(),
                owner_worker_id="dead-worker",
                lease_expires_at=expired_lease,
            )
            mgr = RunManager(
                store=store,
                run_ownership_config=RunOwnershipConfig(lease_seconds=30, grace_seconds=grace, heartbeat_enabled=True),
            )
            record = await mgr.get("takeover-wait")
            assert record is not None
            assert record.store_only is True

            outcome = await mgr.cancel("takeover-wait", action="interrupt")
            assert outcome == CancelOutcome.taken_over

            bridge = _FastHeartbeatBridge()
            completed = await asyncio.wait_for(
                wait_for_run_completion(bridge, record, _FakeRequest(), mgr),
                timeout=1.0,
            )

            assert completed is True

        asyncio.run(run())


@pytest.mark.asyncio
@pytest.mark.parametrize("consumer_kind", ["sse", "wait"])
@pytest.mark.parametrize("recovery_path", ["occurrence", "once"])
async def test_scheduler_recovery_completes_subscribed_consumers(tmp_path, consumer_kind, recovery_path) -> None:
    """Both scheduler recovery paths terminate already-subscribed consumers."""
    from datetime import UTC, datetime, timedelta

    from app.gateway.services import sse_consumer, wait_for_run_completion
    from deerflow.config.database_config import DatabaseConfig
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine_from_config
    from deerflow.persistence.run import RunRepository
    from deerflow.persistence.scheduled_task_runs import ScheduledTaskRunRepository
    from deerflow.persistence.scheduled_tasks import ScheduledTaskRepository
    from deerflow.runtime import RunManager, RunStatus

    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    consumer_task = None
    try:
        session_factory = get_session_factory()
        assert session_factory is not None
        task_repo = ScheduledTaskRepository(session_factory)
        occurrence_repo = ScheduledTaskRunRepository(session_factory)
        run_repo = RunRepository(session_factory)
        now = datetime.now(UTC)
        await task_repo.create(
            task_id="orphan-task",
            user_id="user-1",
            thread_id="orphan-thread",
            context_mode="reuse_thread",
            assistant_id="lead_agent",
            title="Recovered task",
            prompt="test",
            schedule_type="once" if recovery_path == "once" else "cron",
            schedule_spec={"run_at": now.isoformat()} if recovery_path == "once" else {"cron": "* * * * *"},
            timezone="UTC",
            next_run_at=None,
        )
        await occurrence_repo.create(
            run_record_id="orphan-occurrence",
            task_id="orphan-task",
            thread_id="orphan-thread",
            scheduled_for=now,
            trigger="scheduled",
            status="running",
        )
        await occurrence_repo.update_status("orphan-occurrence", status="running", run_id="orphan-run")
        if recovery_path == "once":
            await task_repo.update("orphan-task", user_id="user-1", updates={"status": "running"})
        await run_repo.put(
            "orphan-run",
            thread_id="orphan-thread",
            user_id="user-1",
            status="running",
            owner_worker_id="dead-worker",
            lease_expires_at=(now - timedelta(seconds=60)).isoformat(),
        )
        manager = RunManager(store=run_repo)
        record = await manager.get("orphan-run", user_id="user-1")
        assert record is not None and record.store_only
        assert record.status == RunStatus.running
        subscribed = asyncio.Event()

        class SubscribedBridge(_FastHeartbeatBridge):
            def subscribe(self, run_id, **kwargs):
                subscribed.set()
                return super().subscribe(run_id, **kwargs)

        bridge = SubscribedBridge()
        await bridge.publish(record.run_id, "values", {"step": 1})

        async def consume():
            if consumer_kind == "wait":
                return await wait_for_run_completion(bridge, record, _FakeRequest(), manager)
            return [frame async for frame in sse_consumer(bridge, record, _FakeRequest(), manager)]

        consumer_task = asyncio.create_task(consume())
        await asyncio.wait_for(subscribed.wait(), timeout=1.0)
        assert not consumer_task.done()
        recover = task_repo.reconcile_stuck_once_tasks if recovery_path == "once" else occurrence_repo.reconcile_active_runs
        await recover(error="crashed owner", now=now)
        recovered = await run_repo.get(record.run_id, user_id="user-1")
        assert recovered is not None
        assert recovered["status"] == "error"
        assert recovered["stop_reason"] == "scheduled_task_orphan_recovered"
        result = await asyncio.wait_for(consumer_task, timeout=1.0)
        if consumer_kind == "wait":
            assert result is True
        else:
            assert result[-1] == "event: end\ndata: null\n\n"
    finally:
        if consumer_task is not None and not consumer_task.done():
            consumer_task.cancel()
            await asyncio.gather(consumer_task, return_exceptions=True)
        await close_engine()


@pytest.mark.parametrize("route_name", ["stateless_wait", "thread_wait", "cancel_wait", "cancel_stream_wait"])
def test_wait_routes_propagate_bridge_failures(route_name: str) -> None:
    """Every wait caller must preserve infrastructure failures as errors."""
    from app.gateway.routers import runs, thread_runs

    error = RuntimeError("stream bridge unavailable")
    request = SimpleNamespace()
    body = thread_runs.RunCreateRequest(config={"configurable": {"thread_id": THREAD_ID}})
    record = SimpleNamespace(
        run_id="run-route-bridge-failure",
        thread_id=THREAD_ID,
        task=object(),
        store_only=False,
        status=RunStatus.running,
        error=None,
        idempotency_reused=False,
    )
    bridge = SimpleNamespace(supports_cross_process=True)
    manager = SimpleNamespace(
        get=AsyncMock(return_value=record),
        cancel=AsyncMock(return_value=CancelOutcome.requested),
    )

    async def run() -> None:
        if route_name == "stateless_wait":
            with (
                patch.object(runs, "get_stream_bridge", return_value=bridge),
                patch.object(runs, "get_run_manager", return_value=manager),
                patch.object(runs, "start_run", AsyncMock(return_value=record)),
                patch.object(runs, "wait_for_run_completion", AsyncMock(side_effect=error)),
            ):
                await call_unwrapped(runs.stateless_wait, body, request)
            return

        if route_name == "thread_wait":
            with (
                patch.object(thread_runs, "get_stream_bridge", return_value=bridge),
                patch.object(thread_runs, "get_run_manager", return_value=manager),
                patch.object(thread_runs, "start_run", AsyncMock(return_value=record)),
                patch.object(thread_runs, "wait_for_run_completion", AsyncMock(side_effect=error)),
            ):
                await call_unwrapped(thread_runs.wait_run, THREAD_ID, body, request)
            return

        record.task = None
        record.store_only = True
        with (
            patch.object(thread_runs, "_require_run_visible_to_scope", AsyncMock()),
            patch.object(thread_runs, "get_stream_bridge", return_value=bridge),
            patch.object(thread_runs, "get_run_manager", return_value=manager),
            patch.object(thread_runs, "require_cancel_permission_when_action"),
            patch.object(thread_runs, "wait_for_run_completion", AsyncMock(side_effect=error)),
        ):
            if route_name == "cancel_wait":
                await call_unwrapped(
                    thread_runs.cancel_run,
                    THREAD_ID,
                    record.run_id,
                    request,
                    wait=True,
                    action="interrupt",
                )
            else:
                await thread_runs._stream_existing_run(
                    THREAD_ID,
                    record.run_id,
                    request,
                    action="interrupt",
                    wait=1,
                )

    with pytest.raises(RuntimeError, match="stream bridge unavailable"):
        asyncio.run(run())
