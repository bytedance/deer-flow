"""Worker identification for multi-worker deployments.

Generates a unique ``WORKER_ID`` (8-char hex) at import time and provides
a :class:`logging.Filter` that injects it into every log record.
"""

from __future__ import annotations

import logging
import uuid

WORKER_ID: str = uuid.uuid4().hex[:8]


class WorkerIdFilter(logging.Filter):
    """Inject ``worker_id`` into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.worker_id = WORKER_ID  # type: ignore[attr-defined]
        return True


def apply_worker_id_filter() -> None:
    """Attach the worker-id filter to all root handlers so every log line gets ``worker_id``."""
    filt = WorkerIdFilter()
    for handler in logging.root.handlers:
        handler.addFilter(filt)
