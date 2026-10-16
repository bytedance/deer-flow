"""Regression anchor: ``/model`` status must not read agent configs on the event loop.

``_resolve_configured_model_name`` resolves a custom-agent selection into its
configured model, which means reading the owner's agent config from disk.
Every run and channel shares the Gateway event loop, so that read must happen
in a worker thread (``asyncio.to_thread``), mirroring ``_handle_agent_command``.
If the ``to_thread`` wrapper is ever dropped, the strict Blockbuster gate raises
``BlockingError`` at the real filesystem read below.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.channels import manager as manager_module
from app.channels.manager import ChannelManager
from app.channels.message_bus import InboundMessage, MessageBus
from app.channels.store import JsonChannelStore

pytestmark = pytest.mark.asyncio


async def test_resolve_configured_model_name_loads_agent_config_off_loop(monkeypatch, tmp_path) -> None:
    config_file = tmp_path / "agent.yaml"
    await asyncio.to_thread(config_file.write_text, "model: cfg-agent-model\n", encoding="utf-8")

    def spy_load_agent_config(name, *, user_id=None):
        # A genuine filesystem read: if ``_resolve_configured_model_name``
        # calls the loader synchronously again, the Blockbuster gate fires here.
        text = config_file.read_text(encoding="utf-8")
        assert name == "cfg-agent"
        return SimpleNamespace(model=text.split(":", 1)[1].strip())

    # Module-level import (collection time): deriving the import path here
    # would itself perform file reads under the Blockbuster gate.
    monkeypatch.setattr(manager_module, "load_agent_config", spy_load_agent_config)

    # The JSON store constructor only resolves paths; keep setup I/O off the loop, same
    # as the file writes above — only the manager call is the unit under test.
    store = await asyncio.to_thread(JsonChannelStore, path=tmp_path / "store.json")
    manager = ChannelManager(bus=MessageBus(), store=store)
    thread_id = "thread-1"
    # Seeded cache: the assistant resolution needs no client round-trip.
    manager._thread_agent_names[thread_id] = "cfg-agent"
    msg = InboundMessage(channel_name="test", chat_id="chat1", user_id="platform-user", text="/model")

    resolved, source = await manager._resolve_configured_model_name(MagicMock(), msg, thread_id)

    assert (resolved, source) == ("cfg-agent-model", "agent")
