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
    )
