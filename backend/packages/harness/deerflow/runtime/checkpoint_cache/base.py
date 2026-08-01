"""Cache backend contract for checkpoint delta-history entries.

Entries are ``DeltaChannelHistory``-shaped dicts (``{"writes": [...], "seed"?}``)
keyed by immutable (database, thread, namespace, checkpoint_id, channel)
tuples. Checkpoint lineage is append-only and a checkpoint's history excludes
its own pending writes, so entries never change once written: there is no
delete or invalidate API, and a shared backend is coherent across processes
without any coordination.
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
    """Async backend contract. No delete: entries are immutable."""

    async def aget_many(self, keys: list[str]) -> dict[str, dict[str, Any]]: ...
    async def aset_many(self, entries: dict[str, dict[str, Any]]) -> None: ...
    def stats(self) -> CheckpointCacheStats: ...
    async def aclose(self) -> None: ...


class SyncCheckpointHistoryCache(Protocol):
    """Sync backend contract (embedded/TUI path). Memory backend only."""

    def get_many(self, keys: list[str]) -> dict[str, dict[str, Any]]: ...
    def set_many(self, entries: dict[str, dict[str, Any]]) -> None: ...
    def stats(self) -> CheckpointCacheStats: ...
