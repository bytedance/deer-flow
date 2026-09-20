"""Canonical MCP session scope construction."""

from __future__ import annotations

import json
from typing import Any, TypeGuard

THREAD_INCARNATION_CONTEXT_KEY = "thread_incarnation"
THREAD_INCARNATION_METADATA_GUARD_KEY = "__deerflow_thread_incarnation_metadata_guard"
_MISSING = object()


def is_valid_thread_incarnation(value: object) -> TypeGuard[str | None]:
    """Return whether *value* is a supported legacy or versioned incarnation."""
    return value is None or (isinstance(value, str) and bool(value))


def mcp_session_scope_key(
    *,
    user_id: str,
    thread_id: str,
    thread_incarnation: str | None = None,
) -> str:
    """Return the canonical user/thread/incarnation session key.

    A legacy NULL incarnation retains the pre-activation scope so rolling
    upgrades do not split an existing legacy session.
    """
    if not is_valid_thread_incarnation(thread_incarnation):
        raise RuntimeError("MCP session scope requires a non-empty thread incarnation")
    scope = f"{user_id}:{thread_id}"
    if thread_incarnation is None:
        return scope
    # A JSON tuple is an unambiguous, versioned encoding even when an opaque
    # user/thread id contains the delimiter used by the legacy scope.
    return "v2:" + json.dumps(
        [user_id, thread_id, thread_incarnation],
        ensure_ascii=True,
        separators=(",", ":"),
    )


def runtime_thread_incarnation(runtime: Any | None) -> str | None:
    """Read the server-owned incarnation from ``ToolRuntime.context``."""
    if runtime is None:
        # Direct tool invocation has no Agent thread lifecycle and retains the
        # legacy scope. An actual runtime with a missing key remains invalid.
        return None
    context = getattr(runtime, "context", None)
    if not isinstance(context, dict) or THREAD_INCARNATION_CONTEXT_KEY not in context:
        raise RuntimeError("MCP tool execution requires a server-owned thread incarnation")
    value = context[THREAD_INCARNATION_CONTEXT_KEY]
    if not is_valid_thread_incarnation(value):
        raise RuntimeError("MCP tool execution received an invalid thread incarnation")
    if context.get(THREAD_INCARNATION_METADATA_GUARD_KEY) is True:
        config = getattr(runtime, "config", None)
        metadata = config.get("metadata") if isinstance(config, dict) else None
        persisted = metadata.get(THREAD_INCARNATION_CONTEXT_KEY, _MISSING) if isinstance(metadata, dict) else _MISSING
        if persisted is _MISSING:
            if value is not None:
                raise RuntimeError("MCP tool execution received a stale thread incarnation")
        elif not is_valid_thread_incarnation(persisted) or persisted != value:
            raise RuntimeError("MCP tool execution received a stale thread incarnation")
    return value
