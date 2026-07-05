"""Regression tests for the per-engine SQLite bootstrap lock cache.

The cache (``deerflow.persistence.bootstrap._SQLITE_LOCKS``) maps an engine
to the ``asyncio.Lock`` that serialises its in-process bootstrap. It is keyed
by the engine object itself via ``WeakKeyDictionary`` -- not ``id(engine)`` --
to avoid two failure modes that are silent in production (one long-lived
engine) but real in pytest (one fresh engine per test):

1. **CPython id reuse.** After an engine is garbage-collected its memory
   address can be reused by a new engine. An ``id``-keyed cache would hand
   the new engine the dead engine's ``Lock``. That lock was bound to the
   dead engine's event loop at first ``async with``; pytest gives each async
   test its own loop, so reusing it raises ``RuntimeError: ... bound to a
   different event loop``.
2. **Unbounded growth.** An ``id``-keyed cache never drops entries because
   nothing notifies it when the engine dies. With ``WeakKeyDictionary`` the
   entry disappears as soon as the engine is collected.

These tests do not open any DB connection -- they exercise the cache helper
directly so they can run without an event loop and without aiosqlite warnings
about unclosed engines.
"""

from __future__ import annotations

import gc
import weakref

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from deerflow.persistence import bootstrap as bootstrap_mod
from deerflow.persistence.bootstrap import _get_sqlite_local_lock


def _make_engine():
    return create_async_engine("sqlite+aiosqlite:///:memory:")


def test_cache_is_weak_key_dictionary() -> None:
    """Pin the cache type so a refactor cannot silently revert to a plain
    dict (which would reintroduce the id-reuse bug)."""
    assert isinstance(bootstrap_mod._SQLITE_LOCKS, weakref.WeakKeyDictionary)


def test_same_engine_returns_same_lock() -> None:
    engine = _make_engine()
    assert _get_sqlite_local_lock(engine) is _get_sqlite_local_lock(engine)


def test_distinct_engines_get_distinct_locks() -> None:
    """Two live engines must not share a lock -- otherwise unrelated
    bootstraps would serialise against each other."""
    engine_a = _make_engine()
    engine_b = _make_engine()
    assert _get_sqlite_local_lock(engine_a) is not _get_sqlite_local_lock(engine_b)


def test_entry_drops_when_engine_is_garbage_collected() -> None:
    """The cache must not pin the engine alive.

    This is the structural guarantee behind the id-reuse fix: when the engine
    is collected, its lock entry goes with it, so a future engine landing on
    the same address cannot inherit a stale, loop-bound lock.
    """
    engine = _make_engine()
    _get_sqlite_local_lock(engine)
    assert engine in bootstrap_mod._SQLITE_LOCKS

    engine_ref = weakref.ref(engine)
    del engine
    gc.collect()

    assert engine_ref() is None, "engine should be collectible -- cache must not hold a strong ref"
    # WeakKeyDictionary may defer removal until the next access; touch it.
    assert all(ref() is not None for ref in bootstrap_mod._SQLITE_LOCKS.keyrefs())


@pytest.mark.asyncio
async def test_fresh_engine_gets_lock_usable_on_current_loop() -> None:
    """End-to-end guard for the pytest pattern: a brand-new engine in a
    brand-new event loop must receive a lock that ``async with`` accepts.

    This is the behaviour an ``id``-keyed cache could break if the new engine
    landed on a previously-used address -- it would return a lock bound to a
    dead loop and raise ``RuntimeError: ... bound to a different event loop``.
    """
    engine = _make_engine()
    try:
        lock = _get_sqlite_local_lock(engine)
        async with lock:
            pass
        # Re-entrant acquire on the same loop must also succeed.
        async with lock:
            pass
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_cache_does_not_grow_across_disposed_engines() -> None:
    """Create + dispose + drop many engines and assert the cache stays bounded.

    Without ``WeakKeyDictionary`` this loop would leak one entry per engine.
    """
    initial = len(bootstrap_mod._SQLITE_LOCKS)
    for _ in range(20):
        engine = _make_engine()
        _get_sqlite_local_lock(engine)
        await engine.dispose()
        del engine
    gc.collect()
    # Touch the dict so WeakKeyDictionary clears any deferred removals.
    _ = list(bootstrap_mod._SQLITE_LOCKS.items())
    # Allow a small slack for any engine that is still pinned by a frame.
    assert len(bootstrap_mod._SQLITE_LOCKS) - initial <= 1
