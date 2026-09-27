"""Canonical MCP session scope construction."""

from __future__ import annotations

import json
from typing import Any, TypeGuard

THREAD_INCARNATION_CONTEXT_KEY = "thread_incarnation"
THREAD_INCARNATION_METADATA_GUARD_KEY = "__deerflow_thread_incarnation_metadata_guard"
_MISSING = object()

# Prefix that distinguishes a versioned scope from the legacy ``user:thread``
# encoding. Shared with :func:`mcp_scope_belongs_to_thread` so the two can
# never drift apart.
_V2_SCOPE_PREFIX = "v2:"


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
    return _V2_SCOPE_PREFIX + json.dumps(
        [user_id, thread_id, thread_incarnation],
        ensure_ascii=True,
        separators=(",", ":"),
    )


def mcp_scope_belongs_to_thread(scope_key: str, *, user_id: str, thread_id: str) -> bool:
    """Return whether *scope_key* was minted for this user/thread identity.

    Matches both encodings :func:`mcp_session_scope_key` can produce: the legacy
    ``user:thread`` scope (NULL incarnation) and the versioned
    ``v2:[user, thread, incarnation]`` scope. The incarnation is deliberately
    *not* compared — a caller tearing down a whole thread has to invalidate every
    generation of it, and the current generation cannot be read reliably at
    teardown time (see ``MCPSessionPool.close_thread_scope``).

    The legacy branch is a prefix-free string compare, so a crafted ``user_id``
    containing ``:`` can collide with another owner's legacy key. That can only
    ever over-close (tear down an extra session), never leak one, and the
    versioned encoding — which every incarnation-aware caller uses — is exact.
    """
    if scope_key == f"{user_id}:{thread_id}":
        return True
    if not scope_key.startswith(_V2_SCOPE_PREFIX):
        return False
    try:
        decoded = json.loads(scope_key[len(_V2_SCOPE_PREFIX) :])
    except ValueError:
        return False
    return isinstance(decoded, list) and len(decoded) == 3 and decoded[0] == user_id and decoded[1] == thread_id


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
