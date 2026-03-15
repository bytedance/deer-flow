"""Tests for memory update queue deduplication behavior."""

from types import SimpleNamespace
from unittest.mock import patch

from src.agents.memory.queue import MemoryUpdateQueue


def _enabled_memory_config() -> SimpleNamespace:
    return SimpleNamespace(enabled=True, debounce_seconds=30)


def test_queue_deduplicates_same_thread_and_same_agent() -> None:
    queue = MemoryUpdateQueue()

    with (
        patch("src.agents.memory.queue.get_memory_config", return_value=_enabled_memory_config()),
        patch.object(queue, "_reset_timer"),
    ):
        queue.add("thread-1", ["m1"], agent_name="agent-a")
        queue.add("thread-1", ["m2"], agent_name="agent-a")

    assert queue.pending_count == 1
    assert queue._queue[0].messages == ["m2"]


def test_queue_keeps_distinct_agents_for_same_thread() -> None:
    queue = MemoryUpdateQueue()

    with (
        patch("src.agents.memory.queue.get_memory_config", return_value=_enabled_memory_config()),
        patch.object(queue, "_reset_timer"),
    ):
        queue.add("thread-1", ["global"], agent_name=None)
        queue.add("thread-1", ["agent"], agent_name="agent-a")

    assert queue.pending_count == 2
    agent_names = {ctx.agent_name for ctx in queue._queue}
    assert agent_names == {None, "agent-a"}
