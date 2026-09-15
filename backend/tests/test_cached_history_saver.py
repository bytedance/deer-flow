"""CachedHistorySaver composition vs. the saver's own full walk."""

from typing import Any

import pytest
from langgraph.checkpoint.base import BaseCheckpointSaver, CheckpointTuple

from deerflow.runtime.checkpoint_cache.memory import MemoryCheckpointHistoryCache
from deerflow.runtime.checkpointer.cached_saver import CachedHistorySaver

PREFIX = "ckpt-hist:v1:testdb"


class _DictSaver(BaseCheckpointSaver):
    """Minimal in-memory saver. Deliberately does NOT override the delta
    history methods, so the base class full parent-chain walk is the
    differential oracle."""

    def __init__(self) -> None:
        super().__init__()
        self.checkpoints: dict[str, tuple[CheckpointTuple, ...]] = {}
        self.tuple_reads = 0
        self.history_walks = 0

    def put_tuple(self, tup: CheckpointTuple) -> None:
        cid = tup.config["configurable"]["checkpoint_id"]
        self.checkpoints[cid] = (tup,)

    def get_tuple(self, config):
        self.tuple_reads += 1
        configurable = config["configurable"]
        cid = configurable.get("checkpoint_id")
        if cid is None:
            cid = next(reversed(self.checkpoints), None)
            if cid is None:
                return None
        stored = self.checkpoints.get(cid)
        return stored[0] if stored else None

    async def aget_tuple(self, config):
        return self.get_tuple(config)

    def get_delta_channel_history(self, *, config, channels):
        self.history_walks += 1
        return super().get_delta_channel_history(config=config, channels=channels)

    async def aget_delta_channel_history(self, *, config, channels):
        self.history_walks += 1
        return await super().aget_delta_channel_history(config=config, channels=channels)

    # Unused abstract surface.
    def list(self, config, *, filter=None, before=None, limit=None):
        yield from ()

    def put(self, config, checkpoint, metadata, new_versions):
        raise NotImplementedError

    def put_writes(self, config, writes, task_id, task_path=""):
        raise NotImplementedError

    def delete_thread(self, thread_id):
        raise NotImplementedError


def _cfg(thread: str, cid: str | None) -> dict:
    configurable: dict[str, Any] = {"thread_id": thread, "checkpoint_ns": ""}
    if cid is not None:
        configurable["checkpoint_id"] = cid
    return {"configurable": configurable}


def _tup(thread: str, cid: str, parent: str | None, *, channel_values: dict, writes: list) -> CheckpointTuple:
    config = _cfg(thread, cid)
    parent_config = _cfg(thread, parent) if parent else None
    checkpoint = {"v": 1, "id": cid, "channel_values": channel_values, "channel_versions": {}, "versions_seen": {}, "updated_at": None}
    return CheckpointTuple(config=config, checkpoint=checkpoint, metadata={}, parent_config=parent_config, pending_writes=list(writes))


def _chain(saver: _DictSaver, thread: str = "t1") -> list[str]:
    """c0(seed snapshot) -> c1(writes w1) -> c2(writes w2)."""
    saver.put_tuple(_tup(thread, "c0", None, channel_values={"messages": ["seed-msg"]}, writes=[]))
    saver.put_tuple(_tup(thread, "c1", "c0", channel_values={}, writes=[("task1", "messages", "w1")]))
    saver.put_tuple(_tup(thread, "c2", "c1", channel_values={}, writes=[("task2", "messages", "w2")]))
    return ["c0", "c1", "c2"]


def _wrap(saver: _DictSaver, cache) -> CachedHistorySaver:
    return CachedHistorySaver(saver, cache, key_prefix=PREFIX)


class _DeletableSaver(_DictSaver):
    """Functional delete/prune so purge behavior is observable."""

    def __init__(self) -> None:
        super().__init__()
        self.deleted_threads: list[str] = []
        self.deleted_run_ids: list[list[str]] = []
        self.pruned_threads: list[list[str]] = []

    def delete_for_runs(self, run_ids):
        self.deleted_run_ids.append(list(run_ids))

    async def adelete_for_runs(self, run_ids):
        self.deleted_run_ids.append(list(run_ids))

    def _drop(self, thread_id: str) -> None:
        self.deleted_threads.append(thread_id)
        self.checkpoints = {cid: stored for cid, stored in self.checkpoints.items() if stored[0].config["configurable"]["thread_id"] != thread_id}

    def delete_thread(self, thread_id):
        self._drop(thread_id)

    async def adelete_thread(self, thread_id):
        self._drop(thread_id)

    def prune(self, thread_ids, *, strategy="keep_latest"):
        self.pruned_threads.append(list(thread_ids))

    async def aprune(self, thread_ids, *, strategy="keep_latest"):
        self.pruned_threads.append(list(thread_ids))


def _thread_entries(cache: MemoryCheckpointHistoryCache, thread_id: str) -> int:
    stem = f"{PREFIX}:{thread_id}:"
    return sum(1 for key in cache._data if key.startswith(stem))


@pytest.mark.anyio
async def test_adelete_thread_purges_only_that_threads_cache_entries():
    inner = _DeletableSaver()
    _chain(inner, "t1")
    # _DictSaver keys tuples by checkpoint_id alone: t2 needs distinct cids.
    inner.put_tuple(_tup("t2", "u0", None, channel_values={"messages": ["seed2"]}, writes=[]))
    inner.put_tuple(_tup("t2", "u1", "u0", channel_values={}, writes=[("task1", "messages", "x1")]))
    cache = MemoryCheckpointHistoryCache(max_entries=32)
    saver = _wrap(inner, cache)
    await saver.aget_delta_channel_history(config=_cfg("t1", "c2"), channels=["messages"])
    await saver.aget_delta_channel_history(config=_cfg("t2", "u1"), channels=["messages"])
    assert _thread_entries(cache, "t1") > 0
    assert _thread_entries(cache, "t2") > 0

    await saver.adelete_thread("t1")

    assert inner.deleted_threads == ["t1"]
    assert inner.get_tuple(_cfg("t1", "c2")) is None  # source of truth gone
    assert _thread_entries(cache, "t1") == 0  # residual history payloads purged
    assert _thread_entries(cache, "t2") > 0  # other threads untouched


def test_sync_delete_thread_purges_cache_entries():
    inner = _DeletableSaver()
    _chain(inner, "t1")
    cache = MemoryCheckpointHistoryCache(max_entries=32)
    saver = _wrap(inner, cache)
    saver.get_delta_channel_history(config=_cfg("t1", "c2"), channels=["messages"])
    assert _thread_entries(cache, "t1") > 0

    saver.delete_thread("t1")

    assert inner.deleted_threads == ["t1"]
    assert _thread_entries(cache, "t1") == 0


@pytest.mark.anyio
async def test_prune_purges_rewritten_threads_cache_entries():
    inner = _DeletableSaver()
    _chain(inner, "t1")
    cache = MemoryCheckpointHistoryCache(max_entries=32)
    saver = _wrap(inner, cache)
    await saver.aget_delta_channel_history(config=_cfg("t1", "c2"), channels=["messages"])
    assert _thread_entries(cache, "t1") > 0

    await saver.aprune(["t1"], strategy="keep_latest")

    assert inner.pruned_threads == [["t1"]]
    # The chain was rewritten: pre-prune histories must not linger.
    assert _thread_entries(cache, "t1") == 0


@pytest.mark.anyio
async def test_delete_for_runs_delegates_without_cache_purge():
    """Run-scoped deletes cannot be mapped to threads cheaply; documented
    behavior is delegation with LRU/TTL-bounded residual retention."""
    inner = _DeletableSaver()
    _chain(inner, "t1")
    cache = MemoryCheckpointHistoryCache(max_entries=32)
    saver = _wrap(inner, cache)
    await saver.aget_delta_channel_history(config=_cfg("t1", "c2"), channels=["messages"])
    entries_before = cache.stats().entries

    await saver.adelete_for_runs(["run-1"])  # base-class no-op on _DictSaver lineage

    assert inner.deleted_run_ids == [["run-1"]]
    assert cache.stats().entries == entries_before


class _RecordingSaver(_DictSaver):
    """Captures the config passed into each fallback walk."""

    def __init__(self) -> None:
        super().__init__()
        self.walk_configs: list[dict] = []

    def get_delta_channel_history(self, *, config, channels):
        self.walk_configs.append(config)
        return super().get_delta_channel_history(config=config, channels=channels)

    async def aget_delta_channel_history(self, *, config, channels):
        self.walk_configs.append(config)
        return await super().aget_delta_channel_history(config=config, channels=channels)


@pytest.mark.anyio
async def test_composition_matches_full_walk_and_avoids_it():
    inner = _DictSaver()
    _chain(inner)
    cache = MemoryCheckpointHistoryCache(max_entries=16)
    saver = _wrap(inner, cache)

    # Cold: c1 composes from snapshot parent c0 (channel_values hit) — no walk.
    h1 = await saver.aget_delta_channel_history(config=_cfg("t1", "c1"), channels=["messages"])
    assert h1["messages"]["writes"] == []
    assert h1["messages"]["seed"] == ["seed-msg"]
    assert inner.history_walks == 0

    # c2 composes from cached history(c1) + c1's pending writes: no inner walk.
    # NOTE: history(c2) excludes c2's OWN pending writes (they belong to the
    # next super-step per the LangGraph contract) — on-path writes are c1's.
    h2 = await saver.aget_delta_channel_history(config=_cfg("t1", "c2"), channels=["messages"])
    assert h2["messages"]["writes"] == [("task1", "messages", "w1")]
    assert h2["messages"]["seed"] == ["seed-msg"]
    assert inner.history_walks == 0  # unchanged: composition, not a walk

    # Differential oracle: identical to the inner saver's own full walk.
    oracle = _DictSaver()
    _chain(oracle)
    for cid in ("c0", "c1", "c2"):
        expected = await oracle.aget_delta_channel_history(config=_cfg("t1", cid), channels=["messages"])
        actual = await saver.aget_delta_channel_history(config=_cfg("t1", cid), channels=["messages"])
        assert actual == expected, cid


@pytest.mark.anyio
async def test_snapshot_parent_composes_without_parent_history_lookup():
    inner = _DictSaver()
    _chain(inner)
    # c3 has c0-style snapshot directly at parent c1: rewrite c1 with channel_values.
    inner.put_tuple(_tup("t1", "c1b", "c0", channel_values={"messages": ["snap"]}, writes=[("t", "messages", "wx")]))
    inner.put_tuple(_tup("t1", "c2b", "c1b", channel_values={}, writes=[("t2", "messages", "wy")]))
    saver = _wrap(inner, MemoryCheckpointHistoryCache(max_entries=16))
    h = await saver.aget_delta_channel_history(config=_cfg("t1", "c2b"), channels=["messages"])
    assert h["messages"] == {"writes": [("t", "messages", "wx")], "seed": ["snap"]}
    assert inner.history_walks == 0


@pytest.mark.anyio
async def test_root_checkpoint_history_is_empty_writes():
    inner = _DictSaver()
    _chain(inner)
    saver = _wrap(inner, MemoryCheckpointHistoryCache(max_entries=16))
    h = await saver.aget_delta_channel_history(config=_cfg("t1", "c0"), channels=["messages"])
    assert h["messages"] == {"writes": []}
    assert "seed" not in h["messages"]


@pytest.mark.anyio
async def test_latest_config_caches_under_resolved_checkpoint_id():
    inner = _DictSaver()
    _chain(inner)
    cache = MemoryCheckpointHistoryCache(max_entries=16)
    saver = _wrap(inner, cache)
    await saver.aget_delta_channel_history(config=_cfg("t1", None), channels=["messages"])
    reads_after_first = inner.tuple_reads
    await saver.aget_delta_channel_history(config=_cfg("t1", "c2"), channels=["messages"])
    # Second call resolves by id from cache: target tuple only, no parent refetch.
    assert inner.tuple_reads == reads_after_first + 1


@pytest.mark.anyio
async def test_eviction_falls_back_to_walk_but_stays_correct():
    inner = _DictSaver()
    _chain(inner)
    cache = MemoryCheckpointHistoryCache(max_entries=1)
    saver = _wrap(inner, cache)
    await saver.aget_delta_channel_history(config=_cfg("t1", "c2"), channels=["messages"])  # cold: fallback walk
    await saver.aget_delta_channel_history(config=_cfg("t1", "c1"), channels=["messages"])  # compose; evicts c2 entry
    h = await saver.aget_delta_channel_history(config=_cfg("t1", "c2"), channels=["messages"])  # recomposes via cached history(c1)
    assert h["messages"]["writes"] == [("task1", "messages", "w1")]
    assert h["messages"]["seed"] == ["seed-msg"]
    assert saver.stats()["full_walks"] == 0  # cold read resolved by recursive compose
    assert inner.history_walks == 0  # resolution never delegates to the inner walk
    assert cache.stats().evictions >= 1


def test_sync_path_matches_async():
    inner = _DictSaver()
    _chain(inner)
    saver = _wrap(inner, MemoryCheckpointHistoryCache(max_entries=16))
    h = saver.get_delta_channel_history(config=_cfg("t1", "c2"), channels=["messages"])
    assert h["messages"]["writes"] == [("task1", "messages", "w1")]
    assert h["messages"]["seed"] == ["seed-msg"]


@pytest.mark.anyio
async def test_cold_resolve_never_delegates_to_inner_history():
    """Cold reads compose recursively (or walk themselves via aget_tuple):
    the inner saver's own history method is never called, so a 'latest'
    config cannot be re-resolved mid-resolution (the old pinned race is gone
    by construction)."""
    inner = _RecordingSaver()
    _chain(inner)
    saver = _wrap(inner, MemoryCheckpointHistoryCache(max_entries=16))
    h = await saver.aget_delta_channel_history(config=_cfg("t1", None), channels=["messages"])
    assert h["messages"]["writes"] == [("task1", "messages", "w1")]
    assert h["messages"]["seed"] == ["seed-msg"]
    assert inner.walk_configs == [], "resolution must not delegate to the inner history walk"


def test_sync_cold_resolve_never_delegates_to_inner_history():
    inner = _RecordingSaver()
    _chain(inner)
    saver = _wrap(inner, MemoryCheckpointHistoryCache(max_entries=16))
    h = saver.get_delta_channel_history(config=_cfg("t1", None), channels=["messages"])
    assert h["messages"]["writes"] == [("task1", "messages", "w1")]
    assert inner.walk_configs == []


@pytest.mark.anyio
async def test_recursive_resolve_caches_intermediate_levels():
    """Cold short chains resolve by recursive compose: every intermediate
    level is computed once and cached, later reads hit directly."""
    inner = _DictSaver()
    _chain(inner)
    inner.put_tuple(_tup("t1", "c3", "c2", channel_values={}, writes=[("task3", "messages", "w3")]))
    oracle = _DictSaver()
    _chain(oracle)
    oracle.put_tuple(_tup("t1", "c3", "c2", channel_values={}, writes=[("task3", "messages", "w3")]))
    saver = _wrap(inner, MemoryCheckpointHistoryCache(max_entries=16))

    await saver.aget_delta_channel_history(config=_cfg("t1", "c3"), channels=["messages"])
    reads_after_cold = inner.tuple_reads

    for cid in ("c0", "c1", "c2", "c3"):
        expected = await oracle.aget_delta_channel_history(config=_cfg("t1", cid), channels=["messages"])
        actual = await saver.aget_delta_channel_history(config=_cfg("t1", cid), channels=["messages"])
        assert actual == expected, cid
    # Every level is now warm: each read costs exactly its target tuple fetch.
    assert inner.tuple_reads - reads_after_cold == 4


@pytest.mark.anyio
async def test_deep_cold_chain_delegates_one_inner_walk_at_depth_limit():
    """A cold chain deeper than the compose budget resolves the deepest
    reached level with ONE inner fast-path walk (2 SQL), caches every level
    above it, and leaves deeper ancestors cold until asked."""
    inner = _DictSaver()
    # 12-deep chain: c0(seed) <- c1 <- ... <- c11, deeper than the budget.
    inner.put_tuple(_tup("t1", "c0", None, channel_values={"messages": ["seed-msg"]}, writes=[]))
    for i in range(1, 12):
        inner.put_tuple(_tup("t1", f"c{i}", f"c{i - 1}", channel_values={}, writes=[("task", "messages", f"w{i}")]))
    oracle = _DictSaver()
    oracle.put_tuple(_tup("t1", "c0", None, channel_values={"messages": ["seed-msg"]}, writes=[]))
    for i in range(1, 12):
        oracle.put_tuple(_tup("t1", f"c{i}", f"c{i - 1}", channel_values={}, writes=[("task", "messages", f"w{i}")]))
    saver = _wrap(inner, MemoryCheckpointHistoryCache(max_entries=64))

    h = await saver.aget_delta_channel_history(config=_cfg("t1", "c11"), channels=["messages"])
    assert saver.stats()["full_walks"] == 1
    assert inner.history_walks == 1  # exactly one delegated fast-path walk
    assert h["messages"]["writes"] == [("task", "messages", f"w{i}") for i in range(1, 11)]
    assert h["messages"]["seed"] == ["seed-msg"]

    reads_after_cold = inner.tuple_reads
    for cid in [f"c{i}" for i in range(12)]:
        expected = await oracle.aget_delta_channel_history(config=_cfg("t1", cid), channels=["messages"])
        actual = await saver.aget_delta_channel_history(config=_cfg("t1", cid), channels=["messages"])
        assert actual == expected, cid
    # Warm after the cold read: c2..c11. Reads: c0 = 1 (root, no parent);
    # c1 = 2 (target + snapshot parent c0); c2..c11 = 1 each.
    assert inner.tuple_reads - reads_after_cold == 13


@pytest.mark.anyio
async def test_stats_expose_composition_counters():
    inner = _DictSaver()
    _chain(inner)
    saver = _wrap(inner, MemoryCheckpointHistoryCache(max_entries=16))
    await saver.aget_delta_channel_history(config=_cfg("t1", "c2"), channels=["messages"])  # cold: recursive compose ×2, warms c1+c2
    await saver.aget_delta_channel_history(config=_cfg("t1", "c1"), channels=["messages"])  # direct hit (warmed)
    # Compose: add c3 (parent c2, not a snapshot) AFTER the cold read — c3 is
    # not cached but history(c2) is, so c3 composes without a walk.
    inner.put_tuple(_tup("t1", "c3", "c2", channel_values={}, writes=[("task3", "messages", "w3")]))
    h3 = await saver.aget_delta_channel_history(config=_cfg("t1", "c3"), channels=["messages"])
    assert h3["messages"]["writes"] == [("task1", "messages", "w1"), ("task2", "messages", "w2")]
    stats = saver.stats()
    assert stats["full_walks"] == 0
    assert stats["compose_hits"] == 3  # c1-level + c2-level (cold) + c3
    assert stats["hits"] >= 1
