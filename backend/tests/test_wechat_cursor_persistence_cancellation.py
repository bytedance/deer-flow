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


@pytest.mark.asyncio
@pytest.mark.parametrize("blocked_write", [None, "cursor", "auth"], ids=["no-cancellation", "cancel-during-cursor", "cancel-during-auth"])
async def test_poll_token_expiry_finishes_both_writes_before_cancellation(monkeypatch, tmp_path: Path, caplog, blocked_write: str | None) -> None:
    channel = WechatChannel(MessageBus(), config={"bot_token": "expired-token", "state_dir": str(tmp_path)})
    channel._get_updates_buf = "cursor-before-expiry"
    await asyncio.to_thread(channel._save_state)
    await asyncio.to_thread(channel._save_auth_state, status="confirmed", bot_token="expired-token")
    channel._running = True

    started = threading.Event()
    release = threading.Event()
    original_save_state = channel._save_state
    original_save_auth_state = channel._save_auth_state
    auth_lock_observations = []

    async def ensure_authenticated() -> bool:
        return True

    async def request_json(*_args, **_kwargs):
        return {"ret": 1, "errcode": -14}

    def save_state() -> None:
        if blocked_write == "cursor":
            started.set()
            assert release.wait(timeout=5)
        original_save_state()

    def save_auth_state(**kwargs):
        auth_lock_observations.append(channel._auth_lock.locked())
        if blocked_write == "auth":
            started.set()
            assert release.wait(timeout=5)
        return original_save_auth_state(**kwargs)

    monkeypatch.setattr(channel, "_ensure_authenticated", ensure_authenticated)
    monkeypatch.setattr(channel, "_request_json", request_json)
    monkeypatch.setattr(channel, "_save_state", save_state)
    monkeypatch.setattr(channel, "_save_auth_state", save_auth_state)

    task = asyncio.create_task(channel._poll_loop())
    try:
        if blocked_write is None:
            await asyncio.wait_for(task, timeout=5)
        else:
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

    cursor = json.loads((tmp_path / "wechat-getupdates.json").read_text(encoding="utf-8"))
    auth = json.loads((tmp_path / "wechat-auth.json").read_text(encoding="utf-8"))
    assert cursor["get_updates_buf"] == ""
    assert auth["status"] == "expired"
    assert "bot_token" not in auth
    assert channel._bot_token == ""
    assert not channel._running
    assert "bot token expired" in caplog.text
    assert auth_lock_observations == [True]
    assert not channel._auth_lock.locked()

    restored = WechatChannel(MessageBus(), config={"state_dir": str(tmp_path)})
    await asyncio.to_thread(restored._load_state)
    assert restored._bot_token == ""
    assert restored._get_updates_buf == ""
