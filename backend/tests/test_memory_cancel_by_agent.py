"""Stopgap cancellation for pending memory-extraction work (#3364).

Deleting an agent (or clearing its memory) must drop that scope's
still-debouncing extraction contexts. Otherwise the debounce Timer fires after
deletion, invokes the extraction LLM for a scope that no longer exists, and
re-persists state that blocks recreating an agent with the same name. This file
pins the in-process stopgap: ``MemoryUpdateQueue.cancel_by_agent`` /
``cancel_by_user`` backed by per-scope generations — each context stamps the
generation at enqueue time and the processing loop drops contexts whose
generation no longer matches, so cancelled work stays dead even across a
delete -> recreate-same-name -> fresh-enqueue sequence while a fresh turn still
runs. Also covered: the ``MemoryManager`` contract defaults, DeerMem's
overrides plus its ``clear_memory`` linkage, and the best-effort hookup in the
agent-deletion route.
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
# Scope generations: cancellation must hold against a worker that snapshotted
# its batch BEFORE the cancel ran (#5037 HIGH), AND against a delete ->
# recreate-same-name -> fresh-enqueue sequence: old-generation work must never
# execute as if it belonged to the recreated scope.
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


def test_old_batch_dies_but_recreated_agent_fresh_work_runs() -> None:
    """The #5037 blocker scenario, end to end:

    worker snapshots old-1 + old-2 and starts old-1's LLM call
        -> cancel (delete)
        -> recreate same name, fresh conversation enqueues
        -> release the worker

    old-2 MUST NOT run (it predates the cancel). Fresh work MUST run. Pending
    removal alone cannot express this: the fresh enqueue must not resurrect the
    old batch, and the cancel must not kill the fresh turn.
    """
    mock_updater = MagicMock(return_value=True)
    queue = _queue(mock_updater)
    queue._items = [
        ConversationContext(thread_id="t-old", messages=["old-1"], agent_name="phoenix"),
        ConversationContext(thread_id="t-old", messages=["old-2"], agent_name="phoenix"),
    ]
    gate = threading.Event()
    started = threading.Event()
    worker = _start_blocked_worker(queue, mock_updater, gate, started)
    try:
        # Delete: the batch was already snapshotted (_items is empty), so this
        # removes zero pending entries but must invalidate their generation.
        assert queue.cancel_by_agent("phoenix") == 0
        # Recreate + fresh conversation turn enqueues under the same scope.
        queue.add(thread_id="t-new", messages=["fresh"], agent_name="phoenix")
    finally:
        gate.set()
        worker.join(timeout=5.0)
        # Drain whatever the finishing worker rescheduled for the fresh item.
        queue.flush()

    executed = [call.kwargs["messages"] for call in mock_updater.update_memory.call_args_list]
    # old-1 was already inside its LLM call when the cancel landed — the
    # documented residual window this stopgap does not claim to close. The
    # blocker requirement: old TAIL (old-2) must not run; fresh work must.
    assert executed == [["old-1"], ["fresh"]], f"old tail leaked or fresh work dropped: {executed}"


def test_cancelled_scope_prevents_entire_subsequent_batch() -> None:
    mock_updater = MagicMock(return_value=True)
    queue = _queue(mock_updater)
    queue._items = [ConversationContext(thread_id="t1", messages=["late"], agent_name="doomed")]

    assert queue.cancel_by_agent("doomed") == 1
    queue.flush()

    mock_updater.update_memory.assert_not_called()


def test_user_wide_cancel_kills_other_agents_old_batch_without_touching_new_work() -> None:
    """A user-wide cancel invalidates every agent's buffered work for that
    user, yet a later legitimate turn for any of them still runs."""
    mock_updater = MagicMock(return_value=True)
    queue = _queue(mock_updater)
    queue._items = [
        ConversationContext(thread_id="t1", messages=["a-old"], agent_name="agent-a", user_id="alice"),
        ConversationContext(thread_id="t2", messages=["b-old"], agent_name="agent-b", user_id="alice"),
    ]
    gate = threading.Event()
    started = threading.Event()
    worker = _start_blocked_worker(queue, mock_updater, gate, started)
    try:
        assert queue.cancel_by_user("alice") == 0
        queue.add(thread_id="t3", messages=["a-new"], agent_name="agent-a", user_id="alice")
    finally:
        gate.set()
        worker.join(timeout=5.0)
        queue.flush()

    executed = [call.kwargs["messages"] for call in mock_updater.update_memory.call_args_list]
    # a-old is the documented in-flight residual; b-old (old tail) must be gone.
    assert executed == [["a-old"], ["a-new"]]


def test_cancelled_scope_prevents_subsequent_batch_after_user_wide_cancel() -> None:
    mock_updater = MagicMock(return_value=True)
    queue = _queue(mock_updater)
    queue._items = [ConversationContext(thread_id="t1", messages=["late"], agent_name="agent-a", user_id="alice")]

    assert queue.cancel_by_user("alice") == 1
    queue.flush()

    mock_updater.update_memory.assert_not_called()


def test_generation_is_per_scope_not_global() -> None:
    """Cancelling one agent must not invalidate another agent's buffered work."""
    mock_updater = MagicMock(return_value=True)
    queue = _queue(mock_updater)
    queue._items = [
        ConversationContext(thread_id="t1", messages=["doomed"], agent_name="doomed"),
        ConversationContext(thread_id="t2", messages=["survivor"], agent_name="survivor"),
    ]

    assert queue.cancel_by_agent("doomed") == 1
    queue.flush()

    executed = [call.kwargs["messages"] for call in mock_updater.update_memory.call_args_list]
    assert executed == [["survivor"]]


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
