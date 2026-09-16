"""Read-through delta-history cache wrapper for any BaseCheckpointSaver.

Correctness argument (spec §3): a checkpoint's delta history is a pure
function of its sealed ancestor chain — the LangGraph contract excludes the
target's own pending writes, parent links are fixed at creation, and an
ancestor's writes are sealed once its child exists. Entries keyed by
(thread, ns, checkpoint_id, channel) are therefore immutable: no
invalidation, and shared backends are coherent across processes.

The wrapper never caches the "latest checkpoint" resolution; only histories
keyed by resolved immutable checkpoint_ids.

Data lifecycle: thread deletion and prune purge the thread's cached entries
(source-of-truth removal must not leave residual history payloads in the
cache); run-scoped deletes cannot be mapped to threads cheaply and rely on
LRU/TTL bounds.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, Sequence
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver, CheckpointTuple, PendingWrite

from deerflow.runtime.checkpoint_cache.base import make_history_key

logger = logging.getLogger(__name__)

# Depth budget for recursive compose before falling back to a chain-warming
# walk. Steady-state runs need ~2 (one intermediate checkpoint per step);
# deeper cold chains are handled faster by one warming walk than by many
# recursive single-tuple fetches.
_COMPOSE_MAX_DEPTH = 8


def _checkpoint_ref(tup: CheckpointTuple) -> tuple[str, str, str]:
    configurable = tup.config["configurable"]
    return (
        str(configurable["thread_id"]),
        str(configurable.get("checkpoint_ns", "")),
        str(configurable["checkpoint_id"]),
    )


def _channel_writes(tup: CheckpointTuple, channel: str) -> list[PendingWrite]:
    """Writes for one channel, oldest→newest (tuple storage order)."""
    return [w for w in (tup.pending_writes or []) if w[1] == channel]


class CachedHistorySaver(BaseCheckpointSaver):
    def __init__(self, inner: BaseCheckpointSaver, cache: Any, *, key_prefix: str) -> None:
        # Instance attr shadows the base class JsonPlusSerializer default.
        self.serde = inner.serde
        self._inner = inner
        self._cache = cache
        self._key_prefix = key_prefix
        self._compose_hits = 0
        self._full_walks = 0

    def __getattr__(self, name: str) -> Any:
        # Safety net for saver-specific extras (e.g. AsyncSqliteSaver.setup).
        # Base-class methods are explicitly delegated below, so this only
        # fires for attributes BaseCheckpointSaver does not define.
        inner = self.__dict__.get("_inner")
        if inner is None:
            raise AttributeError(name)
        return getattr(inner, name)

    # ------------------------------------------------------------------
    # Key building
    # ------------------------------------------------------------------

    def _key(self, tup: CheckpointTuple, channel: str) -> str:
        thread_id, ns, checkpoint_id = _checkpoint_ref(tup)
        return make_history_key(self._key_prefix, thread_id, ns, checkpoint_id, channel)

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def stats(self) -> dict[str, int]:
        backend = self._cache.stats().as_dict()
        return {**backend, "compose_hits": self._compose_hits, "full_walks": self._full_walks}

    # ------------------------------------------------------------------
    # Delta history: the only overridden behavior
    # ------------------------------------------------------------------

    async def aget_delta_channel_history(self, *, config: RunnableConfig, channels: Sequence[str]) -> dict[str, Any]:
        if not channels:
            return {}
        if not getattr(self._cache, "enabled", True):
            # Disabled cache: pass straight through; composing over all-miss
            # entries is strictly more work than the raw saver's walk.
            return await self._walk_inner(config, channels)
        target = await self._inner.aget_tuple(config)
        if target is None:
            return await self._walk_inner(config, channels)

        keys = {ch: self._key(target, ch) for ch in channels}
        hits = await self._cache.aget_many(list(keys.values()))
        found: dict[str, dict[str, Any]] = {}
        missing: list[str] = []
        for ch in channels:
            entry = hits.get(keys[ch])
            if entry is None:
                missing.append(ch)
            else:
                found[ch] = entry

        computed: dict[str, dict[str, Any]] = {}
        if missing:
            computed = await self._compose_or_walk(config, target, missing)

        new_entries = {keys[ch]: computed[ch] for ch in missing if ch in computed}
        if new_entries:
            await self._cache.aset_many(new_entries)

        return {ch: found.get(ch) or computed.get(ch) or {"writes": []} for ch in channels}

    async def _compose_or_walk(self, config: RunnableConfig, target: CheckpointTuple, missing: list[str]) -> dict[str, dict[str, Any]]:
        return {ch: await self._aresolve(target, ch, _COMPOSE_MAX_DEPTH) for ch in missing}

    async def _aresolve(self, tup: CheckpointTuple, channel: str, depth: int) -> dict[str, Any]:
        """Recursively compose history(tup) from the nearest warm ancestor.

        Real runs create several checkpoints per super-step and only some are
        ever materialized as targets, so the parent is usually an unwarmed
        intermediate checkpoint (measured: 0 cache hits with single-level
        compose on a 500-step sqlite run). Recursing one level per
        intermediate lands on a warmed ancestor within ~2 levels in steady
        state; each composed level is cached, so the warm frontier follows
        the run. At depth 0 on a cold chain it delegates one inner fast-path
        walk (2 SQL) rather than crawling ancestors tuple-by-tuple.
        """
        parent_config = tup.parent_config
        if parent_config is None:
            return {"writes": []}
        parent = await self._inner.aget_tuple(parent_config)
        if parent is None:
            return {"writes": []}

        channel_values = parent.checkpoint.get("channel_values") or {}
        writes = _channel_writes(parent, channel)
        if channel in channel_values:
            self._compose_hits += 1
            return {"writes": writes, "seed": channel_values[channel]}

        key = self._key(parent, channel)
        hits = await self._cache.aget_many([key])
        parent_history = hits.get(key)
        if parent_history is None:
            if depth > 0:
                parent_history = await self._aresolve(parent, channel, depth - 1)
            else:
                # Depth budget exhausted on a cold chain: delegate ONE inner
                # fast-path walk (2 SQL total) for this level instead of
                # fetching every ancestor tuple individually. Ancestors below
                # stay cold; resolving them later recurses up to the nearest
                # warm level, so the frontier still follows the run.
                self._full_walks += 1
                walked = await self._inner.aget_delta_channel_history(config=parent.config, channels=[channel])
                parent_history = walked.get(channel) or {"writes": []}
            if parent_history is not None:
                await self._cache.aset_many({key: parent_history})

        self._compose_hits += 1
        entry: dict[str, Any] = {"writes": list(parent_history["writes"]) + writes}
        if "seed" in parent_history:
            entry["seed"] = parent_history["seed"]
        return entry

    async def _walk_inner(self, config: RunnableConfig, channels: Sequence[str]) -> dict[str, Any]:
        self._full_walks += 1
        return dict(await self._inner.aget_delta_channel_history(config=config, channels=channels))

    def get_delta_channel_history(self, *, config: RunnableConfig, channels: Sequence[str]) -> dict[str, Any]:
        if not channels:
            return {}
        if not getattr(self._cache, "enabled", True):
            return self._walk_inner_sync(config, channels)
        get_many = getattr(self._cache, "get_many", None)
        set_many = getattr(self._cache, "set_many", None)
        if get_many is None or set_many is None:
            raise TypeError("sync get_delta_channel_history requires a SyncCheckpointHistoryCache (memory backend)")
        target = self._inner.get_tuple(config)
        if target is None:
            return self._walk_inner_sync(config, channels)

        keys = {ch: self._key(target, ch) for ch in channels}
        hits = get_many(list(keys.values()))
        found: dict[str, dict[str, Any]] = {}
        missing: list[str] = []
        for ch in channels:
            entry = hits.get(keys[ch])
            if entry is None:
                missing.append(ch)
            else:
                found[ch] = entry

        computed: dict[str, dict[str, Any]] = {}
        if missing:
            computed = {ch: self._resolve_sync(target, ch, _COMPOSE_MAX_DEPTH) for ch in missing}

        new_entries = {keys[ch]: computed[ch] for ch in missing if ch in computed}
        if new_entries:
            set_many(new_entries)
        return {ch: found.get(ch) or computed.get(ch) or {"writes": []} for ch in channels}

    def _resolve_sync(self, tup: CheckpointTuple, channel: str, depth: int) -> dict[str, Any]:
        """Sync twin of _aresolve (recursive compose, see its docstring)."""
        parent_config = tup.parent_config
        if parent_config is None:
            return {"writes": []}
        parent = self._inner.get_tuple(parent_config)
        if parent is None:
            return {"writes": []}

        channel_values = parent.checkpoint.get("channel_values") or {}
        writes = _channel_writes(parent, channel)
        if channel in channel_values:
            self._compose_hits += 1
            return {"writes": writes, "seed": channel_values[channel]}

        key = self._key(parent, channel)
        parent_history = self._cache.get_many([key]).get(key)
        if parent_history is None:
            if depth > 0:
                parent_history = self._resolve_sync(parent, channel, depth - 1)
            else:
                # See _aresolve: one inner fast-path walk, no per-tuple crawl.
                self._full_walks += 1
                parent_history = self._inner.get_delta_channel_history(config=parent.config, channels=[channel]).get(channel) or {"writes": []}
            if parent_history is not None:
                self._cache.set_many({key: parent_history})

        self._compose_hits += 1
        entry: dict[str, Any] = {"writes": list(parent_history["writes"]) + writes}
        if "seed" in parent_history:
            entry["seed"] = parent_history["seed"]
        return entry

    def _walk_inner_sync(self, config: RunnableConfig, channels: Sequence[str]) -> dict[str, Any]:
        self._full_walks += 1
        return dict(self._inner.get_delta_channel_history(config=config, channels=channels))

    # ------------------------------------------------------------------
    # Explicit delegation (BaseCheckpointSaver defines these concretely,
    # so __getattr__ never fires for them)
    # ------------------------------------------------------------------

    def get_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        return self._inner.get_tuple(config)

    def list(self, config: RunnableConfig | None, *, filter: dict[str, Any] | None = None, before: RunnableConfig | None = None, limit: int | None = None) -> Iterator[CheckpointTuple]:
        return self._inner.list(config, filter=filter, before=before, limit=limit)

    def put(self, config: RunnableConfig, checkpoint: dict[str, Any], metadata: dict[str, Any], new_versions: dict[str, Any]) -> RunnableConfig:
        return self._inner.put(config, checkpoint, metadata, new_versions)

    def put_writes(self, config: RunnableConfig, writes: Sequence[tuple[str, str, Any]], task_id: str, task_path: str = "") -> None:
        self._inner.put_writes(config, writes, task_id, task_path)

    def delete_thread(self, thread_id: str) -> None:
        self._inner.delete_thread(thread_id)
        self._purge_thread_sync(thread_id)

    def delete_for_runs(self, run_ids: Sequence[str]) -> None:
        # Run-scoped deletes cannot be mapped back to threads without an extra
        # query, so cached entries are left in place: they stay *correct* (the
        # sealed-chain argument is unaffected by other chains) and residual
        # retention is bounded by LRU/TTL. No in-tree callers today.
        self._inner.delete_for_runs(run_ids)

    def _purge_thread_sync(self, thread_id: str) -> None:
        delete = getattr(self._cache, "delete_thread", None)
        if delete is not None:
            delete(self._key_prefix, thread_id)

    def copy_thread(self, source_thread_id: str, target_thread_id: str) -> None:
        self._inner.copy_thread(source_thread_id, target_thread_id)

    def prune(self, thread_ids: Sequence[str], *, strategy: str = "keep_latest") -> None:
        self._inner.prune(thread_ids, strategy=strategy)
        # Pruning rewrites these threads' chains: purge so no cached history
        # references a deleted ancestor (retention) or its pre-prune chain.
        for thread_id in thread_ids:
            self._purge_thread_sync(thread_id)

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        return await self._inner.aget_tuple(config)

    def alist(self, config: RunnableConfig | None, *, filter: dict[str, Any] | None = None, before: RunnableConfig | None = None, limit: int | None = None) -> Any:
        return self._inner.alist(config, filter=filter, before=before, limit=limit)

    async def aput(self, config: RunnableConfig, checkpoint: dict[str, Any], metadata: dict[str, Any], new_versions: dict[str, Any]) -> RunnableConfig:
        return await self._inner.aput(config, checkpoint, metadata, new_versions)

    async def aput_writes(self, config: RunnableConfig, writes: Sequence[tuple[str, str, Any]], task_id: str, task_path: str = "") -> None:
        await self._inner.aput_writes(config, writes, task_id, task_path)

    async def adelete_thread(self, thread_id: str) -> None:
        await self._inner.adelete_thread(thread_id)
        await self._apurge_thread(thread_id)

    async def adelete_for_runs(self, run_ids: Sequence[str]) -> None:
        # See delete_for_runs: unscoped residual retention bounded by LRU/TTL.
        await self._inner.adelete_for_runs(run_ids)

    async def _apurge_thread(self, thread_id: str) -> None:
        delete = getattr(self._cache, "adelete_thread", None)
        if delete is not None:
            await delete(self._key_prefix, thread_id)

    async def acopy_thread(self, source_thread_id: str, target_thread_id: str) -> None:
        await self._inner.acopy_thread(source_thread_id, target_thread_id)

    async def aprune(self, thread_ids: Sequence[str], *, strategy: str = "keep_latest") -> None:
        await self._inner.aprune(thread_ids, strategy=strategy)
        # See prune: rewritten chains must not keep pre-prune cached histories.
        for thread_id in thread_ids:
            await self._apurge_thread(thread_id)

    def get_next_version(self, current: Any, channel: Any) -> Any:
        return self._inner.get_next_version(current, channel)
