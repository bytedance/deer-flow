"""Process-local LRU backend with serialized LRU and statistics access."""

from __future__ import annotations

import threading
from collections import OrderedDict
from copy import deepcopy
from typing import Any

from deerflow.runtime.checkpoint_cache.base import CheckpointCacheStats, thread_key_stem


def _copy_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Own nested write payloads and snapshot seeds on both sides of the cache."""
    return deepcopy(entry)


class MemoryCheckpointHistoryCache:
    def __init__(self, max_entries: int = 128) -> None:
        if max_entries < 0:
            raise ValueError("max_entries must be >= 0")
        self._lock = threading.Lock()
        self._max_entries = max_entries
        self._data: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._hits = 0
        self._misses = 0
        self._evictions = 0

    @property
    def enabled(self) -> bool:
        return self._max_entries > 0

    def get_many(self, keys: list[str]) -> dict[str, dict[str, Any]]:
        with self._lock:
            found: dict[str, dict[str, Any]] = {}
            for key in keys:
                entry = self._data.get(key)
                if entry is None:
                    self._misses += 1
                    continue
                self._data.move_to_end(key)
                self._hits += 1
                found[key] = entry
        # Entries are privately owned and never changed after publication. Copy
        # outside the registry lock: user payloads can implement __deepcopy__.
        return {key: _copy_entry(entry) for key, entry in found.items()}

    def set_many(self, entries: dict[str, dict[str, Any]]) -> None:
        if not self.enabled:
            return
        copied = {key: _copy_entry(entry) for key, entry in entries.items()}
        with self._lock:
            for key, entry in copied.items():
                self._data[key] = entry
                self._data.move_to_end(key)
                while len(self._data) > self._max_entries:
                    self._data.popitem(last=False)
                    self._evictions += 1

    async def aget_many(self, keys: list[str]) -> dict[str, dict[str, Any]]:
        return self.get_many(keys)

    async def aset_many(self, entries: dict[str, dict[str, Any]]) -> None:
        self.set_many(entries)

    def delete_thread(self, key_prefix: str, thread_id: str) -> None:
        """Purge every entry of one thread (lifecycle, not invalidation)."""
        with self._lock:
            stem = thread_key_stem(key_prefix, thread_id)
            for key in [k for k in self._data if k.startswith(stem)]:
                del self._data[key]

    async def adelete_thread(self, key_prefix: str, thread_id: str) -> None:
        self.delete_thread(key_prefix, thread_id)

    def stats(self) -> CheckpointCacheStats:
        with self._lock:
            return CheckpointCacheStats(
                hits=self._hits,
                misses=self._misses,
                evictions=self._evictions,
                entries=len(self._data),
            )

    async def aclose(self) -> None:
        with self._lock:
            self._data.clear()
