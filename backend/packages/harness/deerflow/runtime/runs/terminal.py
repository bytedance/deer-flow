"""Shared terminal-run helpers.

Single source of truth for the set of terminal run statuses and the SSE
``end`` frame payload shape.  Both the router-level terminal short-circuit
(``thread_runs.py``) and the service-layer terminal reconciliation
(``services.py``) import from here so the three ``end`` paths (real END,
short-circuit end, synthetic end) never drift apart.

This module lives in the harness ``runtime`` layer and must only return
plain Python data.  It must not depend on FastAPI / Gateway / SSE
formatting helpers — those belong to the ``app/gateway`` layer.
"""

from __future__ import annotations

from .manager import RunRecord
from .schemas import RunStatus

TERMINAL_STATUSES: tuple[RunStatus, ...] = (
    RunStatus.success,
    RunStatus.error,
    RunStatus.timeout,
    RunStatus.interrupted,
)


def build_end_payload(record: RunRecord) -> dict:
    """Build the canonical terminal ``end`` frame payload.

    Single construction point shared by the J short-circuit and the K
    reconciliation so all ``end`` frames carry the same ``{status, error}``
    schema.
    """
    return {"status": record.status.value, "error": record.error}
