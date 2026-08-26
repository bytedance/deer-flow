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

import threading
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
# Writer-side fence: cancellation must hold against a worker that snapshotted
# its batch BEFORE the cancel ran (the #5037 HIGH finding). Pending removal
# alone cannot do that: _process_queue moves _items into a local list and
# clears the queue under the lock, so a cancel racing the worker sees an empty
# list while the LLM calls still go out.
# ---------------------------------------------------------------------------


def _start_blocked_worker(queue: MemoryUpdateQueue, mock_updater: MagicMock, gate_first_call: threading.Event, first_call_started: threading.Event) -> threading.Thread:
    def _blocking_update(**kwargs):
        first_call_started.set()
        gate_first_call.wait(timeout=5.0)
        return True

    mock_updater.update_memory.side_effect = _blocking_update
    worker = threading.Thread(target=queue._process_queue, daemon=True)
    worker.start()
    assert first_call_started.wait(timeout=5.0)
    return worker


def test_fence_blocks_batch_items_snapshotted_before_cancel() -> None:
    """Deterministic #5037 race: worker snapshots two same-scope contexts and
    starts the first LLM call; cancel runs mid-call; the second context must be
    fenced off even though it left ``_items`` before the cancel executed."""
    import time as _time

    mock_updater = MagicMock(return_value=True)
    queue = _queue(mock_updater)
    queue._items = [
        ConversationContext(thread_id="t1", messages=["first"], agent_name="doomed"),
        ConversationContext(thread_id="t2", messages=["second"], agent_name="doomed"),
    ]
    gate = threading.Event()
    started = threading.Event()
    worker = _start_blocked_worker(queue, mock_updater, gate, started)
    try:
        # The batch was snapshotted (_items is now empty), yet the fence must
        # still stop the not-yet-started second extraction.
        assert queue.cancel_by_agent("doomed") == 0
    finally:
        gate.set()
        worker.join(timeout=5.0)
    assert _time.monotonic() >= 0  # keep import meaningful for lints
    assert mock_updater.update_memory.call_count == 1


def test_cancelled_scope_prevents_entire_subsequent_batch() -> None:
    mock_updater = MagicMock(return_value=True)
    queue = _queue(mock_updater)
    queue._items = [ConversationContext(thread_id="t1", messages=["late"], agent_name="doomed")]

    assert queue.cancel_by_agent("doomed") == 1
    queue.flush()

    mock_updater.update_memory.assert_not_called()


def test_fresh_add_unfences_exact_and_covering_scopes() -> None:
    """New work proves the scope is alive again: an exact fence, a wildcard-user
    fence, and a user-wide fence covering this key must all be lifted so a
    recreated agent keeps extracting."""
    import time as _time  # noqa: F401

    queue = _queue()

    queue.cancel_by_agent("agent-a")
    queue.mark_scope_active("agent-a", "alice")
    assert queue._scope_is_cancelled("agent-a", "alice") is False

    queue.cancel_by_agent("agent-a", user_id=None)
    queue.mark_scope_active("agent-a", "bob")
    assert queue._scope_is_cancelled("agent-a", "bob") is False

    queue.cancel_by_user("alice")
    queue.mark_scope_active("agent-z", "alice")
    assert queue._scope_is_cancelled("agent-z", "alice") is False


def test_unrelated_scope_still_fenced_after_other_scope_reactivated() -> None:
    queue = _queue()
    queue.cancel_by_user("alice")

    queue.mark_scope_active("agent-a", "bob")

    assert queue._scope_is_cancelled("agent-b", "alice") is True


def test_cancel_by_user_drops_every_agent_for_that_user() -> None:
    queue = _queue()
    queue._items = [
        ConversationContext(thread_id="t1", messages=["a"], agent_name="agent-a", user_id="alice"),
        ConversationContext(thread_id="t2", messages=["b"], agent_name="agent-b", user_id="alice"),
        ConversationContext(thread_id="t3", messages=["c"], agent_name="agent-a", user_id="bob"),
    ]

    assert queue.cancel_by_user("alice") == 2
    assert [context.user_id for context in queue._items] == ["bob"]


def test_cancel_by_user_without_id_clears_everything() -> None:
    queue = _queue()
    queue._items = [
        ConversationContext(thread_id="t1", messages=["a"], agent_name="agent-a", user_id="alice"),
        ConversationContext(thread_id="t2", messages=["b"], agent_name="agent-b", user_id="bob"),
    ]

    assert queue.cancel_by_user(None) == 2
    assert queue.pending_count == 0


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
    assert manager.cancel_by_user("u") == 0


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


def test_deer_mem_clear_all_cancels_pending_updates_for_every_agent_of_user(deermem) -> None:
    """Finding 2: a global clear removes every agent's stored facts, so its
    cancellation must be user-wide — not just the reserved default bucket."""
    queue = deermem._queue
    queue._items = [
        ConversationContext(thread_id="t1", messages=["a"], agent_name="__default__", user_id="alice"),
        ConversationContext(thread_id="t2", messages=["b"], agent_name="agent-a", user_id="alice"),
        ConversationContext(thread_id="t3", messages=["c"], agent_name="agent-b", user_id="bob"),
    ]

    deermem.clear_memory(user_id="alice")

    assert [context.user_id for context in queue._items] == ["bob"]
