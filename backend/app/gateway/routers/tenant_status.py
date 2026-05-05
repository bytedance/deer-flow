"""Tenant status endpoint — lightweight check for frontend guard."""

from __future__ import annotations

from fastapi import APIRouter, Request

from deerflow.config.tenant import get_current_tenant_id
from deerflow.config.tenant_storage import TenantStorage

router = APIRouter()


@router.get("/api/tenant/status")
async def tenant_status(request: Request):
    tenant_id = get_current_tenant_id()
    ts = TenantStorage()
    tc = ts.get(tenant_id)
    if tc is None:
        return {"tenant_id": tenant_id, "is_active": False, "name": tenant_id, "found": False}
    return {
        "tenant_id": tc.tenant_id,
        "is_active": tc.is_active,
        "name": tc.name,
        "found": True,
    }
