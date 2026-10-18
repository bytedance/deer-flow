"""Retiring a memory stream must release its buffer and wake established readers."""

import asyncio
import json
import weakref
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from deerflow.runtime import MemoryStreamBridge, RunManager, RunStatus, StreamGap
from deerflow.runtime.runs.store.memory import MemoryRunStore
from deerflow.runtime.stream_bridge.base import END_SENTINEL, HEARTBEAT_SENTINEL


async def _finish(bridge, streams, pending=()):
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
    for stream in streams:
        await stream.aclose()
    await bridge.close()


async def _attach_behind_retirement(bridge, run_id, stream, operation, monkeypatch):
    """Queue retirement before attachment on the real Condition's fair lock."""
    condition = bridge._streams[run_id].condition
    real_acquire = condition.acquire
    retirement_queued = asyncio.Event()
    attachment_queued = asyncio.Event()
    tasks = []

    async def observe_acquire():
        if asyncio.current_task() is tasks[0]:
            retirement_queued.set()
        else:
            attachment_queued.set()
        return await real_acquire()

    try:
        async with condition:
            monkeypatch.setattr(condition, "acquire", observe_acquire)
            retirement = bridge.cleanup(run_id) if operation == "cleanup" else bridge.close()
            tasks.append(asyncio.create_task(retirement))
            await asyncio.wait_for(retirement_queued.wait(), 1)
            tasks.append(asyncio.create_task(anext(stream)))
            await asyncio.wait_for(attachment_queued.wait(), 1)
        await asyncio.wait_for(asyncio.shield(tasks[0]), 1)
        return await asyncio.wait_for(asyncio.shield(tasks[1]), 1)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["cleanup", "close"])
@pytest.mark.parametrize("ended", [False, True])
@pytest.mark.parametrize("with_cursor", [False, True])
async def test_attachment_queued_behind_retirement_reports_gap(monkeypatch, operation, ended, with_cursor):
    bridge = MemoryStreamBridge()
    await bridge.publish("attach-window", "messages", "earlier")
    await bridge.publish("attach-window", "messages", "unread")
    cursor = bridge._streams["attach-window"].events[0].id if with_cursor else None
    if ended:
        await bridge.publish_end("attach-window")
    stream = bridge.subscribe("attach-window", last_event_id=cursor)
    try:
        assert await _attach_behind_retirement(bridge, "attach-window", stream, operation, monkeypatch) == StreamGap(cursor, None, None)
        with pytest.raises(StopAsyncIteration):
            await anext(stream)
    finally:
        await _finish(bridge, [stream])


@pytest.mark.asyncio
@pytest.mark.parametrize("observer", [False, True])
@pytest.mark.parametrize("emit_gap_on_missing_stream", [False, True])
async def test_gateway_late_attachment_reloads_instead_of_reporting_an_empty_run(monkeypatch, observer, emit_gap_on_missing_stream):
    from app.gateway.services import sse_consumer

    manager = RunManager()
    bridge = MemoryStreamBridge()
    record = await manager.create("retirement-attach")
    await manager.set_status(record.run_id, RunStatus.success)
    monkeypatch.setattr(manager, "cancel", AsyncMock())
    request = SimpleNamespace(headers={}, is_disconnected=AsyncMock(return_value=False))
    await bridge.publish(record.run_id, "messages", "saved answer")
    await bridge.publish_end(record.run_id)
    stream = sse_consumer(bridge, record, request, manager, apply_on_disconnect=not observer, emit_gap_on_missing_stream=emit_gap_on_missing_stream)
    try:
        frame = await _attach_behind_retirement(bridge, record.run_id, stream, "cleanup", monkeypatch)
        assert "event: gap" in frame and "event: end" not in frame
        payload = json.loads(next(line[6:] for line in frame.splitlines() if line.startswith("data: ")))
        assert payload["recovery"] == "reload_durable_state"
        assert payload["requested_event_id"] is None
        assert payload["earliest_available_event_id"] is None
        assert payload["latest_available_event_id"] is None
        with pytest.raises(StopAsyncIteration):
            await anext(stream)
        manager.cancel.assert_not_awaited()
    finally:
        await _finish(bridge, [stream])
        await manager.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["cleanup", "close"])
@pytest.mark.parametrize("published", [False, True])
async def test_retirement_wakes_a_waiting_subscriber(monkeypatch, operation, published):
    bridge = MemoryStreamBridge(heartbeat_interval=30)
    run = "retire-waiting"
    stream = bridge.subscribe(run)
    cursor = None
    if published:
        await bridge.publish(run, "message", {"text": "partial"})
        cursor = (await anext(stream)).id
    else:
        # Establish an empty subscription, then wait on its real Condition.
        initial = bridge.subscribe(run, heartbeat_interval=0.001)
        try:
            assert await anext(initial) is HEARTBEAT_SENTINEL
        finally:
            await initial.aclose()
    condition = bridge._streams[run].condition
    entered = asyncio.Event()
    real_wait = condition.wait

    async def observe_wait():
        entered.set()
        return await real_wait()

    monkeypatch.setattr(condition, "wait", observe_wait)
    pending = asyncio.create_task(anext(stream))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        if operation == "cleanup":
            await bridge.cleanup(run)
        else:
            await bridge.close()
        assert await asyncio.wait_for(asyncio.shield(pending), 0.5) == StreamGap(cursor, None, None)
        with pytest.raises(StopAsyncIteration):
            await anext(stream)
        assert not await bridge.stream_exists(run)
    finally:
        await _finish(bridge, [stream], [pending])


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["cleanup", "close"])
@pytest.mark.parametrize("ended", [False, True])
async def test_retired_buffer_is_released_and_does_not_replay_a_stale_tail(operation, ended):
    class Payload:
        pass

    bridge = MemoryStreamBridge()
    await bridge.publish("buffer", "metadata", {})
    payload = Payload()
    reference = weakref.ref(payload)
    await bridge.publish("buffer", "messages", payload)
    del payload
    if ended:
        await bridge.publish_end("buffer")
    stream = bridge.subscribe("buffer")
    first = await anext(stream)
    try:
        if operation == "cleanup":
            await bridge.cleanup("buffer")
        else:
            await bridge.close()
        assert reference() is None, "the established generator must not retain the retired payload"
        assert await anext(stream) == StreamGap(first.id, None, None)
        with pytest.raises(StopAsyncIteration):
            await anext(stream)
    finally:
        await _finish(bridge, [stream])


@pytest.mark.asyncio
async def test_cleanup_is_scoped_and_old_readers_cannot_consume_a_recreated_stream():
    bridge = MemoryStreamBridge()
    for run in ("retired", "untouched"):
        await bridge.publish(run, "messages", {"generation": "old", "run": run})
    old = bridge.subscribe("retired")
    cursor = (await anext(old)).id
    try:
        await bridge.cleanup("retired")
        await bridge.cleanup("missing")
        await bridge.cleanup("retired")
        await bridge.publish("retired", "messages", {"generation": "new"})
        await bridge.publish_end("retired")
        await bridge.publish_end("untouched")
        assert await asyncio.wait_for(anext(old), 0.5) == StreamGap(cursor, None, None)
        replacement = [entry async for entry in bridge.subscribe("retired")]
        unaffected = [entry async for entry in bridge.subscribe("untouched")]
        assert replacement[0].data == {"generation": "new"}
        assert replacement[-1] is END_SENTINEL
        assert unaffected[0].data["run"] == "untouched"
        assert unaffected[-1] is END_SENTINEL
    finally:
        await _finish(bridge, [old])


@pytest.mark.asyncio
async def test_close_retires_all_established_readers_and_is_idempotent():
    bridge = MemoryStreamBridge()
    streams = []
    cursors = []
    try:
        for index in range(3):
            await bridge.publish(str(index), "messages", index)
            stream = bridge.subscribe(str(index))
            cursors.append((await anext(stream)).id)
            streams.append(stream)
        await bridge.close()
        await bridge.close()
        for stream, cursor in zip(streams, cursors, strict=True):
            assert await asyncio.wait_for(anext(stream), 0.5) == StreamGap(cursor, None, None)
        assert not bridge._streams and not bridge._counters
    finally:
        await _finish(bridge, streams)


@pytest.mark.asyncio
async def test_delayed_cleanup_preserves_replay_until_its_grace_expires():
    bridge = MemoryStreamBridge()
    await bridge.publish("grace", "messages", "first")
    stream = bridge.subscribe("grace")
    cleanup = asyncio.create_task(bridge.cleanup("grace", delay=0.05))
    try:
        first = await anext(stream)
        assert first.data == "first"
        assert await bridge.stream_exists("grace")
        await cleanup
        assert await asyncio.wait_for(anext(stream), 0.5) == StreamGap(first.id, None, None)
    finally:
        await _finish(bridge, [stream], [cleanup])


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["cleanup", "close"])
@pytest.mark.parametrize("count", [0, 1, 5])
async def test_fully_consumed_terminal_generation_keeps_end_even_after_recreation(operation, count):
    bridge = MemoryStreamBridge(queue_maxsize=2)
    for index in range(count):
        await bridge.publish("complete", "messages", index)
    stream = bridge.subscribe("complete", heartbeat_interval=0.001)
    try:
        if count:
            for _ in range(min(count, 2)):
                await anext(stream)
        else:
            assert await anext(stream) is HEARTBEAT_SENTINEL
        await bridge.publish_end("complete")
        if operation == "cleanup":
            await bridge.cleanup("complete")
        else:
            await bridge.close()
        await bridge.publish("complete", "messages", "replacement")
        assert await asyncio.wait_for(anext(stream), 0.5) is END_SENTINEL
        with pytest.raises(StopAsyncIteration):
            await anext(stream)
    finally:
        await _finish(bridge, [stream])


@pytest.mark.asyncio
async def test_unretired_empty_stream_heartbeats_then_delivers_normally():
    bridge = MemoryStreamBridge(heartbeat_interval=0.001)
    stream = bridge.subscribe("live")
    try:
        assert await anext(stream) is HEARTBEAT_SENTINEL
        await bridge.publish("live", "messages", "answer")
        await bridge.publish_end("live")
        entries = [entry async for entry in stream]
        assert entries[0].data == "answer"
        assert entries[-1] is END_SENTINEL
    finally:
        await _finish(bridge, [stream])


@pytest.mark.asyncio
@pytest.mark.parametrize("observer", [False, True])
@pytest.mark.parametrize("terminal", [False, True])
async def test_gateway_reports_recovery_gap_without_cancelling_a_running_run(monkeypatch, observer, terminal):
    from app.gateway.services import sse_consumer

    manager = RunManager()
    bridge = MemoryStreamBridge()
    record = await manager.create("retirement-sse")
    await manager.set_status(record.run_id, RunStatus.running)
    monkeypatch.setattr(manager, "cancel", AsyncMock())
    request = SimpleNamespace(headers={}, is_disconnected=AsyncMock(return_value=False))
    await bridge.publish(record.run_id, "messages", {"text": "partial"})
    stream = sse_consumer(bridge, record, request, manager, apply_on_disconnect=not observer)
    try:
        assert "event: messages" in await anext(stream)
        if terminal:
            await bridge.publish_end(record.run_id)
            await manager.set_status(record.run_id, RunStatus.success)
        await bridge.cleanup(record.run_id)
        frame = await asyncio.wait_for(anext(stream), 0.5)
        if terminal:
            assert "event: end" in frame and "event: gap" not in frame
        else:
            assert "event: gap" in frame and "event: end" not in frame
            payload = json.loads(next(line[6:] for line in frame.splitlines() if line.startswith("data: ")))
            assert payload["recovery"] == "reload_durable_state"
            assert payload["earliest_available_event_id"] is None
            assert payload["latest_available_event_id"] is None
        with pytest.raises(StopAsyncIteration):
            await anext(stream)
        manager.cancel.assert_not_awaited()
    finally:
        await _finish(bridge, [stream])
        await manager.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("store_only", [False, True])
async def test_gateway_wait_finishes_from_terminal_state_after_retirement(store_only):
    from app.gateway.services import wait_for_run_completion

    store = MemoryRunStore() if store_only else None
    manager = RunManager(store=store)
    bridge = MemoryStreamBridge(heartbeat_interval=30)
    if store_only:
        await store.put("retirement-wait", thread_id="retirement", status="running")
        record = await manager.get("retirement-wait")
    else:
        record = await manager.create("retirement")
        await manager.set_status(record.run_id, RunStatus.running)

    async def retire_after_first_delivery():
        if store_only:
            await store.update_status(record.run_id, "success")
        else:
            await manager.set_status(record.run_id, RunStatus.success)
        await bridge.cleanup(record.run_id)
        return False

    request = SimpleNamespace(headers={}, is_disconnected=retire_after_first_delivery)
    await bridge.publish(record.run_id, "messages", "last update")
    try:
        assert await asyncio.wait_for(wait_for_run_completion(bridge, record, request, manager), 0.5)
    finally:
        await bridge.close()
        await manager.shutdown()
