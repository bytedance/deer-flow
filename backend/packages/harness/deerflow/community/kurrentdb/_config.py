"""Shared config-parsing helpers for the KurrentDB community integrations.

Kept tiny and dependency-free (stdlib only) so both the memory storage
(``memory_storage.py``) and the run event store (``run_event_store.py``) can
import it without pulling in kurrentdbclient at module load time.
"""

from __future__ import annotations

import logging
import math
import os

logger = logging.getLogger(__name__)


def resolve_timeout_seconds(env_var: str, default: float) -> float:
    """Parse a positive finite float timeout from an environment variable.

    Falls back to ``default`` (with a logged warning) when the variable is
    unset, not a number, non-positive, or non-finite (``inf``/``nan``).
    """
    raw = os.environ.get(env_var, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        logger.warning("Invalid %s %r: not a number, using default %s", env_var, raw, default)
        return default
    if not math.isfinite(value) or value <= 0:
        logger.warning("Invalid %s %r: must be a positive finite number, using default %s", env_var, raw, default)
        return default
    return value
