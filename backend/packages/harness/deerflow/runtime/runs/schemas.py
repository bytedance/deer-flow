"""Compatibility exports for run status and disconnect mode enums."""

# Existing callers import these enums from ``runs.schemas``. Re-export the
# domain definitions until all imports move to ``runs.domain``.
from .domain import DisconnectMode, RunStatus

__all__ = [
    "DisconnectMode",
    "RunStatus",
]
