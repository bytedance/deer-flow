"""Concurrency regression tests for the MCP session-pool singleton lifecycle.

These guard the module-level ``get_session_pool`` / ``reset_session_pool``
singleton in ``deerflow.mcp.session_pool``. ``reset_session_pool`` is reachable
in production through the ``/api/mcp/cache/reset`` admin endpoint
(``reset_mcp_tools_cache`` closes the pool so it is rebuilt on the next tool
load), and the harness runs the main event loop alongside channel threads on
their own loops, so a reset can race a concurrent ``get_session_pool``. Before
the lock was extended to cover the return, ``get_session_pool`` re-read the
global after its fast-path ``None`` check, so a ``reset_session_pool`` landing in
that window handed the caller ``None`` despite the ``-> MCPSessionPool``
annotation.

This mirrors ``test_skill_storage_lifecycle.py`` — the sibling singleton fixed
the same way in #3778 — adapted to the session pool, whose ``MCPSessionPool`` is
cheap to construct and already serialises creation, so the gap that mattered
here was the reset racing the get's return.
"""

import sys
import threading

from deerflow.mcp.session_pool import (
    MCPSessionPool,
    get_session_pool,
    reset_session_pool,
)


def test_get_session_pool_returns_one_singleton_under_concurrent_cold_start():
    """Threads racing a cold start all observe the same single instance."""
    reset_session_pool()
    n_threads = 8
    pools: list[MCPSessionPool] = []
    pools_lock = threading.Lock()
    # Barrier makes all threads enter get_session_pool() together, so the
    # cold-start race is triggered rather than left to chance.
    barrier = threading.Barrier(n_threads)

    def get_pool() -> None:
        barrier.wait()
        pool = get_session_pool()
        with pools_lock:
            pools.append(pool)

    threads = [threading.Thread(target=get_pool) for _ in range(n_threads)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    try:
        assert len(pools) == n_threads
        assert len({id(pool) for pool in pools}) == 1
    finally:
        reset_session_pool()


def test_reset_racing_get_never_returns_none():
    """A reset racing concurrent gets must never hand back ``None``.

    Getters and a resetter run in tight loops while the interpreter is forced to
    switch threads very often, so the reset repeatedly lands while a getter is
    between its fast-path ``None`` check and its return — the interleaving that
    the unlocked check-then-return path turned into a ``None`` return. Without
    the lock covering the return this reliably observes ``None``; with it, never.
    """
    reset_session_pool()
    none_seen: list[int] = []
    none_seen_lock = threading.Lock()
    stop = threading.Event()

    def getter() -> None:
        while not stop.is_set():
            if get_session_pool() is None:
                with none_seen_lock:
                    none_seen.append(1)

    def resetter() -> None:
        for _ in range(100000):
            reset_session_pool()
        stop.set()

    previous_interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        getters = [threading.Thread(target=getter) for _ in range(4)]
        reset_thread = threading.Thread(target=resetter)
        for thread in getters:
            thread.start()
        reset_thread.start()
        for thread in getters:
            thread.join()
        reset_thread.join()
    finally:
        sys.setswitchinterval(previous_interval)
        reset_session_pool()

    assert not none_seen, "get_session_pool() returned None while a reset raced it"
