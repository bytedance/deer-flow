"""Deterministic regressions for per-conversation memory scheduling."""

from unittest.mock import MagicMock, patch

import pytest

from deerflow.agents.memory.backends.deermem.deermem.config import DeerMemConfig
from deerflow.agents.memory.backends.deermem.deermem.core.queue import MemoryUpdateQueue

MODULE = "deerflow.agents.memory.backends.deermem.deermem.core.queue"


def test_other_users_cannot_postpone_or_accelerate_a_conversation() -> None:
    updater = MagicMock(update_memory=MagicMock(return_value=True))
    queue = MemoryUpdateQueue(DeerMemConfig(debounce_seconds=30), updater)
    with patch(MODULE + ".time.monotonic") as clock, patch(MODULE + ".threading.Timer") as timer:
        clock.return_value = 100
        queue.add("shared", ["quiet"], user_id="a")
        first_timer = queue._timer
        for now in (110, 120, 129):
            clock.return_value = now
            queue.add("shared", ["chatty"], user_id="b")
        # An unrelated arrival must leave the earliest wakeup intact.
        assert queue._timer is first_timer
        assert timer.call_count == 1
        clock.return_value = 130
        queue._process_queue()
        assert [c.kwargs["user_id"] for c in updater.update_memory.call_args_list] == ["a"]
        assert queue.pending_count == 1
        assert timer.call_args.args[0] == 29


def test_continuous_same_key_refreshes_reach_max_wait() -> None:
    updater = MagicMock(update_memory=MagicMock(return_value=True))
    queue = MemoryUpdateQueue(DeerMemConfig(debounce_seconds=30, max_wait_seconds=60), updater)
    with patch(MODULE + ".time.monotonic") as clock, patch(MODULE + ".threading.Timer"):
        clock.return_value = 100
        queue.add("t", ["first"], user_id="a")
        for now in (120, 140, 159):
            clock.return_value = now
            queue.add("t", [str(now)], user_id="a")
        assert queue._items[0].first_at == 100
        assert queue._items[0].due_at == 160
        clock.return_value = 160
        queue._process_queue()
    updater.update_memory.assert_called_once()
    assert updater.update_memory.call_args.kwargs["messages"] == ["159"]
    assert queue.pending_count == 0


@pytest.mark.parametrize("method", ["flush", "flush_sync", "flush_nowait"])
def test_explicit_flush_drains_unripe_items(method: str) -> None:
    updater = MagicMock(update_memory=MagicMock(return_value=True))
    queue = MemoryUpdateQueue(DeerMemConfig(), updater)
    with patch(MODULE + ".threading.Timer"), patch(MODULE + ".time.sleep"):
        queue.add("t", ["not due"])
        if method == "flush_sync":
            assert queue.flush_sync(2)
        elif method == "flush_nowait":
            queue.flush_nowait()
            queue._process_queue()
        else:
            queue.flush()
    updater.update_memory.assert_called_once()
    assert queue.pending_count == 0


def test_early_wakeup_rearms_with_minimum_delay() -> None:
    updater = MagicMock()
    queue = MemoryUpdateQueue(DeerMemConfig(debounce_seconds=30), updater)
    with patch(MODULE + ".time.monotonic") as clock, patch(MODULE + ".threading.Timer") as timer:
        clock.return_value = 100
        queue.add("t", [])
        clock.return_value = 129.999
        queue._process_queue()
        assert timer.call_args.args[0] == pytest.approx(0.05)
        assert queue.pending_count == 1
        updater.update_memory.assert_not_called()
        rearmed = queue._timer
        timer.reset_mock()
        queue.add("other", [])
        assert queue._timer is rearmed
        timer.assert_not_called()


def test_arrival_during_extraction_keeps_its_deadline() -> None:
    updater = MagicMock()
    queue = MemoryUpdateQueue(DeerMemConfig(debounce_seconds=30), updater)
    with patch(MODULE + ".time.monotonic") as clock, patch(MODULE + ".threading.Timer") as timer:
        clock.return_value = 100
        queue.add("first", [])
        clock.return_value = 130

        def arrive(**_kwargs) -> bool:
            queue.add("later", [])
            queue._process_queue()  # Simulate a callback racing the active worker.
            return True

        updater.update_memory.side_effect = arrive
        queue._process_queue()
        assert queue.pending_count == 1
        assert timer.call_args.args[0] == 30
        updater.update_memory.assert_called_once()


def test_emergency_is_immediate_and_cannot_be_delayed_by_normal_add() -> None:
    updater = MagicMock(update_memory=MagicMock(return_value=True))
    queue = MemoryUpdateQueue(DeerMemConfig(), updater)
    with patch(MODULE + ".time.monotonic", return_value=100), patch(MODULE + ".threading.Timer"):
        queue.add_nowait("t", ["before compaction"])
        queue.add("t", ["normal"])
        queue._process_queue()
    updater.update_memory.assert_called_once()
    assert updater.update_memory.call_args.kwargs["bypass_watermark"] is True
    assert queue.pending_count == 1


@pytest.mark.parametrize("method", ["flush", "flush_nowait"])
def test_flush_during_extraction_preserves_forced_drain_on_refresh(method: str) -> None:
    updater = MagicMock()
    queue = MemoryUpdateQueue(DeerMemConfig(), updater)
    with patch(MODULE + ".time.monotonic", return_value=100), patch(MODULE + ".threading.Timer") as timer:
        queue.add_nowait("first", [])

        def arrive(**_kwargs) -> bool:
            queue.add("later", ["old"])
            getattr(queue, method)()
            if method == "flush_nowait":
                queue._process_queue()  # The immediate timer fires while busy.
            queue.add("later", ["new"])
            return True

        updater.update_memory.side_effect = arrive
        queue._process_queue()
        assert queue._items[0].due_at == 100
        assert timer.call_args.args[0] == 0.05
        updater.update_memory.side_effect = None
        updater.update_memory.return_value = True
        queue._process_queue()
    assert updater.update_memory.call_count == 2
    assert updater.update_memory.call_args.kwargs["messages"] == ["new"]
    assert queue.pending_count == 0


def test_processed_key_starts_a_new_max_wait_window() -> None:
    queue = MemoryUpdateQueue(DeerMemConfig(debounce_seconds=30, max_wait_seconds=60), MagicMock())
    with patch(MODULE + ".time.monotonic") as clock, patch(MODULE + ".threading.Timer"):
        clock.return_value = 100
        queue.add("t", [])
        clock.return_value = 130
        queue._process_queue()
        clock.return_value = 150
        queue.add("t", [])
        assert queue._items[0].first_at == 150
        assert queue._items[0].due_at == 180


@pytest.mark.parametrize("value", [0, -1])
def test_max_wait_must_be_positive(value: int) -> None:
    with pytest.raises(ValueError, match="max_wait_seconds"):
        DeerMemConfig(max_wait_seconds=value)


def test_max_wait_can_cap_a_longer_debounce_period() -> None:
    queue = MemoryUpdateQueue(DeerMemConfig(debounce_seconds=30, max_wait_seconds=10), MagicMock())
    with patch(MODULE + ".time.monotonic", return_value=100), patch(MODULE + ".threading.Timer"):
        queue.add("t", [])
        assert queue._items[0].due_at == 110
