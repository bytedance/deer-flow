"""Map checkpoint-mode guard failures to precise HTTP statuses.

A mismatch means the thread's persisted checkpoints conflict with the process's
frozen mode (operator-actionable, 409); a reconfiguration means the process
itself is mid mode-flip (transient, 503). Both must surface their message — a
generic 500 would force operators to grep logs to discover the root cause after
a mode flip.
"""

from __future__ import annotations

from fastapi import HTTPException

from deerflow.runtime.checkpoint_mode import CheckpointModeMismatchError, CheckpointModeReconfigurationError

CHECKPOINT_MODE_ERRORS = (CheckpointModeMismatchError, CheckpointModeReconfigurationError)


def checkpoint_mode_http_error(exc: Exception, thread_id: str) -> HTTPException:
    """Return the HTTP error for a checkpoint-mode guard failure."""
    if isinstance(exc, CheckpointModeMismatchError):
        return HTTPException(status_code=409, detail=f"Thread {thread_id}: {exc}")
    return HTTPException(status_code=503, detail=str(exc))
