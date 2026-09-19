"""Regression: DeerMem async enqueue must not peek the manifest on the loop."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from deerflow.agents.memory.backends.deermem.deer_mem import DeerMem


def _manager(tmp_path: Path) -> DeerMem:
    return DeerMem(
        backend_config={
            "storage_path": str(tmp_path),
            "fact_confidence_threshold": 0.7,
            "max_facts": 100,
            "debounce_seconds": 30,
            "token_counting": "char",
            "host_llm": MagicMock(),
        }
    )


def _cancel_timer(manager: DeerMem) -> None:
    timer = manager._queue._timer
    if timer is not None:
        timer.cancel()
        manager._queue._timer = None


@pytest.mark.asyncio
async def test_deermem_async_enqueue_does_not_block_event_loop(tmp_path: Path) -> None:
    manager = await asyncio.to_thread(_manager, tmp_path)
    messages: list[Any] = [
        HumanMessage(content="Remember that I like Python."),
        AIMessage(content="I'll keep that preference in mind."),
    ]

    await manager.aadd("thread-1", messages, agent_name="researcher", user_id="alice")
    await asyncio.to_thread(_cancel_timer, manager)

    await manager.aadd_nowait("thread-1", messages, agent_name="researcher", user_id="alice")
    await asyncio.to_thread(_cancel_timer, manager)
