"""A failed pre-compaction snapshot must be retried instead of dropped."""

import json
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from deerflow.agents.memory.backends.deermem.deer_mem import DeerMem
from deerflow.agents.memory.backends.deermem.deermem.config import DeerMemConfig
from deerflow.agents.memory.backends.deermem.deermem.core.queue import MemoryUpdateQueue

MODULE = "deerflow.agents.memory.backends.deermem.deermem.core.queue"
PREFERENCE = "My favorite beverage is oolong tea."


@pytest.fixture
def fake():
    """Fake monotonic clock and timer, as in ``test_memory_queue_deadlines.py``."""
    with patch(MODULE + ".threading.Timer") as timer, patch(MODULE + ".time.sleep"), patch(MODULE + ".time.monotonic") as clock:
        clock.return_value = 100.0
        yield SimpleNamespace(clock=clock, timer=timer)


def _queue(update_memory: MagicMock) -> MemoryUpdateQueue:
    return MemoryUpdateQueue(DeerMemConfig(), MagicMock(update_memory=update_memory))


def _wake_at_armed_deadline(queue: MemoryUpdateQueue, fake: SimpleNamespace) -> float:
    """Advance the clock by the delay the queue last armed, then run the consumer."""
    delay = fake.timer.call_args.args[0]
    fake.clock.return_value += delay
    queue._process_queue()
    return delay


@pytest.mark.parametrize("failure", [False, RuntimeError("provider unavailable")])
def test_failed_snapshot_is_retried_after_backoff(fake, failure) -> None:
    update_memory = MagicMock(side_effect=[failure, True])
    queue = _queue(update_memory)
    queue.add_nowait("thread", ["removed by compaction"], user_id="alice", agent_name="researcher", trace_id="trace", signals=frozenset({"preference"}))

    queue._process_queue()
    # Compaction already removed these messages, so nothing else can re-feed them.
    assert queue.pending_count == 1
    delay = fake.timer.call_args.args[0]
    assert delay >= 1

    fake.clock.return_value += delay - 0.001
    queue._process_queue()
    assert update_memory.call_count == 1  # An early wakeup must not skip the backoff.

    fake.clock.return_value = 100.0 + delay
    queue._process_queue()
    first, second = (call.kwargs for call in update_memory.call_args_list)
    assert second == first
    assert second["bypass_watermark"] is True
    assert queue.pending_count == 0


def test_snapshot_is_dropped_after_bounded_attempts(fake, caplog) -> None:
    update_memory = MagicMock(return_value=False)
    queue = _queue(update_memory)
    queue.add_nowait("thread-7", ["SENSITIVE CONTENT"], user_id="alice")

    delays = []
    with caplog.at_level(logging.WARNING, logger=MODULE):
        queue._process_queue()
        while queue.pending_count and len(delays) < 10:
            delays.append(_wake_at_armed_deadline(queue, fake))

    assert delays == [5, 30]
    assert update_memory.call_count == 3
    assert queue.pending_count == 0
    logged = [record.getMessage() for record in caplog.records if record.name == MODULE]
    assert any("thread-7" in message and "3 failed" in message for message in logged)
    assert all("SENSITIVE CONTENT" not in message for message in logged)


def test_failed_normal_update_is_not_requeued(fake) -> None:
    update_memory = MagicMock(return_value=False)
    queue = _queue(update_memory)
    queue.add("thread", ["full transcript"], user_id="alice")
    queue.flush()
    # The watermark did not advance, so the next turn re-feeds this conversation.
    update_memory.assert_called_once()
    assert queue.pending_count == 0


def test_retry_keeps_a_conversations_snapshots_in_arrival_order(fake) -> None:
    extracted: list[str] = []
    outcomes = iter([False, True, True, True, True])
    queue: MemoryUpdateQueue

    def update(**kwargs) -> bool:
        label = kwargs["messages"][0]
        extracted.append(label)
        if extracted == ["first"]:
            # The next compaction lands while the failing attempt is in flight.
            queue.add_nowait("thread", ["second"], user_id="alice")
            queue._process_queue()  # Its immediate timer fires while the worker is busy.
        return next(outcomes)

    queue = _queue(MagicMock(side_effect=update))
    queue.add_nowait("thread", ["first"], user_id="alice")
    queue.add_nowait("other", ["unrelated"], user_id="alice")

    queue._process_queue()
    # Only the failed snapshot's own conversation waits.
    assert extracted == ["first", "unrelated"]
    assert [context.messages for context in queue._items] == [["first"], ["second"]]
    delay = fake.timer.call_args.args[0]

    # A compaction during the backoff queues behind the retry too.
    fake.clock.return_value += 1
    queue.add_nowait("thread", ["third"], user_id="alice")
    queue._process_queue()
    assert extracted == ["first", "unrelated"]
    assert fake.timer.call_args.args[0] == pytest.approx(delay - 1)

    fake.clock.return_value = 100.0 + delay
    queue._process_queue()
    assert extracted == ["first", "unrelated", "first", "second", "third"]
    assert queue.pending_count == 0


def test_repeated_failure_keeps_holding_later_snapshots(fake) -> None:
    extracted: list[str] = []
    outcomes = iter([False, False, True, True])

    def update(**kwargs) -> bool:
        extracted.append(kwargs["messages"][0])
        return next(outcomes)

    queue = _queue(MagicMock(side_effect=update))
    queue.add_nowait("thread", ["first"], user_id="alice")
    queue.add_nowait("thread", ["second"], user_id="alice")

    queue._process_queue()
    _wake_at_armed_deadline(queue, fake)
    assert extracted == ["first", "first"]
    assert [context.messages for context in queue._items] == [["first"], ["second"]]

    _wake_at_armed_deadline(queue, fake)
    assert extracted == ["first", "first", "first", "second"]
    assert queue.pending_count == 0


def test_dropped_snapshot_releases_later_snapshots(fake) -> None:
    extracted: list[str] = []

    def update(**kwargs) -> bool:
        extracted.append(kwargs["messages"][0])
        return kwargs["messages"][0] != "poison"

    queue = _queue(MagicMock(side_effect=update))
    queue.add_nowait("thread", ["poison"], user_id="alice")
    queue.add_nowait("thread", ["healthy"], user_id="alice")

    queue._process_queue()
    while queue.pending_count and len(extracted) < 10:
        _wake_at_armed_deadline(queue, fake)

    assert extracted == ["poison", "poison", "poison", "healthy"]
    assert queue.pending_count == 0


def test_retry_holds_the_conversations_pending_normal_update(fake) -> None:
    extracted: list[str] = []
    outcomes = iter([False, False, True, True])

    def update(**kwargs) -> bool:
        extracted.append(kwargs["messages"][0])
        return next(outcomes)

    queue = _queue(MagicMock(side_effect=update))
    queue.add_nowait("thread", ["compacted"], user_id="alice")
    queue.add("thread", ["tail with a correction"], user_id="alice")  # Due after the 30 s debounce.

    queue._process_queue()
    _wake_at_armed_deadline(queue, fake)  # The second retry is now due after that debounce.
    assert extracted == ["compacted", "compacted"]

    _wake_at_armed_deadline(queue, fake)
    # The compacted messages are older, so the tail that may correct them is extracted last.
    assert extracted == ["compacted", "compacted", "compacted", "tail with a correction"]
    assert queue.pending_count == 0


def test_normal_update_arriving_during_the_backoff_waits_for_the_retry(fake) -> None:
    extracted: list[str] = []
    outcomes = iter([False, True, True])

    def update(**kwargs) -> bool:
        extracted.append(kwargs["messages"][0])
        return next(outcomes)

    queue = MemoryUpdateQueue(DeerMemConfig(debounce_seconds=1), MagicMock(update_memory=MagicMock(side_effect=update)))
    queue.add_nowait("thread", ["compacted"], user_id="alice")
    queue._process_queue()

    fake.clock.return_value += 1
    queue.add("thread", ["tail"], user_id="alice")  # Its 1 s debounce ends before the 5 s retry.
    _wake_at_armed_deadline(queue, fake)
    assert extracted == ["compacted", "compacted", "tail"]
    assert queue.pending_count == 0


def test_failed_snapshot_holds_a_normal_update_of_the_same_batch(fake) -> None:
    extracted: list[str] = []
    outcomes = iter([False, True, True, True])

    def update(**kwargs) -> bool:
        extracted.append(kwargs["messages"][0])
        return next(outcomes)

    queue = _queue(MagicMock(side_effect=update))
    queue.add_nowait("thread", ["compacted"], user_id="alice")
    queue.add("thread", ["tail"], user_id="alice")
    queue.add("other", ["unrelated"], user_id="alice")

    queue.flush()
    assert extracted == ["compacted", "unrelated"]
    assert [context.messages for context in queue._items] == [["compacted"], ["tail"]]

    _wake_at_armed_deadline(queue, fake)
    assert extracted == ["compacted", "unrelated", "compacted", "tail"]
    assert queue.pending_count == 0


def test_newer_normal_update_replaces_one_held_behind_a_retry(fake) -> None:
    queue: MemoryUpdateQueue
    calls: list[tuple[str, frozenset[str]]] = []

    def update(**kwargs) -> bool:
        calls.append((kwargs["messages"][0], kwargs["signals"]))
        if len(calls) == 1:
            # The next turn ends while the failing attempt is in flight.
            queue.add("thread", ["newer transcript"], user_id="alice", signals=frozenset({"correction"}))
        return len(calls) > 1

    queue = _queue(MagicMock(side_effect=update))
    queue.add_nowait("thread", ["compacted"], user_id="alice")
    queue.add("thread", ["older transcript"], user_id="alice", signals=frozenset({"preference"}))

    queue.flush()
    while queue.pending_count and len(calls) < 10:
        _wake_at_armed_deadline(queue, fake)

    # A conversation keeps one normal update: the newer one, with both signals.
    assert calls == [
        ("compacted", frozenset()),
        ("compacted", frozenset()),
        ("newer transcript", frozenset({"preference", "correction"})),
    ]


def test_cancellation_during_a_failing_attempt_also_cancels_its_retry(fake) -> None:
    queue: MemoryUpdateQueue
    clear_alice = True

    def fail(**_kwargs) -> bool:
        if clear_alice:
            # The in-flight context is outside ``_items``, so nothing is counted here.
            assert queue.cancel_by_agent("researcher", user_id="alice") == 0
        return False

    queue = _queue(MagicMock(side_effect=fail))
    queue.add_nowait("thread", ["cleared"], user_id="alice", agent_name="researcher")
    queue.add_nowait("thread", ["other user"], user_id="bob", agent_name="researcher")
    queue.add_nowait("thread", ["other agent"], user_id="alice", agent_name="writer")

    queue._process_queue()
    assert [(context.user_id, context.agent_name) for context in queue._items] == [("bob", "researcher"), ("alice", "writer")]

    # The cancellation covered that batch only; later snapshots retry as usual.
    clear_alice = False
    queue.cancel_by_agent(all_agents=True, user_id="bob")
    queue.cancel_by_agent(all_agents=True, user_id="alice")
    queue.add_nowait("thread", ["after clear"], user_id="alice", agent_name="researcher")
    queue._process_queue()
    assert [context.messages for context in queue._items] == [["after clear"]]


def test_shutdown_drain_reports_an_unsaved_snapshot_and_retries_without_backoff(fake) -> None:
    update_memory = MagicMock(side_effect=[False, True])
    queue = _queue(update_memory)
    queue.add_nowait("thread", ["removed by compaction"], user_id="alice")

    assert queue.flush_sync(2) is False
    assert queue.pending_count == 1
    assert queue.flush_sync(2) is True
    assert update_memory.call_count == 2
    assert queue.pending_count == 0


def test_shutdown_drain_holds_nothing_back(fake) -> None:
    extracted: list[str] = []

    def update(**kwargs) -> bool:
        extracted.append(kwargs["messages"][0])
        return kwargs["messages"][0] != "failing"

    queue = _queue(MagicMock(side_effect=update))
    queue.add_nowait("thread", ["failing"], user_id="alice")
    queue.add_nowait("thread", ["later snapshot"], user_id="alice")
    queue.add("thread", ["tail"], user_id="alice")

    # No retry follows a shutdown, so waiting for one would skip the other updates.
    assert queue.flush_sync(2) is False
    assert extracted == ["failing", "later snapshot", "tail"]
    assert queue.pending_count == 1


class _FlakyExtractor:
    """Synthetic provider that fails a fixed number of calls before extracting."""

    def __init__(self, failures: list) -> None:
        self.failures = list(failures)
        self.calls = 0

    def invoke(self, messages: list, **_kwargs) -> AIMessage:
        self.calls += 1
        if self.failures:
            failure = self.failures.pop(0)
            if isinstance(failure, Exception):
                raise failure
            return AIMessage(content=failure)
        conversation = str(messages[-1].content).split("<conversation>", 1)[1].split("</conversation>", 1)[0]
        facts = [{"content": PREFERENCE, "category": "preference", "confidence": 0.95, "scope": "user", "durability": "durable", "authority": "descriptive"}] if PREFERENCE in conversation else []
        return AIMessage(content=json.dumps({"user": {}, "history": {}, "newFacts": facts, "factsToRemove": []}))


@pytest.mark.parametrize("failure", ["this is not JSON", RuntimeError("provider unavailable")])
def test_snapshot_facts_persist_after_a_failed_extraction(tmp_path: Path, failure) -> None:
    extractor = _FlakyExtractor([failure])
    manager = DeerMem(backend_config={"storage_path": str(tmp_path), "retrieval_adapter": "", "host_llm": extractor})
    queue = manager._queue
    messages = [HumanMessage(content=PREFERENCE, id="human-0"), AIMessage(content="I have recorded your preference.", id="ai-0")]
    try:
        with patch(MODULE + ".threading.Timer"):
            manager.add_nowait("target", messages, agent_name="researcher", user_id="alice")
            queue._process_queue(skip_inter_item_delay=True)
            # The failed attempt wrote nothing and the snapshot is still held.
            assert manager.get_memory(agent_name="researcher", user_id="alice")["facts"] == []
            assert queue.pending_count == 1

            queue.flush(skip_inter_item_delay=True)

        assert [fact["content"] for fact in manager.get_memory(agent_name="researcher", user_id="alice")["facts"]] == [PREFERENCE]
        assert extractor.calls == 2
        assert queue.pending_count == 0
    finally:
        queue.clear()
        manager._storage.close()
