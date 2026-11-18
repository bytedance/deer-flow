"""KurrentDB storage for DeerFlow: run events and memory, canonical kurrent-agents events, and a deletion recovery service."""

from __future__ import annotations

from typing import Any

from deerflow_extension_api import extension

from .service import KurrentRecoveryService

__all__ = ["KurrentRecoveryService", "install"]

RUN_EVENT_BACKEND = "kurrent"


def _make_run_event_store(run_events_config: Any) -> Any:
    # Imported on first use so installing the plugin neither loads the store nor connects.
    from .run_events import make_store

    return make_store(run_events_config)


@extension(api="0.2.14", name="kurrentdb")
def install(registry, config):
    if not registry.run_event_store(RUN_EVENT_BACKEND, _make_run_event_store):
        raise RuntimeError(f"This host does not support extension run-event store backends (needed for run_events.backend: {RUN_EVENT_BACKEND})")
    # Recovery of open deletions (ruling R1): primary sides at start, canonical obligations in the background.
    registry.service(KurrentRecoveryService())
