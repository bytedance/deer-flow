"""Regression tests for issue #3265.

The non-streaming ``/wait`` endpoints used to ``await record.task`` with no
disconnect handling and silently swallow ``CancelledError``.  When a long
tool call (e.g. ``pip install`` inside a custom skill) kept the connection
idle long enough for an intermediate HTTP layer to time out, the handler
would return a stale checkpoint that looked like a normal completion.

The fix introduces ``wait_for_run_completion`` in ``app.gateway.services``:
it subscribes to the stream bridge until ``END_SENTINEL``, polls
``request.is_disconnected()`` on every wake-up, and honours the record's
``on_disconnect`` mode by cancelling the background run on real client
disconnect.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from deerflow.runtime import RunManager, RunRecord, RunStatus
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
