"""Tests for KbTelemetryCollector.

Covers: counters, latency recording + stats, event recording, JSONL sink,
thread safety, singleton lifecycle, and clear/reset.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from deerflow.knowledge_base.telemetry import (
    KbTelemetryCollector,
    get_kb_telemetry,
    init_kb_telemetry,
)


# ---------------------------------------------------------------------------
# Counters
# ---------------------------------------------------------------------------


class TestCounters:
    def test_increment_default(self):
        t = KbTelemetryCollector()
        t.increment("hits")
        assert t.get("hits") == 1

    def test_increment_custom_delta(self):
        t = KbTelemetryCollector()
        t.increment("hits", delta=5)
        assert t.get("hits") == 5

    def test_increment_accumulates(self):
        t = KbTelemetryCollector()
        t.increment("hits")
        t.increment("hits")
        t.increment("hits", delta=3)
        assert t.get("hits") == 5

    def test_get_missing_key_returns_zero(self):
        t = KbTelemetryCollector()
        assert t.get("nonexistent") == 0

    def test_snapshot_returns_copy(self):
        t = KbTelemetryCollector()
        t.increment("a")
        t.increment("b", delta=2)
        snap = t.snapshot()
        assert snap == {"a": 1, "b": 2}
        snap["a"] = 999
        assert t.get("a") == 1

    def test_clear_resets_all(self):
        t = KbTelemetryCollector()
        t.increment("x")
        t.record_latency("kb-1", 10.0)
        t.clear()
        assert t.get("x") == 0
        assert t.latency_stats("kb-1")["total_queries"] == 0


# ---------------------------------------------------------------------------
# Latency
# ---------------------------------------------------------------------------


class TestLatency:
    def test_record_single_latency(self):
        t = KbTelemetryCollector()
        t.record_latency("kb-1", 50.0)
        stats = t.latency_stats("kb-1")
        assert stats["avg_ms"] == 50.0
        assert stats["total_queries"] == 1

    def test_latency_stats_empty(self):
        t = KbTelemetryCollector()
        stats = t.latency_stats("missing")
        assert stats == {"avg_ms": 0.0, "p95_ms": 0.0, "total_queries": 0}

    def test_latency_p95(self):
        t = KbTelemetryCollector()
        for i in range(100):
            t.record_latency("kb-1", float(i))
        stats = t.latency_stats("kb-1")
        assert stats["total_queries"] == 100
        assert stats["avg_ms"] == pytest.approx(49.5, abs=0.1)
        assert stats["p95_ms"] == 95.0

    def test_latency_cap_at_1000_samples(self):
        t = KbTelemetryCollector()
        for i in range(1200):
            t.record_latency("kb-1", float(i))
        stats = t.latency_stats("kb-1")
        assert stats["total_queries"] == 1000

    def test_latency_per_kb_isolation(self):
        t = KbTelemetryCollector()
        t.record_latency("kb-a", 10.0)
        t.record_latency("kb-b", 20.0)
        assert t.latency_stats("kb-a")["avg_ms"] == 10.0
        assert t.latency_stats("kb-b")["avg_ms"] == 20.0


# ---------------------------------------------------------------------------
# Event recording
# ---------------------------------------------------------------------------


class TestEventRecording:
    def test_record_event_increments_counter(self):
        t = KbTelemetryCollector()
        t.record_event("index.success", {"kb_id": "kb-1"})
        t.record_event("index.success", {"kb_id": "kb-2"})
        t.record_event("index.failed", {"kb_id": "kb-3"})

        assert t.get("event.index.success") == 2
        assert t.get("event.index.failed") == 1

    def test_record_event_writes_jsonl(self, tmp_path: Path):
        log_file = tmp_path / "telemetry.jsonl"
        t = KbTelemetryCollector(log_path=str(log_file))
        t.record_event("retrieval.completed", {"query": "test", "kb_count": 2})

        lines = log_file.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["type"] == "retrieval.completed"
        assert entry["query"] == "test"
        assert entry["kb_count"] == 2

    def test_record_event_multiple_writes(self, tmp_path: Path):
        log_file = tmp_path / "telemetry.jsonl"
        t = KbTelemetryCollector(log_path=str(log_file))
        t.record_event("a", {"x": 1})
        t.record_event("b", {"y": 2})
        t.record_event("c", {"z": 3})

        lines = log_file.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 3
        types = [json.loads(l)["type"] for l in lines]
        assert types == ["a", "b", "c"]

    def test_record_event_no_log_path_does_not_crash(self):
        t = KbTelemetryCollector(log_path=None)
        t.record_event("test", {"data": "val"})
        assert t.get("event.test") == 1

    def test_record_event_parent_dir_missing_swallows_error(self):
        t = KbTelemetryCollector(log_path="/nonexistent/path/telemetry.jsonl")
        t.record_event("test", {})
        assert t.get("event.test") == 1


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------


class TestThreadSafety:
    def test_concurrent_increments(self):
        t = KbTelemetryCollector()
        barrier = threading.Barrier(8)

        def worker():
            barrier.wait()
            for _ in range(1000):
                t.increment("concurrent")

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()

        assert t.get("concurrent") == 8000

    def test_concurrent_record_event(self, tmp_path: Path):
        log_file = tmp_path / "concurrent.jsonl"
        t = KbTelemetryCollector(log_path=str(log_file))
        barrier = threading.Barrier(4)

        def worker(idx: int):
            barrier.wait()
            for i in range(50):
                t.record_event(f"worker-{idx}", {"i": i})

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()

        for i in range(4):
            assert t.get(f"event.worker-{i}") == 50

        lines = log_file.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) >= 190


# ---------------------------------------------------------------------------
# Singleton lifecycle
# ---------------------------------------------------------------------------


class TestSingleton:
    def test_get_kb_telemetry_returns_same_instance(self):
        import deerflow.knowledge_base.telemetry as mod

        original = mod._collector
        try:
            mod._collector = None
            a = get_kb_telemetry()
            b = get_kb_telemetry()
            assert a is b
        finally:
            mod._collector = original

    def test_init_kb_telemetry_creates_new_instance(self):
        import deerflow.knowledge_base.telemetry as mod

        original = mod._collector
        try:
            old = get_kb_telemetry()
            new = init_kb_telemetry()
            assert new is not old
            assert get_kb_telemetry() is new
        finally:
            mod._collector = original
