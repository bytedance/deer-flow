"""Unit tests for session memory update queue."""

import threading
import time
from unittest.mock import MagicMock, patch

from deerflow.agents.memory.session_queue import (
    SessionConversationContext,
    SessionMemoryUpdateQueue,
    get_session_memory_queue,
    reset_session_memory_queue,
)
from deerflow.config.session_memory_config import SessionMemoryConfig


def _session_config(**overrides: object) -> SessionMemoryConfig:
    return SessionMemoryConfig(**overrides)


def test_add_when_disabled_does_nothing() -> None:
    """add() returns early when session memory is disabled."""
    queue = SessionMemoryUpdateQueue()

    with (
        patch("deerflow.agents.memory.session_queue.get_session_memory_config", return_value=_session_config(enabled=False)),
        patch.object(queue, "_reset_timer") as mock_timer,
    ):
        queue.add(thread_id="thread-1", messages=["hello"])

    mock_timer.assert_not_called()
    assert queue.pending_count == 0


def test_add_enqueues_and_resets_timer() -> None:
    """add() enqueues context and resets debounce timer."""
    queue = SessionMemoryUpdateQueue()

    with (
        patch("deerflow.agents.memory.session_queue.get_session_memory_config", return_value=_session_config(enabled=True, debounce_seconds=10)),
        patch.object(queue, "_reset_timer") as mock_timer,
    ):
        queue.add(thread_id="thread-1", messages=["hello"], user_id="user-1")

    assert queue.pending_count == 1
    assert queue._queue[0].thread_id == "thread-1"
    assert queue._queue[0].user_id == "user-1"
    mock_timer.assert_called_once()


def test_add_merges_correction_flag_for_same_thread() -> None:
    """add() preserves existing correction flag when re-queuing same thread."""
    queue = SessionMemoryUpdateQueue()

    with (
        patch("deerflow.agents.memory.session_queue.get_session_memory_config", return_value=_session_config(enabled=True)),
        patch.object(queue, "_reset_timer"),
    ):
        queue.add(thread_id="thread-1", messages=["first"], correction_detected=True)
        queue.add(thread_id="thread-1", messages=["second"], correction_detected=False)

    assert queue.pending_count == 1
    assert queue._queue[0].messages == ["second"]
    assert queue._queue[0].correction_detected is True


def test_add_merges_reinforcement_flag_for_same_thread() -> None:
    """add() preserves existing reinforcement flag when re-queuing same thread."""
    queue = SessionMemoryUpdateQueue()

    with (
        patch("deerflow.agents.memory.session_queue.get_session_memory_config", return_value=_session_config(enabled=True)),
        patch.object(queue, "_reset_timer"),
    ):
        queue.add(thread_id="thread-1", messages=["first"], reinforcement_detected=True)
        queue.add(thread_id="thread-1", messages=["second"], reinforcement_detected=False)

    assert queue.pending_count == 1
    assert queue._queue[0].reinforcement_detected is True


def test_add_separate_threads_creates_separate_entries() -> None:
    """add() creates separate queue entries for different threads."""
    queue = SessionMemoryUpdateQueue()

    with (
        patch("deerflow.agents.memory.session_queue.get_session_memory_config", return_value=_session_config(enabled=True)),
        patch.object(queue, "_reset_timer"),
    ):
        queue.add(thread_id="thread-1", messages=["msg1"])
        queue.add(thread_id="thread-2", messages=["msg2"])

    assert queue.pending_count == 2


def test_process_queue_calls_update_session_from_conversation() -> None:
    """_process_queue() calls update_session_from_conversation with correct args."""
    queue = SessionMemoryUpdateQueue()
    queue._queue = [
        SessionConversationContext(
            thread_id="thread-1",
            messages=["conversation"],
            user_id="user-xyz",
            correction_detected=True,
        )
    ]
    mock_update = MagicMock(return_value=True)

    with patch("deerflow.agents.memory.updater.update_session_from_conversation", mock_update):
        queue._process_queue()

    mock_update.assert_called_once_with(
        messages=["conversation"],
        thread_id="thread-1",
        correction_detected=True,
        reinforcement_detected=False,
        user_id="user-xyz",
    )


def test_process_queue_handles_exception_gracefully() -> None:
    """_process_queue() logs error and continues on exception."""
    queue = SessionMemoryUpdateQueue()
    queue._queue = [
        SessionConversationContext(thread_id="thread-1", messages=["msg1"]),
        SessionConversationContext(thread_id="thread-2", messages=["msg2"]),
    ]
    mock_update = MagicMock(side_effect=[RuntimeError("boom"), True])

    with patch("deerflow.agents.memory.updater.update_session_from_conversation", mock_update):
        queue._process_queue()

    assert mock_update.call_count == 2
    assert not queue.is_processing


def test_process_queue_reschedules_when_already_processing() -> None:
    """_process_queue() reschedules immediately if another worker is active."""
    queue = SessionMemoryUpdateQueue()
    queue._processing = True
    created_timer = MagicMock()

    with patch("deerflow.agents.memory.session_queue.threading.Timer", return_value=created_timer) as timer_cls:
        queue._process_queue()

    timer_cls.assert_called_once_with(0, queue._process_queue)
    assert created_timer.daemon is True
    created_timer.start.assert_called_once()


def test_process_queue_clears_queue_before_processing() -> None:
    """_process_queue() clears the queue before processing to allow new items."""
    queue = SessionMemoryUpdateQueue()
    queue._queue = [
        SessionConversationContext(thread_id="thread-1", messages=["msg1"]),
    ]
    mock_update = MagicMock(return_value=True)

    with patch("deerflow.agents.memory.updater.update_session_from_conversation", mock_update):
        queue._process_queue()

    assert queue.pending_count == 0
    assert not queue.is_processing


def test_flush_cancels_timer_and_processes() -> None:
    """flush() cancels pending timer and processes queue immediately."""
    queue = SessionMemoryUpdateQueue()
    mock_timer = MagicMock()
    queue._timer = mock_timer
    queue._queue = [
        SessionConversationContext(thread_id="thread-1", messages=["msg1"]),
    ]
    mock_update = MagicMock(return_value=True)

    with patch("deerflow.agents.memory.updater.update_session_from_conversation", mock_update):
        queue.flush()

    mock_timer.cancel.assert_called_once()
    assert queue._timer is None
    mock_update.assert_called_once()


def test_clear_empties_queue_without_processing() -> None:
    """clear() removes all items without processing."""
    queue = SessionMemoryUpdateQueue()
    queue._queue = [
        SessionConversationContext(thread_id="thread-1", messages=["msg1"]),
        SessionConversationContext(thread_id="thread-2", messages=["msg2"]),
    ]
    mock_timer = MagicMock()
    queue._timer = mock_timer

    queue.clear()

    assert queue.pending_count == 0
    mock_timer.cancel.assert_called_once()
    assert queue._timer is None
    assert not queue.is_processing


def test_singleton_get_session_memory_queue() -> None:
    """get_session_memory_queue() returns same instance on repeated calls."""
    reset_session_memory_queue()
    try:
        q1 = get_session_memory_queue()
        q2 = get_session_memory_queue()
        assert q1 is q2
    finally:
        reset_session_memory_queue()


def test_reset_session_memory_queue_clears_singleton() -> None:
    """reset_session_memory_queue() creates fresh instance on next get."""
    q1 = get_session_memory_queue()
    reset_session_memory_queue()
    q2 = get_session_memory_queue()
    assert q1 is not q2


def test_pending_count_reflects_queue_size() -> None:
    """pending_count returns correct queue size."""
    queue = SessionMemoryUpdateQueue()
    assert queue.pending_count == 0

    queue._queue = [
        SessionConversationContext(thread_id="t1", messages=[]),
        SessionConversationContext(thread_id="t2", messages=[]),
    ]
    assert queue.pending_count == 2


def test_is_processing_reflects_state() -> None:
    """is_processing reflects current processing state."""
    queue = SessionMemoryUpdateQueue()
    assert not queue.is_processing

    queue._processing = True
    assert queue.is_processing
