"""Run status and disconnect mode enums.

ISSUE-02: RunStatus and canonical_run_status() are now imported from the shared
canonical source.  This module re-exports them for backward compatibility.
New code should import directly from ``deerflow.shared.status``.
"""

from __future__ import annotations

from enum import StrEnum

from deerflow.shared.status import RunStatus, canonical_run_status  # noqa: F401 — re-export


class DisconnectMode(StrEnum):
    """Behaviour when the SSE consumer disconnects."""

    cancel = "cancel"
    continue_ = "continue"
