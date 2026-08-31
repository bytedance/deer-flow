"""Regression anchor: DingTalk ``receive_file`` must not block the event loop.

``_receive_single_file`` prepares the thread directories, resolves the uploads
dir, scans it for the uniqueness claim, and writes the attachment — all blocking
filesystem IO that must run inside ``asyncio.to_thread`` (and sandbox sync must
go through ``acquire_async`` + an offloaded ``update_file``). This anchor drives
the real ``receive_file`` under the strict Blockbuster gate; if any of that
regresses back onto the event loop, Blockbuster raises ``BlockingError``.

The ``Paths`` construction is offloaded only because ``Paths.__init__`` resolves
paths synchronously; the surface under test (``receive_file``'s persist path) is
exercised on the event loop, not bypassed. The download itself is mocked — the
network leg is httpx-async and not the subject here.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

pytestmark = pytest.mark.asyncio


async def test_receive_file_persist_does_not_block_event_loop(tmp_path, monkeypatch) -> None:
    from app.channels.dingtalk import DingTalkChannel
    from app.channels.message_bus import MessageBus
    from deerflow.config.paths import Paths

    paths = await asyncio.to_thread(Paths, str(tmp_path))
    monkeypatch.setattr("app.channels.dingtalk.get_paths", lambda: paths)

    async def _acquire_async(thread_id, user_id=None):
        return "local"

    monkeypatch.setattr(
        "app.channels.dingtalk.get_sandbox_provider",
        lambda: SimpleNamespace(acquire_async=_acquire_async, get=lambda sid: None),
    )

    channel = DingTalkChannel(MessageBus(), config={})
    channel._download_by_code = AsyncMock(return_value=b"DATA")

    msg = channel._make_inbound(
        chat_id="c",
        user_id="u",
        text="hi",
        thread_ts="m",
        files=[{"type": "file", "download_code": "dc", "filename": "a.pdf"}],
    )
    out = await channel.receive_file(msg, "t1", user_id="default")

    assert "/uploads/a.pdf" in out.text
    assert out.files == []
