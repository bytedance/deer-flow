"""Regression tests for bounded IM-channel intake and handler ownership."""

from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import MagicMock

import pytest

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
async def test_stop_cancels_and_awaits_workers_drops_queue_and_releases_dedupe(tmp_path: Path) -> None:
    bus = MessageBus(inbound_queue_maxsize=2)
    manager = ChannelManager(
        bus=bus,
        store=ChannelStore(path=tmp_path / "store.json"),
        max_concurrency=1,
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


def test_channel_service_threads_intake_limits_into_bus_and_worker_pool() -> None:
    service = ChannelService(
        channels_config={
            "inbound_queue_maxsize": 17,
            "max_concurrency": 3,
        }
    )

    assert service.bus.inbound_queue_maxsize == 17
    assert service.manager._max_concurrency == 3
    assert "inbound_queue_maxsize" not in service._config
    assert "max_concurrency" not in service._config


@pytest.mark.asyncio
async def test_cancelled_service_stop_still_drains_manager_workers() -> None:
    service = ChannelService(channels_config={"inbound_queue_maxsize": 1, "max_concurrency": 1})
    await service.start()
    channel_stop_started = asyncio.Event()

    class SlowChannel:
        async def stop(self) -> None:
            channel_stop_started.set()
            await asyncio.Event().wait()

    service._channels["slow"] = SlowChannel()  # type: ignore[assignment]
    workers = tuple(service.manager._worker_tasks)
    stop_task = asyncio.create_task(service.stop())
    await asyncio.wait_for(channel_stop_started.wait(), timeout=1)
    stop_task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await stop_task

    assert service.manager._worker_tasks == set()
    assert all(worker.done() for worker in workers)
    assert service._channels == {}
    with pytest.raises(InboundQueueClosedError):
        await service.bus.publish_inbound(_message(9))
