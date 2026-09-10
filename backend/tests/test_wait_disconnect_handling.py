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
events have already been published. A durable ``orphan_recovered`` stop reason
provides the narrow heartbeat fallback when the publisher is known to be gone.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from deerflow.runtime import LOCAL_FINALIZER_PENDING_STOP_REASON, ORPHAN_RECOVERY_STOP_REASON, RunManager, RunStatus
from deerflow.runtime.events.store.memory import MemoryRunEventStore
from deerflow.runtime.runs.schemas import DisconnectMode
from deerflow.runtime.runs.terminal_events import (
    persist_run_delivery_receipt,
    persist_run_terminal_event,
)
from deerflow.runtime.stream_bridge.memory import MemoryStreamBridge
from deerflow.runtime.user_context import get_current_user

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


class _FailingEndBridge(_FastHeartbeatBridge):
    """Model a transient Redis END-publication failure after durable commit."""

    async def publish_end(self, run_id: str) -> None:
        raise RuntimeError("simulated END publication failure")


class _OwnerCapturingReadEventStore(MemoryRunEventStore):
    """Records the identity used by the receipt fallback read."""

    def __init__(self) -> None:
        super().__init__()
        self.read_user_ids: list[str | None] = []

    async def list_events(self, *args, **kwargs):
        user = get_current_user()
        self.read_user_ids.append(user.id if user is not None else None)
        return await super().list_events(*args, **kwargs)


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

    def test_terminal_missing_stream_with_receipt_returns_complete(self) -> None:
        """A cleaned-up stream may end once its durable tail receipt exists."""
        from app.gateway.services import wait_for_run_completion
        from deerflow.runtime.runs.store.memory import MemoryRunStore

        async def run() -> None:
            store = MemoryRunStore()
            events = MemoryRunEventStore()
            await store.put(
                "terminal-missing-run",
                thread_id=THREAD_ID,
                status=RunStatus.success.value,
            )
            await persist_run_delivery_receipt(
                events,
                thread_id=THREAD_ID,
                run_id="terminal-missing-run",
                content={"presented": 0, "paths": [], "by_tool": {}},
            )
            mgr = RunManager(store=store, event_store=events)
            bridge = _MissingStreamBridge()
            record = await mgr.get("terminal-missing-run")
            assert record is not None
            request = _FakeRequest()

            completed = await wait_for_run_completion(bridge, record, request, mgr)

            assert completed is True
            assert bridge.subscribed is False

        asyncio.run(run())

    def test_sse_consumer_terminal_missing_stream_with_receipt_yields_end(self) -> None:
        """A missing stream is recoverable only with durable tail evidence."""
        from app.gateway.services import sse_consumer
        from deerflow.runtime.runs.store.memory import MemoryRunStore

        async def run() -> None:
            store = MemoryRunStore()
            events = MemoryRunEventStore()
            await store.put(
                "terminal-missing-run",
                thread_id=THREAD_ID,
                status=RunStatus.success.value,
            )
            await persist_run_delivery_receipt(
                events,
                thread_id=THREAD_ID,
                run_id="terminal-missing-run",
                content={"presented": 0, "paths": [], "by_tool": {}},
            )
            mgr = RunManager(store=store, event_store=events)
            bridge = _MissingStreamBridge()
            record = await mgr.get("terminal-missing-run")
            assert record is not None
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

    @pytest.mark.parametrize("consumer_kind", ["sse", "wait"])
    @pytest.mark.parametrize("failure_mode", ["worker_crash", "publish_end_failure"])
    def test_delivery_receipt_recovers_missing_bridge_end(
        self,
        consumer_kind: str,
        failure_mode: str,
    ) -> None:
        """A terminal row plus its tail receipt is a durable END outbox."""
        from app.gateway.services import sse_consumer, wait_for_run_completion
        from deerflow.runtime.runs.store.memory import MemoryRunStore

        async def run() -> None:
            store = MemoryRunStore()
            events = _OwnerCapturingReadEventStore()
            await store.put(
                "terminal-with-receipt",
                thread_id=THREAD_ID,
                status="running",
                user_id="run-owner",
            )
            mgr = RunManager(store=store, event_store=events)
            record = await mgr.get("terminal-with-receipt", user_id="run-owner")
            assert record is not None
            assert record.store_only is True

            bridge: _FastHeartbeatBridge
            if failure_mode == "publish_end_failure":
                bridge = _FailingEndBridge()
            else:
                bridge = _FastHeartbeatBridge()
            await bridge.publish(record.run_id, "values", {"step": 1})

            if consumer_kind == "sse":
                consumer = sse_consumer(bridge, record, _FakeRequest(), mgr)
                assert (await anext(consumer)).startswith("event: values\n")
                waiter = None
            else:
                waiter = asyncio.create_task(wait_for_run_completion(bridge, record, _FakeRequest(), mgr))
                await asyncio.sleep(0)

            # This is the worker's established ordering: all tail frames, then
            # the singleton receipt, then the authoritative terminal RunRow.
            await persist_run_delivery_receipt(
                events,
                thread_id=record.thread_id,
                run_id=record.run_id,
                content={"presented": 1, "paths": [], "by_tool": {}},
                user_id=record.user_id,
            )
            await store.update_status(record.run_id, "success")

            if failure_mode == "publish_end_failure":
                with pytest.raises(RuntimeError, match="END publication failure"):
                    await bridge.publish_end(record.run_id)
            # worker_crash intentionally performs no publish_end call.

            if consumer_kind == "sse":
                assert await asyncio.wait_for(anext(consumer), timeout=1.0) == ("event: end\ndata: null\n\n")
            else:
                assert waiter is not None
                assert await asyncio.wait_for(waiter, timeout=1.0)
            assert events.read_user_ids
            assert set(events.read_user_ids) == {"run-owner"}

        asyncio.run(run())

    @pytest.mark.parametrize("consumer_kind", ["sse", "wait"])
    def test_authoritative_run_end_recovers_when_receipt_and_bridge_end_fail(
        self,
        consumer_kind: str,
    ) -> None:
        """A marked run.end is the fallback outbox when run.delivery is absent."""
        from app.gateway.services import sse_consumer, wait_for_run_completion
        from deerflow.runtime.runs.store.memory import MemoryRunStore

        async def run() -> None:
            store = MemoryRunStore()
            events = _OwnerCapturingReadEventStore()
            await store.put(
                "terminal-with-authoritative-end",
                thread_id=THREAD_ID,
                status=RunStatus.running.value,
                user_id="run-owner",
            )
            mgr = RunManager(store=store, event_store=events)
            record = await mgr.get(
                "terminal-with-authoritative-end",
                user_id="run-owner",
            )
            assert record is not None and record.store_only

            bridge = _FailingEndBridge()
            await bridge.publish(record.run_id, "values", {"step": 1})
            if consumer_kind == "sse":
                consumer = sse_consumer(bridge, record, _FakeRequest(), mgr)
                assert (await anext(consumer)).startswith("event: values\n")
                waiter = None
            else:
                waiter = asyncio.create_task(wait_for_run_completion(bridge, record, _FakeRequest(), mgr))
                await asyncio.sleep(0)

            # Model the real failure order: run.delivery exhausted its retries,
            # the terminal row committed, marked run.end succeeded, then Redis
            # END publication failed. No delivery receipt is written here.
            await store.update_status(record.run_id, RunStatus.success.value)
            await persist_run_terminal_event(
                events,
                thread_id=record.thread_id,
                run_id=record.run_id,
                status=RunStatus.success,
                user_id=record.user_id,
            )
            with pytest.raises(RuntimeError, match="END publication failure"):
                await bridge.publish_end(record.run_id)

            if consumer_kind == "sse":
                assert await asyncio.wait_for(anext(consumer), timeout=1.0) == ("event: end\ndata: null\n\n")
            else:
                assert waiter is not None
                assert await asyncio.wait_for(waiter, timeout=1.0)

            assert not await MemoryRunEventStore.list_events(
                events,
                record.thread_id,
                record.run_id,
                event_types=["run.delivery"],
            )
            assert events.read_user_ids
            assert set(events.read_user_ids) == {"run-owner"}

        asyncio.run(run())

    def test_live_local_finalizer_marker_does_not_synthesize_end(self) -> None:
        """A consumer cannot race a finalizer that still owns a live lease."""
        from app.gateway.services import _terminal_completion_observed_after_heartbeat
        from deerflow.runtime.runs.store.memory import MemoryRunStore

        async def run() -> None:
            store = MemoryRunStore()
            await store.put(
                "live-local-finalizer",
                thread_id=THREAD_ID,
                status=RunStatus.interrupted.value,
                owner_worker_id="worker-a",
                lease_expires_at=(datetime.now(UTC) + timedelta(seconds=30)).isoformat(),
                stop_reason=LOCAL_FINALIZER_PENDING_STOP_REASON,
            )
            mgr = RunManager(store=store, worker_id="worker-b")
            record = await mgr.get("live-local-finalizer")
            assert record is not None and record.store_only

            assert await _terminal_completion_observed_after_heartbeat(record, mgr) is False
            stored = await store.get(record.run_id)
            assert stored["owner_worker_id"] == "worker-a"
            assert stored["stop_reason"] == LOCAL_FINALIZER_PENDING_STOP_REASON

        asyncio.run(run())

    def test_expired_local_finalizer_is_atomically_recovered(self) -> None:
        """Expiry must be won by a store CAS before a consumer synthesizes END."""
        from app.gateway.services import _terminal_completion_observed_after_heartbeat
        from deerflow.runtime.runs.store.memory import MemoryRunStore

        async def run() -> None:
            store = MemoryRunStore()
            events = MemoryRunEventStore()
            await store.put(
                "expired-local-finalizer",
                thread_id=THREAD_ID,
                status=RunStatus.interrupted.value,
                owner_worker_id="worker-a",
                lease_expires_at=(datetime.now(UTC) - timedelta(seconds=30)).isoformat(),
                stop_reason=LOCAL_FINALIZER_PENDING_STOP_REASON,
            )
            mgr = RunManager(
                store=store,
                event_store=events,
                worker_id="worker-b",
            )
            record = await mgr.get("expired-local-finalizer")
            assert record is not None

            assert await _terminal_completion_observed_after_heartbeat(record, mgr) is True
            stored = await store.get(record.run_id)
            assert stored["owner_worker_id"] == "worker-b"
            assert stored["stop_reason"] == ORPHAN_RECOVERY_STOP_REASON
            assert (
                len(
                    await events.list_events(
                        THREAD_ID,
                        record.run_id,
                        event_types=["run.delivery"],
                    )
                )
                == 1
            )

        asyncio.run(run())

    def test_local_finalizer_receipt_allows_immediate_end_without_claim(self) -> None:
        from app.gateway.services import _terminal_completion_observed_after_heartbeat
        from deerflow.runtime.runs.store.memory import MemoryRunStore

        async def run() -> None:
            store = MemoryRunStore()
            events = MemoryRunEventStore()
            live = (datetime.now(UTC) + timedelta(seconds=30)).isoformat()
            await store.put(
                "received-local-finalizer",
                thread_id=THREAD_ID,
                status=RunStatus.interrupted.value,
                owner_worker_id="worker-a",
                lease_expires_at=live,
                stop_reason=LOCAL_FINALIZER_PENDING_STOP_REASON,
            )
            await persist_run_delivery_receipt(
                events,
                thread_id=THREAD_ID,
                run_id="received-local-finalizer",
                content={"presented": 0, "paths": [], "by_tool": {}},
            )
            mgr = RunManager(
                store=store,
                event_store=events,
                worker_id="worker-b",
            )
            record = await mgr.get("received-local-finalizer")
            assert record is not None

            assert await _terminal_completion_observed_after_heartbeat(record, mgr) is True
            stored = await store.get(record.run_id)
            assert stored["owner_worker_id"] == "worker-a"
            assert stored["stop_reason"] == LOCAL_FINALIZER_PENDING_STOP_REASON

        asyncio.run(run())

    def test_missing_stream_still_requires_authoritative_completion_evidence(
        self,
    ) -> None:
        from app.gateway.services import _terminal_record_stream_missing
        from deerflow.runtime.runs.store.memory import MemoryRunStore

        async def run() -> None:
            store = MemoryRunStore()
            await store.put(
                "terminal-without-tail-evidence",
                thread_id=THREAD_ID,
                status=RunStatus.success.value,
            )
            events = MemoryRunEventStore()
            # An older runtime's unmarked run.end is intentionally not enough:
            # its ordering relative to late visible frames is unknown.
            await events.put(
                thread_id=THREAD_ID,
                run_id="terminal-without-tail-evidence",
                event_type="run.end",
                category="outputs",
                content={},
                metadata={"status": RunStatus.success.value},
            )
            mgr = RunManager(store=store, event_store=events)
            record = await mgr.get("terminal-without-tail-evidence")
            assert record is not None

            assert (
                await _terminal_record_stream_missing(
                    MemoryStreamBridge(),
                    record,
                    mgr,
                )
                is False
            )

        asyncio.run(run())

    @pytest.mark.parametrize("stop_reason", [ORPHAN_RECOVERY_STOP_REASON, "scheduled_task_orphan_recovered"])
    def test_sse_consumer_uses_explicit_orphan_recovery_liveness_boundary(
        self,
        stop_reason: str,
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
                stop_reason=stop_reason,
            )

            end_frame = await asyncio.wait_for(anext(consumer), timeout=1.0)
            assert end_frame == "event: end\ndata: null\n\n"

        asyncio.run(run())

    @pytest.mark.parametrize("stop_reason", [ORPHAN_RECOVERY_STOP_REASON, "scheduled_task_orphan_recovered"])
    def test_wait_uses_explicit_orphan_recovery_liveness_boundary(self, stop_reason: str) -> None:
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
                stop_reason=stop_reason,
            )

            completed = await asyncio.wait_for(
                wait_for_run_completion(bridge, record, _FakeRequest(), mgr),
                timeout=1.0,
            )

            assert completed is True

        asyncio.run(run())

    @pytest.mark.parametrize("consumer_kind", ["sse", "wait"])
    def test_recovery_liveness_refreshes_a_stale_idempotent_snapshot(
        self,
        consumer_kind: str,
    ) -> None:
        """A cached idempotent retry must still observe a peer recovery."""
        from app.gateway.services import sse_consumer, wait_for_run_completion
        from deerflow.runtime.runs.store.memory import MemoryRunStore

        async def run() -> None:
            store = MemoryRunStore()
            await store.put(
                "idempotent-orphan",
                thread_id=THREAD_ID,
                status="running",
                user_id="user-1",
                idempotency_key="scheduled-task:retry-1",
            )
            mgr = RunManager(store=store)
            record = await mgr.create_or_reject(
                THREAD_ID,
                user_id="user-1",
                idempotency_key="scheduled-task:retry-1",
            )
            assert record.idempotency_reused is True
            assert record.store_only is True
            assert record.run_id not in mgr._runs

            bridge = _FastHeartbeatBridge()
            await bridge.publish(record.run_id, "values", {"step": 1})

            if consumer_kind == "sse":
                consumer = sse_consumer(bridge, record, _FakeRequest(), mgr)
                assert (await anext(consumer)).startswith("event: values\n")

            await store.update_status(
                record.run_id,
                "error",
                error="lease expired",
                stop_reason=ORPHAN_RECOVERY_STOP_REASON,
            )

            if consumer_kind == "sse":
                assert await asyncio.wait_for(anext(consumer), timeout=1.0) == "event: end\ndata: null\n\n"
            else:
                assert await asyncio.wait_for(
                    wait_for_run_completion(bridge, record, _FakeRequest(), mgr),
                    timeout=1.0,
                )

            # The heartbeat decision is based on a fresh snapshot; it must not
            # rewrite the cached object used by the local runtime.
            assert record.status == RunStatus.running

        asyncio.run(run())

    @pytest.mark.parametrize("consumer_kind", ["sse", "wait"])
    def test_taskless_cancel_uses_durable_liveness_when_no_end_is_published(
        self,
        consumer_kind: str,
    ) -> None:
        """A pre-worker cancellation cannot rely on a worker finally block."""
        from app.gateway.services import sse_consumer, wait_for_run_completion
        from deerflow.runtime.runs.store.memory import MemoryRunStore

        async def run() -> None:
            store = MemoryRunStore()
            mgr = RunManager(store=store)
            record = await mgr.create_or_reject(THREAD_ID, user_id="user-1")
            assert record.task is None
            assert record.store_only is False

            bridge = _FastHeartbeatBridge()
            await bridge.publish(record.run_id, "values", {"step": 1})

            if consumer_kind == "sse":
                consumer = sse_consumer(bridge, record, _FakeRequest(), mgr)
                assert (await anext(consumer)).startswith("event: values\n")
                waiter = None
            else:
                waiter = asyncio.create_task(wait_for_run_completion(bridge, record, _FakeRequest(), mgr))
                await asyncio.sleep(0)

            assert await mgr.cancel(record.run_id)
            stored = await store.get(record.run_id, user_id="user-1")
            assert stored is not None
            assert stored["stop_reason"] == ORPHAN_RECOVERY_STOP_REASON

            if consumer_kind == "sse":
                assert await asyncio.wait_for(anext(consumer), timeout=1.0) == "event: end\ndata: null\n\n"
            else:
                assert waiter is not None
                assert await asyncio.wait_for(waiter, timeout=1.0)

        asyncio.run(run())

    @pytest.mark.parametrize("consumer_kind", ["sse", "wait"])
    def test_recovery_liveness_refreshes_a_fenced_local_record(
        self,
        consumer_kind: str,
    ) -> None:
        """A local wrapper fenced before ``run_agent`` must not strand waiters."""
        from app.gateway.services import sse_consumer, wait_for_run_completion
        from deerflow.config.run_ownership_config import RunOwnershipConfig
        from deerflow.runtime.runs.store.memory import MemoryRunStore

        async def run() -> None:
            store = MemoryRunStore()
            mgr = RunManager(
                store=store,
                worker_id="worker-a",
                run_ownership_config=RunOwnershipConfig(
                    heartbeat_enabled=True,
                    lease_seconds=30,
                    grace_seconds=10,
                ),
            )
            record = await mgr.create_or_reject(THREAD_ID, user_id="user-1")
            wrapper_started = asyncio.Event()

            async def metadata_wrapper() -> None:
                wrapper_started.set()
                await asyncio.Event().wait()

            wrapper = asyncio.create_task(metadata_wrapper())
            record.task = wrapper
            await wrapper_started.wait()

            bridge = _FastHeartbeatBridge()
            await bridge.publish(record.run_id, "values", {"step": 1})
            if consumer_kind == "sse":
                consumer = sse_consumer(bridge, record, _FakeRequest(), mgr)
                assert (await anext(consumer)).startswith("event: values\n")

            await mgr._mark_ownership_lost(
                record,
                reason="lease ownership lost",
                require_active=False,
            )
            with pytest.raises(asyncio.CancelledError):
                await wrapper
            await store.update_status(
                record.run_id,
                "error",
                error="recovered by peer",
                stop_reason=ORPHAN_RECOVERY_STOP_REASON,
            )

            if consumer_kind == "sse":
                assert await asyncio.wait_for(anext(consumer), timeout=1.0) == "event: end\ndata: null\n\n"
            else:
                assert await asyncio.wait_for(
                    wait_for_run_completion(bridge, record, _FakeRequest(), mgr),
                    timeout=1.0,
                )

        asyncio.run(run())
