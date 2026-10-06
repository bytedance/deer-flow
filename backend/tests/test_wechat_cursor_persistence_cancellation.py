from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path

import pytest

from app.channels.message_bus import MessageBus
from app.channels.wechat import WechatChannel


@pytest.mark.asyncio
async def test_poll_cursor_persistence_drains_across_cancellation(monkeypatch, tmp_path: Path) -> None:
    channel = WechatChannel(
        MessageBus(),
        config={"bot_token": "test-token", "state_dir": str(tmp_path)},
    )
    channel._running = True

    started = threading.Event()
    release = threading.Event()
    original_save_state = channel._save_state
    requests = 0

    async def ensure_authenticated() -> bool:
        return True

    async def request_json(*_args, **_kwargs):
        nonlocal requests
        requests += 1
        if requests == 1:
            return {"ret": 0, "msgs": [], "get_updates_buf": "cursor-next"}
        await asyncio.Future()

    def blocking_save_state() -> None:
        started.set()
        assert release.wait(timeout=5)
        original_save_state()

    monkeypatch.setattr(channel, "_ensure_authenticated", ensure_authenticated)
    monkeypatch.setattr(channel, "_request_json", request_json)
    monkeypatch.setattr(channel, "_save_state", blocking_save_state)

    task = asyncio.create_task(channel._poll_loop())
    try:
        assert await asyncio.to_thread(started.wait, 5)

        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()

        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        release.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    persisted = json.loads((tmp_path / "wechat-getupdates.json").read_text(encoding="utf-8"))
    assert persisted["get_updates_buf"] == "cursor-next"
