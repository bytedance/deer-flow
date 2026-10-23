"""Malformed cache write records must rebuild from authoritative checkpoints."""

from typing import Annotated, TypedDict

import pytest
from langgraph.channels import DeltaChannel
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import StateGraph

from deerflow.runtime.checkpoint_cache import redis as redis_cache
from deerflow.runtime.checkpoint_state import CheckpointStateAccessor
from deerflow.runtime.checkpointer.cached_saver import CachedHistorySaver


class RedisTransport:
    """Only the Redis transport is replaced; serialization and graph reads are real."""

    def __init__(self):
        self.values = {}

    async def mget(self, keys):
        return [self.values.get(key) for key in keys]

    def pipeline(self, transaction=False):
        return self

    def set(self, key, value, ex=None):
        self.values[key] = value
        return self

    async def execute(self):
        return []

    async def aclose(self):
        pass


def fold(state, writes):
    result = list(state)
    for batch in writes:
        result.extend(batch)
    return result


class State(TypedDict):
    items: Annotated[list[str], DeltaChannel(fold, snapshot_frequency=100)]


BAD_WRITES = [None, 17, "abc", {"task": "x"}, (), ("task", "items"), ("task", "items", [], "extra"), (17, "items", []), ("task", 17, [])]


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_write", BAD_WRITES, ids=["null", "number", "string", "mapping", "empty", "short", "long", "task-type", "channel-type"])
async def test_bad_write_rebuilds_snapshot_and_replaces_corrupt_cache(monkeypatch, bad_write):
    transport = RedisTransport()
    monkeypatch.setattr(redis_cache, "_create_client", lambda *args, **kwargs: transport)
    serde = JsonPlusSerializer()
    cache = redis_cache.RedisCheckpointHistoryCache("redis://unused", serde=serde, ttl_seconds=60)
    inner = InMemorySaver()
    saver = CachedHistorySaver(inner, cache, key_prefix="record-validation")
    builder = StateGraph(State)
    builder.add_node("one", lambda state: {"items": ["saved"]})
    builder.set_entry_point("one")
    builder.set_finish_point("one")
    graph = builder.compile(checkpointer=saver)
    accessor = CheckpointStateAccessor.bind(graph, saver, mode="delta")
    config = {"configurable": {"thread_id": "invalid-record"}}
    try:
        await graph.ainvoke({"items": ["input"]}, config)
        expected = (await accessor.aget(config)).values
        assert expected == {"items": ["input", "saved"]}
        target = await inner.aget_tuple(config)
        key = saver._key(target, "items")
        # Keep a plausible prefix too: accepting only part of a corrupt entry
        # would inject this uncommitted value into an otherwise successful read.
        tag, payload = serde.dumps_typed({"writes": [("task", "items", ["injected"]), bad_write]})
        corrupted = tag.encode() + b"\x00" + payload
        transport.values[key] = corrupted
        misses = cache.stats().misses

        assert (await accessor.aget(config)).values == expected
        assert cache.stats().misses > misses
        assert transport.values[key] != corrupted
        # The repaired cache is warm: reads stay correct without a new walk.
        misses = cache.stats().misses
        assert (await accessor.aget(config)).values == expected
        assert cache.stats().misses == misses
    finally:
        await cache.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("record", [("task", "items", ["saved"]), ["task", "items", ["saved"]]], ids=["tuple", "list"])
@pytest.mark.parametrize("include_corrupt", [False, True], ids=["valid-control", "corrupt-neighbor"])
async def test_valid_record_shapes_and_neighbor_entries_are_preserved(monkeypatch, record, include_corrupt):
    transport = RedisTransport()
    monkeypatch.setattr(redis_cache, "_create_client", lambda *args, **kwargs: transport)
    serde = JsonPlusSerializer()
    cache = redis_cache.RedisCheckpointHistoryCache("redis://unused", serde=serde, ttl_seconds=60)
    try:
        await cache.aset_many({"good": {"writes": [record]}, "empty": {"writes": [], "seed": None}})
        if include_corrupt:
            await cache.aset_many({"bad": {"writes": ["abc"]}})
        found = await cache.aget_many(["good", "bad", "empty"] if include_corrupt else ["good", "empty"])
        assert set(found) == {"good", "empty"}
        assert list(found["good"]["writes"][0]) == list(record)
        assert found["empty"] == {"writes": [], "seed": None}
        assert cache.stats().hits == 2
        assert cache.stats().misses == int(include_corrupt)
    finally:
        await cache.aclose()
