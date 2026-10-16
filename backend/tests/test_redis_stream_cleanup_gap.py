"""An established subscriber must not idle forever after retained data is deleted."""

import asyncio
import json

import anyio
import pytest
from test_stream_bridge import REDIS_TEST_URL, _DelayedBlockingReadRedis, _FakeRedis, requires_redis

from deerflow.runtime import RunManager, RunStatus, StreamGap
from deerflow.runtime.stream_bridge.base import END_SENTINEL, HEARTBEAT_SENTINEL
from deerflow.runtime.stream_bridge.redis import RedisStreamBridge


class _ConnectedRequest:
    headers = {}

    async def is_disconnected(self):
        return False


@pytest.fixture
async def cleanup_bridge(request):
    real = request.param == "redis"
    bridge = RedisStreamBridge(
        redis_url=REDIS_TEST_URL if real else "redis://fake",
        key_prefix="test-cleanup-gap",
        heartbeat_interval=0.01,
        client=None if real else _FakeRedis(),
    )
    try:
        yield bridge
    finally:
        await bridge.cleanup("cleanup-gap")
        await bridge.close()


BACKENDS = ["fake", pytest.param("redis", marks=[pytest.mark.integration, requires_redis])]


@pytest.mark.anyio
@pytest.mark.parametrize("cleanup_bridge", BACKENDS, indirect=True)
@pytest.mark.parametrize("consumed", [1, 64, 65])
async def test_deleted_observed_stream_reports_gap(cleanup_bridge, consumed):
    bridge = cleanup_bridge
    for index in range(130):
        await bridge.publish("cleanup-gap", "messages", {"index": index})
    await bridge.publish_end("cleanup-gap")
    stream = bridge.subscribe("cleanup-gap")
    try:
        cursor = None
        for _ in range(consumed):
            cursor = await anext(stream)
        await bridge.cleanup("cleanup-gap")
        # The already-fetched batch may drain, but the absent next batch is a gap.
        with anyio.fail_after(2):
            while True:
                entry = await anext(stream)
                assert entry is not HEARTBEAT_SENTINEL
                assert entry is not END_SENTINEL
                if isinstance(entry, StreamGap):
                    break
                cursor = entry
        assert entry == StreamGap(cursor.id, None, None)
        with pytest.raises(StopAsyncIteration):
            await anext(stream)
    finally:
        await stream.aclose()


@pytest.mark.anyio
@pytest.mark.parametrize("cleanup_bridge", BACKENDS, indirect=True)
async def test_unpublished_stream_still_waits_for_its_producer(cleanup_bridge):
    bridge = cleanup_bridge
    stream = bridge.subscribe("cleanup-gap")
    try:
        with anyio.fail_after(2):
            assert await anext(stream) is HEARTBEAT_SENTINEL
            await bridge.publish("cleanup-gap", "messages", {"index": 0})
            await bridge.publish_end("cleanup-gap")
            entries = [entry async for entry in stream]
        assert entries[0].data == {"index": 0}
        assert entries[-1] is END_SENTINEL
    finally:
        await stream.aclose()


@pytest.mark.anyio
@pytest.mark.parametrize("cleanup_bridge", BACKENDS, indirect=True)
async def test_deleted_stream_after_initial_wakeup_reports_gap(cleanup_bridge):
    bridge = cleanup_bridge
    delayed = _DelayedBlockingReadRedis(bridge._redis)
    bridge._redis = delayed
    stream = bridge.subscribe("cleanup-gap", heartbeat_interval=1)
    pending = asyncio.create_task(anext(stream))
    try:
        with anyio.fail_after(2):
            await delayed.blocking_read_started.wait()
            await bridge.publish("cleanup-gap", "messages", {"index": 0})
            await delayed.wake_response_captured.wait()
            await bridge.cleanup("cleanup-gap")
            delayed.release_wake_response.set()
            assert await pending == StreamGap(None, None, None)
        with pytest.raises(StopAsyncIteration):
            await anext(stream)
    finally:
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
        await stream.aclose()


@pytest.mark.anyio
@pytest.mark.parametrize("cleanup_bridge", BACKENDS, indirect=True)
async def test_gateway_emits_recovery_gap_after_stream_cleanup(cleanup_bridge):
    from app.gateway.services import sse_consumer

    bridge = cleanup_bridge
    manager = RunManager()
    record = await manager.create("cleanup-gap-thread")
    run_id = record.run_id
    try:
        await manager.set_status(run_id, RunStatus.success)
        for index in range(70):
            await bridge.publish(run_id, "messages", {"index": index})
        await bridge.publish_end(run_id)
        stream = sse_consumer(bridge, record, _ConnectedRequest(), manager, apply_on_disconnect=False)
        try:
            assert (await anext(stream)).startswith("event: messages\n")
            await bridge.cleanup(run_id)
            with anyio.fail_after(2):
                frames = [frame async for frame in stream]
            assert frames[-1].startswith("event: gap\n")
            data = json.loads(frames[-1].split("data: ", 1)[1])
            assert data["recovery"] == "reload_durable_state"
            assert data["latest_available_event_id"] is None
            assert not any(frame.startswith("event: end\n") for frame in frames)
            assert record.status == RunStatus.success
        finally:
            await stream.aclose()
    finally:
        await bridge.cleanup(run_id)
        await manager.shutdown()


@pytest.mark.anyio
@pytest.mark.parametrize("store_only", [False, True])
async def test_wait_completes_when_gap_has_no_retained_tail(store_only):
    from app.gateway.services import wait_for_run_completion
    from deerflow.runtime.runs.store.memory import MemoryRunStore

    store = MemoryRunStore() if store_only else None
    manager = RunManager(store=store)
    if store_only:
        await store.put("cleanup-gap", thread_id="cleanup-thread", status="running")
        record = await manager.get("cleanup-gap")
    else:
        record = await manager.create("cleanup-thread")
        await manager.set_status(record.run_id, RunStatus.running)

    class DeletedStreamBridge:
        async def stream_exists(self, run_id):
            return False

        async def subscribe(self, run_id, *, last_event_id=None):
            await asyncio.sleep(0)
            if store_only:
                await store.update_status(run_id, "success")
            else:
                await manager.set_status(run_id, RunStatus.success)
            yield StreamGap("123-0", None, None)
            # A new subscription must not wait on the already-deleted stream.
            await asyncio.Event().wait()

    try:
        with anyio.fail_after(2):
            assert await wait_for_run_completion(DeletedStreamBridge(), record, _ConnectedRequest(), manager)
    finally:
        await manager.shutdown()


@pytest.mark.anyio
@pytest.mark.parametrize("cleanup_bridge", BACKENDS, indirect=True)
@pytest.mark.parametrize("store_only", [False, True])
async def test_wait_survives_cleanup_with_real_bridge(cleanup_bridge, store_only):
    from app.gateway.services import wait_for_run_completion
    from deerflow.runtime.runs.store.memory import MemoryRunStore

    store = MemoryRunStore() if store_only else None
    manager = RunManager(store=store)
    if store_only:
        await store.put("cleanup-gap", thread_id="cleanup-thread", status="running")
        record = await manager.get("cleanup-gap")
    else:
        record = await manager.create("cleanup-thread")
        await manager.set_status(record.run_id, RunStatus.running)
    bridge = cleanup_bridge
    run_id = record.run_id

    class CleanupAfterFirstMessage(_ConnectedRequest):
        async def is_disconnected(self):
            if store_only:
                await store.update_status(run_id, "success")
            else:
                await manager.set_status(run_id, RunStatus.success)
            await bridge.cleanup(run_id)
            return False

    try:
        for index in range(70):
            await bridge.publish(run_id, "messages", {"index": index})
        await bridge.publish_end(run_id)
        with anyio.fail_after(2):
            assert await wait_for_run_completion(bridge, record, CleanupAfterFirstMessage(), manager)
    finally:
        await bridge.cleanup(run_id)
        await manager.shutdown()


@pytest.mark.anyio
@pytest.mark.parametrize("terminal_with_retained_tail", [False, True])
async def test_empty_gap_does_not_complete_running_or_retained_run(terminal_with_retained_tail):
    from app.gateway.services import wait_for_run_completion

    manager = RunManager()
    record = await manager.create("cleanup-control")
    await manager.set_status(record.run_id, RunStatus.success if terminal_with_retained_tail else RunStatus.running)
    resumed = asyncio.Event()
    allow_end = asyncio.Event()

    class GapThenEndBridge:
        subscriptions = 0

        async def stream_exists(self, run_id):
            # Initial probe must not skip the subscription.
            return True if self.subscriptions == 0 else terminal_with_retained_tail

        async def subscribe(self, run_id, *, last_event_id=None):
            self.subscriptions += 1
            if self.subscriptions == 1:
                yield StreamGap("123-0", None, None)
                return
            resumed.set()
            await allow_end.wait()
            yield END_SENTINEL

    task = asyncio.create_task(wait_for_run_completion(GapThenEndBridge(), record, _ConnectedRequest(), manager))
    try:
        with anyio.fail_after(2):
            await resumed.wait()
            assert not task.done()
            allow_end.set()
            assert await task
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await manager.shutdown()
