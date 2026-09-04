"""Async keyed locks whose idle entries are reclaimed safely."""

from __future__ import annotations

import asyncio
import threading
import weakref
from collections.abc import AsyncIterator, Hashable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field


@dataclass(slots=True)
class _Entry:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    participants: int = 0  # holders + queued waiters


class AsyncKeyedLockTable[KeyT: Hashable]:
    """Serialize work per key without retaining keys after their last participant."""

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._entries_by_loop: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict[KeyT, _Entry]] = weakref.WeakKeyDictionary()

    @asynccontextmanager
    async def hold(self, key: KeyT) -> AsyncIterator[None]:
        loop = asyncio.get_running_loop()
        with self._guard:
            entries = self._entries_by_loop.get(loop)
            if entries is None:
                entries = {}
                self._entries_by_loop[loop] = entries
            entry = entries.get(key)
            if entry is None:
                entry = _Entry()
                entries[key] = entry
            entry.participants += 1

        acquired = False
        try:
            await entry.lock.acquire()
            acquired = True
            yield
        finally:
            if acquired:
                entry.lock.release()
            with self._guard:
                entry.participants -= 1
                if entry.participants == 0:
                    current_entries = self._entries_by_loop.get(loop)
                    if current_entries is not None and current_entries.get(key) is entry:
                        del current_entries[key]
                        if not current_entries:
                            del self._entries_by_loop[loop]

    def _entry_count(self) -> int:
        """Return the number of entries for the current loop (for diagnostics/tests)."""
        loop = asyncio.get_running_loop()
        with self._guard:
            return len(self._entries_by_loop.get(loop, {}))
