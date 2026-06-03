import threading
import time
from unittest.mock import MagicMock, call, patch

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
        user_id=None,
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
        user_id=None,
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


def test_queue_keeps_updates_for_different_agents_in_same_thread() -> None:
    queue = MemoryUpdateQueue()

    with (
        patch("deerflow.agents.memory.queue.get_memory_config", return_value=_memory_config(enabled=True)),
        patch.object(queue, "_reset_timer"),
    ):
        queue.add(thread_id="thread-1", messages=["agent-a"], agent_name="agent-a")
        queue.add(thread_id="thread-1", messages=["agent-b"], agent_name="agent-b")

    assert queue.pending_count == 2
    assert [context.agent_name for context in queue._queue] == ["agent-a", "agent-b"]


def test_queue_still_coalesces_updates_for_same_agent_in_same_thread() -> None:
    queue = MemoryUpdateQueue()

    with (
        patch("deerflow.agents.memory.queue.get_memory_config", return_value=_memory_config(enabled=True)),
        patch.object(queue, "_reset_timer"),
    ):
        queue.add(
            thread_id="thread-1",
            messages=["first"],
            agent_name="agent-a",
            correction_detected=True,
        )
        queue.add(
            thread_id="thread-1",
            messages=["second"],
            agent_name="agent-a",
            correction_detected=False,
        )

    assert queue.pending_count == 1
    assert queue._queue[0].agent_name == "agent-a"
    assert queue._queue[0].messages == ["second"]
    assert queue._queue[0].correction_detected is True


def test_process_queue_updates_different_agents_in_same_thread_separately() -> None:
    queue = MemoryUpdateQueue()

    with (
        patch("deerflow.agents.memory.queue.get_memory_config", return_value=_memory_config(enabled=True)),
        patch.object(queue, "_reset_timer"),
    ):
        queue.add(thread_id="thread-1", messages=["agent-a"], agent_name="agent-a")
        queue.add(thread_id="thread-1", messages=["agent-b"], agent_name="agent-b")

    mock_updater = MagicMock()
    mock_updater.update_memory.return_value = True

    with (
        patch("deerflow.agents.memory.updater.MemoryUpdater", return_value=mock_updater),
        patch("deerflow.agents.memory.queue.time.sleep"),
    ):
        queue.flush()

    assert mock_updater.update_memory.call_count == 2
    mock_updater.update_memory.assert_has_calls(
        [
            call(
                messages=["agent-a"],
                thread_id="thread-1",
                agent_name="agent-a",
                correction_detected=False,
                reinforcement_detected=False,
                user_id=None,
            ),
            call(
                messages=["agent-b"],
                thread_id="thread-1",
                agent_name="agent-b",
                correction_detected=False,
                reinforcement_detected=False,
                user_id=None,
            ),
        ]
    )


def test_discard_removes_pending_updates_for_agent() -> None:
    queue = MemoryUpdateQueue()

    with (
        patch("deerflow.agents.memory.queue.get_memory_config", return_value=_memory_config(enabled=True)),
        patch.object(queue, "_reset_timer"),
    ):
        queue.add(thread_id="t1", messages=["agent-a"], agent_name="agent-a", user_id="alice")
        queue.add(thread_id="t2", messages=["agent-a-2"], agent_name="agent-a", user_id="alice")
        queue.add(thread_id="t3", messages=["agent-b"], agent_name="agent-b", user_id="alice")

    removed = queue.discard(user_id="alice", agent_name="agent-a")

    assert removed == 2
    assert [context.agent_name for context in queue._queue] == ["agent-b"]


def test_discard_is_scoped_by_user_id() -> None:
    queue = MemoryUpdateQueue()

    with (
        patch("deerflow.agents.memory.queue.get_memory_config", return_value=_memory_config(enabled=True)),
        patch.object(queue, "_reset_timer"),
    ):
        queue.add(thread_id="t1", messages=["alice"], agent_name="shared", user_id="alice")
        queue.add(thread_id="t1", messages=["bob"], agent_name="shared", user_id="bob")

    removed = queue.discard(user_id="alice", agent_name="shared")

    assert removed == 1
    assert [(context.user_id, context.agent_name) for context in queue._queue] == [("bob", "shared")]


def test_discard_skips_inflight_update_already_dequeued() -> None:
    """The core issue #3364 race: a worker copies the queue out, then the agent
    is deleted (discard) before update_memory runs. _process_queue must skip the
    write so it cannot recreate the deleted agent's directory.
    """
    queue = MemoryUpdateQueue()
    queue._queue = [
        ConversationContext(
            thread_id="t1",
            messages=["conversation"],
            agent_name="agent-a",
            user_id="alice",
        )
    ]

    mock_updater = MagicMock()
    mock_updater.update_memory.return_value = True

    # By the time _process_queue builds the updater it has already
    # snapshotted+cleared the queue and set _processing=True. Deleting the
    # agent here mirrors discard() racing with that in-flight run.
    def delete_agent_mid_flight(*args, **kwargs):
        queue.discard(user_id="alice", agent_name="agent-a")
        return mock_updater

    with (
        patch("deerflow.agents.memory.updater.MemoryUpdater", side_effect=delete_agent_mid_flight),
        patch("deerflow.agents.memory.queue.time.sleep"),
    ):
        queue._process_queue()

    mock_updater.update_memory.assert_not_called()
    # Tombstones are cleared once the run finishes, so the set never leaks.
    assert queue._deleted_agents == set()


def test_discard_without_inflight_run_records_no_tombstone() -> None:
    queue = MemoryUpdateQueue()

    with (
        patch("deerflow.agents.memory.queue.get_memory_config", return_value=_memory_config(enabled=True)),
        patch.object(queue, "_reset_timer"),
    ):
        queue.add(thread_id="t1", messages=["first"], agent_name="agent-a", user_id="alice")

    removed = queue.discard(user_id="alice", agent_name="agent-a")

    assert removed == 1
    assert queue._deleted_agents == set()


def test_recreated_agent_after_discard_writes_memory() -> None:
    queue = MemoryUpdateQueue()

    with (
        patch("deerflow.agents.memory.queue.get_memory_config", return_value=_memory_config(enabled=True)),
        patch.object(queue, "_reset_timer"),
    ):
        queue.add(thread_id="t1", messages=["first"], agent_name="agent-a", user_id="alice")
        queue.discard(user_id="alice", agent_name="agent-a")
        # A same-named agent recreated and used again must not be suppressed.
        queue.add(thread_id="t1", messages=["second"], agent_name="agent-a", user_id="alice")

    mock_updater = MagicMock()
    mock_updater.update_memory.return_value = True

    with (
        patch("deerflow.agents.memory.updater.MemoryUpdater", return_value=mock_updater),
        patch("deerflow.agents.memory.queue.time.sleep"),
    ):
        queue.flush()

    mock_updater.update_memory.assert_called_once_with(
        messages=["second"],
        thread_id="t1",
        agent_name="agent-a",
        correction_detected=False,
        reinforcement_detected=False,
        user_id="alice",
    )
