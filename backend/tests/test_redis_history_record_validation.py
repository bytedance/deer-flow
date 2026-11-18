"""Malformed cache write records must rebuild from authoritative checkpoints."""

from types import SimpleNamespace
from typing import Annotated, TypedDict
from unittest.mock import AsyncMock

import pytest
from langgraph.channels import DeltaChannel
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import StateGraph

from deerflow.runtime.checkpoint_cache import redis as redis_cache
from deerflow.runtime.checkpoint_cache.memory import MemoryCheckpointHistoryCache
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


def fail_warning(*args, **kwargs):
    raise RuntimeError("handler failed")


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_write", BAD_WRITES, ids=["null", "number", "string", "mapping", "empty", "short", "long", "task-type", "channel-type"])
@pytest.mark.parametrize("warning_handler_fails", [False, True], ids=["logging", "raising-handler"])
async def test_bad_write_rebuilds_snapshot_and_replaces_corrupt_cache(monkeypatch, bad_write, warning_handler_fails):
    if warning_handler_fails:
        monkeypatch.setattr(redis_cache.logger, "warning", fail_warning)
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


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", [{}, None, [], {"writes": None}, {"writes": ()}] + [{"writes": [bad]} for bad in BAD_WRITES])
async def test_invalid_ingest_skips_only_bad_entry(monkeypatch, entry):
    transport = RedisTransport()
    monkeypatch.setattr(redis_cache, "_create_client", lambda *args, **kwargs: transport)
    cache = redis_cache.RedisCheckpointHistoryCache("redis://unused", serde=JsonPlusSerializer(), ttl_seconds=60)
    try:
        await cache.aset_many({"before": {"writes": []}, "bad": entry, "after": {"writes": [("task", "items", ["saved"])]}})
        assert set(transport.values) == {"before", "after"}
        assert set(await cache.aget_many(["before", "after"])) == {"before", "after"}
        assert cache.stats().write_serialization_failures == 0
    finally:
        await cache.aclose()


@pytest.mark.asyncio
async def test_invalid_ingest_logging_cannot_discard_valid_neighbor(monkeypatch):
    transport = RedisTransport()
    monkeypatch.setattr(redis_cache, "_create_client", lambda *args, **kwargs: transport)

    monkeypatch.setattr(redis_cache.logger, "warning", fail_warning)
    cache = redis_cache.RedisCheckpointHistoryCache("redis://unused", serde=JsonPlusSerializer(), ttl_seconds=60)
    try:
        await cache.aset_many({"bad": {"writes": [None]}, "good": {"writes": []}})
        assert set(transport.values) == {"good"}
    finally:
        await cache.aclose()


@pytest.mark.asyncio
async def test_serialization_logging_cannot_discard_valid_neighbors(monkeypatch):
    transport = RedisTransport()
    monkeypatch.setattr(redis_cache, "_create_client", lambda *args, **kwargs: transport)
    monkeypatch.setattr(redis_cache.logger, "warning", fail_warning)
    execute = AsyncMock(wraps=transport.execute)
    monkeypatch.setattr(transport, "execute", execute)
    cache = redis_cache.RedisCheckpointHistoryCache("redis://unused", serde=JsonPlusSerializer(), ttl_seconds=60)
    try:
        await cache.aset_many({"before": {"writes": []}, "bad": {"writes": [], "seed": object()}, "after": {"writes": [("task", "items", ["saved"])]}})

        assert set(transport.values) == {"before", "after"}
        assert set(await cache.aget_many(["before", "after"])) == {"before", "after"}
        assert cache.stats().write_serialization_failures == 1
        execute.assert_awaited_once()
    finally:
        await cache.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["read", "write", "purge"])
async def test_warning_handler_failure_preserves_redis_error_fallback(monkeypatch, operation):
    from redis.exceptions import RedisError

    transport = RedisTransport()
    monkeypatch.setattr(redis_cache, "_create_client", lambda *args, **kwargs: transport)
    monkeypatch.setattr(redis_cache.logger, "warning", fail_warning)
    cache = redis_cache.RedisCheckpointHistoryCache("redis://unused", serde=JsonPlusSerializer(), ttl_seconds=60)
    error = RedisError("Redis unavailable")
    try:
        if operation == "read":
            monkeypatch.setattr(transport, "mget", AsyncMock(side_effect=error))
            assert await cache.aget_many(["one", "two"]) == {}
            assert cache.stats().misses == 2
        elif operation == "write":
            monkeypatch.setattr(transport, "execute", AsyncMock(side_effect=error))
            await cache.aset_many({"good": {"writes": []}})
        else:
            transport.connection_pool = SimpleNamespace(get_encoder=lambda: SimpleNamespace(encode=lambda key: key.encode()))
            transport.scan = AsyncMock(side_effect=error)
            await cache.adelete_thread("logging", "thread")
    finally:
        await cache.aclose()


def build_history_graph(saver, steps=4):
    builder = StateGraph(State)
    for index in range(steps):
        builder.add_node(str(index), lambda state, index=index: {"items": [f"saved{index}"]})
        if index:
            builder.add_edge(str(index - 1), str(index))
    builder.set_entry_point("0")
    builder.set_finish_point(str(steps - 1))
    return builder.compile(checkpointer=saver)


@pytest.mark.asyncio
@pytest.mark.parametrize("async_read", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("location", ["target", "ancestor"])
@pytest.mark.parametrize("record_type", [tuple, list], ids=["tuple", "list"])
async def test_foreign_channel_rebuilds_complete_history(async_read, location, record_type):
    cache = MemoryCheckpointHistoryCache()
    inner = InMemorySaver()
    saver = CachedHistorySaver(inner, cache, key_prefix="channel-validation")
    graph = build_history_graph(saver)
    accessor = CheckpointStateAccessor.bind(graph, saver, mode="delta")
    authority = CheckpointStateAccessor.bind(build_history_graph(inner), inner, mode="delta")
    config = {"configurable": {"thread_id": "foreign-channel"}}
    try:
        # The memory backend supports sync reads even in a running loop. Keep
        # both accessor entry points covered without a transport-only assertion.
        graph.invoke({"items": ["input"]}, config)
        target = inner.get_tuple(config)
        poisoned = target
        if location == "ancestor":
            selected = None
            for candidate in inner.list(config):
                if candidate.parent_config is None:
                    continue
                parent = inner.get_tuple(candidate.parent_config)
                if parent is not None and "items" not in (parent.checkpoint.get("channel_values") or {}):
                    selected = candidate, parent
                    break
            assert selected is not None, "fixture must reach recursive non-snapshot composition"
            target, poisoned = selected
        expected = authority.get(target.config).values
        assert expected["items"]
        before = inner.get_delta_channel_history(config=target.config, channels=["items"])
        cache.delete_thread("channel-validation", "foreign-channel")
        key = saver._key(poisoned, "items")
        bad = {"writes": [("task", "items", ["INJECTED"]), record_type(("task", "foreign-channel", ["FOREIGN"]))]}
        cache.set_many({key: bad})
        if location == "ancestor":
            assert cache.get_many([saver._key(target, "items")]) == {}

        observed = await accessor.aget(target.config) if async_read else accessor.get(target.config)
        assert observed.values == expected
        assert cache.get_many([key])[key] != bad
        assert inner.get_delta_channel_history(config=target.config, channels=["items"]) == before
        misses = cache.stats().misses
        observed = await accessor.aget(target.config) if async_read else accessor.get(target.config)
        assert observed.values == expected
        assert cache.stats().misses == misses
    finally:
        await cache.aclose()


def fold_text(state, writes):
    return state + "".join(writes)


class StringState(TypedDict):
    items: Annotated[str, DeltaChannel(fold_text, snapshot_frequency=100)]


@pytest.mark.asyncio
async def test_plain_string_seed_remains_a_warm_valid_state(monkeypatch):
    transport = RedisTransport()
    monkeypatch.setattr(redis_cache, "_create_client", lambda *args, **kwargs: transport)
    cache = redis_cache.RedisCheckpointHistoryCache("redis://unused", serde=JsonPlusSerializer(), ttl_seconds=60)
    inner = InMemorySaver()
    saver = CachedHistorySaver(inner, cache, key_prefix="string-seed")
    builder = StateGraph(StringState)
    builder.add_node("one", lambda state: {"items": "saved"})
    builder.set_entry_point("one")
    builder.set_finish_point("one")
    graph = builder.compile(checkpointer=saver)
    accessor = CheckpointStateAccessor.bind(graph, saver, mode="delta")
    config = {"configurable": {"thread_id": "string-seed"}}
    try:
        await graph.ainvoke({"items": "input"}, config)
        expected = (await accessor.aget(config)).values
        assert expected == {"items": "inputsaved"}
        target = await inner.aget_tuple(config)
        key = saver._key(target, "items")
        await cache.aset_many({key: {"writes": [], "seed": "inputsaved"}})
        misses = cache.stats().misses
        for _ in range(2):
            assert (await accessor.aget(config)).values == expected
        assert cache.stats().misses == misses
    finally:
        await cache.aclose()
