"""Per-key serialization with waiter-aware entry reclamation.

:func:`AsyncKeyedLockTable` serves asyncio callers;
:class:`KeyedLockTable` is the thread-side counterpart for blocking
critical sections running on worker threads.
"""

from __future__ import annotations

import asyncio
import threading
import weakref
from collections.abc import AsyncIterator, Hashable, Iterator
from contextlib import asynccontextmanager, contextmanager
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


@dataclass(slots=True)
class _ThreadEntry:
    lock: threading.Lock
    participants: int = 0  # current holder plus queued waiters


class KeyedLockTable[KeyT: Hashable]:
    """Serialize same-key blocking work across worker threads.

    Thread-side counterpart of :class:`AsyncKeyedLockTable`: the guard
    protects only the registry, and the blocking critical section never
    holds it. Participants are counted before acquiring the lock, so an
    entry stays discoverable until its final holder or waiter leaves and a
    new caller cannot create a second lock that bypasses an already queued
    waiter. Entries whose last participant leaves are reclaimed so idle
    keys do not accumulate.
    """

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._entries: dict[KeyT, _ThreadEntry] = {}

    @contextmanager
    def hold(self, key: KeyT) -> Iterator[None]:
        """Hold the lock for ``key``, blocking the calling thread."""
        entry = self._checkout(key)
        acquired = False
        try:
            entry.lock.acquire()
            acquired = True
            yield
        finally:
            if acquired:
                entry.lock.release()
            self._checkin(key, entry)

    def _checkout(self, key: KeyT) -> _ThreadEntry:
        with self._guard:
            entry = self._entries.get(key)
            if entry is None:
                entry = _ThreadEntry(lock=threading.Lock())
                self._entries[key] = entry
            entry.participants += 1
            return entry

    def _checkin(self, key: KeyT, entry: _ThreadEntry) -> None:
        with self._guard:
            entry.participants -= 1
            if entry.participants != 0 or entry.lock.locked():
                return
            if self._entries.get(key) is not entry:
                return
            self._entries.pop(key)
