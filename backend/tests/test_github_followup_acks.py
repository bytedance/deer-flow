"""Manager scheduling for GitHub queued and overflow comment reactions."""

from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from langgraph_sdk.errors import ConflictError

from app.channels.manager import FOLLOWUP_BUFFER_MAX_PER_THREAD, THREAD_BUSY_MESSAGE, ChannelManager, _FollowupEntry
from app.channels.message_bus import InboundMessage, MessageBus, OutboundMessage
from app.channels.store import JsonChannelStore


class _AckChannel:
    name = "github"
    supports_followup_ack = True
    supports_streaming = False

    def __init__(self) -> None:
        self.acks: list[tuple[str, dict]] = []
        self.raise_on_ack = False

    async def acknowledge_followup(self, target, *, kind: str) -> None:
        if self.raise_on_ack:
            raise RuntimeError("reaction transport down")
        self.acks.append((kind, dict(target)))


class _Service:
    def __init__(self, channel: _AckChannel | None) -> None:
        self._channel = channel

    def get_channel(self, name: str):
        if name == "github":
            return self._channel
        return None


def _manager() -> ChannelManager:
    store = JsonChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
    return ChannelManager(bus=MessageBus(), store=store, shutdown_grace_period_seconds=0)


def _message(index: int, *, with_ack: bool = True) -> InboundMessage:
    metadata: dict = {"github": {"delivery_id": f"delivery-{index}"}}
    if with_ack:
        metadata["followup_ack"] = {
            "provider": "github",
            "repo": "octo/hello",
            "installation_id": 77,
            "comment_id": 1000 + index,
            "subject": "issue_comment",
        }
    return InboundMessage(
        channel_name="github",
        chat_id="octo/hello",
        user_id="octocat",
        text=f"comment {index}",
        metadata=metadata,
    )


async def _settle(manager: ChannelManager) -> None:
    for _ in range(20):
        pending = [task for task in list(manager._followup_ack_tasks) if not task.done()]
        if not pending:
            await asyncio.sleep(0)
            return
        await asyncio.gather(*pending)
    raise AssertionError("follow-up acknowledgement tasks did not finish")


@pytest.fixture
def ack_channel(monkeypatch: pytest.MonkeyPatch) -> _AckChannel:
    channel = _AckChannel()
    monkeypatch.setattr("app.channels.service.get_channel_service", lambda: _Service(channel))
    return channel


@pytest.mark.asyncio
async def test_buffering_a_comment_requests_eyes(ack_channel: _AckChannel) -> None:
    manager = _manager()
    manager._buffer_followup("thread-1", _message(1))
    await _settle(manager)

    assert ack_channel.acks == [("queued", _message(1).metadata["followup_ack"])]
    assert list(manager._followup_buffers["thread-1"].values())[0].ack_target["comment_id"] == 1001


@pytest.mark.asyncio
async def test_duplicate_delivery_does_not_react_twice(ack_channel: _AckChannel) -> None:
    manager = _manager()
    manager._buffer_followup("thread-1", _message(1))
    manager._buffer_followup("thread-1", _message(1))
    await _settle(manager)

    assert [kind for kind, _ in ack_channel.acks] == ["queued"]
    assert len(manager._followup_buffers["thread-1"]) == 1


@pytest.mark.asyncio
async def test_events_without_a_reaction_target_stay_silent(ack_channel: _AckChannel) -> None:
    manager = _manager()
    manager._buffer_followup("thread-1", _message(1, with_ack=False))
    await _settle(manager)

    assert ack_channel.acks == []
    assert len(manager._followup_buffers["thread-1"]) == 1


@pytest.mark.asyncio
async def test_overflow_reacts_confused_on_the_dropped_comment(ack_channel: _AckChannel) -> None:
    manager = _manager()
    for index in range(FOLLOWUP_BUFFER_MAX_PER_THREAD + 1):
        manager._buffer_followup("thread-1", _message(index))
    await _settle(manager)

    overflow = [target["comment_id"] for kind, target in ack_channel.acks if kind == "overflow"]
    queued = [target["comment_id"] for kind, target in ack_channel.acks if kind == "queued"]
    assert overflow == [1000]
    assert queued.count(1000) == 1
    assert queued[-1] == 1000 + FOLLOWUP_BUFFER_MAX_PER_THREAD
    kept = {entry.ack_target["comment_id"] for entry in manager._followup_buffers["thread-1"].values()}
    assert 1000 not in kept
    assert 1000 + FOLLOWUP_BUFFER_MAX_PER_THREAD in kept


@pytest.mark.asyncio
async def test_requeue_overflow_reacts_confused(ack_channel: _AckChannel) -> None:
    manager = _manager()
    for index in range(FOLLOWUP_BUFFER_MAX_PER_THREAD):
        manager._buffer_followup("thread-1", _message(index))
    await _settle(manager)
    ack_channel.acks.clear()

    extra = _message(FOLLOWUP_BUFFER_MAX_PER_THREAD)
    displaced = _FollowupEntry(
        dedupe_key="github:delivery:delivery-extra",
        text=extra.text,
        ack_target=dict(extra.metadata["followup_ack"]),
    )
    manager._requeue_followups("thread-1", [displaced], channel_name="github")
    await _settle(manager)

    assert ack_channel.acks == [("overflow", extra.metadata["followup_ack"])]
    assert "github:delivery:delivery-extra" not in manager._followup_buffers["thread-1"]


@pytest.mark.asyncio
async def test_ack_failure_keeps_the_buffered_comment(ack_channel: _AckChannel, caplog: pytest.LogCaptureFixture) -> None:
    ack_channel.raise_on_ack = True
    manager = _manager()
    with caplog.at_level(logging.WARNING, logger="app.channels.manager"):
        manager._buffer_followup("thread-1", _message(1))
        await _settle(manager)

    assert len(manager._followup_buffers["thread-1"]) == 1
    assert any("follow-up acknowledgement failed" in record.message for record in caplog.records)


def test_buffer_without_a_running_loop_still_keeps_the_comment(monkeypatch: pytest.MonkeyPatch) -> None:
    channel = _AckChannel()
    monkeypatch.setattr("app.channels.service.get_channel_service", lambda: _Service(channel))
    manager = _manager()
    manager._buffer_followup("thread-1", _message(1))
    assert len(manager._followup_buffers["thread-1"]) == 1
    assert manager._followup_ack_tasks == set()


@pytest.mark.asyncio
async def test_busy_github_run_reacts_eyes_on_the_triggering_comment(ack_channel: _AckChannel) -> None:
    manager = _manager()
    outbound: list[OutboundMessage] = []

    async def capture(msg: OutboundMessage) -> None:
        outbound.append(msg)

    manager.bus.subscribe_outbound(capture)
    request = httpx.Request("POST", "http://127.0.0.1:2024/threads/gh-thread-buf/runs")
    response = httpx.Response(409, request=request)
    conflict = ConflictError("Thread is already running a task.", response=response, body={"message": "busy"})
    client = MagicMock()
    client.threads.create = AsyncMock(return_value={"thread_id": "gh-thread-buf"})
    client.threads.update = AsyncMock(return_value={"thread_id": "gh-thread-buf"})
    client.threads.get = AsyncMock(return_value={"thread_id": "gh-thread-buf"})
    client.runs.create = AsyncMock(side_effect=conflict)
    manager._client = client

    message = _message(7)
    await manager.start()
    try:
        await manager._handle_chat(message)
        await _settle(manager)
    finally:
        await manager.stop()

    assert any(item.text == THREAD_BUSY_MESSAGE for item in outbound)
    assert ack_channel.acks == [("queued", message.metadata["followup_ack"])]
    assert list(manager._followup_buffers["gh-thread-buf"].values())[0].text == "comment 7"
