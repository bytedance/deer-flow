"""Async per-key serialization with waiter-aware entry reclamation."""

from __future__ import annotations

import asyncio
import threading
import weakref
from collections.abc import AsyncIterator, Hashable
from contextlib import asynccontextmanager
from dataclasses import dataclass


@dataclass(slots=True)
class _Entry:
    lock: asyncio.Lock
    participants: int = 0  # current holder plus queued waiters


class AsyncKeyedLockTable[KeyT: Hashable]:
    """Serialize same-key work without retaining idle keys.

    A table may be shared by event loops running in different threads. Each
    loop receives its own entries because ``asyncio.Lock`` instances become
    loop-affine once contended. The thread lock protects only the registry;
    async critical sections never hold it.

    Participants are counted before awaiting the lock. This keeps an entry
    discoverable until its final holder or waiter leaves, so a new caller
    cannot create a second lock and bypass an already queued waiter. Cancelled
    waiters check their participation back in through the same ``finally``
    path.
    """

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._entries_by_loop: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict[KeyT, _Entry]] = weakref.WeakKeyDictionary()

    @asynccontextmanager
    async def hold(self, key: KeyT) -> AsyncIterator[None]:
        """Hold the current event loop's lock for ``key``."""
        loop = asyncio.get_running_loop()
        entries, entry = self._checkout(loop, key)
        acquired = False
        try:
            await entry.lock.acquire()
            acquired = True
            yield
        finally:
            try:
                if acquired:
                    entry.lock.release()
            finally:
                self._checkin(loop, entries, key, entry)

    def _checkout(
        self,
        loop: asyncio.AbstractEventLoop,
        key: KeyT,
    ) -> tuple[dict[KeyT, _Entry], _Entry]:
        with self._guard:
            entries = self._entries_by_loop.get(loop)
            if entries is None:
                entries = {}
                self._entries_by_loop[loop] = entries
            entry = entries.get(key)
            if entry is None:
                entry = _Entry(lock=asyncio.Lock())
                entries[key] = entry
            entry.participants += 1
            return entries, entry

    def _checkin(
        self,
        loop: asyncio.AbstractEventLoop,
        entries: dict[KeyT, _Entry],
        key: KeyT,
        entry: _Entry,
    ) -> None:
        with self._guard:
            entry.participants -= 1
            if entry.participants != 0 or entry.lock.locked():
                return
            if entries.get(key) is not entry:
                return
            entries.pop(key)
            if not entries and self._entries_by_loop.get(loop) is entries:
                self._entries_by_loop.pop(loop, None)
