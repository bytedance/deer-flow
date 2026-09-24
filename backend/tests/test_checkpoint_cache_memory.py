"""Memory LRU backend for the checkpoint history cache."""

import pytest

from deerflow.runtime.checkpoint_cache.base import (
    CACHE_FORMAT_VERSION,
    CheckpointCacheStats,
    make_history_key,
    thread_key_stem,
)
from deerflow.runtime.checkpoint_cache.memory import MemoryCheckpointHistoryCache


def _entry(tag: str) -> dict:
    return {"writes": [("task-1", "messages", tag)], "seed": f"seed-{tag}"}


def test_make_history_key_is_stable_and_scoped():
    k1 = make_history_key("ckpt-hist:v1:db0", "t1", "", "c1", "messages")
    k2 = make_history_key("ckpt-hist:v1:db0", "t1", "", "c1", "messages")
    assert k1 == k2
    assert k1.startswith("ckpt-hist:v1:db0:t1:")
    # ns / checkpoint / channel each change the key
    assert k1 != make_history_key("ckpt-hist:v1:db0", "t1", "sub", "c1", "messages")
    assert k1 != make_history_key("ckpt-hist:v1:db0", "t1", "", "c2", "messages")
    assert k1 != make_history_key("ckpt-hist:v1:db0", "t1", "", "c1", "todos")
    assert k1 != make_history_key("ckpt-hist:v1:db9", "t1", "", "c1", "messages")
    assert CACHE_FORMAT_VERSION == 1


def test_get_many_miss_then_hit():
    cache = MemoryCheckpointHistoryCache(max_entries=4)
    assert cache.get_many(["a"]) == {}
    assert cache.stats().misses == 1
    cache.set_many({"a": _entry("x")})
    hit = cache.get_many(["a"])
    assert hit["a"]["writes"] == [("task-1", "messages", "x")]
    assert hit["a"]["seed"] == "seed-x"
    assert cache.stats().hits == 1


def test_entry_without_seed_roundtrips_without_seed_key():
    cache = MemoryCheckpointHistoryCache(max_entries=4)
    cache.set_many({"a": {"writes": []}})
    hit = cache.get_many(["a"])
    assert hit["a"] == {"writes": []}
    assert "seed" not in hit["a"]


def test_copy_on_read_returns_fresh_writes_list():
    cache = MemoryCheckpointHistoryCache(max_entries=4)
    cache.set_many({"a": _entry("x")})
    first = cache.get_many(["a"])["a"]
    first["writes"].append(("task-2", "messages", "MUTATION"))
    second = cache.get_many(["a"])["a"]
    assert second["writes"] == [("task-1", "messages", "x")]


def test_caller_mutation_after_set_does_not_leak():
    cache = MemoryCheckpointHistoryCache(max_entries=4)
    entry = _entry("x")
    cache.set_many({"a": entry})
    entry["writes"].append(("task-2", "messages", "MUTATION"))
    assert cache.get_many(["a"])["a"]["writes"] == [("task-1", "messages", "x")]


def test_lru_evicts_oldest_and_counts():
    cache = MemoryCheckpointHistoryCache(max_entries=2)
    cache.set_many({"a": _entry("a"), "b": _entry("b")})
    cache.get_many(["a"])  # refresh a
    cache.set_many({"c": _entry("c")})  # evicts b
    assert cache.get_many(["b"]) == {}
    assert cache.get_many(["a"]) != {}
    assert cache.stats().evictions == 1
    assert cache.stats().entries == 2


def test_zero_max_entries_disables():
    cache = MemoryCheckpointHistoryCache(max_entries=0)
    assert cache.enabled is False
    cache.set_many({"a": _entry("x")})
    assert cache.get_many(["a"]) == {}
    assert cache.stats().entries == 0


def test_delete_thread_purges_only_that_thread():
    cache = MemoryCheckpointHistoryCache(max_entries=16)
    prefix = "ckpt-hist:v1:db0"
    t1_keys = [make_history_key(prefix, "t1", "", f"c{i}", "messages") for i in range(3)]
    t2_key = make_history_key(prefix, "t2", "", "c0", "messages")
    # A thread_id that is a prefix of another must not over-match: the stem
    # ends with ':' so "t1" never matches "t10"'s keys.
    t10_key = make_history_key(prefix, "t10", "", "c0", "messages")
    cache.set_many({k: _entry(k) for k in [*t1_keys, t2_key, t10_key]})

    cache.delete_thread(prefix, "t1")

    assert cache.stats().entries == 2
    assert all(cache.get_many([k]) == {} for k in t1_keys)
    assert cache.get_many([t2_key]) != {}
    assert cache.get_many([t10_key]) != {}


@pytest.mark.anyio
async def test_adelete_thread_matches_sync():
    cache = MemoryCheckpointHistoryCache(max_entries=4)
    prefix = "ckpt-hist:v1:db0"
    key = make_history_key(prefix, "t1", "", "c0", "messages")
    await cache.aset_many({key: _entry("x")})
    await cache.adelete_thread(prefix, "t1")
    assert cache.get_many([key]) == {}


def test_thread_key_stem_matches_make_history_key_layout():
    key = make_history_key("p", "t1", "ns", "c1", "messages")
    assert key.startswith(thread_key_stem("p", "t1"))
    assert not key.startswith(thread_key_stem("p", "t"))


@pytest.mark.anyio
async def test_async_protocol_matches_sync():
    cache = MemoryCheckpointHistoryCache(max_entries=4)
    await cache.aset_many({"a": _entry("x")})
    hit = await cache.aget_many(["a"])
    assert hit["a"]["seed"] == "seed-x"
    stats = cache.stats()
    assert isinstance(stats, CheckpointCacheStats)
    assert stats.as_dict()["hits"] == 1
    await cache.aclose()
    assert cache.get_many(["a"]) == {}
