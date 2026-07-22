"""Dual-mode (full/delta) end-to-end parity for thread checkpoint flows.

Exercises the same thread lifecycle — multi-turn writes, latest-state read,
bounded history, branch from an earlier checkpoint, and a compaction-style
wholesale ``Overwrite`` write — against the production thread state schemas
(``get_thread_state_schema(mode)``) on both ``InMemorySaver`` and
``AsyncSqliteSaver``. Every assertion compares the materialized state
produced by the two modes: delta storage must be behaviorally invisible.
"""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import StateGraph
from langgraph.types import Overwrite

from deerflow.agents.thread_state import get_thread_state_schema
from deerflow.runtime.checkpoint_mode import inject_checkpoint_mode
from deerflow.runtime.checkpoint_state import (
    CheckpointStateAccessor,
    build_state_mutation_graph,
)

pytestmark = pytest.mark.anyio


def _build_reply_graph(mode: str, checkpointer: Any):
    """One-node graph on the production thread schema for ``mode``."""

    async def _reply(state: dict[str, Any]) -> dict[str, Any]:
        n = len(state.get("messages") or [])
        return {"messages": [AIMessage(content=f"answer-{n}", id=f"a{n}")]}

    builder = StateGraph(get_thread_state_schema(mode))
    builder.add_node("reply", _reply)
    builder.set_entry_point("reply")
    builder.set_finish_point("reply")
    return builder.compile(checkpointer=checkpointer)


def _normalize_messages(values: dict[str, Any]) -> list[tuple[str, str, str]]:
    return [(message.type, message.content, message.id) for message in values.get("messages", [])]


async def _run_thread_lifecycle(mode: str, checkpointer: Any) -> dict[str, Any]:
    """Drive the full thread lifecycle and return normalized observations."""
    graph = _build_reply_graph(mode, checkpointer)
    accessor = CheckpointStateAccessor.bind(graph, checkpointer, mode=mode)
    config: dict[str, Any] = {"configurable": {"thread_id": "thread-parity"}}
    inject_checkpoint_mode(config, mode)

    # Multi-turn writes.
    for i in range(3):
        await graph.ainvoke({"messages": [HumanMessage(content=f"question-{i}", id=f"h{i}")]}, config)

    # Latest materialized state.
    latest = await accessor.aget(config)
    latest_messages = _normalize_messages(latest.values)

    # Bounded history: limit must hold and the walk must be newest-first.
    history = await accessor.ahistory(config, limit=2)
    history_shapes = [_normalize_messages(snapshot.values) for snapshot in history]

    # Branch from the first checkpoint (regenerate flow): the fork inherits
    # the pre-branch state, then new writes append on top.
    first_checkpoint_id = history[-1].config["configurable"]["checkpoint_id"]
    branch_config: dict[str, Any] = {"configurable": {"thread_id": "thread-parity", "checkpoint_ns": "", "checkpoint_id": first_checkpoint_id}}
    inject_checkpoint_mode(branch_config, mode)
    await accessor.aupdate(branch_config, {"messages": [HumanMessage(content="retry", id="h-retry")]}, as_node="reply")
    branched = await accessor.aget(branch_config)
    branch_messages = _normalize_messages(branched.values)

    # Compaction-style wholesale write through the mutation graph: replace
    # the message list with an Overwrite, no node scheduling.
    mutation_graph = build_state_mutation_graph("compact", mode, get_thread_state_schema(mode))
    mutation_accessor = CheckpointStateAccessor.bind(mutation_graph, checkpointer, mode=mode)
    compacted_messages = [HumanMessage(content="summary so far", id="h-summary")]
    await mutation_accessor.aupdate(config, {"messages": Overwrite(compacted_messages)})
    compacted = await accessor.aget(config)
    compacted_messages_seen = _normalize_messages(compacted.values)

    # The thread keeps working on top of the compacted state.
    await graph.ainvoke({"messages": [HumanMessage(content="after-compact", id="h3b")]}, config)
    resumed = await accessor.aget(config)
    resumed_messages = _normalize_messages(resumed.values)

    return {
        "latest": latest_messages,
        "history": history_shapes,
        "branch": branch_messages,
        "compacted": compacted_messages_seen,
        "resumed": resumed_messages,
    }


async def test_thread_lifecycle_parity_memory_saver() -> None:
    full = await _run_thread_lifecycle("full", InMemorySaver())
    delta = await _run_thread_lifecycle("delta", InMemorySaver())
    assert full == delta


async def test_thread_lifecycle_parity_sqlite_saver(tmp_path) -> None:
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "full.sqlite3")) as saver:
        await saver.setup()
        full = await _run_thread_lifecycle("full", saver)
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "delta.sqlite3")) as saver:
        await saver.setup()
        delta = await _run_thread_lifecycle("delta", saver)
    assert full == delta


async def test_delta_thread_avoids_per_step_full_message_blobs(tmp_path) -> None:
    """Storage-level guard: in delta mode the per-step checkpoints must not
    carry a serialized ``messages`` blob (the channel persists as incremental
    writes plus rare snapshots); full mode re-serializes the whole list into
    every checkpoint, which is exactly the O(N^2) growth delta mode removes."""

    async def _blob_checkpoint_counts(mode: str, db_name: str) -> tuple[int, int]:
        async with AsyncSqliteSaver.from_conn_string(str(tmp_path / db_name)) as saver:
            await saver.setup()
            graph = _build_reply_graph(mode, saver)
            config: dict[str, Any] = {"configurable": {"thread_id": f"thread-{mode}"}}
            inject_checkpoint_mode(config, mode)
            for i in range(4):
                await graph.ainvoke({"messages": [HumanMessage(content=f"q{i}", id=f"h{i}")]}, config)

            total = 0
            with_messages_blob = 0
            async for checkpoint_tuple in saver.alist(config):
                total += 1
                if "messages" in checkpoint_tuple.checkpoint.get("channel_values", {}):
                    with_messages_blob += 1
            return total, with_messages_blob

    delta_total, delta_blobs = await _blob_checkpoint_counts("delta", "delta.sqlite3")
    full_total, full_blobs = await _blob_checkpoint_counts("full", "full.sqlite3")

    assert delta_total > 0 and full_total > 0
    # Delta: at most the periodic snapshot carries a blob; full: every
    # message-writing checkpoint does.
    assert delta_blobs <= 1, f"delta checkpoints re-serialized messages: {delta_blobs}/{delta_total}"
    assert full_blobs >= 4, f"full mode should blob messages per step: {full_blobs}/{full_total}"
