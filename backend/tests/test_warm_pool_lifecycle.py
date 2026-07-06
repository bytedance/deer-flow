"""Unit tests for shared warm-pool lifecycle mechanics."""

from __future__ import annotations

import threading
import time
from typing import Any

from deerflow.community.warm_pool_lifecycle import DEFAULT_IDLE_TIMEOUT, DEFAULT_REPLICAS, WarmPoolLifecycleMixin


class _Provider(WarmPoolLifecycleMixin[str]):
    _idle_checker_thread_name = "test-warm-pool-reaper"

    def __init__(self, *, replicas: int = DEFAULT_REPLICAS, idle_timeout: float = DEFAULT_IDLE_TIMEOUT, active_count: int = 0) -> None:
        self._lock = threading.Lock()
        self._warm_pool: dict[str, tuple[str, float]] = {}
        self._config: dict[str, Any] = {"replicas": replicas, "idle_timeout": idle_timeout}
        self._idle_checker_stop = threading.Event()
        self._idle_checker_thread: threading.Thread | None = None
        self.active_count = active_count
        self.destroyed: list[tuple[str, str, str]] = []

    def _active_count_locked(self) -> int:
        return self.active_count

    def _destroy_warm_entry(self, sandbox_id: str, entry: str, *, reason: str) -> None:
        self.destroyed.append((sandbox_id, entry, reason))


def test_replica_count_includes_active_and_warm_entries() -> None:
    provider = _Provider(replicas=2, active_count=1)
    provider._warm_pool["warm-1"] = ("entry-1", time.time())

    assert provider._replica_count() == (2, 2)


def test_evict_oldest_warm_removes_and_destroys_oldest_entry() -> None:
    provider = _Provider()
    provider._warm_pool["new"] = ("entry-new", 200.0)
    provider._warm_pool["old"] = ("entry-old", 100.0)

    evicted = provider._evict_oldest_warm()

    assert evicted == "old"
    assert "old" not in provider._warm_pool
    assert "new" in provider._warm_pool
    assert provider.destroyed == [("old", "entry-old", "replica_enforcement")]


def test_evict_oldest_warm_returns_none_when_pool_empty() -> None:
    provider = _Provider()

    assert provider._evict_oldest_warm() is None
    assert provider.destroyed == []


def test_reap_expired_warm_destroys_only_expired_entries() -> None:
    provider = _Provider()
    now = time.time()
    provider._warm_pool["expired"] = ("entry-expired", now - 100)
    provider._warm_pool["fresh"] = ("entry-fresh", now)

    provider._reap_expired_warm(idle_timeout=10)

    assert "expired" not in provider._warm_pool
    assert "fresh" in provider._warm_pool
    assert provider.destroyed == [("expired", "entry-expired", "idle_timeout")]


def test_reap_expired_warm_noops_when_timeout_disabled() -> None:
    provider = _Provider(idle_timeout=0)
    provider._warm_pool["expired"] = ("entry-expired", time.time() - 100)

    provider._reap_expired_warm(idle_timeout=0)

    assert "expired" in provider._warm_pool
    assert provider.destroyed == []


def test_start_idle_checker_uses_monkeypatchable_interval(monkeypatch) -> None:
    provider = _Provider(idle_timeout=0.01)
    monkeypatch.setattr(_Provider, "IDLE_CHECK_INTERVAL", 0.01)
    provider._warm_pool["expired"] = ("entry-expired", time.time() - 10)

    provider._start_idle_checker()
    deadline = time.time() + 1
    while "expired" in provider._warm_pool and time.time() < deadline:
        time.sleep(0.01)
    provider._stop_idle_checker()

    assert "expired" not in provider._warm_pool
    assert provider.destroyed == [("expired", "entry-expired", "idle_timeout")]
    assert provider._idle_checker_thread is not None
    assert not provider._idle_checker_thread.is_alive()
