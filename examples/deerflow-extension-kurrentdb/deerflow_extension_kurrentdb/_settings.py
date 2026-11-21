"""Settings for every KurrentDB component, read only from environment variables.

The memory storage is constructed by DeerMem from a dotted path, possibly in a
process where the plugin was never loaded, so ``plugins[].config`` cannot reach
it. The environment is the single source for all components.
"""

from __future__ import annotations

import math
import os
from collections.abc import Mapping
from dataclasses import dataclass

CONNECTION_STRING_ENV = "KURRENTDB_CONNECTION_STRING"
TIMEOUT_ENV = "KURRENTDB_TIMEOUT_SECONDS"
CANONICAL_EVENTS_ENV = "KURRENTDB_CANONICAL_EVENTS"

DEFAULT_TIMEOUT_SECONDS = 10.0
_TRUTHY = frozenset({"1", "true", "yes", "on"})


@dataclass(frozen=True, slots=True)
class KurrentSettings:
    connection_string: str
    timeout: float
    canonical_events: bool


def load_settings(environ: Mapping[str, str] | None = None) -> KurrentSettings:
    env = os.environ if environ is None else environ
    connection_string = env.get(CONNECTION_STRING_ENV, "").strip()
    if not connection_string:
        raise ValueError(f"{CONNECTION_STRING_ENV} must be set to a KurrentDB connection string")
    return KurrentSettings(connection_string=connection_string, timeout=_timeout(env.get(TIMEOUT_ENV)), canonical_events=env.get(CANONICAL_EVENTS_ENV, "").strip().lower() in _TRUTHY)


def _timeout(raw: str | None) -> float:
    if raw is None:
        return DEFAULT_TIMEOUT_SECONDS
    try:
        value = float(raw.strip())
    except ValueError:
        raise ValueError(f"{TIMEOUT_ENV} must be a number of seconds, got {raw!r}") from None
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{TIMEOUT_ENV} must be finite and greater than zero, got {raw!r}")
    return value
