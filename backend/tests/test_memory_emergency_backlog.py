"""Emergency snapshot retention must make a stalled extractor observable."""

import logging
import threading
from unittest.mock import MagicMock, patch

import pytest

from deerflow.agents.memory.backends.deermem.deermem.config import DeerMemConfig
from deerflow.agents.memory.backends.deermem.deermem.core.queue import MemoryUpdateQueue

MODULE = "deerflow.agents.memory.backends.deermem.deermem.core.queue"


@pytest.fixture
def queue_factory():
    queues = []
    with patch(MODULE + ".threading.Timer"):

        def make(max_depth=0):
            updater = MagicMock(update_memory=MagicMock(return_value=True))
            queue = MemoryUpdateQueue(DeerMemConfig(queue_max_depth=max_depth), updater)
            queues.append(queue)
            return queue, updater

        try:
            yield make
        finally:
            for queue in queues:
                queue.clear()


def _warnings(caplog):
    return [record.getMessage() for record in caplog.records if record.name == MODULE and record.levelno == logging.WARNING]


@pytest.mark.parametrize("max_depth", [0, 1, 1000])
def test_stalled_extraction_warns_at_snapshot_threshold_and_doublings(queue_factory, caplog, max_depth):
    queue, updater = queue_factory(max_depth)
    entered, release = threading.Event(), threading.Event()

    def update(**kwargs):
        if kwargs["thread_id"] == "busy":
            entered.set()
            assert release.wait(10), "extraction barrier was not released"
        return True

    updater.update_memory.side_effect = update
    queue.add_nowait("busy", ["blocked extractor"])
    worker = threading.Thread(target=lambda: queue._process_queue(skip_inter_item_delay=True))
    worker.start()
    try:
        assert entered.wait(10)
        with caplog.at_level(logging.WARNING, logger=MODULE):
            for index in range(1, 66):
                queue.add_nowait("thread", [f"private snapshot payload {index}"], user_id="alice", agent_name="researcher", trace_id=f"trace-{index}")
                if index == 31:
                    assert _warnings(caplog) == []
            warnings = _warnings(caplog)
            assert len(warnings) == 2
            assert "32 pending emergency snapshots" in warnings[0]
            assert "64 pending emergency snapshots" in warnings[1]
            assert all("thread" in warning and "alice" in warning and "researcher" in warning for warning in warnings)
            assert "private snapshot payload" not in caplog.text
            assert queue.pending_count == 65
            assert queue.is_processing
    finally:
        release.set()
        worker.join(10)
        assert not worker.is_alive()

    queue.flush(skip_inter_item_delay=True)
    calls = [call.kwargs for call in updater.update_memory.call_args_list][1:]
    assert [call["messages"] for call in calls] == [[f"private snapshot payload {index}"] for index in range(1, 66)]
    assert [call["trace_id"] for call in calls] == [f"trace-{index}" for index in range(1, 66)]
    assert all(call["bypass_watermark"] and call["user_id"] == "alice" and call["agent_name"] == "researcher" for call in calls)
    assert queue.pending_count == 0


def test_backlog_warnings_count_only_same_scope_emergency_snapshots(queue_factory, caplog):
    queue, _ = queue_factory()
    scopes = [("thread", "alice", "researcher"), ("other-thread", "alice", "researcher"), ("thread", "bob", "researcher"), ("thread", "alice", "writer"), ("thread", None, "researcher")]
    with caplog.at_level(logging.WARNING, logger=MODULE):
        for thread, user, agent in scopes:
            for _ in range(31):
                queue.add_nowait(thread, ["private snapshot"], user_id=user, agent_name=agent)
            queue.add(thread, ["normal cumulative update"], user_id=user, agent_name=agent)
        assert _warnings(caplog) == []
        queue.add_nowait("thread", ["32nd snapshot"], user_id="alice", agent_name="researcher")
        for _ in range(10):
            queue.add("thread", ["latest normal update"], user_id="alice", agent_name="researcher")
        warnings = _warnings(caplog)
        assert len(warnings) == 1
        assert "32 pending emergency snapshots" in warnings[0]
        assert "alice" in warnings[0] and "researcher" in warnings[0]
        assert queue.pending_count == 161


@pytest.mark.parametrize("remove", ["drain", "cancel", "clear"])
def test_new_backlog_warns_again_after_pending_snapshots_are_removed(queue_factory, caplog, remove):
    queue, _ = queue_factory()
    with caplog.at_level(logging.WARNING, logger=MODULE):
        for _ in range(32):
            queue.add_nowait("thread", ["snapshot"], user_id="alice", agent_name="researcher")
        assert len(_warnings(caplog)) == 1
        if remove == "drain":
            queue.flush(skip_inter_item_delay=True)
        elif remove == "cancel":
            assert queue.cancel_by_agent("researcher", user_id="alice") == 32
        else:
            queue.clear()
        assert queue.pending_count == 0
        for _ in range(32):
            queue.add_nowait("thread", ["later snapshot"], user_id="alice", agent_name="researcher")
        assert len(_warnings(caplog)) == 2
