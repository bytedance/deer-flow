"""Tests for user_id propagation through memory queue (DI)."""

from unittest.mock import MagicMock, patch

from deerflow.agents.memory.backends.deermem.deermem.config import DeerMemConfig
from deerflow.agents.memory.backends.deermem.deermem.core.queue import ConversationContext, MemoryUpdateQueue


def _queue(updater: MagicMock | None = None) -> MemoryUpdateQueue:
    return MemoryUpdateQueue(DeerMemConfig(), updater or MagicMock())


def test_conversation_context_has_user_id():
    ctx = ConversationContext(thread_id="t1", messages=[], user_id="alice")
    assert ctx.user_id == "alice"


def test_conversation_context_user_id_default_none():
    ctx = ConversationContext(thread_id="t1", messages=[])
    assert ctx.user_id is None


def test_queue_add_stores_user_id():
    q = _queue()
    with patch.object(q, "_reset_timer"):
        q.add(thread_id="t1", messages=["msg"], user_id="alice")
    assert len(q._items) == 1
    assert q._items[0].user_id == "alice"
    q.clear()


def test_queue_process_passes_user_id_to_updater():
    mock_updater = MagicMock()
    mock_updater.update_memory.return_value = True
    q = _queue(mock_updater)
    with patch.object(q, "_reset_timer"):
        q.add(thread_id="t1", messages=["msg"], user_id="alice")

    q._process_queue()

    mock_updater.update_memory.assert_called_once()
    assert mock_updater.update_memory.call_args.kwargs["user_id"] == "alice"


def test_queue_keeps_updates_for_different_users_in_same_thread_and_agent():
    q = _queue()
    with patch.object(q, "_reset_timer"):
        q.add(thread_id="main", messages=["alice update"], agent_name="researcher", user_id="alice")
        q.add(thread_id="main", messages=["bob update"], agent_name="researcher", user_id="bob")

    assert q.pending_count == 2
    assert [context.user_id for context in q._items] == ["alice", "bob"]
    assert [context.messages for context in q._items] == [["alice update"], ["bob update"]]


def test_queue_still_coalesces_updates_for_same_user_thread_and_agent():
    q = _queue()
    with patch.object(q, "_reset_timer"):
        q.add(thread_id="main", messages=["first"], agent_name="researcher", user_id="alice")
        q.add(thread_id="main", messages=["second"], agent_name="researcher", user_id="alice")

    assert q.pending_count == 1
    assert q._items[0].messages == ["second"]
    assert q._items[0].user_id == "alice"
    assert q._items[0].agent_name == "researcher"


def test_add_nowait_keeps_different_users_separate():
    q = _queue()
    with patch.object(q, "_schedule_timer"):
        q.add_nowait(thread_id="main", messages=["alice update"], agent_name="researcher", user_id="alice")
        q.add_nowait(thread_id="main", messages=["bob update"], agent_name="researcher", user_id="bob")

    assert q.pending_count == 2
    assert [context.user_id for context in q._items] == ["alice", "bob"]


def test_deermem_manager_discard_pending_updates_forwards_to_queue(tmp_path):
    """Issue #3364: DeerMem.discard_pending_updates forwards to the queue.

    The manager-owned debounce queue must drop pending updates for a deleted
    agent (and its stored tombstone) so a lagging write cannot recreate the
    agent directory.
    """
    from deerflow.agents.memory.backends.deermem.deer_mem import DeerMem

    manager = DeerMem(backend_config={"storage_path": str(tmp_path)})
    queue = manager._queue
    with patch.object(queue, "_reset_timer"):
        queue.add(thread_id="t1", messages=["m"], agent_name="agent-a", user_id="alice")
        queue.add(thread_id="t2", messages=["m"], agent_name="agent-b", user_id="alice")

    assert queue.pending_count == 2

    removed = manager.discard_pending_updates(user_id="alice", agent_name="agent-a")

    assert removed == 1
    assert queue.pending_count == 1
    assert [c.agent_name for c in queue._items] == ["agent-b"]
    assert not any(c.agent_name == "agent-a" for c in queue._items)


def test_deermem_manager_clear_agent_deleted_forwards_to_storage(tmp_path) -> None:
    """Issue #3364 review: DeerMem.clear_agent_deleted removes the tombstone
    marker that mark_agent_deleted wrote, so a re-created same-named agent's
    memory writes are not skipped forever."""
    from deerflow.agents.memory.backends.deermem.deer_mem import DeerMem

    manager = DeerMem(backend_config={"storage_path": str(tmp_path)})
    storage = manager._storage

    storage.mark_agent_deleted(user_id="alice", agent_name="agent-a")
    marker = tmp_path / "users" / "alice" / ".deleted-agents" / "agent-a.marker"
    assert marker.exists()

    # A save is skipped while the marker is present...
    memory = {
        "version": "1.0",
        "revision": 0,
        "lastUpdated": "",
        "user": {},
        "history": {},
        "facts": [{"id": "f1", "content": "x"}],
    }
    assert storage.save(memory, "agent-a", user_id="alice") is False

    # ...but once the creation path clears it, the recreated agent writes again.
    manager.clear_agent_deleted(user_id="alice", agent_name="agent-a")
    assert not marker.exists()
    assert storage.save(memory, "agent-a", user_id="alice") is True
