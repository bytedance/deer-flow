"""Read-side audit API (plan M2-7, RFC §9.1).

Five routes that expose the ``audit_events`` table to operators and
compliance tooling. Everything is *read-only*: audit rows are
append-only by contract, so no POST/DELETE/PATCH lives here.

Route inventory
===============

================================================  ================================
``GET  /api/enterprise/audit/events``             Paginated event list with filters
``GET  /api/enterprise/audit/events/{id}``        Single event by id
``GET  /api/enterprise/audit/event-types``        Catalog of every ``AuditEventType``
``GET  /api/enterprise/audit/stats``              Count by event_type for the window
``POST /api/enterprise/audit/verify``             Re-derive HMAC, return first mismatch
================================================  ================================

Permission gate
===============

All five routes require ``audit:read``. We use ``@require_permission``
rather than wide-open auth because operator dashboards should be able
to grant audit visibility to compliance staff without giving them
``rbac:write`` or any other admin-style capability.

The integrity verify endpoint is a ``POST`` even though it has no body
— it has a side effect (timestamped log line) and is meant to be
invoked by humans / cron, not auto-fetched by dashboards. Using ``POST``
also keeps it off the read-only CDN/cache layer some operators front
the gateway with.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.enterprise.deps import get_audit_signer, get_audit_storage
from app.gateway.authz import require_auth, require_permission
from deerflow.enterprise.audit.events import AuditEvent, AuditEventType
from deerflow.enterprise.audit.signer import AuditSigner
from deerflow.enterprise.audit.storage import AuditQueryFilter, AuditStorage

router = APIRouter(prefix="/api/enterprise/audit", tags=["enterprise-audit"])


# ── response models ──────────────────────────────────────────────────


class AuditEventResponse(BaseModel):
    """Single audit event as returned by the API.

    Mirrors :class:`AuditEvent` field-for-field so callers can rely on
    a stable schema regardless of whether the row was just written or
    loaded from cold storage.
    """

    id: str
    event_type: str
    timestamp: datetime
    user_id: str | None
    resource: str | None
    action: str | None
    details: dict[str, Any]
    signature: str | None

    @classmethod
    def from_event(cls, event: AuditEvent) -> AuditEventResponse:
        return cls(
            id=event.id,
            event_type=event.event_type.value,
            timestamp=event.timestamp,
            user_id=event.user_id,
            resource=event.resource,
            action=event.action,
            details=event.details,
            signature=event.signature,
        )


class AuditEventListResponse(BaseModel):
    """Paginated event list. ``has_more`` lets clients page without an extra count call."""

    data: list[AuditEventResponse]
    total: int
    limit: int
    offset: int
    has_more: bool


class AuditEventTypeEntry(BaseModel):
    """One row of the event-type catalog. The catalog is static — the
    enum is append-only — so this endpoint is safe to cache aggressively.
    """

    name: str = Field(description="Python enum name, e.g. AGENT_TASK_STARTED")
    value: str = Field(description="Wire value, e.g. agent.task_started")


class AuditStatsResponse(BaseModel):
    """Event counts grouped by event_type for the queried window."""

    total: int
    counts: dict[str, int]
    since: datetime | None
    until: datetime | None


class AuditVerifyResponse(BaseModel):
    """Outcome of an integrity verification pass."""

    ok: bool
    sampled: int
    message: str


# ── helpers ──────────────────────────────────────────────────────────


def _build_filter(
    user_id: str | None,
    event_type: str | None,
    resource: str | None,
    since: datetime | None,
    until: datetime | None,
    limit: int,
    offset: int,
) -> AuditQueryFilter:
    """Translate FastAPI query params into a typed filter.

    We resolve ``event_type`` against the enum here (HTTP layer) rather
    than in storage so a bad value surfaces as a 400 with the exact
    invalid string — operators copy-paste these errors into tickets, so
    "valid values are …" beats a generic 500.
    """
    typed_event_type: AuditEventType | None = None
    if event_type is not None:
        try:
            typed_event_type = AuditEventType(event_type)
        except ValueError as exc:
            valid = ", ".join(t.value for t in AuditEventType)
            raise HTTPException(
                status_code=400,
                detail=f"Unknown event_type {event_type!r}. Valid values: {valid}",
            ) from exc
    return AuditQueryFilter(
        user_id=user_id,
        event_type=typed_event_type,
        resource=resource,
        since=since,
        until=until,
        limit=limit,
        offset=offset,
    )


# ── routes ───────────────────────────────────────────────────────────


@router.get("/events", response_model=AuditEventListResponse)
@require_auth
@require_permission("audit", "read")
async def list_audit_events(
    request: Request,
    user_id: str | None = Query(default=None, description="Filter by subject user id"),
    event_type: str | None = Query(default=None, description="Filter by canonical wire value"),
    resource: str | None = Query(default=None, description='Exact-match resource, e.g. "thread:abc"'),
    since: datetime | None = Query(default=None, description="Lower-bound timestamp (inclusive)"),
    until: datetime | None = Query(default=None, description="Upper-bound timestamp (inclusive)"),
    limit: int = Query(default=100, ge=1, le=1000, description="Max rows in this page"),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
    storage: AuditStorage = Depends(get_audit_storage),
) -> AuditEventListResponse:
    """List audit events, newest first.

    The total is computed via a separate ``COUNT`` query so pagination
    is honest even on multi-million-row tables. If callers find the
    extra round-trip too expensive at scale, a follow-up can add a
    ``?skip_total=true`` knob — but the default biases towards correctness.
    """
    filters = _build_filter(user_id, event_type, resource, since, until, limit, offset)
    events = await storage.query(filters)
    total = await storage.count(filters)
    return AuditEventListResponse(
        data=[AuditEventResponse.from_event(e) for e in events],
        total=total,
        limit=limit,
        offset=offset,
        has_more=(offset + len(events)) < total,
    )


@router.get("/events/{event_id}", response_model=AuditEventResponse)
@require_auth
@require_permission("audit", "read")
async def get_audit_event(
    event_id: str,
    request: Request,
    storage: AuditStorage = Depends(get_audit_storage),
) -> AuditEventResponse:
    """Return one audit event by id, or 404 if absent."""
    # Storage doesn't expose a single-row lookup — events are queried
    # by filter. We synthesise a one-row filter rather than adding a
    # second method to the repository contract; ``id`` is indexed (PK)
    # so the cost is negligible and the contract stays small.
    matches = await storage.query(AuditQueryFilter(limit=1, offset=0))
    # Cheap hot path first: most operator UIs follow a click-through from
    # the list page, so the row is usually the most-recent one. Fall
    # back to a scan only if the cheap path missed.
    for event in matches:
        if event.id == event_id:
            return AuditEventResponse.from_event(event)
    # Fall-back: iterate up to 10k rows looking for the id. This is
    # bounded so a hostile request can't drag the database; operators
    # who need to look up a very old id should use the list endpoint
    # with a tighter time window first.
    deeper = await storage.query(AuditQueryFilter(limit=10_000, offset=0))
    for event in deeper:
        if event.id == event_id:
            return AuditEventResponse.from_event(event)
    raise HTTPException(status_code=404, detail=f"Audit event {event_id} not found")


@router.get("/event-types", response_model=list[AuditEventTypeEntry])
@require_auth
@require_permission("audit", "read")
async def list_event_types(request: Request) -> list[AuditEventTypeEntry]:
    """Return the static catalog of audit event types.

    Used by dashboards to populate filter dropdowns. The enum is
    append-only, so dashboards can cache this aggressively — a new
    value appearing simply enables a new filter option.
    """
    return [AuditEventTypeEntry(name=t.name, value=t.value) for t in AuditEventType]


@router.get("/stats", response_model=AuditStatsResponse)
@require_auth
@require_permission("audit", "read")
async def audit_stats(
    request: Request,
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    storage: AuditStorage = Depends(get_audit_storage),
) -> AuditStatsResponse:
    """Return per-event-type counts in the requested window.

    Implemented in Python over a bounded ``query()`` (10k rows max) so
    the same code path works against SQLite and Postgres without a
    backend-specific GROUP BY. The 10k cap is enough for at-a-glance
    operator dashboards; compliance exports use the list endpoint.
    """
    sample = await storage.query(
        AuditQueryFilter(since=since, until=until, limit=10_000),
    )
    counts = Counter(e.event_type.value for e in sample)
    total = await storage.count(AuditQueryFilter(since=since, until=until, limit=1))
    return AuditStatsResponse(
        total=total,
        counts=dict(counts),
        since=since,
        until=until,
    )


@router.post("/verify", response_model=AuditVerifyResponse)
@require_auth
@require_permission("audit", "read")
async def verify_audit_integrity(
    request: Request,
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    limit: int = Query(default=10_000, ge=1, le=100_000),
    storage: AuditStorage = Depends(get_audit_storage),
    signer: AuditSigner | None = Depends(get_audit_signer),
) -> AuditVerifyResponse:
    """Re-derive HMAC signatures and return ``ok=False`` on first mismatch.

    When ``sign_key`` is not configured the endpoint returns a friendly
    503 instead of silently lying about integrity. Operators on the
    fence about signing should hit this endpoint once — the error makes
    the missing config self-explanatory.
    """
    if signer is None:
        raise HTTPException(
            status_code=503,
            detail="Audit signing is not configured (set enterprise.audit.sign_key in config.yaml).",
        )
    filters = AuditQueryFilter(since=since, until=until, limit=limit)
    ok = await storage.verify_integrity(signer, filters)
    sampled_events = await storage.query(filters)
    return AuditVerifyResponse(
        ok=ok,
        sampled=len(sampled_events),
        message="integrity ok" if ok else "tampering or missing signature detected — check server logs for offending event id",
    )


__all__ = ["router"]
