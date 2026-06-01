"""REST API for closure (closed-loop) tickets.

Endpoints (all under ``/api/closure``):

    POST   /tickets                         create
    GET    /tickets                         list (paginated, filterable)
    GET    /tickets/{ticket_id}             fetch one
    PATCH  /tickets/{ticket_id}             partial update (status NOT accepted)
    POST   /tickets/{ticket_id}/transition  state-machine transition
    GET    /tickets/{ticket_id}/events      audit trail
    GET    /notifications/summary           open / overdue / pending-verification counts

All routes resolve ``tenant_id`` and ``actor_id`` from the authenticated
session — never from the request body — and gate by the ``closure:read |
write | verify`` permission triplet through ``@require_permission``.

Service-layer ``ClosureServiceError`` codes are mapped to HTTP status codes:

    permission_denied -> 403
    not_found         -> 404
    validation        -> 422
    conflict          -> 409
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from app.gateway.auth.models import UserResponse
from app.gateway.authz import require_permission
from app.gateway.deps import get_closure_service, get_local_provider
from deerflow.closed_loop.schemas import (
    ClosurePriority,
    ClosureSourceType,
    CreateTicketRequest,
    ListTicketsFilter,
    NotificationsSummary,
    TicketEventDTO,
    TicketListResponse,
    TicketResponse,
    TransitionRequest,
    UpdateTicketRequest,
)
from deerflow.closed_loop.service import ClosureServiceError
from deerflow.config.tenant import get_current_tenant_id
from deerflow.runtime.user_context import get_effective_user_id

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/closure", tags=["closure"])


_CODE_TO_STATUS = {
    "permission_denied": 403,
    "not_found": 404,
    "validation": 422,
    "conflict": 409,
}


def _raise_for(error: ClosureServiceError) -> None:
    status = _CODE_TO_STATUS.get(error.code, 400)
    raise HTTPException(status_code=status, detail=str(error))


def _principal(request: Request) -> tuple[str, str, list[str]]:
    """Resolve ``(tenant_id, actor_id, permissions)`` for the current request.

    ``request.state.auth`` is set by ``AuthMiddleware`` (production) or by a
    test stub middleware. Falls back to context-vars when running under
    no-auth (defaults applied at the auth layer) so unit tests can call
    routes directly.
    """
    auth = getattr(request.state, "auth", None)
    user = getattr(auth, "user", None) if auth is not None else getattr(request.state, "user", None)
    permissions = list(getattr(auth, "permissions", []) or [])

    tenant_id = (
        getattr(user, "tenant_id", None) if user is not None else None
    ) or get_current_tenant_id()
    actor_id = (
        getattr(user, "id", None) if user is not None else None
    ) or get_effective_user_id()
    return str(tenant_id), str(actor_id), permissions


# ---------------------------------------------------------------------------
# Tickets
# ---------------------------------------------------------------------------


@router.post("/tickets", response_model=TicketResponse, status_code=201, summary="Create closure ticket")
@require_permission("closure", "write")
async def create_ticket(request: Request, body: CreateTicketRequest, response: Response) -> TicketResponse:
    """Create a closure ticket.

    Idempotent on ``(tenant_id, source_type, source_run_id, device_id)`` —
    the second call for the same key returns the existing row with HTTP 200
    instead of 201. We surface that via the ``X-Closure-Created`` response
    header so callers can distinguish without a second round-trip.
    """
    tenant_id, actor_id, perms = _principal(request)
    service = get_closure_service(request)
    try:
        ticket, created = await service.create_ticket(
            tenant_id=tenant_id,
            actor_id=actor_id,
            permissions=perms,
            request=body,
        )
    except ClosureServiceError as e:
        _raise_for(e)
    response.headers["X-Closure-Created"] = "true" if created else "false"
    if not created:
        response.status_code = 200
    return ticket


@router.get("/tickets", response_model=TicketListResponse, summary="List closure tickets")
@require_permission("closure", "read")
async def list_tickets(
    request: Request,
    device_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    statuses: list[str] | None = Query(default=None),
    assignee_id: str | None = Query(default=None),
    created_by: str | None = Query(default=None),
    source_type: ClosureSourceType | None = Query(default=None),
    source_run_id: str | None = Query(default=None),
    priority: ClosurePriority | None = Query(default=None),
    is_overdue: bool | None = Query(default=None),
    created_at_gte: str | None = Query(default=None),
    created_at_lt: str | None = Query(default=None),
    closed_at_gte: str | None = Query(default=None),
    closed_at_lt: str | None = Query(default=None),
    due_at_gte: str | None = Query(default=None),
    due_at_lt: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    order_by: str = Query(default="created_at"),
    order_desc: bool = Query(default=True),
) -> TicketListResponse:
    tenant_id, _actor, perms = _principal(request)
    service = get_closure_service(request)
    filters = ListTicketsFilter(
        device_id=device_id,
        status=status,
        statuses=statuses,
        assignee_id=assignee_id,
        created_by=created_by,
        source_type=source_type,
        source_run_id=source_run_id,
        priority=priority,
        is_overdue=is_overdue,
        created_at_gte=created_at_gte,
        created_at_lt=created_at_lt,
        closed_at_gte=closed_at_gte,
        closed_at_lt=closed_at_lt,
        due_at_gte=due_at_gte,
        due_at_lt=due_at_lt,
        page=page,
        page_size=page_size,
        order_by=order_by,
        order_desc=order_desc,
    )
    try:
        return await service.list_tickets(
            tenant_id=tenant_id,
            permissions=perms,
            filters=filters,
        )
    except ClosureServiceError as e:
        _raise_for(e)


@router.get("/tickets/{ticket_id}", response_model=TicketResponse, summary="Get closure ticket")
@require_permission("closure", "read")
async def get_ticket(request: Request, ticket_id: str) -> TicketResponse:
    tenant_id, _actor, perms = _principal(request)
    service = get_closure_service(request)
    try:
        return await service.get_ticket(
            tenant_id=tenant_id,
            ticket_id=ticket_id,
            permissions=perms,
        )
    except ClosureServiceError as e:
        _raise_for(e)


@router.patch("/tickets/{ticket_id}", response_model=TicketResponse, summary="Update closure ticket")
@require_permission("closure", "write")
async def update_ticket(
    request: Request,
    ticket_id: str,
    body: dict[str, Any] = Body(...),
) -> TicketResponse:
    """Partial update.

    The body is parsed twice on purpose: once strictly via
    :class:`UpdateTicketRequest` (rejects unknown fields including ``status``)
    and once as raw dict so the service layer can defend against status
    smuggling at the JSON level even if the DTO is bypassed.
    """
    tenant_id, actor_id, perms = _principal(request)
    service = get_closure_service(request)
    try:
        parsed = UpdateTicketRequest.model_validate(body)
    except Exception as e:  # noqa: BLE001 -- bubble Pydantic detail to client
        raise HTTPException(status_code=422, detail=str(e))

    try:
        return await service.update_ticket(
            tenant_id=tenant_id,
            ticket_id=ticket_id,
            actor_id=actor_id,
            permissions=perms,
            request=parsed,
            raw_body=body,
        )
    except ClosureServiceError as e:
        _raise_for(e)


@router.post(
    "/tickets/{ticket_id}/transition",
    response_model=TicketResponse,
    summary="Transition closure ticket through state machine",
)
@require_permission("closure", "read")  # finer-grained gating happens in service.transition()
async def transition_ticket(
    request: Request,
    ticket_id: str,
    body: TransitionRequest,
) -> TicketResponse:
    tenant_id, actor_id, perms = _principal(request)
    service = get_closure_service(request)
    try:
        return await service.transition(
            tenant_id=tenant_id,
            ticket_id=ticket_id,
            actor_id=actor_id,
            permissions=perms,
            action=body.action,
            payload=body.payload,
        )
    except ClosureServiceError as e:
        _raise_for(e)


@router.get(
    "/tickets/{ticket_id}/events",
    response_model=list[TicketEventDTO],
    summary="List audit events for a ticket",
)
@require_permission("closure", "read")
async def list_ticket_events(request: Request, ticket_id: str) -> list[TicketEventDTO]:
    tenant_id, _actor, perms = _principal(request)
    service = get_closure_service(request)
    try:
        return await service.list_events(
            tenant_id=tenant_id,
            ticket_id=ticket_id,
            permissions=perms,
        )
    except ClosureServiceError as e:
        _raise_for(e)


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------


class _NotificationsResponse(BaseModel):
    """Wrapper so future fields (e.g. last_event_at) can ride alongside counts."""

    summary: NotificationsSummary = Field(...)


@router.get(
    "/notifications/summary",
    response_model=NotificationsSummary,
    summary="Aggregate counts for the closure inbox",
)
@require_permission("closure", "read")
async def notifications_summary(request: Request) -> NotificationsSummary:
    tenant_id, actor_id, perms = _principal(request)
    service = get_closure_service(request)
    try:
        return await service.notifications_summary(
            tenant_id=tenant_id,
            actor_id=actor_id,
            permissions=perms,
        )
    except ClosureServiceError as e:
        _raise_for(e)


# ---------------------------------------------------------------------------
# Tenant users (for assignee selection)
# ---------------------------------------------------------------------------


@router.get(
    "/tenant-users",
    response_model=list[UserResponse],
    summary="List users in the current tenant for ticket assignment",
)
@require_permission("closure", "read")
async def list_tenant_users_for_assignment(request: Request) -> list[UserResponse]:
    tenant_id, _actor, _perms = _principal(request)
    try:
        provider = get_local_provider()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="User service not available")
    users = await provider.list_users(tenant_id)
    return [
        UserResponse(
            id=str(u.id),
            email=u.email,
            system_role=u.system_role,
            needs_setup=u.needs_setup,
            tenant_id=u.tenant_id,
        )
        for u in users
    ]
