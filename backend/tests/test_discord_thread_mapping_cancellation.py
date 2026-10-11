from __future__ import annotations

import asyncio
import threading
from unittest.mock import AsyncMock

import pytest

from app.channels.discord import DiscordChannel
from app.channels.message_bus import MessageBus


@pytest.mark.asyncio
async def test_discord_stop_drains_thread_mapping_write_across_repeated_cancellation(tmp_path) -> None:
    channel = DiscordChannel(bus=MessageBus(), config={"bot_token": "token"})
    channel._thread_store_path = tmp_path / "discord_threads.json"
    channel._thread_store_loaded = True
    channel._discord_loop = None
    channel._client = None
    channel._thread = None
    channel._cancel_ephemeral_tasks = AsyncMock()
    channel._record_thread_mapping("chan", "thread")

    started = threading.Event()
    allow = threading.Event()
    original = channel._persist_thread_mappings

    def blocking_persist() -> None:
        started.set()
        assert allow.wait(timeout=2)
        original()

    channel._persist_thread_mappings = blocking_persist
    task = asyncio.create_task(channel.stop())
    try:
        assert await asyncio.to_thread(started.wait, 2)

        task.cancel()
        for _ in range(5):
            await asyncio.sleep(0)
        assert not task.done()

        task.cancel()
        for _ in range(5):
            await asyncio.sleep(0)
        assert not task.done()

        allow.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        allow.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    assert channel._thread_store_path.exists()
