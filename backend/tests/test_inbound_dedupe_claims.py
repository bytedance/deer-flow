"""A retired handler must not release a replacement delivery's dedupe claim."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.channels import dedupe_store as dedupe_module
from app.channels.dedupe_store import MemoryInboundDedupeStore
from app.channels.manager import ChannelManager
from app.channels.message_bus import InboundMessage, MessageBus
from app.channels.store import JsonChannelStore


def _message(attempt: str, *, message_id: str = "same-provider-message") -> InboundMessage:
    return InboundMessage(
        channel_name="slack",
        chat_id="chat",
        user_id="user",
        text="same provider payload",
        metadata={"team_id": "team", "message_id": message_id, "attempt": attempt},
    )


@pytest.mark.asyncio
async def test_current_failure_still_allows_redelivery(tmp_path):
    manager = ChannelManager(bus=MessageBus(), store=JsonChannelStore(path=tmp_path / "store.json"))
    original = _message("old")
    assert await manager._is_duplicate_inbound(original) is False
    assert await manager._is_duplicate_inbound(_message("retry")) is True
    await manager._release_inbound_dedupe_key(original)
    assert await manager._is_duplicate_inbound(_message("retry")) is False


@pytest.mark.asyncio
async def test_repeated_cleanup_does_not_release_a_retry(monkeypatch, tmp_path):
    # Even an immediate retry at the same clock tick needs a new receipt.
    monkeypatch.setattr(dedupe_module, "time", SimpleNamespace(monotonic=lambda: 0.0))
    manager = ChannelManager(bus=MessageBus(), store=JsonChannelStore(path=tmp_path / "store.json"))
    old, replacement = _message("old"), _message("new")
    assert await manager._is_duplicate_inbound(old) is False
    await manager._release_inbound_dedupe_key(old)
    assert await manager._is_duplicate_inbound(replacement) is False
    await manager._release_inbound_dedupe_key(old)
    assert await manager._is_duplicate_inbound(_message("third")) is True
    await manager._release_inbound_dedupe_key(replacement)
    assert await manager._is_duplicate_inbound(_message("retry")) is False


@pytest.mark.asyncio
@pytest.mark.parametrize("reclaim", ["ttl", "capacity"])
@pytest.mark.parametrize("old_outcome", ["success", "error", "cancel"])
@pytest.mark.parametrize("reuse_message", [False, True], ids=["new-envelope", "reused-envelope"])
async def test_retired_worker_preserves_replacement_claim(monkeypatch, tmp_path, reclaim, old_outcome, reuse_message):
    clock = [0.0]
    # Replace only this module's clock, not asyncio's event-loop clock.
    monkeypatch.setattr(dedupe_module, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    store = MemoryInboundDedupeStore(max_entries=1 if reclaim == "capacity" else 4096)
    bus = MessageBus()
    manager = ChannelManager(bus=bus, store=JsonChannelStore(path=tmp_path / "store.json"), inbound_dedupe_store=store, max_concurrency=3)
    old_started, new_started = asyncio.Event(), asyncio.Event()
    finish_old, finish_new = asyncio.Event(), asyncio.Event()
    released, sentinel_handled = asyncio.Event(), asyncio.Event()
    filler_handled = [asyncio.Event(), asyncio.Event()]
    admitted = []
    old_worker = []
    release = store.release

    async def observe_release(claim):
        await release(claim)
        released.set()

    monkeypatch.setattr(store, "release", observe_release)

    async def handler(msg):
        attempt = msg.metadata["attempt"]
        admitted.append(attempt)
        if attempt == "old":
            old_worker.append(asyncio.current_task())
            old_started.set()
            await finish_old.wait()
            if old_outcome == "error":
                raise RuntimeError("old handling failed after redelivery was admitted")
            released.set()
        elif attempt == "new":
            new_started.set()
            await finish_new.wait()
        elif attempt.startswith("filler-"):
            filler_handled[int(attempt[-1])].set()
        elif attempt == "sentinel":
            sentinel_handled.set()

    monkeypatch.setattr(manager, "_handle_message", handler)
    await manager.start()
    try:
        original = _message("old")
        await bus.publish_inbound(original)
        await asyncio.wait_for(old_started.wait(), 2)
        if reclaim == "ttl":
            clock[0] = dedupe_module.INBOUND_DEDUPE_TTL_SECONDS + 1
        else:
            for index in range(2):
                await bus.publish_inbound(_message(f"filler-{index}", message_id=f"other-{index}"))
                await asyncio.wait_for(filler_handled[index].wait(), 2)
        if reuse_message:
            original.metadata = {**original.metadata, "attempt": "new"}
            await bus.publish_inbound(original)
        else:
            await bus.publish_inbound(_message("new"))
        await asyncio.wait_for(new_started.wait(), 2)
        assert await manager._is_duplicate_inbound(_message("check-new-is-held")) is True
        if old_outcome == "cancel":
            old_worker[0].cancel()
        else:
            finish_old.set()
        await asyncio.wait_for(released.wait(), 2)
        await bus.publish_inbound(_message("third"))
        await bus.publish_inbound(_message("sentinel", message_id="sentinel-id"))
        await asyncio.wait_for(sentinel_handled.wait(), 2)
        assert not finish_new.is_set()
        assert "third" not in admitted, f"Old cleanup admitted another execution: {admitted}"
    finally:
        finish_old.set()
        finish_new.set()
        await asyncio.wait_for(bus.join_inbound(), 2)
        await manager.stop()


@pytest.mark.asyncio
async def test_message_copy_keeps_the_original_cleanup_key(tmp_path):
    manager = ChannelManager(bus=MessageBus(), store=JsonChannelStore(path=tmp_path / "store.json"))
    original = _message("original")
    other = _message("other", message_id="other-id")
    assert await manager._is_duplicate_inbound(original) is False
    assert await manager._is_duplicate_inbound(other) is False
    copied = replace(original, metadata=dict(other.metadata))
    assert copied._inbound_dedupe_claim is original._inbound_dedupe_claim
    await manager._release_inbound_dedupe_key(copied)
    assert await manager._is_duplicate_inbound(_message("retry")) is False
    assert await manager._is_duplicate_inbound(_message("other-retry", message_id="other-id")) is True


@pytest.mark.asyncio
async def test_receive_file_replacement_keeps_the_admission_receipt(monkeypatch, tmp_path):
    from app.channels import manager as manager_module
    from app.channels import service as service_module

    manager = ChannelManager(bus=MessageBus(), store=JsonChannelStore(path=tmp_path / "store.json"))
    original = _message("original")
    original.files = [{"filename": "example.txt"}]
    assert await manager._is_duplicate_inbound(original) is False
    rewritten = _message("rewritten", message_id="adapter-id")
    channel = SimpleNamespace(receive_file=AsyncMock(return_value=rewritten))
    monkeypatch.setattr(service_module, "get_channel_service", lambda: SimpleNamespace(get_channel=lambda name: channel))
    monkeypatch.setattr(manager, "_resolve_run_params", lambda msg, thread_id: ("lead_agent", {}, {}))
    monkeypatch.setattr(manager, "_apply_channel_policy", AsyncMock(return_value=None))
    monkeypatch.setattr(manager, "_channel_supports_streaming", lambda name: True)
    monkeypatch.setattr(manager_module, "_ingest_inbound_files", AsyncMock(return_value=[]))

    async def consume_stream(client, message, *args, **kwargs):
        assert message is rewritten
        assert message._inbound_dedupe_claim is original._inbound_dedupe_claim
        await manager._release_inbound_dedupe_key(message)

    monkeypatch.setattr(manager, "_handle_streaming_chat", consume_stream)
    await manager._handle_chat_on_thread(SimpleNamespace(), original, "thread", storage_user_id="owner")
    assert await manager._is_duplicate_inbound(_message("retry")) is False


@pytest.mark.asyncio
@pytest.mark.parametrize("old_has_error", [False, True], ids=["success-control", "late-stream-error"])
async def test_retired_stream_preserves_replacement_claim(monkeypatch, tmp_path, old_has_error):
    clock = [0.0]
    monkeypatch.setattr(dedupe_module, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    store = MemoryInboundDedupeStore()
    bus = MessageBus()
    manager = ChannelManager(bus=bus, store=JsonChannelStore(path=tmp_path / "store.json"), inbound_dedupe_store=store, max_concurrency=2)
    old_publishing, new_publishing = asyncio.Event(), asyncio.Event()
    finish_old_publish, finish_new_publish = asyncio.Event(), asyncio.Event()
    old_finished, sentinel_handled = asyncio.Event(), asyncio.Event()
    remote_calls = []
    remote_active = [False]

    async def outbound(message):
        if not message.is_final:
            return
        if message.text == "old-reply":
            old_publishing.set()
            await finish_old_publish.wait()
        elif message.text == "new-reply":
            new_publishing.set()
            await finish_new_publish.wait()

    bus.subscribe_outbound(outbound)

    async def handler(msg):
        attempt = msg.metadata["attempt"]
        if attempt == "sentinel":
            sentinel_handled.set()
            return

        async def stream(*args, **kwargs):
            assert not remote_active[0], "Do not bypass concurrent-run rejection"
            remote_active[0] = True
            remote_calls.append(attempt)
            try:
                yield SimpleNamespace(event="values", data={"messages": [{"type": "ai", "id": attempt, "content": f"{attempt}-reply"}]})
                if attempt == "old" and old_has_error:
                    yield SimpleNamespace(event="error", data={"name": "RuntimeError", "message": "model execution failed"})
            finally:
                remote_active[0] = False

        client = SimpleNamespace(runs=SimpleNamespace(stream=stream))
        await manager._handle_streaming_chat(client, msg, "same-thread", "lead_agent", {}, {}, {"role": "user", "content": msg.text})
        if attempt == "old":
            old_finished.set()

    monkeypatch.setattr(manager, "_handle_message", handler)
    await manager.start()
    try:
        await bus.publish_inbound(_message("old"))
        await asyncio.wait_for(old_publishing.wait(), 2)
        assert not remote_active[0], "The old remote run already ended"
        clock[0] = dedupe_module.INBOUND_DEDUPE_TTL_SECONDS + 1
        await bus.publish_inbound(_message("new"))
        await asyncio.wait_for(new_publishing.wait(), 2)
        assert not remote_active[0], "Only the replacement reply is waiting"
        assert await manager._is_duplicate_inbound(_message("check-new-is-held")) is True
        finish_old_publish.set()
        await asyncio.wait_for(old_finished.wait(), 2)
        await bus.publish_inbound(_message("third"))
        await bus.publish_inbound(_message("sentinel", message_id="sentinel-id"))
        await asyncio.wait_for(sentinel_handled.wait(), 2)
        assert not finish_new_publish.is_set()
        assert remote_calls == ["old", "new"], f"Stale cleanup caused an extra run: {remote_calls}"
    finally:
        finish_old_publish.set()
        finish_new_publish.set()
        await asyncio.wait_for(bus.join_inbound(), 2)
        await manager.stop()
