"""In-memory health-check metrics.

Tracks ``health_check_total{backend, status}`` counters exposed via
``GET /health/metrics`` (plain-text, Prometheus-compatible format).
"""

from __future__ import annotations

import threading
from collections import Counter

_lock = threading.Lock()
_counters: Counter[tuple[str, str]] = Counter()


def record_health_check(backend: str, status: str) -> None:
    """Increment the health-check counter for *backend* / *status*."""
    with _lock:
        _counters[(backend, status)] += 1


def get_health_metrics() -> dict[str, int]:
    """Return a snapshot of all health-check counters."""
    with _lock:
        return {f"{b},{s}": v for (b, s), v in _counters.items()}


def format_prometheus() -> str:
    """Render counters in Prometheus text-exposition format."""
    with _lock:
        lines = [
            "# TYPE health_check_total counter",
            "# HELP health_check_total Health check results by backend and status.",
        ]
        for (backend, status), value in sorted(_counters.items()):
            lines.append(f'health_check_total{{backend="{backend}",status="{status}"}} {value}')
        return "\n".join(lines) + "\n"


def reset_health_metrics() -> None:
    """Reset all counters (for tests)."""
    with _lock:
        _counters.clear()
