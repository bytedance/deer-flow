"""In-memory telemetry collector for knowledge base indexing and retrieval.

Mirrors the pattern in ``report_templates/telemetry.py``:
thread-safe counters + JSONL file append for offline reconstruction.
No external observability dependencies.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

logger = logging.getLogger(__name__)


class KbTelemetryCollector:
    """Thread-safe in-memory counter bag with optional JSONL flush."""

    def __init__(self, *, log_path: str | None = None) -> None:
        self._lock = threading.Lock()
        self._log_path = Path(log_path) if log_path else None
        self._counters: dict[str, int] = {}
        self._latencies: dict[str, list[float]] = {}

    # -- counters -------------------------------------------------------

    def increment(self, key: str, delta: int = 1) -> None:
        with self._lock:
            self._counters[key] = self._counters.get(key, 0) + delta

    def get(self, key: str) -> int:
        with self._lock:
            return self._counters.get(key, 0)

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(self._counters)

    # -- latency --------------------------------------------------------

    def record_latency(self, kb_id: str, latency_ms: float) -> None:
        with self._lock:
            if kb_id not in self._latencies:
                self._latencies[kb_id] = []
            self._latencies[kb_id].append(latency_ms)
            # Keep last 1000 samples per KB
            if len(self._latencies[kb_id]) > 1000:
                self._latencies[kb_id] = self._latencies[kb_id][-1000:]

    def latency_stats(self, kb_id: str) -> dict[str, float]:
        """Return {avg_ms, p95_ms, total_queries} for a knowledge base."""
        with self._lock:
            samples = list(self._latencies.get(kb_id, []))
        if not samples:
            return {"avg_ms": 0.0, "p95_ms": 0.0, "total_queries": 0}
        avg = sum(samples) / len(samples)
        p95 = sorted(samples)[int(len(samples) * 0.95)]
        return {
            "avg_ms": round(avg, 2),
            "p95_ms": round(p95, 2),
            "total_queries": len(samples),
        }

    # -- event recording ------------------------------------------------

    def record_event(self, event_type: str, payload: dict) -> None:
        """Record a structured event (index success/fail/cancel, query, etc.).

        Increments counters and optionally appends to the JSONL log.
        """
        self.increment(f"event.{event_type}")
        if self._log_path and self._log_path.parent.exists():
            try:
                entry = {"type": event_type, **payload}
                with open(self._log_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
            except OSError:
                pass  # best-effort; don't crash the pipeline for telemetry

    def clear(self) -> None:
        """Reset all counters (useful in tests)."""
        with self._lock:
            self._counters.clear()
            self._latencies.clear()


# Module-level singleton
_collector: KbTelemetryCollector | None = None
_collector_lock = threading.Lock()


def get_kb_telemetry() -> KbTelemetryCollector:
    global _collector
    if _collector is None:
        with _collector_lock:
            if _collector is None:
                _collector = KbTelemetryCollector()
    return _collector


def init_kb_telemetry(*, log_path: str | None = None) -> KbTelemetryCollector:
    global _collector
    with _collector_lock:
        _collector = KbTelemetryCollector(log_path=log_path)
        return _collector
