import threading
import time
from unittest.mock import MagicMock, patch

from deerflow.agents.memory.queue import ConversationContext, MemoryUpdateQueue
from deerflow.config.memory_config import MemoryConfig


def _memory_config(**overrides: object) -> MemoryConfig:
    config = MemoryConfig()
    for key, value in overrides.items():
        setattr(config, key, value)
    return config


def test_queue_add_preserves_existing_correction_flag_for_same_thread() -> None:
    queue = MemoryUpdateQueue()

    with (
        patch("deerflow.agents.memory.queue.get_memory_config", return_value=_memory_config(enabled=True)),
        patch.object(queue, "_reset_timer"),
    ):
        queue.add(thread_id="thread-1", messages=["first"], correction_detected=True)
        queue.add(thread_id="thread-1", messages=["second"], correction_detected=False)

    assert len(queue._queue) == 1
    assert queue._queue[0].messages == ["second"]
    assert queue._queue[0].correction_detected is True


def test_process_queue_forwards_correction_flag_to_updater() -> None:
    queue = MemoryUpdateQueue()
    queue._queue = [
        ConversationContext(
            thread_id="thread-1",
            messages=["conversation"],
            agent_name="lead_agent",
            correction_detected=True,
        )
    ]
    mock_updater = MagicMock()
    mock_updater.update_memory.return_value = True

    with patch("deerflow.agents.memory.updater.MemoryUpdater", return_value=mock_updater):
        queue._process_queue()

    mock_updater.update_memory.assert_called_once_with(
        messages=["conversation"],
        thread_id="thread-1",
        agent_name="lead_agent",
        correction_detected=True,
        reinforcement_detected=False,
    )


def test_queue_add_preserves_existing_reinforcement_flag_for_same_thread() -> None:
    queue = MemoryUpdateQueue()

    with (
        patch("deerflow.agents.memory.queue.get_memory_config", return_value=_memory_config(enabled=True)),
        patch.object(queue, "_reset_timer"),
    ):
        queue.add(thread_id="thread-1", messages=["first"], reinforcement_detected=True)
        queue.add(thread_id="thread-1", messages=["second"], reinforcement_detected=False)

    assert len(queue._queue) == 1
    assert queue._queue[0].messages == ["second"]
    assert queue._queue[0].reinforcement_detected is True


def test_process_queue_forwards_reinforcement_flag_to_updater() -> None:
    queue = MemoryUpdateQueue()
    queue._queue = [
        ConversationContext(
            thread_id="thread-1",
            messages=["conversation"],
            agent_name="lead_agent",
            reinforcement_detected=True,
        )
    ]
    mock_updater = MagicMock()
    mock_updater.update_memory.return_value = True

    with patch("deerflow.agents.memory.updater.MemoryUpdater", return_value=mock_updater):
        queue._process_queue()

    mock_updater.update_memory.assert_called_once_with(
        messages=["conversation"],
        thread_id="thread-1",
        agent_name="lead_agent",
        correction_detected=False,
        reinforcement_detected=True,
    )


def test_flush_nowait_cancels_existing_timer_and_starts_immediate_timer() -> None:
    queue = MemoryUpdateQueue()
    existing_timer = MagicMock()
    queue._timer = existing_timer
    created_timer = MagicMock()

    with patch("deerflow.agents.memory.queue.threading.Timer", return_value=created_timer) as timer_cls:
        queue.flush_nowait()

    existing_timer.cancel.assert_called_once_with()
    timer_cls.assert_called_once_with(0, queue._process_queue)
    assert created_timer.daemon is True
    created_timer.start.assert_called_once_with()
    assert queue._timer is created_timer


def test_add_nowait_cancels_existing_timer_and_starts_immediate_timer() -> None:
    queue = MemoryUpdateQueue()
    existing_timer = MagicMock()
    queue._timer = existing_timer
    created_timer = MagicMock()

    with (
        patch("deerflow.agents.memory.queue.get_memory_config", return_value=_memory_config(enabled=True)),
        patch("deerflow.agents.memory.queue.threading.Timer", return_value=created_timer) as timer_cls,
    ):
        queue.add_nowait(thread_id="thread-1", messages=["conversation"], agent_name="lead-agent")

    existing_timer.cancel.assert_called_once_with()
    timer_cls.assert_called_once_with(0, queue._process_queue)
    assert queue.pending_count == 1
    assert queue._queue[0].agent_name == "lead-agent"
    assert created_timer.daemon is True
    created_timer.start.assert_called_once_with()


def test_process_queue_reschedules_immediately_when_already_processing() -> None:
    queue = MemoryUpdateQueue()
    queue._processing = True
    created_timer = MagicMock()

    with patch("deerflow.agents.memory.queue.threading.Timer", return_value=created_timer) as timer_cls:
        queue._process_queue()

    timer_cls.assert_called_once_with(0, queue._process_queue)
    assert created_timer.daemon is True
    created_timer.start.assert_called_once_with()


def test_flush_nowait_is_non_blocking() -> None:
    queue = MemoryUpdateQueue()
    started = threading.Event()
    finished = threading.Event()

    def _slow_process_queue() -> None:
        started.set()
        time.sleep(0.2)
        finished.set()

    queue._process_queue = _slow_process_queue

    start = time.perf_counter()
    queue.flush_nowait()
    elapsed = time.perf_counter() - start

    assert started.wait(0.1) is True
    assert elapsed < 0.1
    assert finished.is_set() is False
    assert finished.wait(1.0) is True
