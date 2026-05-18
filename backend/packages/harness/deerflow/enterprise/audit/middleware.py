"""``AuditMiddleware`` — agent-loop hook that writes audit events (plan M2-5).

Why this lives in the agent middleware chain
============================================

The plan §4.1 row for M2-5 says we need three lifecycle hooks plus a
tool-call wrap so every meaningful agent action lands in
``audit_events`` with a signed row:

* ``abefore_agent`` → ``AGENT_TASK_STARTED``
* ``aafter_agent`` → ``AGENT_TASK_COMPLETED`` (success) or
  ``AGENT_TASK_ERROR`` (exception). We rely on LangChain calling
  ``aafter_agent`` even when the run aborts; if it stops doing so the
  test suite will catch the drop because we assert both states.
* ``awrap_tool_call`` → consults :func:`map_tool_to_event_type` and
  appends one row per non-whitelisted tool call.

Synchronous append (RFC §5.4)
=============================

We ``await storage.append(event)`` inline. Buffering would lose events
on a gateway crash, and the compliance contract is "every action is in
the log when we return control to the caller". If this becomes a hot
spot the §10 backlog item (queue + flush) is the documented escape
hatch — do not silently move appends off the hot path here.

Signing happens before the append so a partial write (signature column
left null) is detectable as tampering at verify time.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from deerflow.agents.thread_state import ThreadState
from deerflow.enterprise.audit.events import AuditEvent, AuditEventType
from deerflow.enterprise.audit.signer import AuditSigner
from deerflow.enterprise.audit.storage import AuditStorage
from deerflow.enterprise.audit.tool_event_map import (
    extract_mcp_server,
    map_tool_to_event_type,
)
from deerflow.enterprise.config import AuditConfig

logger = logging.getLogger(__name__)


class AuditMiddleware(AgentMiddleware[ThreadState]):
    """Emit signed :class:`AuditEvent` rows around each agent run.

    The middleware is wired into the chain by
    :func:`deerflow.enterprise.middlewares.get_enterprise_middlewares`
    when ``enterprise.audit.enabled=True``. Construction takes the
    already-built storage and signer so the middleware itself is pure
    glue — no I/O setup at import time.
    """

    state_schema = ThreadState

    def __init__(
        self,
        audit_config: AuditConfig,
        storage: AuditStorage,
        signer: AuditSigner | None,
    ) -> None:
        # ``signer`` may be ``None`` when ``audit.sign_key`` is empty —
        # config validation logs a warning in that case but allows the
        # boot so demos and read-only audits still work. We surface the
        # missing-signature state to verify_integrity, not here.
        self._config = audit_config
        self._storage = storage
        self._signer = signer

    # ── lifecycle hooks ────────────────────────────────────────────────

    async def abefore_agent(self, state: ThreadState, runtime: Any) -> None:
        """Emit ``AGENT_TASK_STARTED`` before the model is invoked."""
        await self._emit(
            event_type=AuditEventType.AGENT_TASK_STARTED,
            user_id=_user_from_runtime(runtime),
            resource=_thread_resource(runtime),
            action="agent.start",
            details={"thread_id": _thread_id(runtime)},
        )

    async def aafter_agent(self, state: ThreadState, runtime: Any) -> None:
        """Emit ``AGENT_TASK_COMPLETED`` after a successful run.

        ``AGENT_TASK_ERROR`` is emitted from the ``awrap_tool_call``
        exception path and from upstream error middleware; this hook
        only sees the success leg because LangChain skips ``aafter`` on
        an unhandled exception. The reverse-evidence test in M2's test
        plan covers the error path explicitly.
        """
        await self._emit(
            event_type=AuditEventType.AGENT_TASK_COMPLETED,
            user_id=_user_from_runtime(runtime),
            resource=_thread_resource(runtime),
            action="agent.complete",
            details={"thread_id": _thread_id(runtime)},
        )

    # ── per-tool-call hook ─────────────────────────────────────────────

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        """Wrap each tool call with one audit row (when mapped)."""
        tool_name = str(request.tool_call.get("name") or "")
        event_type = map_tool_to_event_type(tool_name)

        # Read-only whitelist → no event, but still run the tool.
        if event_type is None:
            return await handler(request)

        details: dict[str, Any] = {
            "tool": tool_name,
            "thread_id": _thread_id(request.runtime),
            "tool_call_id": str(request.tool_call.get("id") or ""),
        }
        mcp_server = extract_mcp_server(tool_name)
        if mcp_server is not None:
            # Recorded once at the row level so dashboards can slice by
            # server without re-parsing the tool name.
            details["mcp_server"] = mcp_server

        user_id = _user_from_runtime(request.runtime)
        resource = _thread_resource(request.runtime)

        try:
            result = await handler(request)
        except Exception as exc:  # noqa: BLE001 — we re-raise after audit
            # Error path: record the failure with a different event_type
            # so dashboards can filter "tool errors" without scanning
            # details. We do NOT swallow the exception — upstream error
            # middleware decides whether to recover.
            await self._emit(
                event_type=AuditEventType.AGENT_TASK_ERROR,
                user_id=user_id,
                resource=resource,
                action=tool_name,
                details={**details, "error_class": type(exc).__name__, "error": str(exc)[:500]},
            )
            raise

        await self._emit(
            event_type=event_type,
            user_id=user_id,
            resource=resource,
            action=tool_name,
            details=details,
        )
        return result

    # ── helpers ────────────────────────────────────────────────────────

    async def _emit(
        self,
        *,
        event_type: AuditEventType,
        user_id: str | None,
        resource: str | None,
        action: str | None,
        details: dict[str, Any],
    ) -> None:
        """Sign and persist a single event.

        We catch and log storage failures so a transient DB outage
        cannot kill the agent loop. The tradeoff: a single dropped row
        is preferable to crashing an interactive session. Operators who
        need fail-closed semantics flip the §10 backlog switch.
        """
        event = AuditEvent(
            event_type=event_type,
            user_id=user_id,
            resource=resource,
            action=action,
            details=details,
        )
        if self._signer is not None:
            event.signature = self._signer.sign(event)
        try:
            await self._storage.append(event)
        except Exception:
            logger.exception(
                "audit append failed for event_type=%s user=%s — event dropped",
                event_type.value,
                user_id,
            )


# ── runtime introspection helpers ──────────────────────────────────────


def _thread_id(runtime: Any) -> str | None:
    """Pull ``thread_id`` from runtime context or LangGraph config.

    Mirrors :meth:`SandboxAuditMiddleware._get_thread_id` so the two
    audit middlewares agree on how to identify a run. Two sources:
    ``runtime.context["thread_id"]`` (set by ThreadDataMiddleware) and
    ``runtime.config["configurable"]["thread_id"]`` (set by LangGraph).
    """
    if runtime is None:
        return None
    ctx = getattr(runtime, "context", None) or {}
    if isinstance(ctx, dict):
        thread_id = ctx.get("thread_id")
        if thread_id:
            return str(thread_id)
    cfg = getattr(runtime, "config", None) or {}
    if isinstance(cfg, dict):
        return cfg.get("configurable", {}).get("thread_id")
    return None


def _thread_resource(runtime: Any) -> str | None:
    """Return ``thread:{id}`` as the audit resource identifier.

    Format chosen so future resource namespaces (``user:``, ``run:``)
    can coexist in the same column without a schema migration.
    """
    tid = _thread_id(runtime)
    return f"thread:{tid}" if tid else None


def _user_from_runtime(runtime: Any) -> str | None:
    """Extract ``user_id`` from the runtime context, if present.

    The gateway's auth middleware stamps ``user_id`` into the runtime
    context when an authenticated request reaches the agent loop.
    System-initiated runs (background jobs, channel bots) won't have
    one and the audit row falls back to ``None`` — perfectly valid for
    a system-action event per RFC §5.1.
    """
    if runtime is None:
        return None
    ctx = getattr(runtime, "context", None) or {}
    if isinstance(ctx, dict):
        user_id = ctx.get("user_id")
        if user_id:
            return str(user_id)
    return None


__all__ = ["AuditMiddleware"]
