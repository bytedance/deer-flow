"""Regression: async memory flush hook must not build the manager on the loop."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from deerflow.agents.memory.manager import get_memory_manager, reset_memory_manager
from deerflow.agents.memory.summarization_hook import amemory_flush_hook
from deerflow.agents.middlewares.summarization_middleware import SummarizationEvent
from deerflow.config.memory_config import MemoryConfig, get_memory_config, set_memory_config


def _cancel_timer(manager) -> None:
    timer = getattr(getattr(manager, "_queue", None), "_timer", None)
    if timer is not None:
        timer.cancel()
        manager._queue._timer = None


@pytest.mark.asyncio
async def test_amemory_flush_hook_cold_start_does_not_block_event_loop(tmp_path: Path) -> None:
    """First get_memory_manager() scans backends; that I/O must stay off-loop."""
    original = get_memory_config()
    reset_memory_manager()
    set_memory_config(
        MemoryConfig(
            enabled=True,
            manager_class="deermem",
            backend_config={
                "storage_path": str(tmp_path),
                "token_counting": "char",
                "debounce_seconds": 30,
                "host_llm": MagicMock(),
            },
        )
    )
    try:
        await amemory_flush_hook(
            SummarizationEvent(
                messages_to_summarize=(
                    HumanMessage(content="Remember that I like Python."),
                    AIMessage(content="I'll keep that preference in mind."),
                ),
                preserved_messages=(),
                thread_id="thread-1",
                agent_name="researcher",
                runtime=SimpleNamespace(context={"thread_id": "thread-1", "agent_name": "researcher", "user_id": "alice"}),
            )
        )
        _cancel_timer(get_memory_manager())
    finally:
        reset_memory_manager()
        set_memory_config(original)
