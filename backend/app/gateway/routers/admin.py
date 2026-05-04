"""Admin API router — system stats, tenant management, usage reports, and audit logs."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from app.gateway.auth.dependencies import require_admin
from app.gateway.deps import get_checkpointer
from deerflow.content_safety.log_storage import AuditLogEntry, AuditLogStorage
from deerflow.cost.storage import UsageStorage

router = APIRouter(prefix="/api/admin", tags=["admin"])


class AdminStatsResponse(BaseModel):
    total_tenants: int
    active_tenants_today: int
    total_threads: int
    total_llm_calls_today: int
    total_tokens_today: int
    total_cost_today: float
    total_cost_month: float


class TenantSummary(BaseModel):
    tenant_id: str
    name: str
    created_at: str
    user_count: int
    thread_count: int
    cost_today: float
    cost_month: float
    is_active: bool


class CreateTenantRequest(BaseModel):
    tenant_id: str = Field(..., description="Tenant ID", pattern=r"^[A-Za-z0-9-]+$")
    name: str = Field(..., description="Tenant display name")


class UpdateTenantRequest(BaseModel):
    name: str | None = Field(default=None, description="New display name")


class AuditLogResponse(BaseModel):
    entries: list[dict]
    total: int
    limit: int
    offset: int


def _get_cross_tenant_records(
    start_date: str | None = None,
    end_date: str | None = None,
) -> list:
    """Fetch usage records across all tenants (admin view)."""
    return UsageStorage.query_all_tenants(
        start_date=start_date, end_date=end_date,
    )


def _get_audit_storage() -> AuditLogStorage:
    return AuditLogStorage()


async def _discover_tenants(cross_tenant_records: list, checkpointer) -> dict[str, dict]:
    """Discover all tenants from usage records and checkpointer metadata.

    Returns a dict mapping ``tenant_id`` → ``{name, thread_count, is_active}``.
    """
    tenants: dict[str, dict] = {}

    # Phase 1: scan cross-tenant usage records for tenant activity
    for r in cross_tenant_records:
        if r.tenant_id not in tenants:
            tenants[r.tenant_id] = {
                "name": r.tenant_id,
                "thread_count": 0,
                "is_active": True,
            }

    # Phase 2: scan checkpointer for tenants with threads but no usage yet
    if checkpointer is not None:
        try:
            async for ckpt in checkpointer.alist(None):
                cfg = getattr(ckpt, "config", {})
                if cfg.get("configurable", {}).get("checkpoint_ns", ""):
                    continue
                meta = getattr(ckpt, "metadata", {}) or {}
                tid = meta.get("tenant_id", "default")
                if tid not in tenants:
                    tenants[tid] = {
                        "name": tid,
                        "thread_count": 0,
                        "is_active": True,
                    }
                tenants[tid]["thread_count"] += 1
        except Exception:
            pass

    # Ensure "default" always exists
    if "default" not in tenants:
        tenants["default"] = {
            "name": "Default Tenant",
            "thread_count": 0,
            "is_active": True,
        }
    elif tenants["default"]["name"] == "default":
        tenants["default"]["name"] = "Default Tenant"

    return tenants


@router.get("/stats", response_model=AdminStatsResponse)
async def get_admin_stats(request: Request, user=Depends(require_admin)) -> AdminStatsResponse:
    """Get system overview statistics (admin only)."""
    checkpointer = get_checkpointer(request)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    today_records = _get_cross_tenant_records(start_date=today)
    month_records = _get_cross_tenant_records(start_date=datetime.now(timezone.utc).strftime("%Y-%m") + "-01")

    total_llm_calls_today = len(today_records)
    total_tokens_today = sum(r.total_tokens for r in today_records)
    total_cost_today = sum(r.cost_usd for r in today_records)
    total_cost_month = sum(r.cost_usd for r in month_records)

    tenants = await _discover_tenants(today_records + month_records, checkpointer)
    active_today: set[str] = {r.tenant_id for r in today_records}

    return AdminStatsResponse(
        total_tenants=len(tenants),
        active_tenants_today=len(active_today),
        total_threads=sum(t["thread_count"] for t in tenants.values()),
        total_llm_calls_today=total_llm_calls_today,
        total_tokens_today=total_tokens_today,
        total_cost_today=round(total_cost_today, 4),
        total_cost_month=round(total_cost_month, 4),
    )


@router.get("/tenants", response_model=list[TenantSummary])
async def list_tenants(request: Request, user=Depends(require_admin)) -> list[TenantSummary]:
    """List all tenants discovered from usage data and checkpointer (admin only)."""
    checkpointer = get_checkpointer(request)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    month_start = datetime.now(timezone.utc).strftime("%Y-%m") + "-01"

    today_records = _get_cross_tenant_records(start_date=today)
    month_records = _get_cross_tenant_records(start_date=month_start)

    tenants = await _discover_tenants(today_records + month_records, checkpointer)

    result: list[TenantSummary] = []
    for tid, info in tenants.items():
        tenant_today = [r for r in today_records if r.tenant_id == tid]
        tenant_month = [r for r in month_records if r.tenant_id == tid]
        result.append(
            TenantSummary(
                tenant_id=tid,
                name=info["name"],
                created_at="",
                user_count=1,
                thread_count=info["thread_count"],
                cost_today=round(sum(r.cost_usd for r in tenant_today), 4),
                cost_month=round(sum(r.cost_usd for r in tenant_month), 4),
                is_active=info["is_active"],
            )
        )

    result.sort(key=lambda t: t.cost_month, reverse=True)
    return result


@router.post("/tenants", response_model=TenantSummary)
def create_tenant(req: CreateTenantRequest, user=Depends(require_admin)) -> TenantSummary:
    """Create a new tenant (admin only)."""
    return TenantSummary(
        tenant_id=req.tenant_id,
        name=req.name,
        created_at=datetime.now(timezone.utc).isoformat(),
        user_count=0,
        thread_count=0,
        cost_today=0.0,
        cost_month=0.0,
        is_active=True,
    )


@router.put("/tenants/{tenant_id}", response_model=TenantSummary)
def update_tenant(tenant_id: str, req: UpdateTenantRequest, user=Depends(require_admin)) -> TenantSummary:
    """Update a tenant's configuration (admin only)."""
    return TenantSummary(
        tenant_id=tenant_id,
        name=req.name or tenant_id,
        created_at="",
        user_count=0,
        thread_count=0,
        cost_today=0.0,
        cost_month=0.0,
        is_active=True,
    )


@router.get("/usage", response_model=list[dict])
def get_admin_usage(
    start_date: str | None = None,
    end_date: str | None = None,
    user=Depends(require_admin),
) -> list[dict]:
    """Get aggregated usage data for all tenants (admin only)."""
    records = _get_cross_tenant_records(start_date=start_date, end_date=end_date)
    return [r.to_dict() for r in records]


@router.get("/logs", response_model=AuditLogResponse)
def get_admin_logs(
    tenant_id: str | None = Query(default=None, description="Filter by tenant ID"),
    thread_id: str | None = Query(default=None, description="Filter by thread ID"),
    direction: str | None = Query(default=None, description="Filter by direction: input or output"),
    start_date: str | None = Query(default=None, description="Start date (ISO format)"),
    end_date: str | None = Query(default=None, description="End date (ISO format)"),
    limit: int = Query(default=100, ge=1, le=1000, description="Max entries to return"),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
    user=Depends(require_admin),
) -> AuditLogResponse:
    """Query content safety audit logs (admin only)."""
    storage = _get_audit_storage()
    entries, total = storage.query(
        tenant_id=tenant_id,
        thread_id=thread_id,
        direction=direction,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        offset=offset,
    )
    return AuditLogResponse(
        entries=[e.to_dict() for e in entries],
        total=total,
        limit=limit,
        offset=offset,
    )
