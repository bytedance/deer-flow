"""Pre-compaction snapshots must survive overlapping queued extraction."""

import json
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from deerflow.agents.memory.backends.deermem.deer_mem import DeerMem
from deerflow.agents.memory.backends.deermem.deermem.config import DeerMemConfig
from deerflow.agents.memory.backends.deermem.deermem.core.queue import MemoryUpdateQueue
from deerflow.agents.memory.summarization_hook import memory_flush_hook
from deerflow.agents.middlewares.summarization_middleware import DeerFlowSummarizationMiddleware
from deerflow.config.memory_config import MemoryConfig

QUEUE_MODULE = "deerflow.agents.memory.backends.deermem.deermem.core.queue"
HOOK_MODULE = "deerflow.agents.memory.summarization_hook"
PREFERENCES = (
    "My favorite beverage is oolong tea.",
    "My preferred programming language is Rust.",
    "My preferred editor is Neovim.",
    "My favorite season is autumn.",
)


def _pair(content: str, suffix: str) -> list:
    return [HumanMessage(content=content, id=f"human-{suffix}"), AIMessage(content="I have recorded your preference.", id=f"ai-{suffix}")]


class _BlockingExtractor:
    """Synthetic provider: extract every supplied preference, pausing one call."""

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.conversations: list[str] = []

    def invoke(self, messages: list, **_kwargs) -> AIMessage:
        conversation = str(messages[-1].content).split("<conversation>", 1)[1].split("</conversation>", 1)[0]
        self.conversations.append(conversation)
        if "BLOCK_OTHER_THREAD" in conversation:
            self.entered.set()
            assert self.release.wait(10), "extraction barrier was not released"
        facts = [{"content": content, "category": "preference", "confidence": 0.95, "scope": "user", "durability": "durable", "authority": "descriptive"} for content in PREFERENCES if content in conversation]
        return AIMessage(content=json.dumps({"user": {}, "history": {}, "newFacts": facts, "factsToRemove": []}))


@pytest.mark.parametrize("compaction_count", [1, 3])
def test_disjoint_compaction_snapshots_persist_while_extraction_is_busy(tmp_path: Path, compaction_count: int) -> None:
    extractor = _BlockingExtractor()
    manager = DeerMem(backend_config={"storage_path": str(tmp_path), "retrieval_adapter": "", "host_llm": extractor})
    summary_model = MagicMock()
    summary_model.with_config.return_value = summary_model
    summary_model.invoke.return_value = SimpleNamespace(text="A short summary omitting specific preferences.")
    snapshots = []
    middleware = DeerFlowSummarizationMiddleware(
        model=summary_model,
        trigger=("messages", 4),
        keep=("messages", 2),
        token_counter=len,
        before_summarization=[snapshots.append, memory_flush_hook],
    )
    runtime = SimpleNamespace(context={"thread_id": "target", "user_id": "alice", "agent_name": "researcher"})
    queue = manager._queue
    worker = None
    try:
        with patch(QUEUE_MODULE + ".threading.Timer"), patch(HOOK_MODULE + ".get_memory_config", return_value=MemoryConfig(enabled=True)), patch(HOOK_MODULE + ".get_memory_manager", return_value=manager):
            try:
                # A real consumer holds another thread's work at the provider boundary.
                manager.add_nowait("unrelated", _pair("BLOCK_OTHER_THREAD", "busy"), user_id="alice")
                worker = threading.Thread(target=lambda: queue._process_queue(skip_inter_item_delay=True))
                worker.start()
                assert extractor.entered.wait(10)

                state = {"messages": _pair(PREFERENCES[0], "0")}
                for index in range(compaction_count):
                    state["messages"].extend(_pair(PREFERENCES[index + 1], str(index + 1)))
                    compacted = middleware.compact_state(state, runtime, force=True)
                    assert compacted is not None
                    assert [message.id for message in compacted.messages_to_summarize] == [f"human-{index}", f"ai-{index}"]
                    state = {"messages": list(compacted.preserved_messages), "summary_text": compacted.summary_text}
                    # After-agent capture sees only the tail retained by compaction.
                    manager.add("target", state["messages"], agent_name="researcher", user_id="alice")
            finally:
                extractor.release.set()
                if worker is not None:
                    worker.join(10)
                    assert not worker.is_alive()
            assert queue.flush_sync(10)

        assert len(snapshots) == compaction_count
        expected = set(PREFERENCES[: compaction_count + 1])
        assert {fact["content"] for fact in manager.get_memory(agent_name="researcher", user_id="alice")["facts"]} == expected
        assert all(any(content in conversation for conversation in extractor.conversations) for content in expected)
    finally:
        queue.clear()
        manager._storage.close()


@pytest.mark.parametrize("flush_method", ["flush", "flush_nowait", "flush_sync"])
def test_emergency_snapshots_keep_fifo_metadata_and_normal_updates_still_coalesce(flush_method: str) -> None:
    updater = MagicMock(update_memory=MagicMock(return_value=True))
    queue = MemoryUpdateQueue(DeerMemConfig(queue_max_depth=1), updater)
    with patch(QUEUE_MODULE + ".threading.Timer"), patch(QUEUE_MODULE + ".time.monotonic", return_value=100), patch(QUEUE_MODULE + ".time.sleep"):
        queue.add("thread", ["old full transcript"], user_id="alice", agent_name="researcher")
        # Even at capacity, neither one-shot snapshot may be shed or replace another.
        queue.add_nowait("thread", ["removed first"], user_id="alice", agent_name="researcher", trace_id="trace-first", signals=frozenset({"preference"}))
        queue.add_nowait("thread", ["removed second"], user_id="alice", agent_name="researcher", trace_id="trace-second", signals=frozenset({"correction"}))
        queue.add("thread", ["latest full transcript"], user_id="alice", agent_name="researcher", trace_id="trace-normal")
        if flush_method == "flush_sync":
            assert queue.flush_sync(2)
        else:
            getattr(queue, flush_method)()
            if flush_method == "flush_nowait":
                queue._process_queue()

    calls = [call.kwargs for call in updater.update_memory.call_args_list]
    assert [call["messages"] for call in calls] == [["removed first"], ["removed second"], ["latest full transcript"]]
    assert [call["trace_id"] for call in calls] == ["trace-first", "trace-second", "trace-normal"]
    assert [call["signals"] for call in calls] == [frozenset({"preference"}), frozenset({"correction"}), frozenset()]
    assert [call["bypass_watermark"] for call in calls] == [True, True, False]
    assert all(call["user_id"] == "alice" and call["agent_name"] == "researcher" for call in calls)
    assert queue.pending_count == 0


def test_scoped_cancellation_removes_all_snapshots_without_touching_other_scopes() -> None:
    updater = MagicMock(update_memory=MagicMock(return_value=True))
    queue = MemoryUpdateQueue(DeerMemConfig(), updater)
    with patch(QUEUE_MODULE + ".threading.Timer"), patch(QUEUE_MODULE + ".time.sleep"):
        queue.add_nowait("thread", ["first"], user_id="alice", agent_name="researcher")
        queue.add_nowait("thread", ["second"], user_id="alice", agent_name="researcher")
        queue.add("thread", ["normal"], user_id="alice", agent_name="researcher")
        queue.add_nowait("thread", ["other user"], user_id="bob", agent_name="researcher")
        queue.add_nowait("thread", ["other agent"], user_id="alice", agent_name="writer")
        queue.add_nowait("thread", ["legacy scope"], agent_name="researcher")

        assert queue.cancel_by_agent("researcher", user_id="alice") == 3
        assert queue.flush_sync(2)

    assert [(call.kwargs["user_id"], call.kwargs["agent_name"], call.kwargs["messages"]) for call in updater.update_memory.call_args_list] == [
        ("bob", "researcher", ["other user"]),
        ("alice", "writer", ["other agent"]),
        (None, "researcher", ["legacy scope"]),
    ]
