"""Regression anchor: the DeerMem watermark sidecar stays off the event loop."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from deerflow.agents.memory.backends.deermem.deermem.config import DeerMemConfig
from deerflow.agents.memory.backends.deermem.deermem.core.storage import FileMemoryStorage
from deerflow.agents.memory.backends.deermem.deermem.core.updater import MemoryUpdater

pytestmark = pytest.mark.asyncio


class _Response:
    content = json.dumps({"user": {}, "history": {}, "newFacts": [], "factsToRemove": []})
    usage_metadata: dict[str, int] | None = None


class _LLM:
    def __init__(self) -> None:
        self.calls = 0

    def invoke(self, prompt: Any, config: Any = None) -> _Response:
        del prompt, config
        self.calls += 1
        return _Response()


def _updater(root: Path, llm: _LLM) -> MemoryUpdater:
    # Config validation stats storage_path; the host builds DeerMem at startup.
    config = DeerMemConfig(storage_path=str(root), retrieval_adapter="")
    return MemoryUpdater(config, FileMemoryStorage(config), llm)


async def test_async_update_reads_and_writes_the_watermark_sidecar_off_the_loop(tmp_path: Path) -> None:
    llm = _LLM()
    messages = [HumanMessage(content="I prefer green tea.", id="h1"), AIMessage(content="Noted.", id="a1")]

    first = await asyncio.to_thread(_updater, tmp_path, llm)
    assert await first.aupdate_memory(messages, thread_id="t1", agent_name="a", user_id="u")
    # A fresh updater (a restarted process) reads the sidecar and skips the batch.
    restarted = await asyncio.to_thread(_updater, tmp_path, llm)
    assert await restarted.aupdate_memory(messages, thread_id="t1", agent_name="a", user_id="u")

    assert llm.calls == 1
    sidecar = tmp_path / "users" / "u" / "agents" / "a" / ".metadata" / "watermarks.json"
    assert await asyncio.to_thread(sidecar.is_file)
