"""``KurrentRunEventStore``: DeerFlow run events in one KurrentDB stream per thread."""

from __future__ import annotations

from typing import Any

from .store import (
    BOUNDARY_EVENT_TYPES,
    RUN_EVENT_TYPE,
    RUNS_COMPACTED_EVENT_TYPE,
    THREAD_CLEARED_EVENT_TYPE,
    KurrentRunEventStore,
    KurrentRunEventStoreCorruption,
    KurrentRunEventWriteError,
    encode_record,
)

__all__ = [
    "BOUNDARY_EVENT_TYPES",
    "RUN_EVENT_TYPE",
    "RUNS_COMPACTED_EVENT_TYPE",
    "THREAD_CLEARED_EVENT_TYPE",
    "KurrentRunEventStore",
    "KurrentRunEventStoreCorruption",
    "KurrentRunEventWriteError",
    "encode_record",
    "make_store",
]


def make_store(config: Any) -> KurrentRunEventStore:
    """The ``run_events.backend: kurrent`` factory; settings come from the environment."""
    return KurrentRunEventStore(config)
