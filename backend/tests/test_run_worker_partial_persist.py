"""End-to-end integration tests for partial-stream persistence in run_agent.

These tests drive the full worker path with a fake agent that yields
``messages`` chunks, trips ``record.abort_event`` mid-stream, and then
asserts that the cancel branch persisted the partial AIMessage to both
``run_events`` and the checkpoint — exactly the design contract in
``docs/plans/2026-06-14-partial-stream-persistence-proposal.md``.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from deerflow.runtime.events.store.memory import MemoryRunEventStore
from deerflow.runtime.runs.manager import RunManager
from deerflow.runtime.runs.schemas import RunStatus
from deerflow.runtime.runs.worker import RunContext, run_agent


async def _seed_checkpoint(checkpointer: InMemorySaver, thread_id: str, messages: list) -> None:
    """Write a baseline checkpoint so the partial-append helper has a target.

    Includes ``new_versions={'messages': v}`` because InMemorySaver (like the
    other savers) only persists channel values for channels listed in
    ``new_versions``. Production graphs go through this versioning path
    automatically via LangGraph; manual ``aput`` callers must do it explicitly.
    """
    from langgraph.checkpoint.base import empty_checkpoint

    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    ckpt = empty_checkpoint()
    ckpt["channel_values"] = {"messages": list(messages)}
    version = checkpointer.get_next_version(None, None)
    ckpt["channel_versions"] = {"messages": version}
    await checkpointer.aput(config, ckpt, {"source": "input", "step": 0}, {"messages": version})


class _AbortAfterTwoChunks:
    """Fake agent: yields 2 messages-mode chunks, then trips abort, then yields 1 more.

    After abort, the worker's loop sees ``record.abort_event.is_set()`` on the
    next iteration and breaks. The accumulator should hold the merged content
    of the first two chunks.
    """

    def __init__(self, record):
        self._record = record
        self.checkpointer = None
        self.store = None
        self.interrupt_before_nodes = None
        self.interrupt_after_nodes = None
        self.metadata: dict = {}

    async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
        # First two chunks: partial AI response
        yield (AIMessageChunk(id="m_partial", content="hello "), {"langgraph_node": "agent"})
        yield (AIMessageChunk(id="m_partial", content="world"), {"langgraph_node": "agent"})
        # Trip abort BEFORE yielding the next chunk so the loop breaks at the next check.
        self._record.abort_event.set()
        self._record.abort_action = "interrupt"
        # Yield one more so the loop has something to iterate on after abort fires.
        yield (AIMessageChunk(id="m_partial", content=" (extra after abort)"), {"langgraph_node": "agent"})


@pytest.mark.anyio
async def test_run_agent_persists_partial_on_interrupt():
    """Cancelling mid-stream lands the partial AIMessage in run_events AND checkpoint."""
    run_manager = RunManager()
    record = await run_manager.create("thread-partial")

    bridge = SimpleNamespace(
        publish=AsyncMock(),
        publish_end=AsyncMock(),
        cleanup=AsyncMock(),
    )
    checkpointer = InMemorySaver()
    event_store = MemoryRunEventStore()

    # Seed a baseline checkpoint so the partial append target exists.
    await _seed_checkpoint(checkpointer, "thread-partial", [HumanMessage(id="h1", content="say hi")])

    agent = _AbortAfterTwoChunks(record)

    def factory(*, config):
        return agent

    await run_agent(
        bridge,
        run_manager,
        record,
        ctx=RunContext(checkpointer=checkpointer, event_store=event_store),
        agent_factory=factory,
        graph_input={},
        config={},
        stream_modes=["messages"],
    )

    # 1. Run status reflects interrupt
    assert record.status == RunStatus.interrupted

    # 2. run_events captured the partial AIMessage with interrupted markers
    messages = await event_store.list_messages_by_run("thread-partial", record.run_id, limit=100)
    ai_events = [e for e in messages if e["event_type"] == "llm.ai.response"]
    assert len(ai_events) == 1, f"expected 1 llm.ai.response, got {len(ai_events)}: {messages}"
    ai_event = ai_events[0]
    assert ai_event["metadata"]["interrupted"] is True
    assert ai_event["metadata"]["partial"] is True
    assert ai_event["metadata"]["abort_action"] == "interrupt"
    # Content includes both chunks merged together
    assert ai_event["content"]["id"] == "m_partial"
    assert "hello world" in ai_event["content"]["content"]

    # 3. Checkpoint received a new checkpoint with the partial AIMessage appended
    ckpt_tuple = await checkpointer.aget_tuple({"configurable": {"thread_id": "thread-partial", "checkpoint_ns": ""}})
    assert ckpt_tuple is not None
    written_messages = ckpt_tuple.checkpoint["channel_values"]["messages"]
    # Original HumanMessage + appended partial AIMessage
    ids = [getattr(m, "id", None) for m in written_messages]
    assert "h1" in ids
    assert "m_partial" in ids


class _AbortAfterToolCallChunks:
    """Fake agent: yields tool_call chunks that build a complete tool_call, then aborts."""

    def __init__(self, record):
        self._record = record
        self.checkpointer = None
        self.store = None
        self.interrupt_before_nodes = None
        self.interrupt_after_nodes = None
        self.metadata: dict = {}

    async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
        yield (
            AIMessageChunk(
                id="m_tc",
                content="",
                tool_call_chunks=[{"name": "bash", "args": '{"cmd":"l', "id": "call_xyz", "index": 0}],
            ),
            {"langgraph_node": "agent"},
        )
        yield (
            AIMessageChunk(
                id="m_tc",
                content="",
                tool_call_chunks=[{"name": None, "args": 's"}', "id": None, "index": 0}],
            ),
            {"langgraph_node": "agent"},
        )
        self._record.abort_event.set()
        self._record.abort_action = "interrupt"
        # Make the generator awaitable so the worker sees the abort signal
        yield (AIMessageChunk(id="m_tc", content=""), {"langgraph_node": "agent"})


@pytest.mark.anyio
async def test_run_agent_closes_open_tool_call_on_interrupt():
    """Tool calls present in the partial AIMessage get synthetic closure ToolMessages."""
    run_manager = RunManager()
    record = await run_manager.create("thread-tc")

    bridge = SimpleNamespace(
        publish=AsyncMock(),
        publish_end=AsyncMock(),
        cleanup=AsyncMock(),
    )
    checkpointer = InMemorySaver()
    event_store = MemoryRunEventStore()

    await _seed_checkpoint(checkpointer, "thread-tc", [HumanMessage(id="h1", content="run ls")])

    agent = _AbortAfterToolCallChunks(record)

    def factory(*, config):
        return agent

    await run_agent(
        bridge,
        run_manager,
        record,
        ctx=RunContext(checkpointer=checkpointer, event_store=event_store),
        agent_factory=factory,
        graph_input={},
        config={},
        stream_modes=["messages"],
    )

    assert record.status == RunStatus.interrupted

    messages = await event_store.list_messages_by_run("thread-tc", record.run_id, limit=100)
    tool_events = [e for e in messages if e["event_type"] == "llm.tool.result"]
    assert len(tool_events) == 1, f"expected 1 synthetic tool result, got {len(tool_events)}: {messages}"
    tm_event = tool_events[0]
    assert tm_event["metadata"]["synthetic"] is True
    assert tm_event["metadata"]["interrupted"] is True
    assert tm_event["content"]["tool_call_id"] == "call_xyz"
    assert tm_event["content"]["status"] == "error"

    # Checkpoint contains human + partial AI + closure ToolMessage
    ckpt_tuple = await checkpointer.aget_tuple({"configurable": {"thread_id": "thread-tc", "checkpoint_ns": ""}})
    written = ckpt_tuple.checkpoint["channel_values"]["messages"]
    assert any(getattr(m, "tool_call_id", None) == "call_xyz" for m in written)


class _AbortAfterRollback:
    """Fake agent that aborts with action='rollback' to verify partial is NOT persisted."""

    def __init__(self, record):
        self._record = record
        self.checkpointer = None
        self.store = None
        self.interrupt_before_nodes = None
        self.interrupt_after_nodes = None
        self.metadata: dict = {}

    async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
        yield (AIMessageChunk(id="m_rollback", content="will be discarded"), {"langgraph_node": "agent"})
        self._record.abort_event.set()
        self._record.abort_action = "rollback"
        yield (AIMessageChunk(id="m_rollback", content=""), {"langgraph_node": "agent"})


@pytest.mark.anyio
async def test_run_agent_skips_partial_persist_on_rollback():
    """abort_action='rollback' must not persist partial — rollback discards everything."""
    run_manager = RunManager()
    record = await run_manager.create("thread-rb")

    bridge = SimpleNamespace(
        publish=AsyncMock(),
        publish_end=AsyncMock(),
        cleanup=AsyncMock(),
    )
    checkpointer = InMemorySaver()
    event_store = MemoryRunEventStore()

    await _seed_checkpoint(checkpointer, "thread-rb", [HumanMessage(id="h1", content="rollback me")])

    agent = _AbortAfterRollback(record)

    def factory(*, config):
        return agent

    await run_agent(
        bridge,
        run_manager,
        record,
        ctx=RunContext(checkpointer=checkpointer, event_store=event_store),
        agent_factory=factory,
        graph_input={},
        config={},
        stream_modes=["messages"],
    )

    # Rollback path sets status to error
    assert record.status == RunStatus.error

    # No llm.ai.response event was emitted for the partial
    messages = await event_store.list_messages_by_run("thread-rb", record.run_id, limit=100)
    ai_events = [e for e in messages if e["event_type"] == "llm.ai.response"]
    assert ai_events == []


class _CompletesNormally:
    """Fake agent that streams chunks AND fires on_llm_end via callback so the partial
    accumulator's skip_ids logic engages."""

    def __init__(self, record, journal_callback):
        self._record = record
        self._journal_callback = journal_callback
        self.checkpointer = None
        self.store = None
        self.interrupt_before_nodes = None
        self.interrupt_after_nodes = None
        self.metadata: dict = {}

    async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
        # Turn 1: completed (with on_llm_end firing)
        msg1 = AIMessage(id="m_done", content="turn 1 reply")
        yield (AIMessageChunk(id="m_done", content="turn 1 reply"), {"langgraph_node": "agent"})
        # Simulate on_llm_end firing so journal records m_done
        self._journal_callback(msg1)
        # Turn 2 partial
        yield (AIMessageChunk(id="m_partial", content="turn 2 par"), {"langgraph_node": "agent"})
        yield (AIMessageChunk(id="m_partial", content="tial"), {"langgraph_node": "agent"})
        self._record.abort_event.set()
        self._record.abort_action = "interrupt"
        yield (AIMessageChunk(id="m_partial", content=""), {"langgraph_node": "agent"})


@pytest.mark.anyio
async def test_run_agent_skips_completed_message_only_persists_partial():
    """If turn 1 completed (recorded via on_llm_end) and turn 2 cancelled mid-stream,
    only the turn 2 partial should be persisted — not a duplicate of turn 1."""
    run_manager = RunManager()
    record = await run_manager.create("thread-mixed")

    bridge = SimpleNamespace(
        publish=AsyncMock(),
        publish_end=AsyncMock(),
        cleanup=AsyncMock(),
    )
    checkpointer = InMemorySaver()
    event_store = MemoryRunEventStore()

    await _seed_checkpoint(checkpointer, "thread-mixed", [HumanMessage(id="h1", content="ask")])

    # Capture the journal so we can manually trigger on_llm_end equivalent behavior.
    captured_journal: dict = {}

    def fake_on_llm_end(msg):
        # Simulate what on_llm_end would have written: mark the id as recorded.
        if (j := captured_journal.get("journal")) is not None:
            j._recorded_ai_message_ids.add(msg.id)

    agent = _CompletesNormally(record, fake_on_llm_end)

    def factory(*, config):
        # The runtime injects the journal under context["__run_journal"] before the
        # factory runs; grab it for the fake on_llm_end shortcut above.
        captured_journal["journal"] = config["context"]["__run_journal"]
        return agent

    await run_agent(
        bridge,
        run_manager,
        record,
        ctx=RunContext(checkpointer=checkpointer, event_store=event_store),
        agent_factory=factory,
        graph_input={},
        config={},
        stream_modes=["messages"],
    )

    assert record.status == RunStatus.interrupted

    messages = await event_store.list_messages_by_run("thread-mixed", record.run_id, limit=100)
    ai_events = [e for e in messages if e["event_type"] == "llm.ai.response"]
    # Only the partial m_partial should land — m_done was skipped via skip_ids.
    assert len(ai_events) == 1
    assert ai_events[0]["content"]["id"] == "m_partial"
    assert "partial" in ai_events[0]["content"]["content"]
