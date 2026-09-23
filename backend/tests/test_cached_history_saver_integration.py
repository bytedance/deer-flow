"""Behavioral integration tests for CachedHistorySaver on REAL LangGraph execution.

Unlike tests/test_cached_history_saver.py (fake saver, hand-built chains), these
tests drive compiled StateGraphs through pregel in delta mode
(``DeltaChannel(merge_message_writes, snapshot_frequency=2)``) and verify the
cache against a differential oracle: the identical scenario executed on a raw
``InMemorySaver`` in a fresh thread. Digests are (type, content, id) triples of
the materialized ``messages`` channel, so any history corruption shows up as a
digest mismatch.

Observed pregel call pattern on langgraph 1.2.9 (5-step linear graph, 7
checkpoints, snapshot cadence 2): one ``aget_delta_channel_history`` per run
start (empty-thread load), none for snapshot checkpoints, one per materialized
non-snapshot checkpoint on the raw saver. The cached saver pays the run-start
walk plus one cold fallback walk; every other materialization composes from a
parent snapshot seed or a cached parent history, and a second identical read
pass costs zero inner walks.
"""

from __future__ import annotations

from typing import Annotated, Any, TypedDict
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from langgraph.channels import DeltaChannel
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import StateGraph
from langgraph.types import Command, interrupt

from deerflow.agents.thread_state import merge_message_writes
from deerflow.runtime.checkpoint_cache.memory import MemoryCheckpointHistoryCache
from deerflow.runtime.checkpoint_state import CheckpointStateAccessor
from deerflow.runtime.checkpointer.cached_saver import CachedHistorySaver

STEPS = 5
SNAPSHOT_FREQUENCY = 2


class _CountingInMemorySaver(InMemorySaver):
    """InMemorySaver that counts full delta-history walks.

    Placed under ``CachedHistorySaver`` it records exactly the walks the cache
    could not serve; used bare it is the uncached oracle's walk counter.
    """

    def __init__(self) -> None:
        super().__init__()
        self.history_walks = 0

    def get_delta_channel_history(self, *, config: Any, channels: Any) -> Any:
        self.history_walks += 1
        return super().get_delta_channel_history(config=config, channels=channels)

    async def aget_delta_channel_history(self, *, config: Any, channels: Any) -> Any:
        self.history_walks += 1
        return await super().aget_delta_channel_history(config=config, channels=channels)


def _state_schema() -> type:
    class State(TypedDict):
        messages: Annotated[
            list[AnyMessage],
            DeltaChannel(merge_message_writes, snapshot_frequency=SNAPSHOT_FREQUENCY),
        ]

    return State


def _make_step_node(n: int) -> Any:
    def node(state: dict) -> dict:
        return {"messages": [AIMessage(content=f"step-{n}", id=f"ai-{n}")]}

    return node


def _build_graph(saver: Any, steps: int = STEPS) -> Any:
    builder = StateGraph(_state_schema())
    for i in range(steps):
        builder.add_node(f"step{i}", _make_step_node(i))
    builder.set_entry_point("step0")
    for i in range(steps - 1):
        builder.add_edge(f"step{i}", f"step{i + 1}")
    builder.set_finish_point(f"step{steps - 1}")
    return builder.compile(checkpointer=saver)


def _build_interrupt_graph(saver: Any) -> Any:
    """step0 -> step1 -> pause(interrupt) -> step2 -> step3."""

    def pause(state: dict) -> dict:
        answer = interrupt({"question": "continue?"})
        return {"messages": [AIMessage(content=f"resumed:{answer}", id="ai-resume")]}

    builder = StateGraph(_state_schema())
    builder.add_node("step0", _make_step_node(0))
    builder.add_node("step1", _make_step_node(1))
    builder.add_node("pause", pause)
    builder.add_node("step2", _make_step_node(2))
    builder.add_node("step3", _make_step_node(3))
    builder.set_entry_point("step0")
    builder.add_edge("step0", "step1")
    builder.add_edge("step1", "pause")
    builder.add_edge("pause", "step2")
    builder.add_edge("step2", "step3")
    builder.set_finish_point("step3")
    return builder.compile(checkpointer=saver)


def _config() -> dict[str, Any]:
    return {"configurable": {"thread_id": f"cache-itest-{uuid4().hex}"}}


def _input() -> dict[str, Any]:
    return {"messages": [HumanMessage(content="kickoff", id="h-0")]}


def _digest(values: dict[str, Any]) -> list[tuple[str, str, str | None]]:
    return [(m.type, m.content, m.id) for m in values["messages"]]


def _history_digests(snapshots: list[Any]) -> list[list[tuple[str, str, str | None]]]:
    return [_digest(s.values) for s in snapshots]


def _expected_final_digest(steps: int = STEPS) -> list[tuple[str, str, str | None]]:
    return [("human", "kickoff", "h-0"), *[("ai", f"step-{n}", f"ai-{n}") for n in range(steps)]]


def _make_cached_stack(max_entries: int = 128) -> tuple[_CountingInMemorySaver, CachedHistorySaver, Any, CheckpointStateAccessor]:
    inner = _CountingInMemorySaver()
    saver = CachedHistorySaver(inner, MemoryCheckpointHistoryCache(max_entries), key_prefix=f"itest-{uuid4().hex}")
    graph = _build_graph(saver)
    accessor = CheckpointStateAccessor.bind(graph, saver, mode="delta")
    return inner, saver, graph, accessor


def _make_oracle_stack() -> tuple[_CountingInMemorySaver, Any, CheckpointStateAccessor]:
    inner = _CountingInMemorySaver()
    graph = _build_graph(inner)
    accessor = CheckpointStateAccessor.bind(graph, inner, mode="delta")
    return inner, graph, accessor


@pytest.mark.anyio
async def test_sequential_run_composes_without_inner_walks() -> None:
    """A cached run must serve warm reads with strictly fewer inner history
    walks than the identical uncached run, composing histories instead."""
    inner, saver, graph, accessor = _make_cached_stack()
    config = _config()
    await graph.ainvoke(_input(), config)

    final = await accessor.aget(config)
    assert _digest(final.values) == _expected_final_digest()

    # Cold pass: materialize every checkpoint in the thread.
    cold = await accessor.ahistory(config)
    cold_walks = inner.history_walks

    # Warm pass: identical reads must be served entirely from the cache.
    warm = await accessor.ahistory(config)
    assert inner.history_walks == cold_walks, "warm re-read triggered an inner walk"
    assert _history_digests(warm) == _history_digests(cold)

    # Differential oracle: same run through the raw saver.
    oracle_inner, oracle_graph, oracle_accessor = _make_oracle_stack()
    oracle_config = _config()
    await oracle_graph.ainvoke(_input(), oracle_config)
    await oracle_accessor.aget(oracle_config)
    oracle_history = await oracle_accessor.ahistory(oracle_config)

    assert _history_digests(cold) == _history_digests(oracle_history)
    assert oracle_inner.history_walks > 0
    assert cold_walks < oracle_inner.history_walks
    assert saver.stats()["compose_hits"] > 0


@pytest.mark.anyio
async def test_cache_disabled_parity() -> None:
    """A zero-entry cache must behave exactly like the raw inner saver."""
    inner, saver, graph, accessor = _make_cached_stack(max_entries=0)
    config = _config()
    await graph.ainvoke(_input(), config)
    final = await accessor.aget(config)
    history = await accessor.ahistory(config)

    oracle_inner, oracle_graph, oracle_accessor = _make_oracle_stack()
    oracle_config = _config()
    await oracle_graph.ainvoke(_input(), oracle_config)
    oracle_final = await oracle_accessor.aget(oracle_config)
    oracle_history = await oracle_accessor.ahistory(oracle_config)

    assert _digest(final.values) == _expected_final_digest()
    assert _digest(final.values) == _digest(oracle_final.values)
    assert _history_digests(history) == _history_digests(oracle_history)
    assert saver.stats()["hits"] == 0


async def _run_branch_scenario(
    graph: Any,
    accessor: CheckpointStateAccessor,
    config: dict[str, Any],
    *,
    fork_next: str,
    as_node: str,
    branch_id: str,
) -> dict[tuple[str, ...], Any]:
    """Run to completion, fork at the checkpoint whose next node is
    ``fork_next``, then resume the branch to completion (the branch head is
    then the thread's latest checkpoint). Returns the original chain's
    snapshots keyed by their ``next`` tuple for pinned re-reads.

    ``fork_next`` must name a NON-snapshot checkpoint: on langgraph 1.2.9 a
    ``aupdate_state`` fork at a snapshot checkpoint silently drops the update
    (verified against a raw InMemorySaver - upstream behavior, not the cache).
    """
    await graph.ainvoke(_input(), config)
    history = await accessor.ahistory(config)
    by_next = {s.next: s for s in history}
    base = by_next[(fork_next,)]
    branch_config = await accessor.aupdate(
        base.config,
        {"messages": [AIMessage(content=branch_id, id=f"ai-{branch_id}")]},
        as_node=as_node,
    )
    await graph.ainvoke(None, branch_config)
    return by_next


@pytest.mark.anyio
async def test_branch_divergence_no_cross_contamination() -> None:
    """A forked branch and the original head must each materialize their own
    distinct history through the SAME cached saver."""
    inner, saver, graph, accessor = _make_cached_stack()
    config = _config()
    by_next = await _run_branch_scenario(graph, accessor, config, fork_next="step2", as_node="step2", branch_id="branch")

    # Oracle: identical branch scenario on the raw saver.
    oracle_inner, oracle_graph, oracle_accessor = _make_oracle_stack()
    oracle_config = _config()
    oracle_by_next = await _run_branch_scenario(oracle_graph, oracle_accessor, oracle_config, fork_next="step2", as_node="step2", branch_id="branch")

    # Branch head = thread's latest checkpoint after the forked resume.
    branch_head = await accessor.aget(config)
    oracle_branch_head = await oracle_accessor.aget(oracle_config)
    expected_branch = [
        ("human", "kickoff", "h-0"),
        ("ai", "step-0", "ai-0"),
        ("ai", "step-1", "ai-1"),
        ("ai", "branch", "ai-branch"),
        ("ai", "step-3", "ai-3"),
        ("ai", "step-4", "ai-4"),
    ]
    assert _digest(branch_head.values) == expected_branch
    assert _digest(branch_head.values) == _digest(oracle_branch_head.values)

    # The original chain still materializes its own un-branched history: the
    # snapshot head and a non-snapshot mid checkpoint (cache-exercising read).
    for next_key, expected_len in [((), 6), (("step4",), 5)]:
        reread_original = await accessor.aget(by_next[next_key].config)
        oracle_reread_original = await oracle_accessor.aget(oracle_by_next[next_key].config)
        assert _digest(reread_original.values) == _expected_final_digest()[:expected_len]
        assert _digest(reread_original.values) == _digest(oracle_reread_original.values)
        assert _digest(reread_original.values) != _digest(branch_head.values)


async def _run_interrupt_scenario(graph: Any, accessor: CheckpointStateAccessor, config: dict[str, Any]) -> None:
    result = await graph.ainvoke(_input(), config)
    assert "__interrupt__" in result
    await graph.ainvoke(Command(resume="yes"), config)


@pytest.mark.anyio
async def test_interrupt_resume_appended_head_writes() -> None:
    """Resume appends writes under the interrupted head checkpoint; the cached
    final state must equal the no-cache reference."""
    inner = _CountingInMemorySaver()
    saver = CachedHistorySaver(inner, MemoryCheckpointHistoryCache(128), key_prefix=f"itest-{uuid4().hex}")
    graph = _build_interrupt_graph(saver)
    accessor = CheckpointStateAccessor.bind(graph, saver, mode="delta")
    config = _config()
    await _run_interrupt_scenario(graph, accessor, config)

    oracle_inner = _CountingInMemorySaver()
    oracle_graph = _build_interrupt_graph(oracle_inner)
    oracle_accessor = CheckpointStateAccessor.bind(oracle_graph, oracle_inner, mode="delta")
    oracle_config = _config()
    await _run_interrupt_scenario(oracle_graph, oracle_accessor, oracle_config)

    final = await accessor.aget(config)
    oracle_final = await oracle_accessor.aget(oracle_config)
    expected = [
        ("human", "kickoff", "h-0"),
        ("ai", "step-0", "ai-0"),
        ("ai", "step-1", "ai-1"),
        ("ai", "resumed:yes", "ai-resume"),
        ("ai", "step-2", "ai-2"),
        ("ai", "step-3", "ai-3"),
    ]
    assert _digest(final.values) == expected
    assert _digest(final.values) == _digest(oracle_final.values)

    # Every checkpoint along the resumed thread matches the oracle, including
    # the interrupted head whose pending writes grew at resume time.
    history = await accessor.ahistory(config)
    oracle_history = await oracle_accessor.ahistory(oracle_config)
    assert _history_digests(history) == _history_digests(oracle_history)


@pytest.mark.anyio
async def test_eviction_only_costs_performance() -> None:
    """A 1-entry LRU thrashes on every read but must stay correct."""
    inner, saver, graph, accessor = _make_cached_stack(max_entries=1)
    config = _config()
    await graph.ainvoke(_input(), config)

    first_pass = await accessor.ahistory(config)
    second_pass = await accessor.ahistory(config)

    oracle_inner, oracle_graph, oracle_accessor = _make_oracle_stack()
    oracle_config = _config()
    await oracle_graph.ainvoke(_input(), oracle_config)
    oracle_history = await oracle_accessor.ahistory(oracle_config)

    assert _history_digests(first_pass) == _history_digests(oracle_history)
    assert _history_digests(second_pass) == _history_digests(oracle_history)
    assert saver.stats()["evictions"] > 0


@pytest.mark.anyio
async def test_rollback_supersede_does_not_pollute() -> None:
    """Re-running from an early checkpoint supersedes the head; the original
    head's cached history must remain intact and re-readable."""
    inner, saver, graph, accessor = _make_cached_stack()
    config = _config()
    by_next = await _run_branch_scenario(graph, accessor, config, fork_next="step0", as_node="step0", branch_id="rollback")

    oracle_inner, oracle_graph, oracle_accessor = _make_oracle_stack()
    oracle_config = _config()
    oracle_by_next = await _run_branch_scenario(oracle_graph, oracle_accessor, oracle_config, fork_next="step0", as_node="step0", branch_id="rollback")

    # New head equals the reference run's new head.
    new_head = await accessor.aget(config)
    oracle_new_head = await oracle_accessor.aget(oracle_config)
    expected_new_head = [
        ("human", "kickoff", "h-0"),
        ("ai", "rollback", "ai-rollback"),
        ("ai", "step-1", "ai-1"),
        ("ai", "step-2", "ai-2"),
        ("ai", "step-3", "ai-3"),
        ("ai", "step-4", "ai-4"),
    ]
    assert _digest(new_head.values) == expected_new_head
    assert _digest(new_head.values) == _digest(oracle_new_head.values)

    # Re-reading ORIGINAL chain checkpoints (pinned by checkpoint_id) returns
    # their own original histories - their cached entries predate the fork and
    # must be untouched by the superseding branch.
    for next_key, expected_len in [((), 6), (("step4",), 5), (("step2",), 3)]:
        reread = await accessor.aget(by_next[next_key].config)
        oracle_reread = await oracle_accessor.aget(oracle_by_next[next_key].config)
        assert _digest(reread.values) == _expected_final_digest()[:expected_len]
        assert _digest(reread.values) == _digest(oracle_reread.values)
