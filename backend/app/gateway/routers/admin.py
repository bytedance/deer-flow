"""Admin API router — system stats, tenant management, usage reports, and audit logs."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.gateway.auth.dependencies import require_admin
from app.gateway.deps import get_checkpointer
from deerflow.config.tenant_storage import TenantConfig, TenantStorage
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
    daily_quota_usd: float = 50.0
    monthly_quota_usd: float = 1000.0


class CreateTenantRequest(BaseModel):
    tenant_id: str = Field(..., description="Tenant ID", pattern=r"^[A-Za-z0-9-]+$")
    name: str = Field(..., description="Tenant display name")


class UpdateTenantRequest(BaseModel):
    name: str | None = Field(default=None, description="New display name")
    is_active: bool | None = Field(default=None, description="Enable or disable the tenant")
    daily_quota_usd: float | None = Field(default=None, description="Daily cost quota in USD")
    monthly_quota_usd: float | None = Field(default=None, description="Monthly cost quota in USD")


class AuditLogResponse(BaseModel):
    entries: list[dict]
    total: int
    limit: int
    offset: int


def _get_tenant_storage() -> TenantStorage:
    return TenantStorage()


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


def _build_tenant_summary(
    tc: TenantConfig,
    today_records: list,
    month_records: list,
    thread_count: int = 0,
) -> TenantSummary:
    """Build a TenantSummary from a TenantConfig and usage data."""
    tenant_today = [r for r in today_records if r.tenant_id == tc.tenant_id]
    tenant_month = [r for r in month_records if r.tenant_id == tc.tenant_id]
    return TenantSummary(
        tenant_id=tc.tenant_id,
        name=tc.name,
        created_at=tc.created_at,
        user_count=1,
        thread_count=thread_count,
        cost_today=round(sum(r.cost_usd for r in tenant_today), 4),
        cost_month=round(sum(r.cost_usd for r in tenant_month), 4),
        is_active=tc.is_active,
        daily_quota_usd=tc.daily_quota_usd,
        monthly_quota_usd=tc.monthly_quota_usd,
    )


async def _discover_thread_counts(checkpointer) -> dict[str, int]:
    """Scan checkpointer for per-tenant thread counts."""
    counts: dict[str, int] = {}
    if checkpointer is None:
        return counts
    try:
        async for ckpt in checkpointer.alist(None):
            cfg = getattr(ckpt, "config", {})
            if cfg.get("configurable", {}).get("checkpoint_ns", ""):
                continue
            meta = getattr(ckpt, "metadata", {}) or {}
            tid = meta.get("tenant_id", "default")
            counts[tid] = counts.get(tid, 0) + 1
    except Exception:
        pass
    return counts


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


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

    ts = _get_tenant_storage()
    ts.ensure_default()
    all_tenants = ts.list_all()
    thread_counts = await _discover_thread_counts(checkpointer)
    active_today: set[str] = {r.tenant_id for r in today_records}

    return AdminStatsResponse(
        total_tenants=len(all_tenants),
        active_tenants_today=len(active_today),
        total_threads=sum(thread_counts.values()),
        total_llm_calls_today=total_llm_calls_today,
        total_tokens_today=total_tokens_today,
        total_cost_today=round(total_cost_today, 4),
        total_cost_month=round(total_cost_month, 4),
    )


# ---------------------------------------------------------------------------
# Tenant CRUD
# ---------------------------------------------------------------------------


@router.get("/tenants", response_model=list[TenantSummary])
async def list_tenants(request: Request, user=Depends(require_admin)) -> list[TenantSummary]:
    """List all registered tenants with usage data (admin only)."""
    checkpointer = get_checkpointer(request)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    month_start = datetime.now(timezone.utc).strftime("%Y-%m") + "-01"

    today_records = _get_cross_tenant_records(start_date=today)
    month_records = _get_cross_tenant_records(start_date=month_start)
    thread_counts = await _discover_thread_counts(checkpointer)

    ts = _get_tenant_storage()
    ts.ensure_default()
    all_tenants = ts.list_all()

    result: list[TenantSummary] = []
    for tc in all_tenants:
        result.append(
            _build_tenant_summary(
                tc, today_records, month_records,
                thread_count=thread_counts.get(tc.tenant_id, 0),
            )
        )

    result.sort(key=lambda t: t.cost_month, reverse=True)
    return result


@router.post("/tenants", response_model=TenantSummary)
def create_tenant(req: CreateTenantRequest, user=Depends(require_admin)) -> TenantSummary:
    """Create a new tenant (admin only)."""
    ts = _get_tenant_storage()
    try:
        tc = ts.create(TenantConfig(tenant_id=req.tenant_id, name=req.name))
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return _build_tenant_summary(tc, [], [])


@router.put("/tenants/{tenant_id}", response_model=TenantSummary)
def update_tenant(tenant_id: str, req: UpdateTenantRequest, user=Depends(require_admin)) -> TenantSummary:
    """Update a tenant's configuration (admin only)."""
    ts = _get_tenant_storage()
    fields: dict = {}
    if req.name is not None:
        fields["name"] = req.name
    if req.is_active is not None:
        fields["is_active"] = req.is_active
    if req.daily_quota_usd is not None:
        fields["daily_quota_usd"] = req.daily_quota_usd
    if req.monthly_quota_usd is not None:
        fields["monthly_quota_usd"] = req.monthly_quota_usd

    tc = ts.update(tenant_id, **fields)
    if tc is None:
        raise HTTPException(status_code=404, detail=f"Tenant {tenant_id!r} not found")
    return _build_tenant_summary(tc, [], [])


@router.delete("/tenants/{tenant_id}")
def delete_tenant(tenant_id: str, user=Depends(require_admin)) -> dict:
    """Delete a tenant (admin only)."""
    if tenant_id == "default":
        raise HTTPException(status_code=400, detail="Cannot delete the default tenant")
    ts = _get_tenant_storage()
    if not ts.delete(tenant_id):
        raise HTTPException(status_code=404, detail=f"Tenant {tenant_id!r} not found")
    return {"success": True}


# ---------------------------------------------------------------------------
# Usage
# ---------------------------------------------------------------------------


@router.get("/usage", response_model=list[dict])
def get_admin_usage(
    start_date: str | None = None,
    end_date: str | None = None,
    user=Depends(require_admin),
) -> list[dict]:
    """Get aggregated usage data for all tenants (admin only)."""
    records = _get_cross_tenant_records(start_date=start_date, end_date=end_date)
    return [r.to_dict() for r in records]


# ---------------------------------------------------------------------------
# Audit Logs
# ---------------------------------------------------------------------------


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
