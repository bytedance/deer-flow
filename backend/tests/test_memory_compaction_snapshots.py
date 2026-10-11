"""One-shot compaction batches must survive until their own extraction attempt."""

import json
import threading
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.runtime import Runtime

from deerflow.agents.memory import summarization_hook
from deerflow.agents.memory.backends.deermem.deer_mem import DeerMem
from deerflow.agents.memory.backends.deermem.deermem.config import DeerMemConfig
from deerflow.agents.memory.backends.deermem.deermem.core.queue import MemoryUpdateQueue, QueueFull
from deerflow.agents.middlewares.summarization_middleware import SummarizationEvent
from deerflow.config.memory_config import MemoryConfig


@pytest.fixture
def queue(monkeypatch):
    updater = MagicMock(update_memory=MagicMock(return_value=True))
    queue = MemoryUpdateQueue(DeerMemConfig(queue_max_depth=1), updater)
    # Drive callbacks explicitly; the busy-consumer test still uses a real worker.
    monkeypatch.setattr(queue, "_schedule_timer", lambda delay: None)
    return queue, updater


def test_repeated_compaction_hooks_persist_both_batches_after_restart(tmp_path, monkeypatch):
    preferences = ("I prefer detailed Python examples.", "I prefer metric units for measurements.")
    conversations = []

    class ExtractionModel:
        def invoke(self, prompt, config=None):
            # Only inspect the new batch, never facts carried in current_memory.
            conversation = prompt[-1].content.split("<conversation>", 1)[1].split("</conversation>", 1)[0]
            conversations.append(conversation)
            facts = [{"content": text, "category": "preference", "confidence": 0.9, "scope": "user", "durability": "durable", "authority": "descriptive"} for text in preferences if text in conversation]
            return AIMessage(content=json.dumps({"user": {}, "history": {}, "newFacts": facts, "factsToRemove": []}))

    config = {"storage_path": str(tmp_path), "retrieval_adapter": "", "token_counting": "char"}
    manager = DeerMem.from_config(config, host_llm_factory=ExtractionModel)
    monkeypatch.setattr(manager._queue, "_schedule_timer", lambda delay: None)
    monkeypatch.setattr(summarization_hook, "get_memory_manager", lambda: manager)
    monkeypatch.setattr(summarization_hook, "get_memory_config", lambda: MemoryConfig(enabled=True))
    for text in preferences:
        summarization_hook.memory_flush_hook(
            SummarizationEvent(
                messages_to_summarize=(HumanMessage(text), AIMessage("I will remember that preference.")),
                preserved_messages=(),
                thread_id="same-thread",
                agent_name="researcher",
                runtime=Runtime(context={"user_id": "alice"}),
            )
        )
    assert manager.shutdown_flush(timeout=5)

    restarted = DeerMem(backend_config=config)
    facts = restarted.get_memory(user_id="alice", agent_name="researcher")["facts"]
    assert {fact["content"] for fact in facts} == set(preferences)
    assert len(conversations) == 2
    assert all(text in conversation for text, conversation in zip(preferences, conversations, strict=True))
    assert restarted.get_memory(user_id="bob", agent_name="researcher")["facts"] == []
    assert restarted.get_memory(user_id="alice", agent_name="other")["facts"] == []


def test_snapshots_arriving_while_consumer_is_busy_are_processed_in_order(queue):
    queue, updater = queue
    entered, release = threading.Event(), threading.Event()
    calls = []

    def extract(**kwargs):
        calls.append(kwargs)
        if kwargs["messages"] == ["occupied"]:
            entered.set()
            assert release.wait(5), "test did not release the active consumer"
        return True

    updater.update_memory.side_effect = extract
    queue.add_nowait("other-thread", ["occupied"])
    worker = threading.Thread(target=queue.flush, kwargs={"skip_inter_item_delay": True})
    worker.start()
    try:
        assert entered.wait(5), "consumer did not start"
        for index in (1, 2):
            queue.add_nowait("same-thread", [f"snapshot-{index}"], user_id="alice", agent_name="researcher", trace_id=f"trace-{index}", signals=frozenset({f"signal-{index}"}))
            queue._process_queue(skip_inter_item_delay=True)  # Timer callback races the active worker.
        assert len(calls) == 1  # A second consumer must not enter the updater.
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive()
    queue.flush(skip_inter_item_delay=True)
    assert [call["messages"] for call in calls] == [["occupied"], ["snapshot-1"], ["snapshot-2"]]
    for index, call in enumerate(calls[1:], start=1):
        assert (call["user_id"], call["agent_name"], call["trace_id"]) == ("alice", "researcher", f"trace-{index}")
        assert call["signals"] == frozenset({f"signal-{index}"})
        assert call["bypass_watermark"] is True
    assert queue.pending_count == 0


def test_emergency_batches_survive_backpressure_and_normal_refresh(queue):
    queue, updater = queue
    queue.add("t", ["old normal"], signals=frozenset({"preference"}))
    queue.add_nowait("t", ["first compacted batch"])
    queue.add_nowait("t", ["second compacted batch"])
    queue.add("t", ["latest full conversation"], signals=frozenset({"correction"}))
    with pytest.raises(QueueFull):
        queue.add("unrelated", ["reject under load"])
    queue.flush(skip_inter_item_delay=True)
    calls = updater.update_memory.call_args_list
    assert [call.kwargs["messages"] for call in calls] == [["first compacted batch"], ["second compacted batch"], ["latest full conversation"]]
    assert [call.kwargs["bypass_watermark"] for call in calls] == [True, True, False]
    assert calls[-1].kwargs["signals"] == frozenset({"preference", "correction"})


def test_scoped_cancellation_removes_all_matching_snapshots(queue):
    queue, updater = queue
    for text, user, agent in (("first", "alice", "a"), ("second", "alice", "a"), ("other user", "bob", "a"), ("other agent", "alice", "b")):
        queue.add_nowait("t", [text], user_id=user, agent_name=agent)
    assert queue.cancel_by_agent("a", user_id="alice") == 2
    queue.flush(skip_inter_item_delay=True)
    assert [call.kwargs["messages"] for call in updater.update_memory.call_args_list] == [["other user"], ["other agent"]]


@pytest.mark.parametrize("failure", [False, RuntimeError("extraction failed")])
def test_failed_snapshot_does_not_skip_the_next_batch(queue, failure):
    queue, updater = queue
    updater.update_memory.side_effect = [failure, True]
    queue.add_nowait("t", ["first"])
    queue.add_nowait("t", ["second"])
    queue.flush(skip_inter_item_delay=True)
    assert [call.kwargs["messages"] for call in updater.update_memory.call_args_list] == [["first"], ["second"]]
    assert queue.pending_count == 0
