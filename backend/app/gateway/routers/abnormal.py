"""Abnormal list/detail proxy endpoints.

Reads SmsAdapter config from config.yaml via shared resolver.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query, Request

from deerflow.integrations.adapters.base import AuthContext
from deerflow.integrations.sms_adapter_resolver import ensure_sms_adapter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/abnormal", tags=["abnormal"])


def _resolve_token(request: Request) -> str | None:
    """Extract user Bearer token from request, with env fallback."""
    # 1. Authorization header
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        if token:
            return token
    # 2. Cookie
    cookie_token = request.cookies.get("access_token", "").strip()
    if cookie_token:
        return cookie_token
    # 3. Auth middleware state
    state_user = getattr(getattr(request, "state", None), "user", None)
    if isinstance(state_user, dict):
        token = str(state_user.get("ins_base_token") or "").strip()
        if token:
            return token
    # 4. Environment fallback (for A2UI components calling without user context)
    import os
    env_token = os.environ.get("INS_ACCESS_TOKEN", "").strip()
    if env_token:
        return env_token
    return None


@router.get("/list")
async def abnormal_list(
    request: Request,
    current_page: int = Query(1, ge=1, description="当前页码"),
    page_size: int = Query(10, ge=1, le=100, description="每页条数"),
    start_time: int | None = Query(None, description="开始时间（毫秒时间戳），默认30天前"),
    end_time: int | None = Query(None, description="结束时间（毫秒时间戳），默认当前"),
    org_id: int = Query(0, description="组织ID"),
):
    """获取异常列表。"""
    import time

    token = _resolve_token(request)
    # SMS API requires time range — default to last 30 days
    if end_time is None:
        end_time = int(time.time() * 1000)
    if start_time is None:
        start_time = end_time - 30 * 24 * 3600 * 1000

    try:
        adapter = await ensure_sms_adapter()
        from deerflow.integrations.models.queries import AbnormalListQuery

        query = AbnormalListQuery(
            tenant_id="default",
            current_page=current_page,
            page_size=page_size,
            start_time=start_time,
            end_time=end_time,
            org_id=org_id,
        )
        items = await adapter.call(
            "abnormal.list",
            query,
            AuthContext(tenant_id="default", token=token),
        )
        logger.info("abnormal.list returned %d items (page=%d, size=%d, start=%s, end=%s)",
                     len(items) if items else 0, current_page, page_size, start_time, end_time)
    except Exception as e:
        logger.exception("Failed to fetch abnormal list")
        raise HTTPException(status_code=502, detail=str(e)) from e

    return {
        "items": [
            {
                "abnormal_id": item.abnormal_id,
                "mac_path": item.mac_path,
                "mac_name": item.mac_name,
                "component_name": item.component_name,
                "mac_id": item.mac_id,
                "component_id": item.component_id,
                "latest_health": item.latest_health,
                "latest_level": item.latest_level,
                "serious_level": item.serious_level,
                "event_count": item.event_count,
                "first_event_time": item.first_event_time,
                "lastest_event_time": item.lastest_event_time,
                "process_status": item.process_status,
                "run_status": item.run_status,
                "mac_type": item.mac_type,
            }
            for item in items
        ],
    }


@router.get("/detail")
async def abnormal_detail(
    request: Request,
    abnormal_id: str = Query(..., min_length=1, description="异常ID"),
):
    """获取异常详情。"""
    token = _resolve_token(request)
    try:
        adapter = await ensure_sms_adapter()
        from deerflow.integrations.models.queries import AbnormalDetailQuery

        query = AbnormalDetailQuery(tenant_id="default", abnormal_id=abnormal_id)
        detail = await adapter.call(
            "abnormal.detail",
            query,
            AuthContext(tenant_id="default", token=token),
        )
    except Exception as e:
        logger.exception("Failed to fetch abnormal detail")
        raise HTTPException(status_code=502, detail=str(e)) from e

    return {
        "abnormal_id": detail.abnormal_id,
        "mac_path": detail.mac_path,
        "mac_name": detail.mac_name,
        "component_name": detail.component_name,
        "process_status": detail.process_status,
        "events": [
            {
                "time": e.time,
                "health": e.health,
                "type": e.type,
                "run_status": e.run_status,
                "event_level": e.event_level,
                "desc": e.desc,
                "factory_id": e.factory_id,
                "time_range_start": e.time_range_start,
                "time_range_end": e.time_range_end,
                "points": [
                    {
                        "point_id": p.point_id,
                        "point_name": p.point_name,
                        "value_type": p.value_type,
                        "point_type": p.point_type,
                    }
                    for p in e.points
                ],
            }
            for e in detail.events
        ],
        "logs": list(detail.logs),
    }
