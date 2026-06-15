"""Backend-side metrics for the render_ui tool.

Tracks invocation counts, error rates, and latency per component type.
Uses in-memory counters consistent with the telemetry pattern in
app/gateway/routers/genui_telemetry.py.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field


@dataclass
class _ComponentMetrics:
    invocations: int = 0
    errors: int = 0
    durations_ms: list[float] = field(default_factory=list)


class RenderUIMetrics:
    """Thread-safe metrics collector for render_ui tool invocations."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_component: dict[str, _ComponentMetrics] = defaultdict(_ComponentMetrics)
        self._total_invocations: int = 0
        self._total_errors: int = 0

    def record_invocation(self, component: str, duration_ms: float, error: bool = False) -> None:
        with self._lock:
            self._total_invocations += 1
            m = self._by_component[component]
            m.invocations += 1
            m.durations_ms.append(duration_ms)
            if error:
                self._total_errors += 1
                m.errors += 1

    @contextmanager
    def measure(self, component: str) -> Generator[None, None, None]:
        start = time.perf_counter()
        error = False
        try:
            yield
        except Exception:
            error = True
            raise
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            self.record_invocation(component, duration_ms, error=error)

    def summary(self) -> dict:
        with self._lock:
            components = {}
            for name, m in self._by_component.items():
                avg = sum(m.durations_ms) / len(m.durations_ms) if m.durations_ms else 0
                p95 = sorted(m.durations_ms)[int(len(m.durations_ms) * 0.95)] if m.durations_ms else 0
                components[name] = {
                    "invocations": m.invocations,
                    "errors": m.errors,
                    "avg_duration_ms": round(avg, 2),
                    "p95_duration_ms": round(p95, 2),
                }
            return {
                "total_invocations": self._total_invocations,
                "total_errors": self._total_errors,
                "error_rate": round(self._total_errors / self._total_invocations, 4) if self._total_invocations else 0,
                "by_component": components,
            }

    def reset(self) -> None:
        with self._lock:
            self._by_component.clear()
            self._total_invocations = 0
            self._total_errors = 0


_metrics = RenderUIMetrics()


def get_render_ui_metrics() -> RenderUIMetrics:
    return _metrics
