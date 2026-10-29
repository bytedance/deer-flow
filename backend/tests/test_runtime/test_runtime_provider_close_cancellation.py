import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from deerflow.config.stream_bridge_config import StreamBridgeConfig
from deerflow.runtime.checkpoint_cache import provider as checkpoint_provider
from deerflow.runtime.checkpoint_cache import redis as checkpoint_redis
from deerflow.runtime.stream_bridge import async_provider as stream_provider
from deerflow.runtime.stream_bridge import memory as stream_memory
from deerflow.runtime.stream_bridge import redis as stream_redis


class _BlockingCheckpointCache:
    def __init__(self) -> None:
        self.close_started = asyncio.Event()
        self.allow_close = asyncio.Event()

    async def aclose(self) -> None:
        self.close_started.set()
        await self.allow_close.wait()


class _BlockingStreamBridge:
    def __init__(self) -> None:
        self.close_started = asyncio.Event()
        self.allow_close = asyncio.Event()

    async def close(self) -> None:
        self.close_started.set()
        await self.allow_close.wait()


async def _wait_for_owner_event(task: asyncio.Task[None], event: asyncio.Event) -> None:
    waiter = asyncio.create_task(event.wait())
    try:
        done, _ = await asyncio.wait((task, waiter), timeout=1, return_when=asyncio.FIRST_COMPLETED)
        if task in done:
            await task
            raise AssertionError("provider owner finished before its lifecycle event")
        if waiter not in done:
            raise TimeoutError("provider did not reach its lifecycle event")
    finally:
        waiter.cancel()
        await asyncio.gather(waiter, return_exceptions=True)


async def _assert_close_is_drained(cm, close_started: asyncio.Event, allow_close: asyncio.Event) -> None:
    entered = asyncio.Event()
    leave = asyncio.Event()

    async def owner() -> None:
        async with cm:
            entered.set()
            await leave.wait()

    task: asyncio.Task[None] | None = None
    try:
        task = asyncio.create_task(owner())
        await _wait_for_owner_event(task, entered)
        leave.set()
        await _wait_for_owner_event(task, close_started)

        task.cancel()
        for _ in range(5):
            await asyncio.sleep(0)
        assert not task.done(), "provider teardown returned before close finished"

        task.cancel()
        for _ in range(5):
            await asyncio.sleep(0)
        assert not task.done(), "repeated cancellation interrupted provider close"

        allow_close.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        allow_close.set()
        if task is not None:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_checkpoint_cache_context_drains_close_across_repeated_cancellation(monkeypatch: pytest.MonkeyPatch) -> None:
    cache = _BlockingCheckpointCache()
    monkeypatch.setattr(checkpoint_provider, "MemoryCheckpointHistoryCache", lambda **_kwargs: cache)
    config = SimpleNamespace(database=SimpleNamespace(checkpoint_cache=SimpleNamespace(type="memory", max_entries=128)))

    await _assert_close_is_drained(
        checkpoint_provider.make_checkpoint_cache(config, serde=object()),
        cache.close_started,
        cache.allow_close,
    )


@pytest.mark.asyncio
async def test_checkpoint_cache_redis_context_drains_close_across_repeated_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = _BlockingCheckpointCache()
    monkeypatch.setattr(checkpoint_redis, "RedisCheckpointHistoryCache", lambda *_args, **_kwargs: cache)
    config = SimpleNamespace(
        database=SimpleNamespace(
            checkpoint_cache=SimpleNamespace(
                type="redis",
                max_entries=128,
                redis_url="redis://localhost:6379/0",
                ttl_seconds=60,
            )
        )
    )

    await _assert_close_is_drained(
        checkpoint_provider.make_checkpoint_cache(config, serde=object()),
        cache.close_started,
        cache.allow_close,
    )


@pytest.mark.asyncio
async def test_stream_bridge_context_drains_close_across_repeated_cancellation(monkeypatch: pytest.MonkeyPatch) -> None:
    bridge = _BlockingStreamBridge()
    monkeypatch.setattr(stream_memory, "MemoryStreamBridge", lambda **_kwargs: bridge)
    config = SimpleNamespace(stream_bridge=StreamBridgeConfig(type="memory", queue_maxsize=8, heartbeat_interval_seconds=1.0))

    await _assert_close_is_drained(
        stream_provider.make_stream_bridge(config),
        bridge.close_started,
        bridge.allow_close,
    )


@pytest.mark.asyncio
async def test_stream_bridge_redis_context_drains_close_across_repeated_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = _BlockingStreamBridge()
    monkeypatch.setattr(stream_redis, "RedisStreamBridge", lambda *_args, **_kwargs: bridge)
    config = SimpleNamespace(
        stream_bridge=StreamBridgeConfig(
            type="redis",
            redis_url="redis://localhost:6379/0",
            queue_maxsize=8,
            heartbeat_interval_seconds=1.0,
            max_connections=4,
            stream_ttl_seconds=60,
        )
    )

    await _assert_close_is_drained(
        stream_provider.make_stream_bridge(config),
        bridge.close_started,
        bridge.allow_close,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_stage", ["enter", "close"])
async def test_close_drain_helper_propagates_owner_failure(failure_stage: str) -> None:
    error = RuntimeError(f"provider {failure_stage} failed")

    @asynccontextmanager
    async def failing_context():
        if failure_stage == "enter":
            raise error
        yield
        raise error

    with pytest.raises(RuntimeError, match=f"provider {failure_stage} failed") as raised:
        await _assert_close_is_drained(failing_context(), asyncio.Event(), asyncio.Event())

    assert raised.value is error
