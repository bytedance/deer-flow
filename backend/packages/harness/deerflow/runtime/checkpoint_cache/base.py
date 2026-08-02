"""Cache backend contract for checkpoint delta-history entries.

Entries are ``DeltaChannelHistory``-shaped dicts (``{"writes": [...], "seed"?}``)
keyed by immutable (database, thread, namespace, checkpoint_id, channel)
tuples. Checkpoint lineage is append-only and a checkpoint's history excludes
its own pending writes, so entries never change once written: correctness
never requires invalidation, and a shared backend is coherent across
processes without any coordination.

The only delete API is thread-scoped (``adelete_thread``/``delete_thread``),
and it exists purely for data lifecycle, not correctness: when the source
checkpoints are erased (thread deletion, tenant offboarding, GDPR-style
erasure), the cached history payloads for that thread must go too instead of
lingering until LRU eviction or TTL expiry.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Protocol

CACHE_FORMAT_VERSION = 1


def make_history_key(
    key_prefix: str,
    thread_id: str,
    checkpoint_ns: str,
    checkpoint_id: str,
    channel: str,
) -> str:
    """Build a collision-safe cache key.

    ``thread_id`` stays readable for ops debugging; the remaining components
    are hashed with NUL separators so namespaces containing ':' cannot
    produce ambiguous keys.
    """
    digest = hashlib.sha256(f"{checkpoint_ns}\x00{checkpoint_id}\x00{channel}".encode()).hexdigest()[:24]
    return f"{key_prefix}:{thread_id}:{digest}"


def thread_key_stem(key_prefix: str, thread_id: str) -> str:
    """Prefix matching every history key of one thread (see make_history_key)."""
    return f"{key_prefix}:{thread_id}:"


@dataclass
class CheckpointCacheStats:
    hits: int = 0
    misses: int = 0
    evictions: int = 0
    entries: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
            "entries": self.entries,
        }


class CheckpointHistoryCache(Protocol):
    """Async backend contract. Deletes are thread-scoped lifecycle purges only."""

    async def aget_many(self, keys: list[str]) -> dict[str, dict[str, Any]]: ...
    async def aset_many(self, entries: dict[str, dict[str, Any]]) -> None: ...
    async def adelete_thread(self, key_prefix: str, thread_id: str) -> None: ...
    def stats(self) -> CheckpointCacheStats: ...
    async def aclose(self) -> None: ...


class SyncCheckpointHistoryCache(Protocol):
    """Sync backend contract (embedded/TUI path). Memory backend only."""

    def get_many(self, keys: list[str]) -> dict[str, dict[str, Any]]: ...
    def set_many(self, entries: dict[str, dict[str, Any]]) -> None: ...
    def delete_thread(self, key_prefix: str, thread_id: str) -> None: ...
    def stats(self) -> CheckpointCacheStats: ...
