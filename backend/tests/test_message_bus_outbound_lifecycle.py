from __future__ import annotations

import asyncio

import pytest

from app.channels.message_bus import MessageBus, OutboundMessage


@pytest.mark.asyncio
async def test_outbound_dispatch_does_not_admit_listener_added_mid_message() -> None:
    bus = MessageBus()
    first_started = asyncio.Event()
    allow_first = asyncio.Event()
    seen: list[str] = []

    async def first(_msg: OutboundMessage) -> None:
        seen.append("first")
        first_started.set()
        await allow_first.wait()

    async def late(_msg: OutboundMessage) -> None:
        seen.append("late")

    bus.subscribe_outbound(first)
    message = OutboundMessage(
        channel_name="wechat",
        chat_id="chat-1",
        thread_id="thread-1",
        text="reply",
    )

    dispatch = asyncio.create_task(bus.publish_outbound(message))
    try:
        await asyncio.wait_for(first_started.wait(), timeout=1)
        bus.subscribe_outbound(late)
    finally:
        allow_first.set()
        await dispatch

    assert seen == ["first"]

    await bus.publish_outbound(message)
    assert seen == ["first", "first", "late"]


@pytest.mark.asyncio
@pytest.mark.parametrize("removed", ["first", "second"])
async def test_outbound_dispatch_retains_listener_removed_mid_message(removed: str) -> None:
    bus = MessageBus()
    first_started = asyncio.Event()
    allow_first = asyncio.Event()
    seen: list[tuple[str, str]] = []

    async def first(msg: OutboundMessage) -> None:
        first_started.set()
        await allow_first.wait()
        seen.append(("first", msg.text))

    async def second(msg: OutboundMessage) -> None:
        seen.append(("second", msg.text))

    callbacks = {"first": first, "second": second}
    for callback in callbacks.values():
        bus.subscribe_outbound(callback)
    message = OutboundMessage(
        channel_name="wechat",
        chat_id="chat-1",
        thread_id="thread-1",
        text="in-flight",
    )

    dispatch = asyncio.create_task(bus.publish_outbound(message))
    try:
        await asyncio.wait_for(first_started.wait(), timeout=1)
        assert seen == [], "the second listener must still be waiting for its turn"
        bus.unsubscribe_outbound(callbacks[removed])
    finally:
        allow_first.set()
        await dispatch

    assert seen == [("first", "in-flight"), ("second", "in-flight")]

    next_message = OutboundMessage(
        channel_name="wechat",
        chat_id="chat-1",
        thread_id="thread-1",
        text="next",
    )
    await bus.publish_outbound(next_message)
    remaining = "second" if removed == "first" else "first"
    assert seen == [("first", "in-flight"), ("second", "in-flight"), (remaining, "next")]
