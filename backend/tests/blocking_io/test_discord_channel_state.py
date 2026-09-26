"""Regression anchor: Discord channel filesystem IO must not block the event loop.

``DiscordChannel`` persists channel->thread mappings to a dedicated JSON file
(``discord_threads.json``) via synchronous filesystem calls, and reads outbound
attachments from disk before uploading. The async entry points offload all of
that IO via ``asyncio.to_thread``:

- ``start()`` -> ``_load_active_threads`` (``exists`` + ``read_text`` to restore
  mappings on startup)
- ``_on_message`` -> ``_record_thread_mapping`` updates the in-memory mapping
  synchronously (no IO), then ``_persist_thread_mappings`` flushes it to disk
  (``mkdir`` + ``write_text``) via ``asyncio.to_thread``. Memory is updated
  before persistence so a follow-up message in the new thread is recognized
  immediately — see the race noted in the #3927 review.
- ``send_file`` -> ``_read_attachment_bytes`` (``open`` + ``read`` for outbound
  attachments; bytes are handed to ``discord.File`` as an in-memory buffer)

If any of it regresses back onto the event loop, the strict Blockbuster gate
raises ``BlockingError`` and these tests fail.

``__init__`` only computes paths (``Path.home()`` / ``store._path.parent``), so
construction is IO-free; ``ChannelService._start_channel()`` instantiates the
channel directly on the async path without blocking. The IO-bearing helpers
(``_persist_thread_mappings`` / ``_load_active_threads``) are wrapped in
``asyncio.to_thread``; ``_record_thread_mapping`` is pure memory and runs
inline on the event loop so its update is visible before persistence completes.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from app.channels.discord import DiscordChannel
from app.channels.message_bus import MessageBus

pytestmark = pytest.mark.asyncio


class _FakeStore:
    """Stand-in for ChannelStore so the thread-mapping file lands under tmp_path."""

    def __init__(self, tmp_path: Path) -> None:
        self._path = tmp_path / "channel_store.json"


async def test_discord_constructor_is_io_free_on_async_path(tmp_path: Path) -> None:
    """``__init__`` must not touch the filesystem — ``_start_channel`` constructs inline."""
    # Direct construction on the event loop, no asyncio.to_thread wrapper —
    # mirrors the production _start_channel path. __init__ only resolves paths
    # (Path.home / store._path.parent); if it regresses to doing exists/read_text
    # the Blockbuster gate raises BlockingError here.
    channel = DiscordChannel(bus=MessageBus(), config={"bot_token": "t", "channel_store": _FakeStore(tmp_path)})
    assert channel._bot_token == "t"
    assert channel._thread_store_path == tmp_path / "discord_threads.json"


async def test_discord_record_then_persist_does_not_block_event_loop(tmp_path: Path) -> None:
    """``_record_thread_mapping`` updates memory synchronously; ``_persist_thread_mappings``
    writes the thread-mapping JSON through ``asyncio.to_thread``."""
    channel = DiscordChannel(bus=MessageBus(), config={"bot_token": "test-token", "channel_store": _FakeStore(tmp_path)})

    # _on_message does: _record_thread_mapping(...) then await asyncio.to_thread(_persist_thread_mappings)
    channel._record_thread_mapping("chan-1", "thread-1")
    assert channel._active_threads == {"chan-1": "thread-1"}
    assert "thread-1" in channel._active_thread_ids

    await asyncio.to_thread(channel._persist_thread_mappings)

    data = json.loads(await asyncio.to_thread(channel._thread_store_path.read_text))
    assert data == {"chan-1": "thread-1"}


async def test_discord_record_thread_mapping_visible_before_persist(tmp_path: Path) -> None:
    """Race regression (#3927 review): ``_record_thread_mapping`` must update
    ``_active_thread_ids`` synchronously so an inbound message in the new
    thread is recognized BEFORE the offloaded persistence write completes. If
    the memory update were deferred to the worker thread, ``_on_message``'s
    membership check would misclassify the message as orphaned and create a
    duplicate thread.
    """
    channel = DiscordChannel(bus=MessageBus(), config={"bot_token": "test-token", "channel_store": _FakeStore(tmp_path)})

    # Record WITHOUT awaiting any persistence — memory must already reflect it.
    channel._record_thread_mapping("chan-1", "thread-1")
    assert "thread-1" in channel._active_thread_ids
    assert channel._active_threads["chan-1"] == "thread-1"
    # Persistence is a separate offloaded step; the file is not written yet.
    assert not await asyncio.to_thread(channel._thread_store_path.exists)


async def test_discord_record_thread_mapping_discards_replaced_thread(tmp_path: Path) -> None:
    """Recording a new thread for a channel that already had one drops the old
    thread id from the reverse-lookup set, so messages in the stale thread are
    no longer treated as active (mirrors the discard the old ``_save_thread``
    performed against the on-disk record).
    """
    channel = DiscordChannel(bus=MessageBus(), config={"bot_token": "test-token", "channel_store": _FakeStore(tmp_path)})

    channel._record_thread_mapping("chan-1", "thread-1")
    channel._record_thread_mapping("chan-1", "thread-2")  # replace

    assert channel._active_threads == {"chan-1": "thread-2"}
    assert "thread-1" not in channel._active_thread_ids
    assert "thread-2" in channel._active_thread_ids


async def test_discord_load_active_threads_does_not_block_event_loop(tmp_path: Path) -> None:
    """``_load_active_threads`` restores mappings through ``asyncio.to_thread`` (from ``start()``)."""
    path = tmp_path / "discord_threads.json"
    await asyncio.to_thread(path.write_text, json.dumps({"chan-1": "thread-1", "chan-2": "thread-2"}))

    channel = DiscordChannel(bus=MessageBus(), config={"bot_token": "test-token", "channel_store": _FakeStore(tmp_path)})

    # start() does: await asyncio.to_thread(self._load_active_threads)
    await asyncio.to_thread(channel._load_active_threads)

    assert channel._active_threads == {"chan-1": "thread-1", "chan-2": "thread-2"}
    assert channel._active_thread_ids == {"thread-1", "thread-2"}
