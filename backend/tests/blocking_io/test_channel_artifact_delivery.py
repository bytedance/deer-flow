"""Regression anchors: resolving reply artifacts must not block the event loop.

When a run presents files, ``ChannelManager`` turns each virtual
``/mnt/user-data/outputs/...`` path into a host path before delivering the
reply: ``resolve_outputs_confined_path`` resolves it (``realpath``) and checks it
against the resolved outputs root, then the file is checked with ``is_file`` and
``stat``. Both reply paths (``runs.wait`` and ``runs.stream``) run that in a
worker through ``asyncio.to_thread``.

Each case drives the real manager with a real thread outputs directory under a
temporary ``DEER_FLOW_HOME`` and asserts the outbound reply carries the
resolved attachment, so an anchor cannot pass because the artifact was never
resolved.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from blockbuster import BlockingError

from app.channels import manager as mgr
from app.channels.message_bus import InboundMessage, MessageBus, OutboundMessage
from app.channels.store import JsonChannelStore
from deerflow.config import paths as paths_mod

pytestmark = pytest.mark.asyncio

_THREAD_ID = "thread-artifacts"
_ARTIFACT = "/mnt/user-data/outputs/report.txt"


def _final_state() -> dict:
    return {
        "messages": [
            {"type": "human", "content": "make a report"},
            {"type": "ai", "content": "", "tool_calls": [{"name": "present_files", "args": {"filepaths": [_ARTIFACT]}}]},
            {"type": "tool", "name": "present_files", "content": "ok"},
            {"type": "ai", "content": "Here is the report."},
        ],
        "artifacts": [_ARTIFACT],
    }


def _write_artifact(user_id: str) -> None:
    outputs = paths_mod.get_paths().sandbox_outputs_dir(_THREAD_ID, user_id=user_id)
    outputs.mkdir(parents=True, exist_ok=True)
    (outputs / "report.txt").write_text("report", encoding="utf-8")


@pytest_asyncio.fixture
async def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr(paths_mod, "_paths", None)
    storage_user_id = await asyncio.to_thread(mgr._safe_user_id_for_run, "user-1")
    await asyncio.to_thread(_write_artifact, storage_user_id)
    return tmp_path


async def _deliver(home: Path, channel_name: str, client: MagicMock) -> OutboundMessage:
    bus = MessageBus()
    manager = mgr.ChannelManager(bus=bus, store=JsonChannelStore(path=home / "store.json"))
    manager._client = client
    finals: list[OutboundMessage] = []

    async def capture(msg: OutboundMessage) -> None:
        if msg.is_final:
            finals.append(msg)

    bus.subscribe_outbound(capture)
    await manager.start()
    try:
        await bus.publish_inbound(InboundMessage(channel_name=channel_name, chat_id="chat-1", user_id="user-1", text="make a report", thread_ts="source-1"))
        async with asyncio.timeout(5):
            while not finals:
                await asyncio.sleep(0.01)
    finally:
        await manager.stop()
    return finals[0]


def _client() -> MagicMock:
    client = MagicMock()
    client.threads.create = AsyncMock(return_value={"thread_id": _THREAD_ID})
    client.threads.get = AsyncMock(return_value={"thread_id": _THREAD_ID})
    client.threads.update = AsyncMock(return_value={"thread_id": _THREAD_ID})
    return client


async def test_wait_reply_resolves_artifacts_off_the_loop(home: Path) -> None:
    client = _client()
    client.runs.wait = AsyncMock(return_value=_final_state())

    reply = await _deliver(home, "slack", client)

    assert [attachment.filename for attachment in reply.attachments] == ["report.txt"]
    assert reply.attachments[0].size == len("report")


async def test_streamed_reply_resolves_artifacts_off_the_loop(home: Path) -> None:
    async def stream(*_args, **_kwargs):
        yield SimpleNamespace(event="values", data=_final_state())

    client = _client()
    client.runs.stream = MagicMock(side_effect=stream)

    reply = await _deliver(home, "telegram", client)

    assert [attachment.filename for attachment in reply.attachments] == ["report.txt"]
    assert reply.attachments[0].size == len("report")


async def test_blocking_probe_inline_artifact_delivery_actually_trips_the_gate(home: Path) -> None:
    """Meta-check: the same resolution inline on the loop is caught by the gate."""
    storage_user_id = await asyncio.to_thread(mgr._safe_user_id_for_run, "user-1")
    with pytest.raises(BlockingError):
        mgr._prepare_artifact_delivery(_THREAD_ID, "Here is the report.", [_ARTIFACT], user_id=storage_user_id)
