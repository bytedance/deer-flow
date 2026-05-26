"""Unit tests for domain memory update queue."""

import threading
import time
from unittest.mock import MagicMock, patch

from deerflow.agents.memory.domain_queue import (
    DomainConversationContext,
    DomainMemoryUpdateQueue,
    get_domain_memory_queue,
    reset_domain_memory_queue,
)
from deerflow.config.domain_memory_config import DomainMemoryConfig


def _domain_config(**overrides: object) -> DomainMemoryConfig:
    return DomainMemoryConfig(**overrides)


def test_add_when_disabled_does_nothing() -> None:
    """add() returns early when domain memory is disabled."""
    queue = DomainMemoryUpdateQueue()

    with (
        patch("deerflow.agents.memory.domain_queue.get_domain_memory_config", return_value=_domain_config(enabled=False)),
        patch.object(queue, "_reset_timer") as mock_timer,
    ):
        queue.add(thread_id="thread-1", messages=["hello"], tenant_id="tenant-1")

    mock_timer.assert_not_called()
    assert queue.pending_count == 0


def test_add_enqueues_and_resets_timer() -> None:
    """add() enqueues context and resets debounce timer."""
    queue = DomainMemoryUpdateQueue()

    with (
        patch("deerflow.agents.memory.domain_queue.get_domain_memory_config", return_value=_domain_config(enabled=True, debounce_seconds=10)),
        patch.object(queue, "_reset_timer") as mock_timer,
    ):
        queue.add(thread_id="thread-1", messages=["hello"], tenant_id="tenant-1", user_id="user-1")

    assert queue.pending_count == 1
    assert queue._queue[0].thread_id == "thread-1"
    assert queue._queue[0].tenant_id == "tenant-1"
    assert queue._queue[0].user_id == "user-1"
    mock_timer.assert_called_once()


def test_add_replaces_existing_thread_entry() -> None:
    """add() replaces existing entry for same thread_id."""
    queue = DomainMemoryUpdateQueue()

    with (
        patch("deerflow.agents.memory.domain_queue.get_domain_memory_config", return_value=_domain_config(enabled=True)),
        patch.object(queue, "_reset_timer"),
    ):
        queue.add(thread_id="thread-1", messages=["first"], tenant_id="tenant-1")
        queue.add(thread_id="thread-1", messages=["second"], tenant_id="tenant-1")

    assert queue.pending_count == 1
    assert queue._queue[0].messages == ["second"]


def test_add_separate_threads_creates_separate_entries() -> None:
    """add() creates separate queue entries for different threads."""
    queue = DomainMemoryUpdateQueue()

    with (
        patch("deerflow.agents.memory.domain_queue.get_domain_memory_config", return_value=_domain_config(enabled=True)),
        patch.object(queue, "_reset_timer"),
    ):
        queue.add(thread_id="thread-1", messages=["msg1"], tenant_id="tenant-1")
        queue.add(thread_id="thread-2", messages=["msg2"], tenant_id="tenant-1")

    assert queue.pending_count == 2


def test_process_queue_calls_extract_domain_facts() -> None:
    """_process_queue() calls extract_domain_facts with correct args."""
    queue = DomainMemoryUpdateQueue()
    queue._queue = [
        DomainConversationContext(
            thread_id="thread-1",
            messages=["conversation"],
            tenant_id="tenant-xyz",
            user_id="user-1",
        )
    ]
    mock_extract = MagicMock(return_value=[{"id": "fact-1", "content": "Test"}])

    with patch("deerflow.agents.memory.updater.extract_domain_facts", mock_extract):
        queue._process_queue()

    mock_extract.assert_called_once_with(
        messages=["conversation"],
        tenant_id="tenant-xyz",
    )


def test_process_queue_handles_exception_gracefully() -> None:
    """_process_queue() logs error and continues on exception."""
    queue = DomainMemoryUpdateQueue()
    queue._queue = [
        DomainConversationContext(thread_id="thread-1", messages=["msg1"], tenant_id="t1"),
        DomainConversationContext(thread_id="thread-2", messages=["msg2"], tenant_id="t1"),
    ]
    mock_extract = MagicMock(side_effect=[RuntimeError("boom"), [{"id": "fact-1"}]])

    with patch("deerflow.agents.memory.updater.extract_domain_facts", mock_extract):
        queue._process_queue()

    assert mock_extract.call_count == 2
    assert not queue.is_processing


def test_process_queue_reschedules_when_already_processing() -> None:
    """_process_queue() reschedules immediately if another worker is active."""
    queue = DomainMemoryUpdateQueue()
    queue._processing = True
    created_timer = MagicMock()

    with patch("deerflow.agents.memory.domain_queue.threading.Timer", return_value=created_timer) as timer_cls:
        queue._process_queue()

    timer_cls.assert_called_once_with(0, queue._process_queue)
    assert created_timer.daemon is True
    created_timer.start.assert_called_once()


def test_process_queue_clears_queue_before_processing() -> None:
    """_process_queue() clears the queue before processing to allow new items."""
    queue = DomainMemoryUpdateQueue()
    queue._queue = [
        DomainConversationContext(thread_id="thread-1", messages=["msg1"], tenant_id="t1"),
    ]
    mock_extract = MagicMock(return_value=[])

    with patch("deerflow.agents.memory.updater.extract_domain_facts", mock_extract):
        queue._process_queue()

    assert queue.pending_count == 0
    assert not queue.is_processing


def test_flush_cancels_timer_and_processes() -> None:
    """flush() cancels pending timer and processes queue immediately."""
    queue = DomainMemoryUpdateQueue()
    mock_timer = MagicMock()
    queue._timer = mock_timer
    queue._queue = [
        DomainConversationContext(thread_id="thread-1", messages=["msg1"], tenant_id="t1"),
    ]
    mock_extract = MagicMock(return_value=[])

    with patch("deerflow.agents.memory.updater.extract_domain_facts", mock_extract):
        queue.flush()

    mock_timer.cancel.assert_called_once()
    assert queue._timer is None
    mock_extract.assert_called_once()


def test_clear_empties_queue_without_processing() -> None:
    """clear() removes all items without processing."""
    queue = DomainMemoryUpdateQueue()
    queue._queue = [
        DomainConversationContext(thread_id="thread-1", messages=["msg1"], tenant_id="t1"),
        DomainConversationContext(thread_id="thread-2", messages=["msg2"], tenant_id="t1"),
    ]
    mock_timer = MagicMock()
    queue._timer = mock_timer

    queue.clear()

    assert queue.pending_count == 0
    mock_timer.cancel.assert_called_once()
    assert queue._timer is None
    assert not queue.is_processing


def test_singleton_get_domain_memory_queue() -> None:
    """get_domain_memory_queue() returns same instance on repeated calls."""
    reset_domain_memory_queue()
    try:
        q1 = get_domain_memory_queue()
        q2 = get_domain_memory_queue()
        assert q1 is q2
    finally:
        reset_domain_memory_queue()


def test_reset_domain_memory_queue_clears_singleton() -> None:
    """reset_domain_memory_queue() creates fresh instance on next get."""
    q1 = get_domain_memory_queue()
    reset_domain_memory_queue()
    q2 = get_domain_memory_queue()
    assert q1 is not q2


def test_pending_count_reflects_queue_size() -> None:
    """pending_count returns correct queue size."""
    queue = DomainMemoryUpdateQueue()
    assert queue.pending_count == 0

    queue._queue = [
        DomainConversationContext(thread_id="t1", messages=[], tenant_id="t"),
        DomainConversationContext(thread_id="t2", messages=[], tenant_id="t"),
    ]
    assert queue.pending_count == 2


def test_is_processing_reflects_state() -> None:
    """is_processing reflects current processing state."""
    queue = DomainMemoryUpdateQueue()
    assert not queue.is_processing

    queue._processing = True
    assert queue.is_processing
