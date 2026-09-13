"""Regression anchors for enqueue-time memory clear-generation reads."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.runtime import Runtime

from deerflow.agents.memory.backends.deermem.deer_mem import DeerMem
from deerflow.agents.memory.summarization_hook import memory_flush_hook
from deerflow.agents.middlewares import memory_middleware as memory_middleware_module
from deerflow.agents.middlewares.memory_middleware import MemoryMiddleware
from deerflow.agents.middlewares.summarization_middleware import DeerFlowSummarizationMiddleware
from deerflow.config.memory_config import MemoryConfig

pytestmark = pytest.mark.asyncio


def _messages() -> list:
    return [
        HumanMessage(content="I prefer Python for future examples."),
        AIMessage(content="I will use Python for future examples."),
    ]


@pytest.fixture
def manager(tmp_path) -> DeerMem:
    return DeerMem(
        backend_config={
            "storage_path": str(tmp_path),
            "retrieval_adapter": "",
            "debounce_seconds": 300,
        }
    )


async def test_memory_middleware_async_enqueue_offloads_generation_read(manager: DeerMem, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(memory_middleware_module, "get_memory_manager", lambda: manager)
    middleware = MemoryMiddleware(agent_name="researcher", memory_config=MemoryConfig(enabled=True))
    runtime = Runtime(context={"thread_id": "thread-async", "user_id": "alice"})

    await middleware.aafter_agent({"messages": _messages()}, runtime)

    assert manager._queue.pending_count == 1
    assert manager._queue._items[0].clear_generation == (0, 0)
    manager._queue.clear()


async def test_async_summarization_offloads_memory_flush_hook(manager: DeerMem, monkeypatch: pytest.MonkeyPatch) -> None:
    import deerflow.agents.memory.summarization_hook as hook_module

    monkeypatch.setattr(hook_module, "get_memory_config", lambda: MemoryConfig(enabled=True))
    monkeypatch.setattr(hook_module, "get_memory_manager", lambda: manager)
    model = MagicMock()
    model.ainvoke = AsyncMock(return_value=SimpleNamespace(text="compressed summary"))
    model.with_config.return_value = model
    middleware = DeerFlowSummarizationMiddleware(
        model=model,
        trigger=("messages", 4),
        keep=("messages", 2),
        token_counter=len,
        before_summarization=[memory_flush_hook],
    )
    messages = [
        HumanMessage(content="old-user"),
        AIMessage(content="old-assistant"),
        HumanMessage(content="current-user"),
        AIMessage(content="current-assistant"),
    ]

    with patch.object(manager._queue, "_schedule_timer"):
        result = await middleware.abefore_model(
            {"messages": messages},
            SimpleNamespace(context={"thread_id": "thread-summary", "agent_name": "researcher", "user_id": "alice"}),
        )

    assert result is not None
    assert result["summary_text"] == "compressed summary"
    assert manager._queue.pending_count == 1
    assert manager._queue._items[0].clear_generation == (0, 0)
