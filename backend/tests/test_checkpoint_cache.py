"""Behavioral suite for checkpoint history cache config, provider lifecycle, payload isolation, memory LRU, and Redis backend."""

import asyncio
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from queue import Queue
from typing import Annotated, Any, TypedDict
from unittest.mock import AsyncMock, Mock

import pytest
from langgraph.channels import DeltaChannel
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import StateGraph

from deerflow.config.app_config import AppConfig, set_app_config
from deerflow.config.database_config import CheckpointCacheConfig, DatabaseConfig
from deerflow.runtime.checkpoint_cache.base import (
    CACHE_FORMAT_VERSION,
    CheckpointCacheStats,
    make_history_key,
    thread_key_stem,
)
from deerflow.runtime.checkpoint_cache.memory import MemoryCheckpointHistoryCache
from deerflow.runtime.checkpoint_cache.provider import (
    checkpoint_cache_db_hash,
    checkpoint_cache_key_prefix,
    make_checkpoint_cache,
)
from deerflow.runtime.checkpoint_cache.redis import RedisCheckpointHistoryCache
from deerflow.runtime.checkpoint_mode import freeze_checkpoint_channel_mode
from deerflow.runtime.checkpoint_state import CheckpointStateAccessor
from deerflow.runtime.checkpointer.async_provider import make_checkpointer
from deerflow.runtime.checkpointer.cached_saver import CachedHistorySaver
from deerflow.runtime.checkpointer.provider import checkpointer_context, reset_checkpointer

# --- test_checkpoint_cache_config ---


def test_checkpoint_cache_defaults():
    cfg = DatabaseConfig()
    assert cfg.checkpoint_cache.type == "memory"
    assert cfg.checkpoint_cache.max_entries == 128
    assert cfg.checkpoint_cache.redis_url is None
    assert cfg.checkpoint_cache.ttl_seconds == 86400
    assert cfg.checkpoint_cache.key_prefix == ""


def test_checkpoint_cache_from_dict_redis():
    cfg = DatabaseConfig.model_validate(
        {
            "backend": "postgres",
            "postgres_url": "postgresql://u:p@h/db",
            "checkpoint_cache": {
                "type": "redis",
                "max_entries": 256,
                "redis_url": "redis://localhost:6379/3",
                "ttl_seconds": 3600,
                "key_prefix": "prod:",
            },
        }
    )
    assert cfg.checkpoint_cache.type == "redis"
    assert cfg.checkpoint_cache.max_entries == 256
    assert cfg.checkpoint_cache.redis_url == "redis://localhost:6379/3"
    assert cfg.checkpoint_cache.ttl_seconds == 3600
    assert cfg.checkpoint_cache.key_prefix == "prod:"


def test_checkpoint_cache_zero_max_entries_means_disabled():
    cfg = CheckpointCacheConfig(max_entries=0)
    assert cfg.max_entries == 0


def test_checkpoint_cache_rejects_negative_max_entries():
    import pydantic
    import pytest

    with pytest.raises(pydantic.ValidationError):
        CheckpointCacheConfig(max_entries=-1)


# --- test_checkpoint_cache_memory ---


def _memory_entry(tag: str) -> dict:
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
    assert CACHE_FORMAT_VERSION == 2


def test_get_many_miss_then_hit():
    cache = MemoryCheckpointHistoryCache(max_entries=4)
    assert cache.get_many(["a"]) == {}
    assert cache.stats().misses == 1
    cache.set_many({"a": _memory_entry("x")})
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
    cache.set_many({"a": _memory_entry("x")})
    first = cache.get_many(["a"])["a"]
    first["writes"].append(("task-2", "messages", "MUTATION"))
    second = cache.get_many(["a"])["a"]
    assert second["writes"] == [("task-1", "messages", "x")]


def test_caller_mutation_after_set_does_not_leak():
    cache = MemoryCheckpointHistoryCache(max_entries=4)
    entry = _memory_entry("x")
    cache.set_many({"a": entry})
    entry["writes"].append(("task-2", "messages", "MUTATION"))
    assert cache.get_many(["a"])["a"]["writes"] == [("task-1", "messages", "x")]


def test_lru_evicts_oldest_and_counts():
    cache = MemoryCheckpointHistoryCache(max_entries=2)
    cache.set_many({"a": _memory_entry("a"), "b": _memory_entry("b")})
    cache.get_many(["a"])  # refresh a
    cache.set_many({"c": _memory_entry("c")})  # evicts b
    assert cache.get_many(["b"]) == {}
    assert cache.get_many(["a"]) != {}
    assert cache.stats().evictions == 1
    assert cache.stats().entries == 2


def test_zero_max_entries_disables():
    cache = MemoryCheckpointHistoryCache(max_entries=0)
    assert cache.enabled is False
    cache.set_many({"a": _memory_entry("x")})
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
    cache.set_many({k: _memory_entry(k) for k in [*t1_keys, t2_key, t10_key]})

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
    await cache.aset_many({key: _memory_entry("x")})
    await cache.adelete_thread(prefix, "t1")
    assert cache.get_many([key]) == {}


def test_thread_key_stem_matches_make_history_key_layout():
    key = make_history_key("p", "t1", "ns", "c1", "messages")
    assert key.startswith(thread_key_stem("p", "t1"))
    assert not key.startswith(thread_key_stem("p", "t"))


@pytest.mark.anyio
async def test_async_protocol_matches_sync():
    cache = MemoryCheckpointHistoryCache(max_entries=4)
    await cache.aset_many({"a": _memory_entry("x")})
    hit = await cache.aget_many(["a"])
    assert hit["a"]["seed"] == "seed-x"
    stats = cache.stats()
    assert isinstance(stats, CheckpointCacheStats)
    assert stats.as_dict()["hits"] == 1
    await cache.aclose()
    assert cache.get_many(["a"]) == {}


# --- test_checkpoint_cache_memory_concurrency ---


@pytest.mark.parametrize("mutation", ["evict", "purge", "close"])
def test_lookup_survives_concurrent_removal(mutation):
    cache = MemoryCheckpointHistoryCache(max_entries=1)
    key = make_history_key("p", "t1", "", "c1", "messages")
    entry = {"writes": [("task", "messages", "original")], "seed": "seed"}
    cache.set_many({key: entry})
    looked_up = threading.Event()
    release_reader = threading.Event()
    writer_started = threading.Event()
    writer_finished = threading.Event()
    coordination = Queue()
    removal_reported = threading.Event()

    def report_removal():
        if not removal_reported.is_set():
            removal_reported.set()
            coordination.put("removed")

    class PausedLookup(OrderedDict):
        def get(self, lookup_key, default=None):
            value = super().get(lookup_key, default)
            if lookup_key == key:
                looked_up.set()
                assert release_reader.wait(5), "reader was not released"
            return value

        def __delitem__(self, deleted_key):
            super().__delitem__(deleted_key)
            if deleted_key == key:
                report_removal()

        def popitem(self, last=True):
            removed_key, value = super().popitem(last=last)
            if removed_key == key:
                report_removal()
            return removed_key, value

        def clear(self):
            contained_target = key in self
            super().clear()
            if contained_target:
                report_removal()

    class ObservedLock:
        """Report a contender before it blocks behind the paused reader."""

        def __init__(self):
            self._lock = threading.Lock()

        def __enter__(self):
            if self._lock.locked():
                coordination.put("writer_waiting")
            self._lock.acquire()
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            self._lock.release()

    # Pause at the actual lookup -> LRU promotion window, not before get_many.
    cache._data = PausedLookup(cache._data)
    cache._lock = ObservedLock()

    def remove():
        writer_started.set()
        try:
            if mutation == "evict":
                cache.set_many({"other": {"writes": []}})
            elif mutation == "purge":
                cache.delete_thread("p", "t1")
            else:
                asyncio.run(cache.aclose())
        finally:
            writer_finished.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        reader = pool.submit(cache.get_many, [key])
        try:
            assert looked_up.wait(5)
            writer = pool.submit(remove)
            assert writer_started.wait(5)
            # A serialized writer reports that it is waiting on the reader's
            # lock. On unfixed main it instead removes the key and reports that,
            # deterministically reproducing the get -> move_to_end race.
            assert coordination.get(timeout=5) == "writer_waiting"
        finally:
            release_reader.set()
        assert reader.result(timeout=5) == {key: entry}
        writer.result(timeout=5)
    assert cache.get_many([key]) == {}
    assert cache.stats().entries == int(mutation == "evict")


def test_parallel_read_write_keeps_capacity_and_accounting():
    cache = MemoryCheckpointHistoryCache(max_entries=4)
    start = threading.Barrier(8)

    def exercise(worker):
        start.wait(timeout=5)
        for n in range(200):
            key = f"{worker}:{n}"
            cache.set_many({key: {"writes": [("task", "messages", key)]}})
            result = cache.get_many([key])
            if key in result:
                assert result[key]["writes"] == [("task", "messages", key)]

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(exercise, range(8)))
    stats = cache.stats()
    assert stats.entries == 4
    assert stats.evictions == 8 * 200 - 4
    assert stats.hits + stats.misses == 8 * 200


# --- test_checkpoint_cache_payload_isolation ---


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


# --- test_checkpoint_cache_provider ---


def _provider_app_config(mode: str, cache: dict | None = None) -> AppConfig:
    database: dict = {"backend": "memory", "checkpoint_channel_mode": mode}
    if cache is not None:
        database["checkpoint_cache"] = cache
    return AppConfig.model_validate(
        {
            "sandbox": {"use": "deerflow.sandbox.local.provider:LocalSandboxProvider"},
            "database": database,
        }
    )


@pytest.mark.anyio
async def test_delta_mode_wraps_with_cached_saver():
    set_app_config(_provider_app_config("delta"))
    freeze_checkpoint_channel_mode("delta")
    async with make_checkpointer() as saver:
        assert isinstance(saver, CachedHistorySaver)
        assert saver.stats()["entries"] == 0


@pytest.mark.anyio
async def test_full_mode_yields_raw_saver():
    set_app_config(_provider_app_config("full"))
    freeze_checkpoint_channel_mode("full")
    async with make_checkpointer() as saver:
        assert not isinstance(saver, CachedHistorySaver)


@pytest.mark.anyio
async def test_zero_max_entries_disables_but_still_wraps():
    set_app_config(_provider_app_config("delta", {"max_entries": 0}))
    freeze_checkpoint_channel_mode("delta")
    async with make_checkpointer() as saver:
        assert isinstance(saver, CachedHistorySaver)
        # Disabled cache -> every history call is a full walk on the inner saver.
        assert saver._cache.enabled is False


def test_sync_delta_mode_wraps_memory():
    set_app_config(_provider_app_config("delta"))
    freeze_checkpoint_channel_mode("delta")
    reset_checkpointer()
    with checkpointer_context() as saver:
        assert isinstance(saver, CachedHistorySaver)


def test_sync_redis_cache_type_is_config_error():
    set_app_config(_provider_app_config("delta", {"type": "redis"}))
    freeze_checkpoint_channel_mode("delta")
    reset_checkpointer()
    with pytest.raises(ValueError, match="redis"):
        with checkpointer_context():
            pass


def test_sync_full_mode_unwrapped():
    set_app_config(_provider_app_config("full"))
    freeze_checkpoint_channel_mode("full")
    reset_checkpointer()
    with checkpointer_context() as saver:
        assert not isinstance(saver, CachedHistorySaver)


def test_sync_cache_recreated_when_key_prefix_changes():
    """The singleton must not outlive its namespace: a prefix change without
    a process restart leaves old-prefix entries unreachable and unpurgeable."""
    reset_checkpointer()
    set_app_config(_provider_app_config("delta", {"key_prefix": "ns-a"}))
    freeze_checkpoint_channel_mode("delta")
    with checkpointer_context() as saver:
        saver._cache.set_many({"ns-a:t1:x": {"writes": []}})
        first_cache = saver._cache
    # Same prefix: singleton is reused (warm across wrappers).
    with checkpointer_context() as saver:
        assert saver._cache is first_cache
        assert saver._cache.stats().entries == 1
    # Prefix change: fresh cache, stale namespace gone with the old instance.
    set_app_config(_provider_app_config("delta", {"key_prefix": "ns-b"}))
    with checkpointer_context() as saver:
        assert saver._cache is not first_cache
        assert saver._cache.stats().entries == 0
    reset_checkpointer()


# --- test_checkpoint_cache_redis ---


class _FakeEncoder:
    def encode(self, value: str) -> bytes:
        return value.encode()


class _FakeConnectionPool:
    def get_encoder(self) -> _FakeEncoder:
        return _FakeEncoder()


class _FakeRedis:
    """Minimal async redis stand-in: mget / set / pipeline / scan / unlink."""

    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}
        self.ttls: dict[str, int | None] = {}
        self.unlinked: list[tuple[str, ...]] = []
        self.connection_pool = _FakeConnectionPool()

    async def mget(self, keys: list[str]) -> list[bytes | None]:
        return [self.store.get(k) for k in keys]

    def set(self, key: str, value: bytes, ex: int | None = None) -> None:
        self.store[key] = value
        self.ttls[key] = ex

    async def scan(self, cursor: int = 0, match: str | None = None, count: int = 500) -> tuple[int, list[str]]:
        import fnmatch

        keys = sorted(self.store)
        batch = keys[cursor : cursor + count]
        if match is not None:
            batch = [k for k in batch if fnmatch.fnmatchcase(k, match)]
        next_cursor = cursor + count
        return (0 if next_cursor >= len(keys) else next_cursor), batch

    async def unlink(self, *keys: str) -> int:
        self.unlinked.append(tuple(keys))
        removed = 0
        for key in keys:
            removed += self.store.pop(key, None) is not None
        return removed

    def pipeline(self, transaction: bool = False) -> "_FakePipeline":
        return _FakePipeline(self)

    async def aclose(self) -> None:
        pass


class _FakePipeline:
    def __init__(self, client: _FakeRedis) -> None:
        self._client = client

    def set(self, key: str, value: bytes, ex: int | None = None) -> "_FakePipeline":
        self._client.set(key, value, ex=ex)
        return self

    async def execute(self) -> None:
        pass


class _FailingRedis(_FakeRedis):
    """Simulates a redis outage: every operation raises RedisError."""

    async def mget(self, keys: list[str]) -> list[bytes | None]:
        from redis.exceptions import RedisError

        raise RedisError("connection refused")

    async def scan(self, cursor: int = 0, match: str | None = None, count: int = 500) -> tuple[int, list[str]]:
        from redis.exceptions import RedisError

        raise RedisError("connection refused")

    def pipeline(self, transaction: bool = False) -> "_FakePipeline":
        from redis.exceptions import RedisError

        raise RedisError("connection refused")


def _make_cache(
    monkeypatch: pytest.MonkeyPatch,
    fake: _FakeRedis,
    ttl_seconds: int = 60,
    *,
    serde: Any | None = None,
    **kwargs: Any,
):
    import deerflow.runtime.checkpoint_cache.redis as redis_mod

    monkeypatch.setattr(redis_mod, "_create_client", lambda *a, **k: fake)
    return redis_mod.RedisCheckpointHistoryCache(
        "redis://unused",
        serde=serde if serde is not None else JsonPlusSerializer(),
        ttl_seconds=ttl_seconds,
        **kwargs,
    )


def _redis_entry(i: int) -> dict:
    # Real message-like payloads to prove serde fidelity beyond plain dicts.
    from langchain_core.messages import AIMessage

    return {"writes": [("task-1", "messages", AIMessage(content=f"m{i}", id=f"ai-{i}"))], "seed": [AIMessage(content="s", id="ai-s")]}


def _redis_app_config(database: dict) -> AppConfig:
    return AppConfig.model_validate(
        {
            "sandbox": {"use": "deerflow.sandbox.local.provider:LocalSandboxProvider"},
            "database": database,
        }
    )


@pytest.mark.anyio
async def test_redis_roundtrip_preserves_types(monkeypatch: pytest.MonkeyPatch):
    fake = _FakeRedis()
    cache = _make_cache(monkeypatch, fake)
    await cache.aset_many({"k1": _redis_entry(1), "k2": {"writes": []}})
    hit = await cache.aget_many(["k1", "k2", "k3"])
    assert set(hit) == {"k1", "k2"}
    msg = hit["k1"]["writes"][0][2]
    assert msg.content == "m1" and msg.id == "ai-1" and msg.type == "ai"
    assert "seed" not in hit["k2"]
    assert cache.stats().hits == 2 and cache.stats().misses == 1


@pytest.mark.anyio
async def test_redis_keys_land_verbatim_and_ttl_set(monkeypatch: pytest.MonkeyPatch):
    fake = _FakeRedis()
    cache = _make_cache(monkeypatch, fake)
    await cache.aset_many({"k1": _redis_entry(1)})
    assert list(fake.store) == ["k1"]
    assert fake.ttls["k1"] == 60


@pytest.mark.anyio
async def test_redis_outage_degrades_to_all_miss(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture):
    fake = _FailingRedis()
    cache = _make_cache(monkeypatch, fake)
    with caplog.at_level("WARNING"):
        assert await cache.aget_many(["k1", "k2"]) == {}
    assert cache.stats().misses == 2 and cache.stats().hits == 0
    assert "mget failed" in caplog.text


@pytest.mark.anyio
async def test_redis_outage_skips_write(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture):
    fake = _FailingRedis()
    cache = _make_cache(monkeypatch, fake)
    with caplog.at_level("WARNING"):
        await cache.aset_many({"k1": _redis_entry(1)})  # must not raise
    assert fake.store == {}
    assert "write failed" in caplog.text


@pytest.mark.anyio
async def test_redis_serialization_failure_preserves_neighbor_writes(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    class _SelectiveFailingSerde:
        def dumps_typed(self, entry: dict) -> tuple[str, bytes]:
            if entry.get("bad"):
                raise TypeError("sensitive serializer detail")
            return "json", b"encoded"

    fake = _FakeRedis()
    cache = _make_cache(monkeypatch, fake, serde=_SelectiveFailingSerde())
    with caplog.at_level("WARNING"):
        await cache.aset_many(
            {
                "before": {"writes": []},
                "broken": {"writes": [], "bad": True},
                "after": {"writes": []},
            }
        )

    assert fake.store == {
        "before": b"json\x00encoded",
        "after": b"json\x00encoded",
    }
    assert fake.ttls == {"before": 60, "after": 60}
    assert "broken" in caplog.text
    assert "TypeError" in caplog.text
    assert "sensitive serializer detail" not in caplog.text
    assert cache.stats().write_serialization_failures == 1
    assert cache.stats().as_dict()["write_serialization_failures"] == 1


@pytest.mark.anyio
async def test_zero_ttl_disables_expiry_explicitly(monkeypatch: pytest.MonkeyPatch):
    fake = _FakeRedis()
    cache = _make_cache(monkeypatch, fake, ttl_seconds=0)
    await cache.aset_many({"k1": _redis_entry(1)})
    assert cache._ttl is None
    assert fake.ttls["k1"] is None  # SET without EX: redis maxmemory policy only


@pytest.mark.anyio
async def test_adelete_thread_purges_matching_keys_only(monkeypatch: pytest.MonkeyPatch):
    fake = _FakeRedis()
    cache = _make_cache(monkeypatch, fake)
    prefix = f"ckpt-hist:v{CACHE_FORMAT_VERSION}:db0"
    await cache.aset_many(
        {
            f"{prefix}:t1:aaa": _redis_entry(1),
            f"{prefix}:t1:bbb": _redis_entry(2),
            f"{prefix}:t10:ccc": _redis_entry(3),  # 't1' stem must not over-match 't10'
            f"{prefix}:t2:ddd": _redis_entry(4),
        }
    )

    await cache.adelete_thread(prefix, "t1")

    assert sorted(fake.store) == [f"{prefix}:t10:ccc", f"{prefix}:t2:ddd"]
    assert fake.unlinked  # UNLINK, not DEL: non-blocking on big histories


@pytest.mark.anyio
async def test_adelete_thread_outage_degrades_without_raising(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture):
    fake = _FailingRedis()
    cache = _make_cache(monkeypatch, fake)
    with caplog.at_level("WARNING"):
        await cache.adelete_thread("p", "t1")  # must not raise
    assert "thread purge failed" in caplog.text


@pytest.mark.anyio
@pytest.mark.parametrize("key_prefix", ["", "tenant-history"])
async def test_thread_delete_after_redis_cache_upgrade(monkeypatch: pytest.MonkeyPatch, key_prefix: str) -> None:
    config = _redis_app_config(
        {
            "backend": "sqlite",
            "checkpoint_channel_mode": "delta",
            "checkpoint_cache": {"type": "redis", "ttl_seconds": 0, "key_prefix": key_prefix},
        }
    )
    fake = _FakeRedis()
    cache = _make_cache(monkeypatch, fake, ttl_seconds=0)

    async with make_checkpointer(config) as saver:
        thread = {"configurable": {"thread_id": "t1", "checkpoint_ns": ""}}
        checkpoint = empty_checkpoint()
        saved = await saver.aput(thread, checkpoint, {}, {})
        assert await saver.aget_tuple(saved) is not None

        legacy_prefix = f"ckpt-hist:v1:{checkpoint_cache_db_hash(config.database)}"
        active_key = make_history_key(checkpoint_cache_key_prefix(config), "t1", "", checkpoint["id"], "messages")
        legacy_key = make_history_key(legacy_prefix, "t1", "", checkpoint["id"], "messages")
        sibling_key = make_history_key(legacy_prefix, "t10", "", checkpoint["id"], "messages")
        other_db_key = make_history_key("ckpt-hist:v1:other-db", "t1", "", checkpoint["id"], "messages")
        await cache.aset_many({key: _redis_entry(1) for key in (active_key, legacy_key, sibling_key, other_db_key)})
        assert fake.ttls[legacy_key] is None

        await saver.adelete_thread("t1")

        assert await saver.aget_tuple(saved) is None
        expected = {sibling_key, other_db_key}
        if key_prefix:
            expected.add(legacy_key)
        assert set(fake.store) == expected


@pytest.mark.anyio
async def test_provider_memory_default():
    from deerflow.runtime.checkpoint_cache.memory import MemoryCheckpointHistoryCache

    async with make_checkpoint_cache(_redis_app_config({"backend": "sqlite"}), serde=JsonPlusSerializer()) as cache:
        assert isinstance(cache, MemoryCheckpointHistoryCache)
        assert cache.enabled is True


@pytest.mark.anyio
async def test_provider_zero_max_entries_disables_any_type():
    app_config = _redis_app_config({"backend": "sqlite", "checkpoint_cache": {"type": "redis", "max_entries": 0}})
    from deerflow.runtime.checkpoint_cache.memory import MemoryCheckpointHistoryCache

    async with make_checkpoint_cache(app_config, serde=JsonPlusSerializer()) as cache:
        assert isinstance(cache, MemoryCheckpointHistoryCache)
        assert cache.enabled is False


def test_db_hash_distinguishes_backends_and_targets():
    from deerflow.config.database_config import DatabaseConfig

    sqlite_cfg = DatabaseConfig.model_validate({"backend": "sqlite", "sqlite_dir": "/tmp/a"})
    pg_cfg = DatabaseConfig.model_validate({"backend": "postgres", "postgres_url": "postgresql://u:p@h/db"})
    pg_cfg2 = DatabaseConfig.model_validate({"backend": "postgres", "postgres_url": "postgresql://u:p@h/other"})
    assert checkpoint_cache_db_hash(sqlite_cfg) != checkpoint_cache_db_hash(pg_cfg)
    assert checkpoint_cache_db_hash(pg_cfg) != checkpoint_cache_db_hash(pg_cfg2)
    assert len(checkpoint_cache_db_hash(pg_cfg)) == 12


def test_db_hash_stable_across_credential_rotation():
    """Same database, rotated user/password -> same cache namespace."""
    from deerflow.config.database_config import DatabaseConfig

    before = DatabaseConfig.model_validate({"backend": "postgres", "postgres_url": "postgresql://alice:secret1@pg.internal:5432/deerflow"})
    rotated = DatabaseConfig.model_validate({"backend": "postgres", "postgres_url": "postgresql://bob:secret2@pg.internal:5432/deerflow"})
    driver_suffix = DatabaseConfig.model_validate({"backend": "postgres", "postgres_url": "postgresql+asyncpg://alice:secret1@pg.internal:5432/deerflow"})
    other_db = DatabaseConfig.model_validate({"backend": "postgres", "postgres_url": "postgresql://alice:secret1@pg.internal:5432/other"})
    assert checkpoint_cache_db_hash(before) == checkpoint_cache_db_hash(rotated)
    assert checkpoint_cache_db_hash(before) == checkpoint_cache_db_hash(driver_suffix)
    assert checkpoint_cache_db_hash(before) != checkpoint_cache_db_hash(other_db)


def test_db_hash_unparseable_url_falls_back_to_raw():
    from deerflow.config.database_config import DatabaseConfig

    cfg = DatabaseConfig.model_validate({"backend": "postgres", "postgres_url": "not-a-url"})
    assert len(checkpoint_cache_db_hash(cfg)) == 12  # stable, never raises


def test_key_prefix_override_wins():
    app_config = _redis_app_config({"backend": "sqlite", "checkpoint_cache": {"key_prefix": "custom:"}})
    assert checkpoint_cache_key_prefix(app_config) == "custom:"
    default = checkpoint_cache_key_prefix(_redis_app_config({"backend": "sqlite"}))
    assert default.startswith(f"ckpt-hist:v{CACHE_FORMAT_VERSION}:")


# --- test_checkpoint_cache_redis_literal_purge ---


@pytest.fixture
def redis_cache(monkeypatch: pytest.MonkeyPatch) -> tuple[RedisCheckpointHistoryCache, AsyncMock]:
    client = AsyncMock()
    client.connection_pool = Mock()
    client.connection_pool.get_encoder.return_value.encode.side_effect = lambda value: value.encode("utf-8")
    monkeypatch.setattr("deerflow.runtime.checkpoint_cache.redis._create_client", lambda *args, **kwargs: client)
    return RedisCheckpointHistoryCache("redis://unused", serde=None, ttl_seconds=60), client


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("prefix", "thread_id", "sibling_thread_id", "pattern"),
    [
        ("tenant*", "t1", "t10", r"tenant\*:t1:*"),
        ("tenant?", "t1", "t10", r"tenant\?:t1:*"),
        ("tenant[ab]", "t1", "t10", r"tenant\[ab\]:t1:*"),
        (r"tenant\name", "t1", "t10", r"tenant\\name:t1:*"),
        ("plain", "t1", "t10", "plain:t1:*"),
        ("plain", "t1*", "t10", r"plain:t1\*:*"),
    ],
)
async def test_purge_escapes_namespace_and_filters_results(redis_cache, prefix, thread_id, sibling_thread_id, pattern):
    # Exercise the actual purge method without needing a running Redis server.
    # The expected SCAN pattern is a wire-level Redis glob contract; returned
    # keys also include a foreign namespace to pin the final deletion fence.
    cache, client = redis_cache
    owned = make_history_key(prefix, thread_id, "", "c1", "messages").encode()
    foreign = make_history_key("tenant-other", thread_id, "", "c1", "messages").encode()
    sibling = make_history_key(prefix, sibling_thread_id, "", "c1", "messages").encode()

    async def scan(*, cursor, match, count):
        assert match == pattern
        assert count == 500
        # Mixed byte/string results and multiple pages exercise redis clients
        # with either response mode and preserve the scan cursor protocol.
        if cursor == 0:
            return 7, [owned, foreign, sibling]
        assert cursor == 7
        return 0, [owned.decode()]

    client.scan.side_effect = scan
    await cache.adelete_thread(prefix, thread_id)
    assert client.unlink.await_args_list[0].args == (owned,)
    assert client.unlink.await_args_list[1].args == (owned.decode(),)


@pytest.mark.anyio
async def test_purge_does_not_unlink_empty_filtered_page(redis_cache):
    cache, client = redis_cache
    client.scan.return_value = (0, [b"other:t1:history"])
    await cache.adelete_thread("owned", "t1")
    client.unlink.assert_not_awaited()


@pytest.mark.anyio
async def test_purge_uses_client_encoding_for_byte_key_fence(redis_cache):
    """A non-UTF-8 Redis client must still unlink its own non-ASCII keys."""
    cache, client = redis_cache
    client.connection_pool.get_encoder.return_value.encode.side_effect = lambda value: value.encode("latin-1")
    owned = make_history_key("café", "t1", "", "c1", "messages").encode("latin-1")
    sibling = make_history_key("café", "t10", "", "c1", "messages").encode("latin-1")
    client.scan.return_value = (0, [owned, sibling])

    await cache.adelete_thread("café", "t1")

    client.scan.assert_awaited_once_with(cursor=0, match="café:t1:*", count=500)
    client.unlink.assert_awaited_once_with(owned)
