"""Regression anchors: the async compaction path must flush memory off the loop.

``memory_flush_hook`` hands the about-to-be-summarized messages to the memory
backend's ``add_nowait``. mem0 and Honcho inherit the default, which calls
their sync HTTP ``add``, so firing the hook inline from ``acompact_state``
blocked the event loop for the whole backend request.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from deerflow.agents.memory.backends.honcho.honcho_manager import HonchoMemoryManager
from deerflow.agents.memory.backends.mem0.mem0_manager import Mem0Manager
from deerflow.agents.memory.summarization_hook import memory_flush_hook
from deerflow.agents.middlewares.summarization_middleware import DeerFlowSummarizationMiddleware
from deerflow.config.memory_config import MemoryConfig

HOOK_MODULE = "deerflow.agents.memory.summarization_hook"


class _BlockingWrites:
    """Records a backend write only after doing real blocking file IO."""

    def __init__(self, probe_dir: Path) -> None:
        self._probe = probe_dir / "probe.txt"
        self.written: list[str] = []

    def write(self, contents: list[str]) -> None:
        self._probe.write_text("blocked io")
        self.written.extend(contents)


class _FakeMem0Client:
    def __init__(self, writes: _BlockingWrites) -> None:
        self._writes = writes

    def add_memories(self, *, messages: list[dict[str, str]], **_: Any) -> None:
        self._writes.write([message["content"] for message in messages])

    def close(self) -> None:
        pass


class _FakeHonchoClient:
    def __init__(self, writes: _BlockingWrites) -> None:
        self._writes = writes

    def get_or_create_peer(self, ws: str, pid: str) -> None:
        pass

    def get_or_create_session(self, ws: str, sid: str) -> None:
        pass

    def set_session_peers(self, ws: str, sid: str, pids: list[str]) -> None:
        pass

    def add_messages(self, ws: str, sid: str, msgs: list[dict[str, str]]) -> None:
        self._writes.write([message["content"] for message in msgs])

    def close(self) -> None:
        pass


def _mem0(writes: _BlockingWrites, monkeypatch: pytest.MonkeyPatch) -> Mem0Manager:
    monkeypatch.setenv("MEM0_API_KEY", "test-key")
    manager = Mem0Manager(backend_config={})
    manager._client = _FakeMem0Client(writes)
    return manager


def _honcho(writes: _BlockingWrites, monkeypatch: pytest.MonkeyPatch) -> HonchoMemoryManager:
    manager = HonchoMemoryManager.from_config({"base_url": "http://honcho.test"})
    manager._client = _FakeHonchoClient(writes)
    return manager


_BACKENDS = [pytest.param(_mem0, id="mem0"), pytest.param(_honcho, id="honcho")]


def _middleware() -> DeerFlowSummarizationMiddleware:
    model = MagicMock()
    model.ainvoke = AsyncMock(return_value=SimpleNamespace(text="compressed summary"))
    model.with_config.return_value = model
    return DeerFlowSummarizationMiddleware(
        model=model,
        trigger=("messages", 4),
        keep=("messages", 2),
        token_counter=len,
        before_summarization=[memory_flush_hook],
    )


def _messages() -> list[Any]:
    return [
        HumanMessage("I prefer green tea", id="h1"),
        AIMessage("Noted", id="a1"),
        HumanMessage("Plan my week", id="h2"),
        AIMessage("Here is a plan", id="a2"),
    ]


_RUNTIME = SimpleNamespace(context={"thread_id": "thread-1", "user_id": "alice"})


@pytest.mark.asyncio
@pytest.mark.parametrize("make_manager", _BACKENDS)
async def test_async_compaction_flushes_memory_off_the_event_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_manager: Any) -> None:
    writes = _BlockingWrites(tmp_path)
    manager = make_manager(writes, monkeypatch)
    middleware = _middleware()

    with patch(HOOK_MODULE + ".get_memory_config", return_value=MemoryConfig(enabled=True)), patch(HOOK_MODULE + ".get_memory_manager", return_value=manager):
        result = await middleware.abefore_model({"messages": _messages()}, _RUNTIME)

    assert result is not None
    assert result["summary_text"] == "compressed summary"
    # The hook swallows failures, so a write that tripped the gate on the loop
    # would only be logged; the landed write is what proves it ran off-loop.
    assert writes.written == ["I prefer green tea", "Noted"]


@pytest.mark.asyncio
@pytest.mark.parametrize("make_manager", _BACKENDS)
async def test_blocking_probe_inline_flush_actually_trips_the_gate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_manager: Any, caplog: pytest.LogCaptureFixture) -> None:
    """Meta-check: firing the hooks inline on the loop is caught by the gate."""
    writes = _BlockingWrites(tmp_path)
    manager = make_manager(writes, monkeypatch)
    middleware = _middleware()
    messages = _messages()

    with (
        patch(HOOK_MODULE + ".get_memory_config", return_value=MemoryConfig(enabled=True)),
        patch(HOOK_MODULE + ".get_memory_manager", return_value=manager),
        caplog.at_level("DEBUG"),
    ):
        middleware._fire_hooks(messages[:2], messages[2:], _RUNTIME)

    assert writes.written == []
    assert "Blocking call" in caplog.text
