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
    await asyncio.wait_for(first_started.wait(), timeout=1)

    bus.subscribe_outbound(late)
    allow_first.set()
    await dispatch

    assert seen == ["first"]

    await bus.publish_outbound(message)
    assert seen == ["first", "first", "late"]
