"""Stopgap cancellation for pending memory-extraction work (#3364).

Deleting an agent (or clearing its memory) must drop that scope's
still-debouncing extraction contexts. Otherwise the debounce Timer fires after
deletion, invokes the extraction LLM for a scope that no longer exists, and
re-persists state that blocks recreating an agent with the same name. This file
pins the in-process stopgap: ``MemoryUpdateQueue.cancel_by_agent``, the
``MemoryManager.cancel_by_agent`` contract default, DeerMem's override plus its
``clear_memory`` linkage, and the best-effort hookup in the agent-deletion
route. In-flight contexts already pulled out of the queue are NOT interrupted;
the durable outbox design owns full fencing later.
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from deerflow.agents.memory.backends.deermem.deer_mem import DeerMem
from deerflow.agents.memory.backends.deermem.deermem.config import DeerMemConfig
from deerflow.agents.memory.backends.deermem.deermem.core.queue import ConversationContext, MemoryUpdateQueue


def _queue(updater: MagicMock | None = None) -> MemoryUpdateQueue:
    """A MemoryUpdateQueue with DI config + a (mock) updater; timer disabled."""
    return MemoryUpdateQueue(DeerMemConfig(), updater or MagicMock())


# ---------------------------------------------------------------------------
# Queue level
# ---------------------------------------------------------------------------


def test_cancel_by_agent_removes_only_matching_agent_items() -> None:
    queue = _queue()
    queue._items = [
        ConversationContext(thread_id="t1", messages=["a"], agent_name="agent-a"),
        ConversationContext(thread_id="t2", messages=["b"], agent_name="agent-b"),
        ConversationContext(thread_id="t3", messages=["c"], agent_name="agent-a"),
    ]

    removed = queue.cancel_by_agent("agent-a")

    assert removed == 2
    assert [context.agent_name for context in queue._items] == ["agent-b"]


def test_cancel_by_agent_user_scope_filters_matching_owner_only() -> None:
    queue = _queue()
    queue._items = [
        ConversationContext(thread_id="t1", messages=["a"], agent_name="agent-a", user_id="alice"),
        ConversationContext(thread_id="t2", messages=["b"], agent_name="agent-a", user_id="bob"),
    ]

    assert queue.cancel_by_agent("agent-a", user_id="alice") == 1
    assert [context.user_id for context in queue._items] == ["bob"]
    # Unscoped cancellation drops the remaining same-agent entry.
    assert queue.cancel_by_agent("agent-a") == 1
    assert queue.pending_count == 0


def test_cancel_by_agent_returns_zero_without_matches() -> None:
    queue = _queue()
    queue._items = [ConversationContext(thread_id="t1", messages=["a"], agent_name="agent-b")]

    assert queue.cancel_by_agent("agent-a") == 0
    assert queue.cancel_by_agent("agent-a", user_id="alice") == 0
    assert queue.pending_count == 1


def test_cancel_by_agent_is_safe_while_worker_holds_processing_flag() -> None:
    """A worker that already pulled contexts out keeps them; pending ones go."""
    queue = _queue()
    queue._processing = True
    queue._items = [
        ConversationContext(thread_id="t1", messages=["a"], agent_name="agent-a"),
        ConversationContext(thread_id="t2", messages=["b"], agent_name="agent-b"),
    ]

    assert queue.cancel_by_agent("agent-a") == 1
    assert [context.agent_name for context in queue._items] == ["agent-b"]


# ---------------------------------------------------------------------------
# MemoryManager contract default
# ---------------------------------------------------------------------------


def _minimal_manager_cls():
    from deerflow.agents.memory.manager import MemoryManager

    class _Minimal(MemoryManager):
        def add(self, thread_id, messages, *, agent_name=None, user_id=None, trace_id=None):
            return None

        def get_context(self, user_id, *, agent_name=None, thread_id=None):
            return ""

        @classmethod
        def from_config(cls, backend_config=None, *, mode="middleware", **host_hooks):
            return cls(backend_config=backend_config or {}, mode=mode)

    return _Minimal


def test_base_manager_cancel_by_agent_defaults_to_zero() -> None:
    """Backends without a debounce buffer have nothing to cancel; the default
    keeps route-level callers unconditional instead of duck-typing."""
    manager = _minimal_manager_cls()(backend_config={}, mode="middleware")

    assert manager.cancel_by_agent("any-agent") == 0
    assert manager.cancel_by_agent("any-agent", user_id="u") == 0


# ---------------------------------------------------------------------------
# DeerMem level
# ---------------------------------------------------------------------------


@pytest.fixture()
def deermem(tmp_path: Path):
    return DeerMem(backend_config={"storage_path": str(tmp_path)})


def test_deer_mem_cancel_by_agent_normalizes_name_and_delegates(deermem) -> None:
    queue = deermem._queue
    queue._items = [
        ConversationContext(thread_id="t1", messages=["a"], agent_name="agent-a"),
        ConversationContext(thread_id="t2", messages=["b"], agent_name="agent-b"),
    ]

    # Public agent identifiers are case-insensitive; canonicalization happens
    # at the manager boundary exactly like add/clear do.
    assert deermem.cancel_by_agent("Agent-A") == 1
    assert [context.agent_name for context in queue._items] == ["agent-b"]


def test_deer_mem_clear_memory_cancels_pending_same_scope_first(deermem) -> None:
    queue = deermem._queue
    queue._items = [
        ConversationContext(thread_id="t1", messages=["a"], agent_name="doomed", user_id="alice"),
        ConversationContext(thread_id="t2", messages=["b"], agent_name="survivor", user_id="alice"),
    ]

    deermem.clear_memory(agent_name="doomed", user_id="alice")

    assert [context.agent_name for context in queue._items] == ["survivor"]
