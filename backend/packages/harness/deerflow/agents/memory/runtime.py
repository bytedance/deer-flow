"""Runtime helpers for per-run memory behavior."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

MEMORY_ENABLED_CONTEXT_KEY = "memory_enabled"


def is_runtime_memory_injection_enabled(runtime: Any) -> bool:
    """Return False only when the caller explicitly opts out of memory injection."""
    context = getattr(runtime, "context", None)
    return not (isinstance(context, Mapping) and context.get(MEMORY_ENABLED_CONTEXT_KEY) is False)
