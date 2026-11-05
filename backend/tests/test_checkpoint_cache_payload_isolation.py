"""Returned checkpoint snapshots must never mutate cached history payloads."""

from copy import deepcopy
from typing import Annotated, TypedDict

import pytest
from langgraph.channels import DeltaChannel
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import StateGraph

from deerflow.runtime.checkpoint_cache.memory import MemoryCheckpointHistoryCache
from deerflow.runtime.checkpoint_state import CheckpointStateAccessor
from deerflow.runtime.checkpointer.cached_saver import CachedHistorySaver


def _fold(state, writes):
    result = list(state)
    for batch in writes:
        result.extend(batch)
    return result


def _stack(frequency, enabled):
    class State(TypedDict):
        items: Annotated[list[dict], DeltaChannel(_fold, snapshot_frequency=frequency)]

    inner = InMemorySaver()
    cache = MemoryCheckpointHistoryCache(max_entries=32 if enabled else 0)
    saver = CachedHistorySaver(inner, cache, key_prefix="payload-isolation")
    builder = StateGraph(State)
    for step in range(4):
        builder.add_node(str(step), lambda state: {"items": [{"nested": {"value": "saved"}}]})
        if step:
            builder.add_edge(str(step - 1), str(step))
    builder.set_entry_point("0")
    builder.set_finish_point("3")
    graph = builder.compile(checkpointer=saver)
    return graph, CheckpointStateAccessor.bind(graph, saver, mode="delta"), cache


def _mutate(snapshot):
    original = deepcopy(snapshot.values)
    snapshot.values["items"][0]["nested"]["value"] = "tampered"
    snapshot.values["items"].append({"nested": {"value": "injected"}})
    return original


@pytest.mark.parametrize("frequency", [2, 100], ids=["snapshot-seed", "pending-writes"])
@pytest.mark.parametrize("enabled", [True, False], ids=["cached", "uncached-control"])
def test_sync_graph_snapshots_are_isolated(frequency, enabled):
    graph, accessor, cache = _stack(frequency, enabled)
    config = {"configurable": {"thread_id": "sync-payload-isolation"}}
    graph.invoke({"items": [{"nested": {"value": "input"}}]}, config)
    history = accessor.history(config)
    checked = 0
    for checkpoint in history:
        snapshot = accessor.get(checkpoint.config)
        if not snapshot.values.get("items"):
            continue
        original = _mutate(snapshot)
        assert accessor.get(checkpoint.config).values == original
        checked += 1
    assert checked >= 4
    assert cache.stats().hits > 0 if enabled else cache.stats().entries == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("frequency", [2, 100], ids=["snapshot-seed", "pending-writes"])
@pytest.mark.parametrize("enabled", [True, False], ids=["cached", "uncached-control"])
async def test_async_graph_snapshots_are_isolated(frequency, enabled):
    graph, accessor, cache = _stack(frequency, enabled)
    config = {"configurable": {"thread_id": "async-payload-isolation"}}
    await graph.ainvoke({"items": [{"nested": {"value": "input"}}]}, config)
    history = await accessor.ahistory(config)
    checked = 0
    for checkpoint in history:
        snapshot = await accessor.aget(checkpoint.config)
        if not snapshot.values.get("items"):
            continue
        original = _mutate(snapshot)
        assert (await accessor.aget(checkpoint.config)).values == original
        checked += 1
    assert checked >= 4
    assert cache.stats().hits > 0 if enabled else cache.stats().entries == 0


@pytest.mark.parametrize("direction", ["ingest", "read"])
def test_cache_copies_nested_write_payloads_and_snapshot_seeds(direction):
    from langchain_core.messages import HumanMessage
    from langgraph.checkpoint.serde.types import _DeltaSnapshot

    cache = MemoryCheckpointHistoryCache()
    seed = _DeltaSnapshot([HumanMessage(content="seed", id="seed", additional_kwargs={"nested": ["original"]})])
    entry = {"seed": seed, "writes": [("task", "messages", [HumanMessage(content="write", id="write", additional_kwargs={"nested": ["original"]})])]}
    original = deepcopy(entry)
    cache.set_many({"key": entry})
    exposed = entry if direction == "ingest" else cache.get_many(["key"])["key"]
    exposed["seed"].value[0].additional_kwargs["nested"].append("corrupted")
    exposed["writes"][0][2][0].content = "corrupted"
    assert cache.get_many(["key"])["key"] == original


def test_payload_copying_runs_outside_registry_lock():
    cache = MemoryCheckpointHistoryCache()
    copies = []

    class Probe:
        def __deepcopy__(self, memo):
            assert cache._lock.acquire(blocking=False), "copy callback ran under the cache lock"
            cache._lock.release()
            copies.append(True)
            return Probe()

    cache.set_many({"key": {"writes": [("task", "channel", Probe())]}})
    cache.get_many(["key"])
    assert len(copies) == 2
