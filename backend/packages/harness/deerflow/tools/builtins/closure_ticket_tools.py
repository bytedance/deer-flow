"""4 builtin LLM tools for the closed-loop ticket subsystem (§5 of the design).

Each tool is a thin shell over :class:`deerflow.closed_loop.service.ClosureService`
that:

* resolves the principal from the LangGraph ``RunnableConfig`` (so ``tenant_id``
  / ``actor_id`` come from the auth context, never from LLM-supplied args);
* derives the permission triplet from the principal's admin flags;
* delegates to the service for state-machine + repository work;
* returns a JSON envelope -- ``{"ticket": {...}, "created": bool}`` on success
  or ``{"error": {"code": ..., "message": ...}}`` on failure.

The 4 tools:

  1. ``create_closure_ticket``  - new ticket (idempotent on the natural key)
  2. ``list_closure_tickets``    - paginated listing with the same filter set
                                    as the REST endpoint
  3. ``update_closure_ticket``    - partial update; rejects ``status`` outright
                                    (status moves go through ``close_closure_ticket``
                                    or the dedicated transition route)
  4. ``close_closure_ticket``     - verify-close / reject the verification
                                    request; gates on ``closure:verify``

All tools fail closed: any unexpected exception is logged and returned as an
``INTERNAL`` envelope so a buggy DSL call cannot crash the agent loop.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain.tools import tool
from langgraph.config import get_config

from deerflow.closed_loop.permissions import CLOSURE_READ, CLOSURE_VERIFY, CLOSURE_WRITE
from deerflow.closed_loop.schemas import (
    ClosurePriority,
    ClosureSourceType,
    CreateTicketRequest,
    ListTicketsFilter,
    UpdateTicketRequest,
)
from deerflow.closed_loop.service import ClosureService, ClosureServiceError
from deerflow.closed_loop.service_factory import get_default_service
from deerflow.config.tenant import get_current_tenant_id
from deerflow.runtime.user_context import get_effective_user_id

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Envelope helpers (mirror report_template_tools.py)
# ---------------------------------------------------------------------------


def _err(code: str, message: str, **extra: Any) -> str:
    return json.dumps({"error": {"code": code, "message": message, **extra}}, ensure_ascii=False)


def _ok(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)


# ---------------------------------------------------------------------------
# Principal + permission helpers
# ---------------------------------------------------------------------------


class _Principal:
    """Lightweight bag combining ids and the inferred permission set.

    We keep the closed-loop module independent from
    ``report_templates.permissions.Principal`` so the two subsystems can evolve
    on their own roles. The shape is intentionally identical to the one
    documented in ``report_templates.service.principal_from_runnable_config``:
    everything comes off ``RunnableConfig.configurable``, with safe fallbacks
    for the no-auth path.
    """

    __slots__ = ("user_id", "tenant_id", "permissions")

    def __init__(self, *, user_id: str, tenant_id: str, permissions: list[str]) -> None:
        self.user_id = user_id
        self.tenant_id = tenant_id
        self.permissions = permissions


def _principal_from_runnable_config() -> _Principal:
    """Resolve ``(user_id, tenant_id, permissions)`` from the runtime config."""
    cfg = (get_config() or {}).get("configurable", {}) or {}
    user_id = str(cfg.get("user_id") or get_effective_user_id())
    tenant_id = str(cfg.get("tenant_id") or get_current_tenant_id())

    perms: list[str] = [CLOSURE_READ, CLOSURE_WRITE]
    if bool(cfg.get("is_superadmin", False)) or bool(cfg.get("is_tenant_admin", False)):
        perms.append(CLOSURE_VERIFY)
    return _Principal(user_id=user_id, tenant_id=tenant_id, permissions=perms)


def _resolve_service() -> ClosureService | None:
    return get_default_service()


def _service_unavailable() -> str:
    return _err(
        "SERVICE_UNAVAILABLE",
        "Closure service is not configured (no DB session factory). Ask an administrator to enable persistence.",
    )


def _map_service_error(e: ClosureServiceError) -> str:
    """Translate service-layer codes into LLM-facing envelope codes."""
    code_map = {
        "permission_denied": "PERMISSION_DENIED",
        "not_found": "NOT_FOUND",
        "validation": "VALIDATION",
        "conflict": "CONFLICT",
    }
    return _err(code_map.get(e.code, "SERVICE_ERROR"), str(e))


# ---------------------------------------------------------------------------
# Tool 1: create_closure_ticket
# ---------------------------------------------------------------------------


@tool("create_closure_ticket", parse_docstring=True)
async def create_closure_ticket_tool(
    title: str,
    description: str | None = None,
    priority: str = "normal",
    severity: str | None = None,
    device_id: str | None = None,
    device_name: str | None = None,
    source_type: str = "manual",
    source_run_id: str | None = None,
    source_thread_id: str | None = None,
    metadata: dict | None = None,
) -> str:
    """Create or fetch a closure ticket for a defect / fault / remediation item.

    Idempotent on ``(tenant_id, source_type, source_run_id, device_id)`` --
    repeated calls with the same key return the existing ticket and the
    response carries ``"created": false`` so the LLM can avoid duplicate
    notifications.

    Args:
        title: Short headline (1-255 chars). Required.
        description: Long-form description (≤8000 chars).
        priority: One of ``urgent`` / ``important`` / ``normal`` / ``observe``.
            Drives SLA computation when the ticket is later assigned.
        severity: Optional free-form severity tag (e.g. ``S1``, ``S2``).
        device_id: Equipment id this ticket is about (recommended for
            diagnosis-driven creation; required for source-key idempotency).
        device_name: Human-readable equipment name for display.
        source_type: One of ``diagnosis`` / ``report`` / ``inspection`` /
            ``manual`` / ``chat``. Drives metadata schema.
        source_run_id: Originating run / report-run id (combined with
            ``source_type`` and ``device_id`` for idempotency).
        source_thread_id: Conversation thread that triggered creation.
        metadata: Free-form per-source-type extras. Validated by the
            service against the discriminated metadata schema.

    Returns:
        JSON ``{"ticket": {...}, "created": bool}`` on success or
        ``{"error": {"code", "message"}}`` on failure.
    """
    try:
        service = _resolve_service()
        if service is None:
            return _service_unavailable()
        principal = _principal_from_runnable_config()

        try:
            request = CreateTicketRequest(
                title=title,
                description=description,
                priority=ClosurePriority(priority),
                severity=severity,
                device_id=device_id,
                device_name=device_name,
                source_type=ClosureSourceType(source_type),
                source_run_id=source_run_id,
                source_thread_id=source_thread_id,
                metadata=metadata or {},
            )
        except ValueError as e:
            return _err("VALIDATION", str(e))

        ticket, created = await service.create_ticket(
            tenant_id=principal.tenant_id,
            actor_id=principal.user_id,
            permissions=principal.permissions,
            request=request,
        )
        return _ok({"ticket": ticket.model_dump(mode="json"), "created": created})
    except ClosureServiceError as e:
        return _map_service_error(e)
    except Exception as e:  # noqa: BLE001
        logger.exception("create_closure_ticket failed")
        return _err("INTERNAL", str(e))


# ---------------------------------------------------------------------------
# Tool 2: list_closure_tickets
# ---------------------------------------------------------------------------


@tool("list_closure_tickets", parse_docstring=True)
async def list_closure_tickets_tool(
    device_id: str | None = None,
    status: str | None = None,
    statuses: list[str] | None = None,
    assignee_id: str | None = None,
    source_type: str | None = None,
    priority: str | None = None,
    is_overdue: bool | None = None,
    page: int = 1,
    page_size: int = 20,
    order_by: str = "created_at",
    order_desc: bool = True,
) -> str:
    """List closure tickets visible to the current user, with filters.

    Args:
        device_id: Restrict to tickets attached to one device.
        status: Single status filter (mutually exclusive with ``statuses``).
        statuses: Multiple statuses (e.g. ``["pending", "assigned"]``).
        assignee_id: Restrict to tickets assigned to a given user.
        source_type: One of ``diagnosis`` / ``report`` / ``inspection`` /
            ``manual`` / ``chat``.
        priority: ``urgent`` / ``important`` / ``normal`` / ``observe``.
        is_overdue: ``True`` returns only flagged-overdue tickets.
        page: 1-indexed page number.
        page_size: 1-200, default 20.
        order_by: Column to sort by (``created_at`` / ``due_at`` /
            ``updated_at``).
        order_desc: Sort descending when True.

    Returns:
        JSON ``{"items": [...], "meta": {"total", "page", "page_size"}}`` or
        ``{"error": {...}}``.
    """
    try:
        service = _resolve_service()
        if service is None:
            return _service_unavailable()
        principal = _principal_from_runnable_config()

        try:
            filters = ListTicketsFilter(
                device_id=device_id,
                status=status,
                statuses=statuses,
                assignee_id=assignee_id,
                source_type=ClosureSourceType(source_type) if source_type else None,
                priority=ClosurePriority(priority) if priority else None,
                is_overdue=is_overdue,
                page=page,
                page_size=page_size,
                order_by=order_by,
                order_desc=order_desc,
            )
        except ValueError as e:
            return _err("VALIDATION", str(e))

        page_result = await service.list_tickets(
            tenant_id=principal.tenant_id,
            permissions=principal.permissions,
            filters=filters,
        )
        return _ok(page_result.model_dump(mode="json"))
    except ClosureServiceError as e:
        return _map_service_error(e)
    except Exception as e:  # noqa: BLE001
        logger.exception("list_closure_tickets failed")
        return _err("INTERNAL", str(e))


# ---------------------------------------------------------------------------
# Tool 3: update_closure_ticket
# ---------------------------------------------------------------------------


# Fields the LLM is allowed to push through a partial update. Anything outside
# this set -- in particular ``status`` -- is rejected with a hint so the LLM
# learns to use the dedicated transition tool instead.
_UPDATE_ALLOWED_FIELDS: frozenset[str] = frozenset(
    {"title", "description", "priority", "severity", "assignee_id", "device_name", "metadata_patch"}
)


@tool("update_closure_ticket", parse_docstring=True)
async def update_closure_ticket_tool(
    ticket_id: str,
    fields: dict,
) -> str:
    """Patch closure-ticket fields. ``status`` writes are explicitly forbidden.

    Args:
        ticket_id: The ``id`` of the ticket to update.
        fields: Object containing one or more of: ``title``, ``description``,
            ``priority``, ``severity``, ``assignee_id``, ``device_name``,
            ``metadata_patch`` (dict merged into the existing metadata).
            Any other key -- especially ``status`` -- is rejected with
            ``STATUS_FORBIDDEN`` (use ``close_closure_ticket`` or the
            ``/transition`` API to advance the state machine).

    Returns:
        JSON ``{"ticket": {...}}`` on success or ``{"error": {...}}``.
    """
    try:
        if not isinstance(fields, dict):
            return _err("VALIDATION", "fields must be a JSON object")
        if "status" in fields:
            return _err(
                "STATUS_FORBIDDEN",
                "status cannot be modified through update_closure_ticket. "
                "Use close_closure_ticket or POST /api/closure/tickets/{id}/transition.",
            )
        unknown = set(fields.keys()) - _UPDATE_ALLOWED_FIELDS
        if unknown:
            return _err(
                "VALIDATION",
                f"Unsupported fields: {sorted(unknown)}. "
                f"Allowed: {sorted(_UPDATE_ALLOWED_FIELDS)}.",
            )

        service = _resolve_service()
        if service is None:
            return _service_unavailable()
        principal = _principal_from_runnable_config()

        try:
            request = UpdateTicketRequest.model_validate(fields)
        except Exception as e:  # noqa: BLE001 -- bubble pydantic detail
            return _err("VALIDATION", str(e))

        ticket = await service.update_ticket(
            tenant_id=principal.tenant_id,
            ticket_id=ticket_id,
            actor_id=principal.user_id,
            permissions=principal.permissions,
            request=request,
            raw_body=fields,
        )
        return _ok({"ticket": ticket.model_dump(mode="json")})
    except ClosureServiceError as e:
        return _map_service_error(e)
    except Exception as e:  # noqa: BLE001
        logger.exception("update_closure_ticket failed")
        return _err("INTERNAL", str(e))


# ---------------------------------------------------------------------------
# Tool 4: close_closure_ticket
# ---------------------------------------------------------------------------


@tool("close_closure_ticket", parse_docstring=True)
async def close_closure_ticket_tool(
    ticket_id: str,
    decision: str = "verify_close",
    rejection_reason: str | None = None,
    verification_summary: str | None = None,
    payload: dict | None = None,
) -> str:
    """Close a ticket pending verification, or reject the verification request.

    Both decisions require the ``closure:verify`` permission. Members without
    that role get ``PERMISSION_DENIED`` -- the LLM should ask the user to
    escalate to a tenant admin.

    Args:
        ticket_id: The ``id`` of the ticket awaiting verification.
        decision: ``verify_close`` (close the ticket) or ``reject`` (mark
            verification rejected -- caller must also pass
            ``rejection_reason``).
        rejection_reason: Required when ``decision="reject"``; explains why
            the verification was bounced back to the assignee.
        verification_summary: Optional free-text note recorded on the audit
            event when closing.
        payload: Free-form extra fields merged into the audit-event payload.
            Useful for evidence pointers, attachment ids, etc.

    Returns:
        JSON ``{"ticket": {...}}`` or ``{"error": {...}}``.
    """
    try:
        if decision not in {"verify_close", "reject"}:
            return _err(
                "VALIDATION",
                f"decision must be 'verify_close' or 'reject', got {decision!r}",
            )
        if decision == "reject" and not rejection_reason:
            return _err("VALIDATION", "rejection_reason is required when decision='reject'")

        service = _resolve_service()
        if service is None:
            return _service_unavailable()
        principal = _principal_from_runnable_config()

        action = "verify_close" if decision == "verify_close" else "reject_verification"
        merged_payload: dict[str, Any] = dict(payload or {})
        if verification_summary:
            merged_payload.setdefault("verification_summary", verification_summary)
        if rejection_reason:
            merged_payload["rejection_reason"] = rejection_reason

        ticket = await service.transition(
            tenant_id=principal.tenant_id,
            ticket_id=ticket_id,
            actor_id=principal.user_id,
            permissions=principal.permissions,
            action=action,
            payload=merged_payload,
        )
        return _ok({"ticket": ticket.model_dump(mode="json")})
    except ClosureServiceError as e:
        return _map_service_error(e)
    except Exception as e:  # noqa: BLE001
        logger.exception("close_closure_ticket failed")
        return _err("INTERNAL", str(e))


# ---------------------------------------------------------------------------
# Exported list (consumed by tools/tools.py registration)
# ---------------------------------------------------------------------------


CLOSURE_TICKET_TOOLS = [
    create_closure_ticket_tool,
    list_closure_tickets_tool,
    update_closure_ticket_tool,
    close_closure_ticket_tool,
]


__all__ = [
    "CLOSURE_TICKET_TOOLS",
    "close_closure_ticket_tool",
    "create_closure_ticket_tool",
    "list_closure_tickets_tool",
    "update_closure_ticket_tool",
]
