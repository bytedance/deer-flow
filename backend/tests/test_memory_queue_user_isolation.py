"""Tests for user_id propagation through memory queue."""

from unittest.mock import MagicMock, patch

from deerflow.agents.memory.queue import ConversationContext, MemoryUpdateQueue
from deerflow.config.memory_config import MemoryConfig


def test_conversation_context_has_user_id():
    ctx = ConversationContext(thread_id="t1", messages=[], user_id="alice")
    assert ctx.user_id == "alice"


def test_conversation_context_user_id_default_none():
    ctx = ConversationContext(thread_id="t1", messages=[])
    assert ctx.user_id is None


def test_queue_add_stores_user_id():
    q = MemoryUpdateQueue()
    with patch("deerflow.agents.memory.queue.get_memory_config", return_value=MemoryConfig(enabled=True)), patch.object(q, "_reset_timer"):
        q.add(thread_id="t1", messages=["msg"], user_id="alice")
    assert len(q._queue) == 1
    assert q._queue[0].user_id == "alice"
    q.clear()


def test_queue_process_passes_user_id_to_updater():
    q = MemoryUpdateQueue()
    with patch("deerflow.agents.memory.queue.get_memory_config", return_value=MemoryConfig(enabled=True)), patch.object(q, "_reset_timer"):
        q.add(thread_id="t1", messages=["msg"], user_id="alice")

    mock_updater = MagicMock()
    mock_updater.update_memory.return_value = True
    with patch("deerflow.agents.memory.updater.MemoryUpdater", return_value=mock_updater):
        q._process_queue()

    mock_updater.update_memory.assert_called_once()
    call_kwargs = mock_updater.update_memory.call_args.kwargs
    assert call_kwargs["user_id"] == "alice"


def test_queue_keeps_updates_for_different_users_in_same_thread_and_agent():
    q = MemoryUpdateQueue()

    with patch("deerflow.agents.memory.queue.get_memory_config", return_value=MemoryConfig(enabled=True)), patch.object(q, "_reset_timer"):
        q.add(thread_id="main", messages=["alice update"], agent_name="researcher", user_id="alice")
        q.add(thread_id="main", messages=["bob update"], agent_name="researcher", user_id="bob")

    assert q.pending_count == 2
    assert [context.user_id for context in q._queue] == ["alice", "bob"]
    assert [context.messages for context in q._queue] == [["alice update"], ["bob update"]]


def test_queue_still_coalesces_updates_for_same_user_thread_and_agent():
    q = MemoryUpdateQueue()

    with patch("deerflow.agents.memory.queue.get_memory_config", return_value=MemoryConfig(enabled=True)), patch.object(q, "_reset_timer"):
        q.add(thread_id="main", messages=["first"], agent_name="researcher", user_id="alice")
        q.add(thread_id="main", messages=["second"], agent_name="researcher", user_id="alice")

    assert q.pending_count == 1
    assert q._queue[0].messages == ["second"]
    assert q._queue[0].user_id == "alice"
    assert q._queue[0].agent_name == "researcher"


def test_add_nowait_keeps_different_users_separate():
    q = MemoryUpdateQueue()

    with (
        patch("deerflow.agents.memory.queue.get_memory_config", return_value=MemoryConfig(enabled=True)),
        patch.object(q, "_schedule_timer"),
    ):
        q.add_nowait(thread_id="main", messages=["alice update"], agent_name="researcher", user_id="alice")
        q.add_nowait(thread_id="main", messages=["bob update"], agent_name="researcher", user_id="bob")

    assert q.pending_count == 2
    assert [context.user_id for context in q._queue] == ["alice", "bob"]
