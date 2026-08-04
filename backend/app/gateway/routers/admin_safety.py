"""Administrator-only content-safety incident queries and resolution."""

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.gateway.deps import get_current_user_from_request, get_run_event_store, require_admin_user
from deerflow.persistence.engine import get_session_factory
from deerflow.persistence.safety.model import AdminAuditLogRow, RiskEventRow
from deerflow.persistence.safety.service import ContentSafetyService

router = APIRouter(prefix="/api/admin/safety", tags=["admin-safety"])


class RiskResolutionRequest(BaseModel):
    resolution: str = Field(min_length=1, max_length=32)
    reason: str = Field(min_length=1, max_length=500)


class RiskContextRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


def _event_response(event: RiskEventRow) -> dict:
    return {
        "id": event.id,
        "user_id": event.user_id,
        "thread_id": event.thread_id,
        "run_id": event.run_id,
        "direction": event.direction,
        "category": event.category,
        "severity": event.severity,
        "rule_version": event.rule_version,
        "confidence_bps": event.confidence_bps,
        "redacted_excerpt": event.redacted_excerpt,
        "status": event.status,
        "resolution": event.resolution,
        "created_at": event.created_at,
    }


@router.get("/events")
async def list_risk_events(request: Request, status: str | None = None, limit: int = Query(50, ge=1, le=100)) -> dict:
    await require_admin_user(request, detail="Administrator access required")
    sf = get_session_factory()
    if sf is None:
        raise HTTPException(status_code=503, detail="Content safety requires a SQL database")
    query = select(RiskEventRow).order_by(RiskEventRow.created_at.desc()).limit(limit)
    if status:
        query = query.where(RiskEventRow.status == status)
    async with sf() as session:
        rows = list(await session.scalars(query))
    return {"items": [_event_response(row) for row in rows]}


@router.post("/events/{event_id}/resolve")
async def resolve_risk_event(event_id: str, body: RiskResolutionRequest, request: Request) -> dict:
    await require_admin_user(request, detail="Administrator access required")
    sf = get_session_factory()
    if sf is None:
        raise HTTPException(status_code=503, detail="Content safety requires a SQL database")
    actor = await get_current_user_from_request(request)
    try:
        event = await ContentSafetyService(sf).resolve_risk_event(
            event_id,
            actor_user_id=str(actor.id),
            resolution=body.resolution,
            reason=body.reason,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Risk event not found") from exc
    return _event_response(event)


@router.post("/events/{event_id}/context")
async def view_risk_event_context(event_id: str, body: RiskContextRequest, request: Request) -> dict:
    """Return a capped, redacted event-local context after recording the reason."""
    await require_admin_user(request, detail="Administrator access required")
    sf = get_session_factory()
    if sf is None:
        raise HTTPException(status_code=503, detail="Content safety requires a SQL database")
    actor = await get_current_user_from_request(request)
    async with sf() as session:
        event = await session.get(RiskEventRow, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Risk event not found")
    await ContentSafetyService(sf).record_context_access(
        event_id,
        actor_user_id=str(actor.id),
        reason=body.reason,
    )
    if not event.run_id:
        return {"event": _event_response(event), "messages": [], "truncated": False}
    rows = await get_run_event_store(request).list_messages_by_run(
        event.thread_id,
        event.run_id,
        limit=7,
    )
    # Never disclose raw prompt/output in the first release.  Reviewers see
    # only direction and a bounded, redacted marker, while the access itself
    # is auditable.  A future controlled-view policy can add masked snippets.
    selected = rows[-6:]
    return {
        "event": _event_response(event),
        "messages": [{"seq": row.get("seq"), "type": (row.get("content") or {}).get("type", "unknown"), "content": "***"} for row in selected],
        "truncated": len(rows) > len(selected),
    }


@router.get("/audit")
async def list_admin_audit_log(request: Request, limit: int = Query(100, ge=1, le=500)) -> dict:
    """Return metadata-only privileged-operation records for the admin console."""
    await require_admin_user(request, detail="Administrator access required")
    sf = get_session_factory()
    if sf is None:
        raise HTTPException(status_code=503, detail="Content safety requires a SQL database")
    async with sf() as session:
        rows = list(await session.scalars(select(AdminAuditLogRow).order_by(AdminAuditLogRow.created_at.desc()).limit(limit)))
    return {
        "items": [
            {
                "id": row.id,
                "actor_user_id": row.actor_user_id,
                "action": row.action,
                "target_type": row.target_type,
                "target_id": row.target_id,
                "reason": row.reason,
                "created_at": row.created_at,
            }
            for row in rows
        ]
    }
