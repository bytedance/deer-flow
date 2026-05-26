"""Insights dashboard API routes.

Provides endpoints for viewing feedback trends, closure metrics,
improvement suggestions, and KB candidates. All endpoints require
insights:read permission; state-changing endpoints require insights:write.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.gateway.authz import get_auth_context, require_permission
from deerflow.config.tenant import get_current_tenant_id
from deerflow.insights.improvement import ImprovementEngine
from deerflow.insights.kb_candidate_store import KBCandidateStore
from deerflow.insights.models import ImprovementSuggestion

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/insights", tags=["insights"])


# --------------------------------------------------------- Request/Response models


class ApplyImprovementRequest(BaseModel):
    note: str | None = Field(default=None, description="Optional implementation note")


class DismissImprovementRequest(BaseModel):
    reason: str = Field(..., description="Reason for dismissing the suggestion")


class PromoteKBCandidateRequest(BaseModel):
    target_kb_id: str = Field(..., description="Target knowledge base ID")


class DismissKBCandidateRequest(BaseModel):
    reason: str = Field(..., description="Reason for dismissing the candidate")


# --------------------------------------------------------- Helpers


def _get_insights_cache(request: Request):
    """Get insights cache from app state."""
    cache = getattr(request.app.state, "insights_cache", None)
    if cache is None:
        raise HTTPException(
            status_code=503,
            detail="Insights system not initialized",
        )
    return cache


def _get_improvement_engine(request: Request) -> ImprovementEngine:
    """Get improvement engine from app state."""
    engine = getattr(request.app.state, "improvement_engine", None)
    if engine is None:
        # Create on-demand if not in app state
        engine = ImprovementEngine()
    return engine


def _load_suggestions(cache, tenant_id: str) -> list[ImprovementSuggestion]:
    """Load suggestions from cache."""
    data = cache.get(tenant_id, "improvement_suggestions")
    if not data:
        return []
    return [ImprovementSuggestion.model_validate(s) for s in data]


def _save_suggestions(cache, tenant_id: str, suggestions: list[ImprovementSuggestion]) -> None:
    """Save suggestions to cache."""
    cache.set(
        tenant_id,
        "improvement_suggestions",
        [s.model_dump(mode="json") for s in suggestions],
    )


# --------------------------------------------------------- Feedback trends


@router.get("/feedback-trends")
@require_permission("insights", "read")
async def get_feedback_trends(
    request: Request,
    agent_name: str | None = Query(default=None, description="Filter by agent name"),
    days: int = Query(default=30, ge=1, le=365, description="Time window in days"),
    keyword: str | None = Query(default=None, description="Filter by complaint keyword"),
) -> dict[str, Any]:
    """Get aggregated feedback trends."""
    tenant_id = get_current_tenant_id()
    cache = _get_insights_cache(request)

    data = cache.get(tenant_id, f"feedback_trends_{days}d")
    if not data:
        return {
            "trends": [],
            "metadata": {"skill_correlation_available": False},
            "tenant_id": tenant_id,
        }

    trends = data
    if agent_name:
        trends = [t for t in trends if t.get("agent_name") == agent_name]
    if keyword:
        trends = [
            t
            for t in trends
            if any(
                keyword.lower() in complaint[0].lower()
                for complaint in t.get("top_complaints", [])
            )
        ]

    return {
        "trends": trends,
        "metadata": {"skill_correlation_available": False},
        "tenant_id": tenant_id,
    }


# --------------------------------------------------------- Closure metrics


@router.get("/closure-metrics")
@require_permission("insights", "read")
async def get_closure_metrics(
    request: Request,
    priority: str | None = Query(default=None, description="Filter by priority"),
    status: str | None = Query(default=None, description="Filter by status"),
    days: int = Query(default=30, ge=1, le=365, description="Time window in days"),
) -> dict[str, Any]:
    """Get closure ticket metrics."""
    tenant_id = get_current_tenant_id()
    cache = _get_insights_cache(request)

    data = cache.get(tenant_id, f"closure_metrics_{days}d")
    if not data:
        return {
            "metrics": [],
            "tenant_id": tenant_id,
        }

    metrics = data
    if priority:
        metrics = [m for m in metrics if m.get("priority") == priority]
    if status:
        metrics = [m for m in metrics if m.get("status") == status]

    return {
        "metrics": metrics,
        "tenant_id": tenant_id,
    }


# --------------------------------------------------------- Improvement suggestions


@router.get("/improvements")
@require_permission("insights", "read")
async def get_improvements(
    request: Request,
    status: str | None = Query(default=None, description="Filter by status"),
    target: str | None = Query(default=None, description="Filter by target"),
) -> dict[str, Any]:
    """Get ranked improvement suggestions."""
    tenant_id = get_current_tenant_id()
    cache = _get_insights_cache(request)

    suggestions = _load_suggestions(cache, tenant_id)

    if status:
        suggestions = [s for s in suggestions if s.status == status]
    if target:
        suggestions = [s for s in suggestions if s.target == target]

    # Sort by confidence descending
    suggestions.sort(key=lambda s: s.confidence, reverse=True)

    return {
        "suggestions": [s.model_dump(mode="json") for s in suggestions],
        "tenant_id": tenant_id,
    }


@router.post("/improvements/{suggestion_id}/apply")
@require_permission("insights", "write")
async def apply_improvement(
    suggestion_id: str,
    request: Request,
    body: ApplyImprovementRequest | None = None,
) -> dict[str, Any]:
    """Apply an improvement suggestion."""
    tenant_id = get_current_tenant_id()
    cache = _get_insights_cache(request)
    engine = _get_improvement_engine(request)

    suggestions = _load_suggestions(cache, tenant_id)
    target = next((s for s in suggestions if s.id == suggestion_id), None)

    if target is None:
        raise HTTPException(status_code=404, detail="Suggestion not found")

    if target.status != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Suggestion already {target.status}",
        )

    updated = engine.apply(target, note=body.note if body else None)

    # Replace in list
    suggestions = [updated if s.id == suggestion_id else s for s in suggestions]
    _save_suggestions(cache, tenant_id, suggestions)

    # Trigger memory integration
    try:
        from deerflow.insights.memory_integration import FeedbackMemoryIntegration

        integration = FeedbackMemoryIntegration(cache)
        await integration.on_suggestion_applied(updated)
    except Exception as e:
        logger.warning("Memory integration failed: %s", e, exc_info=True)

    return {
        "success": True,
        "suggestion": updated.model_dump(mode="json"),
    }


@router.post("/improvements/{suggestion_id}/dismiss")
@require_permission("insights", "write")
async def dismiss_improvement(
    suggestion_id: str,
    request: Request,
    body: DismissImprovementRequest,
) -> dict[str, Any]:
    """Dismiss an improvement suggestion."""
    tenant_id = get_current_tenant_id()
    cache = _get_insights_cache(request)
    engine = _get_improvement_engine(request)

    suggestions = _load_suggestions(cache, tenant_id)
    target = next((s for s in suggestions if s.id == suggestion_id), None)

    if target is None:
        raise HTTPException(status_code=404, detail="Suggestion not found")

    if target.status not in ("pending", "accepted"):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot dismiss suggestion with status {target.status}",
        )

    updated = engine.dismiss(target, reason=body.reason)

    # Replace in list
    suggestions = [updated if s.id == suggestion_id else s for s in suggestions]
    _save_suggestions(cache, tenant_id, suggestions)

    return {
        "success": True,
        "suggestion": updated.model_dump(mode="json"),
    }


# --------------------------------------------------------- KB candidates


@router.get("/closure-knowledge")
@require_permission("insights", "read")
async def get_closure_knowledge(
    request: Request,
    status: str | None = Query(default=None, description="Filter by status"),
) -> dict[str, Any]:
    """Get KB candidates from closure tickets."""
    tenant_id = get_current_tenant_id()
    store = KBCandidateStore()

    candidates = store.list_candidates(tenant_id, status=status)

    return {
        "candidates": [c.model_dump(mode="json") for c in candidates],
        "tenant_id": tenant_id,
    }


@router.post("/closure-knowledge/{ticket_id}/promote")
@require_permission("insights", "write")
async def promote_kb_candidate(
    ticket_id: str,
    request: Request,
    body: PromoteKBCandidateRequest,
) -> dict[str, Any]:
    """Promote a KB candidate to approved status."""
    tenant_id = get_current_tenant_id()
    store = KBCandidateStore()

    # Verify candidate exists and belongs to tenant
    candidate = store.get(tenant_id, ticket_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="KB candidate not found")

    if candidate.tenant_id != tenant_id:
        raise HTTPException(
            status_code=403,
            detail="Cannot promote candidate from another tenant",
        )

    updated = store.promote(tenant_id, ticket_id, body.target_kb_id)
    if updated is None:
        raise HTTPException(
            status_code=409,
            detail="Cannot promote candidate: status is not pending_review",
        )

    # TODO: Submit to IndexingDispatcher for KB indexing
    # This requires access to the dispatcher from app state

    return {
        "success": True,
        "candidate": updated.model_dump(mode="json"),
    }


@router.post("/closure-knowledge/{ticket_id}/dismiss")
@require_permission("insights", "write")
async def dismiss_kb_candidate(
    ticket_id: str,
    request: Request,
    body: DismissKBCandidateRequest,
) -> dict[str, Any]:
    """Dismiss a KB candidate."""
    tenant_id = get_current_tenant_id()
    store = KBCandidateStore()

    # Verify candidate exists and belongs to tenant
    candidate = store.get(tenant_id, ticket_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="KB candidate not found")

    if candidate.tenant_id != tenant_id:
        raise HTTPException(
            status_code=403,
            detail="Cannot dismiss candidate from another tenant",
        )

    updated = store.dismiss(tenant_id, ticket_id, body.reason)
    if updated is None:
        raise HTTPException(
            status_code=409,
            detail="Cannot dismiss candidate: status is not pending_review or approved",
        )

    return {
        "success": True,
        "candidate": updated.model_dump(mode="json"),
    }
