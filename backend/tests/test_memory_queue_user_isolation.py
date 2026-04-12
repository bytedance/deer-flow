"""Tests for user_id propagation through memory queue."""
from unittest.mock import MagicMock, patch

from deerflow.agents.memory.queue import ConversationContext, MemoryUpdateQueue


def test_conversation_context_has_user_id():
    ctx = ConversationContext(thread_id="t1", messages=[], user_id="alice")
    assert ctx.user_id == "alice"


def test_conversation_context_user_id_default_none():
    ctx = ConversationContext(thread_id="t1", messages=[])
    assert ctx.user_id is None


def test_queue_add_stores_user_id():
    q = MemoryUpdateQueue()
    with patch.object(q, "_reset_timer"):
        q.add(thread_id="t1", messages=["msg"], user_id="alice")
    assert len(q._queue) == 1
    assert q._queue[0].user_id == "alice"
    q.clear()


def test_queue_process_passes_user_id_to_updater():
    q = MemoryUpdateQueue()
    with patch.object(q, "_reset_timer"):
        q.add(thread_id="t1", messages=["msg"], user_id="alice")

    mock_updater = MagicMock()
    mock_updater.update_memory.return_value = True
    with patch("deerflow.agents.memory.updater.MemoryUpdater", return_value=mock_updater):
        q._process_queue()

    mock_updater.update_memory.assert_called_once()
    call_kwargs = mock_updater.update_memory.call_args.kwargs
    assert call_kwargs["user_id"] == "alice"
