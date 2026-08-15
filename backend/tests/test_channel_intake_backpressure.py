"""Regression tests for bounded IM-channel intake and handler ownership."""

from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.channels import service as service_module
from app.channels.manager import ChannelManager
from app.channels.message_bus import (
    InboundMessage,
    InboundQueueClosedError,
    InboundQueueFullError,
    InboundReservationExpiredError,
    MessageBus,
)
from app.channels.service import ChannelService
from app.channels.slack import SlackChannel
from app.channels.store import ChannelStore


def _message(index: int, *, with_dedupe_identity: bool = False) -> InboundMessage:
    metadata = {"team_id": "T1", "message_id": f"m-{index}"} if with_dedupe_identity else {}
    return InboundMessage(
        channel_name="slack",
        chat_id="C1",
        user_id="U1",
        text=f"message-{index}",
        metadata=metadata,
    )


@pytest.mark.asyncio
async def test_inbound_queue_rejects_immediately_when_capacity_is_reserved() -> None:
    bus = MessageBus(inbound_queue_maxsize=1)

    reservation = bus.reserve_inbound(_message(1))
    with pytest.raises(InboundQueueFullError):
        bus.reserve_inbound(_message(2))

    reservation.commit(_message(1))
    assert bus.inbound_queue.qsize() == 1
    assert bus.get_inbound_nowait().text == "message-1"
    bus.inbound_task_done()
    await bus.publish_inbound(_message(2))
    assert (await bus.get_inbound()).text == "message-2"
    bus.inbound_task_done()
    await bus.join_inbound()


def test_shutdown_invalidates_provider_side_reservations() -> None:
    bus = MessageBus(inbound_queue_maxsize=2)
    direct_reservation = bus.reserve_inbound(_message(1))
    adapter_reservation = bus.reserve_inbound(_message(2))
    channel = SlackChannel(bus=bus, config={})

    assert bus.close_inbound() == 2
    with pytest.raises(InboundReservationExpiredError):
        direct_reservation.commit(_message(1))
    direct_reservation.release()
    assert channel._commit_reserved_inbound(adapter_reservation, _message(2)) is False
    assert bus.inbound_queue.empty()


def test_provider_thread_reservations_share_one_hard_capacity_limit() -> None:
    capacity = 8
    contenders = 32
    bus = MessageBus(inbound_queue_maxsize=capacity)
    barrier = threading.Barrier(contenders)

    def reserve(index: int):
        barrier.wait()
        try:
            return bus.reserve_inbound(_message(index))
        except InboundQueueFullError:
            return None

    with ThreadPoolExecutor(max_workers=contenders) as executor:
        reservations = list(executor.map(reserve, range(contenders)))

    admitted = [reservation for reservation in reservations if reservation is not None]
    assert len(admitted) == capacity
    for reservation in admitted:
        reservation.release()


@pytest.mark.asyncio
async def test_realtime_provider_drops_before_ack_when_queue_is_full() -> None:
    bus = MessageBus(inbound_queue_maxsize=1)
    await bus.publish_inbound(_message(0))
    channel = SlackChannel(bus=bus, config={})
    channel._loop = MagicMock()
    channel._loop.is_running.return_value = True
    channel._add_reaction = MagicMock()
    channel._send_running_reply = MagicMock()

    channel._handle_message_event(
        {
            "user": "U1",
            "text": "overloaded",
            "channel": "C1",
            "ts": "1710000000.000100",
        }
    )

    channel._add_reaction.assert_not_called()
    channel._send_running_reply.assert_not_called()
    channel._loop.call_soon_threadsafe.assert_not_called()
    assert bus.inbound_queue.qsize() == 1


@pytest.mark.asyncio
async def test_fixed_worker_pool_bounds_handler_and_queue_tasks(tmp_path: Path) -> None:
    bus = MessageBus(inbound_queue_maxsize=3)
    manager = ChannelManager(
        bus=bus,
        store=ChannelStore(path=tmp_path / "store.json"),
        max_concurrency=2,
    )
    release_handlers = asyncio.Event()
    started: list[str] = []

    async def hold_handler(msg: InboundMessage) -> None:
        started.append(msg.text)
        await release_handlers.wait()

    manager._handle_message = hold_handler  # type: ignore[method-assign]
    await manager.start()
    try:
        assert len(manager._worker_tasks) == 2

        await bus.publish_inbound(_message(0))
        await bus.publish_inbound(_message(1))
        async with asyncio.timeout(1):
            while len(started) < 2:
                await asyncio.sleep(0)

        for index in range(2, 5):
            await bus.publish_inbound(_message(index))
        with pytest.raises(InboundQueueFullError):
            await bus.publish_inbound(_message(5))

        assert bus.inbound_queue.qsize() == 3
        assert len(manager._worker_tasks) == 2
        # The handlers execute inline in the fixed workers. There must not be a
        # separate task per admitted message waiting on a semaphore.
        assert not any(getattr(task.get_coro(), "__name__", "") == "hold_handler" for task in asyncio.all_tasks())

        release_handlers.set()
        await asyncio.wait_for(bus.join_inbound(), timeout=1)
        assert sorted(started) == [f"message-{index}" for index in range(5)]
    finally:
        release_handlers.set()
        await manager.stop()


@pytest.mark.asyncio
async def test_stop_gracefully_drains_every_accepted_message_before_cancelling_workers(tmp_path: Path) -> None:
    bus = MessageBus(inbound_queue_maxsize=2)
    manager = ChannelManager(
        bus=bus,
        store=ChannelStore(path=tmp_path / "store.json"),
        max_concurrency=1,
        shutdown_grace_period_seconds=0.5,
    )
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    completed: list[str] = []
    cancelled = False

    async def graceful_handler(msg: InboundMessage) -> None:
        nonlocal cancelled
        if msg.text == "message-1":
            first_started.set()
            try:
                await release_first.wait()
            except asyncio.CancelledError:
                cancelled = True
                raise
        completed.append(msg.text)

    manager._handle_message = graceful_handler  # type: ignore[method-assign]
    await manager.start()
    await bus.publish_inbound(_message(1))
    await asyncio.wait_for(first_started.wait(), timeout=1)
    await bus.publish_inbound(_message(2))

    stop_task = asyncio.create_task(manager.stop())
    await asyncio.sleep(0.02)

    assert not stop_task.done()
    assert cancelled is False

    release_first.set()
    await asyncio.wait_for(stop_task, timeout=1)

    assert completed == ["message-1", "message-2"]
    assert cancelled is False
    assert bus.inbound_queue.empty()
    await asyncio.wait_for(bus.join_inbound(), timeout=1)


@pytest.mark.asyncio
async def test_stop_cancels_after_grace_drops_queue_and_releases_dedupe(tmp_path: Path) -> None:
    bus = MessageBus(inbound_queue_maxsize=2)
    manager = ChannelManager(
        bus=bus,
        store=ChannelStore(path=tmp_path / "store.json"),
        max_concurrency=1,
        shutdown_grace_period_seconds=0,
    )
    handler_started = asyncio.Event()
    handler_cancelled = asyncio.Event()

    async def blocked_handler(_msg: InboundMessage) -> None:
        handler_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            handler_cancelled.set()
            raise

    manager._handle_message = blocked_handler  # type: ignore[method-assign]
    await manager.start()

    active = _message(1, with_dedupe_identity=True)
    await bus.publish_inbound(active)
    await asyncio.wait_for(handler_started.wait(), timeout=1)
    await bus.publish_inbound(_message(2))
    await bus.publish_inbound(_message(3))
    workers = tuple(manager._worker_tasks)

    await manager.stop()

    assert handler_cancelled.is_set()
    assert manager._worker_tasks == set()
    assert all(task.done() for task in workers)
    assert bus.inbound_queue.empty()
    await asyncio.wait_for(bus.join_inbound(), timeout=1)
    with pytest.raises(InboundQueueClosedError):
        await bus.publish_inbound(_message(4))

    dedupe_key = manager._inbound_dedupe_key(active)
    assert dedupe_key is not None
    # Cancellation must make the delivery retryable instead of black-holing it
    # in the dedupe store until TTL expiry.
    assert await manager._inbound_dedupe_store.try_record(dedupe_key) is False


@pytest.mark.asyncio
async def test_successful_stop_waits_for_cancel_resistant_workers_and_watchers(tmp_path: Path) -> None:
    bus = MessageBus(inbound_queue_maxsize=1)
    manager = ChannelManager(
        bus=bus,
        store=ChannelStore(path=tmp_path / "store.json"),
        max_concurrency=1,
        shutdown_grace_period_seconds=0.01,
    )
    handler_started = asyncio.Event()
    handler_cancelled = asyncio.Event()
    watcher_started = asyncio.Event()
    watcher_cancelled = asyncio.Event()
    release_after_cancel = asyncio.Event()

    async def cancellation_resistant_handler(_msg: InboundMessage) -> None:
        handler_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            handler_cancelled.set()
            await release_after_cancel.wait()

    async def cancellation_resistant_watcher() -> None:
        watcher_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            watcher_cancelled.set()
            await release_after_cancel.wait()

    manager._handle_message = cancellation_resistant_handler  # type: ignore[method-assign]
    await manager.start()
    watcher = asyncio.create_task(cancellation_resistant_watcher())
    manager._followup_watcher_tasks.add(watcher)
    watcher.add_done_callback(manager._followup_watcher_tasks.discard)
    await bus.publish_inbound(_message(1))
    await asyncio.wait_for(handler_started.wait(), timeout=1)
    await asyncio.wait_for(watcher_started.wait(), timeout=1)
    workers = tuple(manager._worker_tasks)

    stop_task = asyncio.create_task(manager.stop())
    await asyncio.wait_for(handler_cancelled.wait(), timeout=1)
    await asyncio.wait_for(watcher_cancelled.wait(), timeout=1)
    await asyncio.sleep(0.02)

    assert not stop_task.done()
    assert any(not worker.done() for worker in workers)
    assert not watcher.done()

    release_after_cancel.set()
    await asyncio.wait_for(stop_task, timeout=1)

    assert manager._worker_tasks == set()
    assert manager._followup_watcher_tasks == set()
    assert all(worker.done() for worker in workers)
    assert watcher.done()
    await asyncio.wait_for(bus.join_inbound(), timeout=1)


@pytest.mark.asyncio
async def test_outer_shutdown_cancellation_does_not_start_an_unbounded_second_join(tmp_path: Path) -> None:
    bus = MessageBus(inbound_queue_maxsize=1)
    manager = ChannelManager(
        bus=bus,
        store=ChannelStore(path=tmp_path / "store.json"),
        max_concurrency=1,
        shutdown_grace_period_seconds=60,
    )
    handler_started = asyncio.Event()
    handler_cancelled = asyncio.Event()
    release_after_cancel = asyncio.Event()

    async def cancellation_resistant_handler(_msg: InboundMessage) -> None:
        handler_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            handler_cancelled.set()
            await release_after_cancel.wait()

    manager._handle_message = cancellation_resistant_handler  # type: ignore[method-assign]
    await manager.start()
    await bus.publish_inbound(_message(1))
    await asyncio.wait_for(handler_started.wait(), timeout=1)
    workers = tuple(manager._worker_tasks)

    stop_task = asyncio.create_task(manager.stop())
    await asyncio.sleep(0)
    started_at = asyncio.get_running_loop().time()
    stop_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await stop_task

    assert asyncio.get_running_loop().time() - started_at < 0.2
    assert handler_cancelled.is_set()
    assert any(not worker.done() for worker in workers)
    assert manager._worker_tasks

    release_after_cancel.set()
    await asyncio.wait_for(manager.stop(), timeout=1)
    assert manager._worker_tasks == set()
    assert all(worker.done() for worker in workers)
    await asyncio.wait_for(bus.join_inbound(), timeout=1)


@pytest.mark.asyncio
async def test_provider_stop_drains_cross_thread_preparation_futures() -> None:
    from app.channels.dingtalk import DingTalkChannel
    from app.channels.feishu import FeishuChannel
    from app.channels.telegram import TelegramChannel

    loop = asyncio.get_running_loop()
    providers = (
        FeishuChannel(MessageBus(), config={}),
        DingTalkChannel(MessageBus(), config={}),
        TelegramChannel(MessageBus(), config={}),
        SlackChannel(MessageBus(), config={}),
    )

    for channel in providers:
        started = asyncio.Event()
        cancelled = asyncio.Event()
        release_after_cancel = asyncio.Event()
        finished = asyncio.Event()

        async def preparation() -> None:
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                await release_after_cancel.wait()
            finally:
                finished.set()

        channel._running = True
        channel._main_loop = loop
        channel._open_threadsafe_future_intake()
        scheduled = await asyncio.to_thread(
            channel._submit_threadsafe_coroutine,
            preparation(),
            loop,
            name="test_preparation",
            msg_id="message-1",
        )
        assert scheduled is True
        await asyncio.wait_for(started.wait(), timeout=1)

        stop_task = asyncio.create_task(channel.stop())
        await asyncio.wait_for(cancelled.wait(), timeout=1)
        await asyncio.sleep(0)

        assert not stop_task.done()
        assert not finished.is_set()

        release_after_cancel.set()
        await asyncio.wait_for(stop_task, timeout=1)

        assert finished.is_set()
        assert channel._threadsafe_submissions == set()


@pytest.mark.asyncio
async def test_shutdown_closes_cross_thread_submission_before_task_start() -> None:
    channel = SlackChannel(MessageBus(), config={})
    channel._open_threadsafe_future_intake()
    coroutine_started = False

    async def preparation() -> None:
        nonlocal coroutine_started
        coroutine_started = True

    scheduled = channel._submit_threadsafe_coroutine(
        preparation(),
        asyncio.get_running_loop(),
        name="test_preparation",
        msg_id="message-1",
    )
    assert scheduled is True

    await asyncio.wait_for(channel._close_and_drain_threadsafe_futures(), timeout=1)

    assert coroutine_started is False
    assert channel._threadsafe_submissions == set()


@pytest.mark.asyncio
async def test_cancelled_cross_thread_drain_remains_retryable() -> None:
    channel = SlackChannel(MessageBus(), config={})
    channel._open_threadsafe_future_intake()
    started = asyncio.Event()
    cancellation_seen = asyncio.Event()
    release_after_cancel = asyncio.Event()
    finished = asyncio.Event()

    async def preparation() -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancellation_seen.set()
            await release_after_cancel.wait()
        finally:
            finished.set()

    assert channel._submit_threadsafe_coroutine(
        preparation(),
        asyncio.get_running_loop(),
        name="test_preparation",
        msg_id="message-1",
    )
    await asyncio.wait_for(started.wait(), timeout=1)
    submission = next(iter(channel._threadsafe_submissions))

    first_drain = asyncio.create_task(channel._close_and_drain_threadsafe_futures())
    await asyncio.wait_for(cancellation_seen.wait(), timeout=1)
    first_drain.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first_drain

    assert not finished.is_set()
    assert channel._threadsafe_submissions
    assert not submission.completion.done()

    second_drain = asyncio.create_task(channel._close_and_drain_threadsafe_futures())
    await asyncio.sleep(0)
    assert not second_drain.done()

    release_after_cancel.set()
    await asyncio.wait_for(second_drain, timeout=1)

    assert finished.is_set()
    assert channel._threadsafe_submissions == set()


def test_channel_service_threads_intake_limits_into_bus_and_worker_pool() -> None:
    service = ChannelService(
        channels_config={
            "inbound_queue_maxsize": 17,
            "max_concurrency": 3,
            "shutdown_grace_period_seconds": 2.5,
        }
    )

    assert service.bus.inbound_queue_maxsize == 17
    assert service.manager._max_concurrency == 3
    assert service.manager._shutdown_grace_period_seconds == 2.5
    assert "inbound_queue_maxsize" not in service._config
    assert "max_concurrency" not in service._config
    assert "shutdown_grace_period_seconds" not in service._config


@pytest.mark.parametrize(
    "invalid_value",
    [True, -1, float("nan"), float("inf"), "3"],
)
def test_invalid_shutdown_grace_period_uses_finite_default(invalid_value: object) -> None:
    service = ChannelService(channels_config={"shutdown_grace_period_seconds": invalid_value})

    assert service.manager._shutdown_grace_period_seconds == 3.0


@pytest.mark.asyncio
async def test_cancelled_service_stop_preserves_unfinished_channel_for_retry() -> None:
    service = ChannelService(channels_config={"inbound_queue_maxsize": 1, "max_concurrency": 1})
    await service.start()
    channel_stop_started = asyncio.Event()
    release_channel_stop = asyncio.Event()

    class SlowChannel:
        async def stop(self) -> None:
            channel_stop_started.set()
            await release_channel_stop.wait()

    slow_channel = SlowChannel()
    service._channels["slow"] = slow_channel  # type: ignore[assignment]
    workers = tuple(service.manager._worker_tasks)
    stop_task = asyncio.create_task(service.stop())
    await asyncio.wait_for(channel_stop_started.wait(), timeout=1)
    stop_task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await stop_task

    assert service.manager._worker_tasks == set()
    assert all(worker.done() for worker in workers)
    assert service._channels == {"slow": slow_channel}
    with pytest.raises(InboundQueueClosedError):
        await service.bus.publish_inbound(_message(9))

    release_channel_stop.set()
    await asyncio.wait_for(service.stop(), timeout=1)
    assert service._channels == {}


@pytest.mark.asyncio
async def test_cancelled_manager_drain_preserves_service_channels() -> None:
    service = ChannelService(channels_config={})
    manager_stop_started = asyncio.Event()
    channel_stop_calls = 0

    async def blocked_manager_stop() -> None:
        manager_stop_started.set()
        await asyncio.Event().wait()

    class Transport:
        async def stop(self) -> None:
            nonlocal channel_stop_calls
            channel_stop_calls += 1

    transport = Transport()
    service.manager.stop = blocked_manager_stop  # type: ignore[method-assign]
    service._channels["transport"] = transport  # type: ignore[assignment]
    stop_task = asyncio.create_task(service.stop())
    await asyncio.wait_for(manager_stop_started.wait(), timeout=1)

    stop_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await stop_task

    assert service._channels == {"transport": transport}
    assert channel_stop_calls == 0


@pytest.mark.asyncio
async def test_failed_channel_stop_preserves_service_ownership() -> None:
    service = ChannelService(channels_config={})

    class BrokenTransport:
        async def stop(self) -> None:
            raise RuntimeError("provider cleanup failed")

    transport = BrokenTransport()
    service._channels["transport"] = transport  # type: ignore[assignment]

    with pytest.raises(ExceptionGroup, match="one or more channels failed to stop"):
        await service.stop()

    assert service._channels == {"transport": transport}


@pytest.mark.asyncio
async def test_global_service_is_retained_until_shutdown_succeeds() -> None:
    service = ChannelService(channels_config={})
    stop_started = asyncio.Event()
    release_stop = asyncio.Event()

    async def blocked_stop() -> None:
        stop_started.set()
        await release_stop.wait()

    service.stop = blocked_stop  # type: ignore[method-assign]
    service_module._channel_service = service
    stop_task = asyncio.create_task(service_module.stop_channel_service())
    await asyncio.wait_for(stop_started.wait(), timeout=1)

    assert service_module.get_channel_service() is service

    stop_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await stop_task
    assert service_module.get_channel_service() is service

    release_stop.set()
    await service_module.stop_channel_service()
    assert service_module.get_channel_service() is None
