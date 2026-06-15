"""Lightweight metrics collection for stream bridge monitoring.

Provides a singleton ``StreamBridgeMetrics`` that tracks:
- Total events published
- Cumulative payload size (for computing averages)
- Per-event-type payload size breakdown
- Current total queue depth across all runs
- Number of backpressure events triggered

This is intentionally simple — no external metrics backend required.
Call ``snapshot()`` to export current counters for logging or Prometheus scraping.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from typing import Any


@dataclass
class _EventTypeStats:
    count: int = 0
    total_bytes: int = 0

    @property
    def avg_bytes(self) -> float:
        return self.total_bytes / self.count if self.count > 0 else 0.0


class StreamBridgeMetrics:
    """Thread-safe metrics collector for stream bridge operations.

    Usage::

        from deerflow.runtime.stream_bridge.metrics import stream_bridge_metrics as metrics

        # On publish:
        metrics.record_publish(event, data)

        # On backpressure:
        metrics.record_backpressure()

        # Track queue depth:
        metrics.set_queue_depth(run_id, depth)

        # Export:
        snapshot = metrics.snapshot()
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._total_published: int = 0
        self._total_payload_bytes: int = 0
        self._by_event_type: dict[str, _EventTypeStats] = {}
        self._backpressure_count: int = 0
        self._queue_depths: dict[str, int] = {}

    def record_publish(self, event: str, data: Any) -> None:
        """Record a published event and its payload size."""
        try:
            payload_bytes = len(json.dumps(data).encode("utf-8"))
        except (TypeError, ValueError):
            payload_bytes = 0

        with self._lock:
            self._total_published += 1
            self._total_payload_bytes += payload_bytes

            if event not in self._by_event_type:
                self._by_event_type[event] = _EventTypeStats()
            stats = self._by_event_type[event]
            stats.count += 1
            stats.total_bytes += payload_bytes

    def record_backpressure(self) -> None:
        """Record a backpressure event (queue full, event dropped/replaced)."""
        with self._lock:
            self._backpressure_count += 1

    def set_queue_depth(self, run_id: str, depth: int) -> None:
        """Update the current queue depth for a specific run."""
        with self._lock:
            if depth <= 0:
                self._queue_depths.pop(run_id, None)
            else:
                self._queue_depths[run_id] = depth

    def remove_run(self, run_id: str) -> None:
        """Remove a run's queue depth tracking (on cleanup)."""
        with self._lock:
            self._queue_depths.pop(run_id, None)

    def snapshot(self) -> dict[str, Any]:
        """Return a point-in-time snapshot of all metrics."""
        with self._lock:
            total_depth = sum(self._queue_depths.values())
            by_type = {
                event_type: {
                    "count": stats.count,
                    "total_bytes": stats.total_bytes,
                    "avg_bytes": round(stats.avg_bytes, 1),
                }
                for event_type, stats in self._by_event_type.items()
            }
            return {
                "total_published": self._total_published,
                "total_payload_bytes": self._total_payload_bytes,
                "avg_payload_bytes": round(
                    self._total_payload_bytes / self._total_published, 1
                )
                if self._total_published > 0
                else 0.0,
                "backpressure_count": self._backpressure_count,
                "active_runs": len(self._queue_depths),
                "total_queue_depth": total_depth,
                "by_event_type": by_type,
            }

    def reset(self) -> None:
        """Reset all metrics (for testing)."""
        with self._lock:
            self._total_published = 0
            self._total_payload_bytes = 0
            self._by_event_type.clear()
            self._backpressure_count = 0
            self._queue_depths.clear()


# Module-level singleton
stream_bridge_metrics = StreamBridgeMetrics()
