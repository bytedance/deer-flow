"""High-level orchestration for closure-ticket workflows.

The service is the only place where the following concerns are stitched
together:

- tenant scoping (``tenant_id`` always comes from the caller, never the body)
- permission enforcement (``closure:read|write|verify``)
- state-machine validation (delegated to :mod:`state_machine`)
- repository persistence (delegated to :mod:`repository`)
- audit-event emission (delegated to :mod:`events`)
- metadata schema validation (delegated to :mod:`schemas`)

It is the entry point used by REST routes, builtin tools, the report-template
``closure_section`` block, and the overdue-scan background job.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from pydantic import TypeAdapter, ValidationError

from deerflow.closed_loop.events import ClosureEventPublisher
from deerflow.closed_loop.permissions import CLOSURE_READ, CLOSURE_VERIFY, CLOSURE_WRITE
from deerflow.closed_loop.repository import ClosureRepository
from deerflow.closed_loop.schemas import (
    ClosureMetadata,
    ClosurePriority,
    ClosureSourceType,
    CreateTicketRequest,
    ListTicketsFilter,
    NotificationsSummary,
    PageMeta,
    TicketEventDTO,
    TicketListResponse,
    TicketResponse,
    UpdateTicketRequest,
)
from deerflow.closed_loop.state_machine import (
    VERIFY_ACTIONS,
    ClosureAction,
    ClosureStatus,
    TicketSnapshot,
    TransitionError,
    transition,
)

logger = logging.getLogger(__name__)


_METADATA_ADAPTER: TypeAdapter[ClosureMetadata] = TypeAdapter(ClosureMetadata)


class ClosureServiceError(Exception):
    """Wraps service-layer rejections.

    ``code`` is a stable string the routes turn into HTTP status codes:

    * ``permission_denied`` -> 403
    * ``not_found``         -> 404
    * ``validation``        -> 422
    * ``conflict``          -> 409
    """

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


class ClosureService:
    def __init__(
        self,
        *,
        repository: ClosureRepository,
        event_publisher: ClosureEventPublisher,
    ) -> None:
        self._repo = repository
        self._events = event_publisher

    # ----------------------------------------------------- helpers

    @staticmethod
    def _require(perms: Sequence[str], needed: str) -> None:
        if needed not in perms:
            raise ClosureServiceError(
                f"Permission denied: {needed} is required",
                code="permission_denied",
            )

    @staticmethod
    def _require_tenant(tenant_id: str | None) -> str:
        if not tenant_id:
            raise ClosureServiceError("tenant_id is required", code="validation")
        return tenant_id

    @staticmethod
    def _validate_metadata(source_type: str, metadata: dict[str, Any]) -> dict[str, Any]:
        body = {**(metadata or {}), "source_type": source_type}
        try:
            validated = _METADATA_ADAPTER.validate_python(body)
        except ValidationError as e:
            raise ClosureServiceError(
                f"Invalid metadata for source_type={source_type!r}: {e.errors()[0]['msg']}",
                code="validation",
            ) from e
        return validated.model_dump(mode="json", exclude={"source_type"})

    @staticmethod
    def _to_response(row: dict[str, Any]) -> TicketResponse:
        return TicketResponse.model_validate(row)

    # ----------------------------------------------------- create

    async def create_ticket(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        permissions: Sequence[str],
        request: CreateTicketRequest,
    ) -> tuple[TicketResponse, bool]:
        """Create a ticket. Returns ``(ticket, created)`` -- ``created=False`` for idempotent hit."""
        tenant_id = self._require_tenant(tenant_id)
        self._require(permissions, CLOSURE_WRITE)

        clean_metadata = self._validate_metadata(request.source_type.value, request.metadata)

        row, created = await self._repo.create_ticket(
            tenant_id=tenant_id,
            title=request.title,
            description=request.description,
            created_by=actor_id,
            priority=request.priority.value,
            severity=request.severity,
            device_id=request.device_id,
            device_name=request.device_name,
            source_type=request.source_type.value,
            source_run_id=request.source_run_id,
            source_thread_id=request.source_thread_id,
            metadata=clean_metadata,
        )

        if created:
            await self._events.publish(
                tenant_id=tenant_id,
                ticket_id=row["id"],
                action="create",
                from_status=None,
                to_status=row["status"],
                actor_id=actor_id,
                payload={
                    "source_type": row["source_type"],
                    "source_run_id": row["source_run_id"],
                    "device_id": row["device_id"],
                    "priority": row["priority"],
                },
            )
        return self._to_response(row), created

    # ----------------------------------------------------- read

    async def get_ticket(
        self,
        *,
        tenant_id: str,
        ticket_id: str,
        permissions: Sequence[str],
    ) -> TicketResponse:
        tenant_id = self._require_tenant(tenant_id)
        self._require(permissions, CLOSURE_READ)
        row = await self._repo.get_ticket(tenant_id=tenant_id, ticket_id=ticket_id)
        if row is None:
            raise ClosureServiceError("Ticket not found", code="not_found")
        return self._to_response(row)

    async def list_tickets(
        self,
        *,
        tenant_id: str,
        permissions: Sequence[str],
        filters: ListTicketsFilter,
    ) -> TicketListResponse:
        tenant_id = self._require_tenant(tenant_id)
        self._require(permissions, CLOSURE_READ)

        page = await self._repo.list_tickets(
            tenant_id=tenant_id,
            device_id=filters.device_id,
            status=filters.status,
            statuses=filters.statuses,
            assignee_id=filters.assignee_id,
            created_by=filters.created_by,
            source_type=filters.source_type.value if filters.source_type else None,
            priority=filters.priority.value if filters.priority else None,
            is_overdue=filters.is_overdue,
            created_at_gte=filters.created_at_gte,
            created_at_lt=filters.created_at_lt,
            closed_at_gte=filters.closed_at_gte,
            closed_at_lt=filters.closed_at_lt,
            due_at_gte=filters.due_at_gte,
            due_at_lt=filters.due_at_lt,
            page=filters.page,
            page_size=filters.page_size,
            order_by=filters.order_by,
            order_desc=filters.order_desc,
        )
        items = [
            TicketResponse.model_validate(
                {
                    "id": row.id,
                    "tenant_id": row.tenant_id,
                    "title": row.title,
                    "description": row.description,
                    "status": row.status,
                    "priority": row.priority,
                    "severity": row.severity,
                    "device_id": row.device_id,
                    "device_name": row.device_name,
                    "created_by": row.created_by,
                    "assignee_id": row.assignee_id,
                    "verifier_id": row.verifier_id,
                    "source_type": row.source_type,
                    "source_run_id": row.source_run_id,
                    "source_thread_id": row.source_thread_id,
                    "metadata": row.extra_metadata or {},
                    "due_at": row.due_at,
                    "is_overdue": row.is_overdue,
                    "created_at": row.created_at,
                    "updated_at": row.updated_at,
                    "assigned_at": row.assigned_at,
                    "started_at": row.started_at,
                    "submitted_at": row.submitted_at,
                    "closed_at": row.closed_at,
                }
            )
            for row in page.items
        ]
        return TicketListResponse(
            items=items,
            meta=PageMeta(total=page.total, page=page.page, page_size=page.page_size),
        )

    async def list_events(
        self,
        *,
        tenant_id: str,
        ticket_id: str,
        permissions: Sequence[str],
    ) -> list[TicketEventDTO]:
        tenant_id = self._require_tenant(tenant_id)
        self._require(permissions, CLOSURE_READ)
        rows = await self._repo.list_events(tenant_id=tenant_id, ticket_id=ticket_id)
        return [TicketEventDTO.model_validate(r) for r in rows]

    # ---------------------------------------------------- update / transition

    async def update_ticket(
        self,
        *,
        tenant_id: str,
        ticket_id: str,
        actor_id: str,
        permissions: Sequence[str],
        request: UpdateTicketRequest,
        raw_body: dict[str, Any] | None = None,
    ) -> TicketResponse:
        """Apply a partial update.

        ``raw_body`` -- if the caller sends fields beyond the DTO (notably
        ``status``) we explicitly reject so they cannot bypass the state
        machine. We accept the parsed ``request`` for type safety AND check
        ``raw_body`` to defend against a JSON-level smuggling attempt.
        """
        tenant_id = self._require_tenant(tenant_id)
        self._require(permissions, CLOSURE_WRITE)

        if raw_body and "status" in raw_body:
            raise ClosureServiceError(
                "status cannot be modified through the update endpoint -- use POST /transition",
                code="validation",
            )

        column_updates: dict[str, Any] = {}
        if request.title is not None:
            column_updates["title"] = request.title
        if request.description is not None:
            column_updates["description"] = request.description
        if request.priority is not None:
            column_updates["priority"] = request.priority.value
        if request.severity is not None:
            column_updates["severity"] = request.severity
        if request.assignee_id is not None:
            column_updates["assignee_id"] = request.assignee_id
        if request.device_name is not None:
            column_updates["device_name"] = request.device_name

        if not column_updates and not request.metadata_patch:
            current = await self._repo.get_ticket(tenant_id=tenant_id, ticket_id=ticket_id)
            if current is None:
                raise ClosureServiceError("Ticket not found", code="not_found")
            return self._to_response(current)

        updated = await self._repo.update_ticket_fields(
            tenant_id=tenant_id,
            ticket_id=ticket_id,
            column_updates=column_updates,
            metadata_patch=request.metadata_patch,
        )
        if updated is None:
            raise ClosureServiceError("Ticket not found", code="not_found")

        await self._events.publish(
            tenant_id=tenant_id,
            ticket_id=ticket_id,
            action="update_metadata",
            from_status=updated["status"],
            to_status=updated["status"],
            actor_id=actor_id,
            payload={"updated_fields": list(column_updates.keys()), "metadata_patched": bool(request.metadata_patch)},
        )
        return self._to_response(updated)

    async def transition(
        self,
        *,
        tenant_id: str,
        ticket_id: str,
        actor_id: str,
        permissions: Sequence[str],
        action: str,
        payload: dict[str, Any] | None = None,
    ) -> TicketResponse:
        tenant_id = self._require_tenant(tenant_id)

        try:
            action_enum = ClosureAction(action)
        except ValueError as e:
            raise ClosureServiceError(f"Unknown action: {action!r}", code="validation") from e

        # Permission gating per action
        if action_enum in VERIFY_ACTIONS:
            self._require(permissions, CLOSURE_VERIFY)
        elif action_enum is ClosureAction.MARK_OVERDUE:
            # Background-only action; in-process callers (the scanner) bypass
            # the permission gate by passing an explicit superset like
            # ("closure:read","closure:write","closure:verify"). External
            # callers must have at least write.
            self._require(permissions, CLOSURE_WRITE)
        else:
            self._require(permissions, CLOSURE_WRITE)

        current = await self._repo.get_ticket(tenant_id=tenant_id, ticket_id=ticket_id)
        if current is None:
            raise ClosureServiceError("Ticket not found", code="not_found")

        snapshot = TicketSnapshot(
            id=current["id"],
            tenant_id=current["tenant_id"],
            status=ClosureStatus(current["status"]),
            priority=current["priority"],
            assignee_id=current.get("assignee_id"),
            verifier_id=current.get("verifier_id"),
        )
        sla_overrides = await self._repo.get_sla_overrides(tenant_id=tenant_id)

        try:
            result = transition(
                snapshot,
                action_enum,
                actor_id=actor_id,
                payload=payload,
                sla_overrides=sla_overrides,
            )
        except TransitionError as e:
            # transition validation -> conflict (409); missing required field -> validation (422).
            code = "validation" if e.code.startswith("missing_") else "conflict"
            raise ClosureServiceError(str(e), code=code) from e

        updated = await self._repo.apply_transition(
            tenant_id=tenant_id,
            ticket_id=ticket_id,
            column_updates=result.column_updates,
            action=action_enum.value,
            actor_id=actor_id,
            from_status=snapshot.status.value,
            to_status=result.new_status.value,
            event_payload=result.event_payload,
        )
        if updated is None:
            raise ClosureServiceError("Ticket not found", code="not_found")

        await self._events.publish(
            tenant_id=tenant_id,
            ticket_id=ticket_id,
            action=action_enum.value,
            from_status=snapshot.status.value,
            to_status=result.new_status.value,
            actor_id=actor_id,
            payload=result.event_payload,
        )
        return self._to_response(updated)

    # --------------------------------------------------------- aggregates

    async def list_for_report(
        self,
        *,
        tenant_id: str,
        period_start: datetime | None = None,
        period_end: datetime | None = None,
        device_ids: list[str] | None = None,
        statuses: list[str] | None = None,
        page_size: int = 200,
    ) -> list[dict[str, Any]]:
        """Return a list of ticket dicts for the report-template ``closure_section``.

        Used by ``report_templates.runtime.step_renderer``. We return raw dicts
        (not DTOs) so the renderer can flatten them into table rows directly.
        """
        tenant_id = self._require_tenant(tenant_id)
        page = await self._repo.list_tickets(
            tenant_id=tenant_id,
            statuses=statuses,
            created_at_gte=period_start,
            created_at_lt=period_end,
            page=1,
            page_size=page_size,
            order_by="created_at",
            order_desc=False,
        )
        rows: list[dict[str, Any]] = []
        for row in page.items:
            if device_ids and row.device_id not in device_ids:
                continue
            rows.append(
                {
                    "id": row.id,
                    "title": row.title,
                    "device_id": row.device_id,
                    "device_name": row.device_name,
                    "status": row.status,
                    "priority": row.priority,
                    "severity": row.severity,
                    "assignee_id": row.assignee_id,
                    "is_overdue": row.is_overdue,
                    "due_at": row.due_at.isoformat() if row.due_at else None,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                    "closed_at": row.closed_at.isoformat() if row.closed_at else None,
                    "source_type": row.source_type,
                }
            )
        return rows

    async def notifications_summary(
        self,
        *,
        tenant_id: str,
        actor_id: str | None,
        permissions: Sequence[str],
    ) -> NotificationsSummary:
        tenant_id = self._require_tenant(tenant_id)
        self._require(permissions, CLOSURE_READ)
        counts = await self._repo.summary_counts(tenant_id=tenant_id, user_id=actor_id)
        return NotificationsSummary(**counts)

    # ----------------------------------------------------- background hooks

    async def scan_overdue_once(self, *, now: datetime | None = None) -> list[dict[str, Any]]:
        """Background task entry point.

        Iterates open tickets with ``due_at < now``, flips ``is_overdue`` and
        emits a ``closure.overdue`` lifecycle event. Skips closed/rejected
        rows. Returns the (already-published) list of overdue rows for
        observability.
        """
        now = now or datetime.now(UTC)
        candidates = await self._repo.find_overdue_candidates(now=now)
        published: list[dict[str, Any]] = []
        for row in candidates:
            updated = await self._repo.mark_overdue(ticket_id=row["id"], now=now)
            if not updated:
                continue
            await self._events.publish(
                tenant_id=row["tenant_id"],
                ticket_id=row["id"],
                action="overdue",
                from_status=row["status"],
                to_status=row["status"],
                actor_id=None,
                payload={"due_at": row["due_at"].isoformat() if row["due_at"] else None},
            )
            published.append(row)
        return published
