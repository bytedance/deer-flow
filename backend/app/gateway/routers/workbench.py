"""Workbench API router — proxies todo statistics from external 服务平台."""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, HTTPException, Request

from deerflow.rpc.workbench_service import WorkbenchServiceClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/workbench", tags=["workbench"])

_client: WorkbenchServiceClient | None = None


def _get_client() -> WorkbenchServiceClient:
    global _client
    if _client is None:
        _client = WorkbenchServiceClient()
    return _client


def _resolve_access_token(request: Request) -> str | None:
    """Extract the user's Bearer token from the incoming request.

    Checks, in order:
    1. Authorization header (Bearer <token>)
    2. access_token cookie
    3. ins_base_token from request.state.user (set by ins_base auth provider)
    """
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        if token:
            return token

    cookie_token = request.cookies.get("access_token", "").strip()
    if cookie_token:
        return cookie_token

    state_user = getattr(getattr(request, "state", None), "user", None)
    if isinstance(state_user, dict):
        token = str(state_user.get("ins_base_token") or "").strip()
        if token:
            return token

    return None


@router.get("/todo-stats")
async def get_todo_stats(request: Request) -> dict:
    """Fetch workbench todo statistics for the current user.

    Returns counts for:
    - anomalyPending: 异常待处理 (pendingCount)
    - startupPending: 启机待处理 (startPendingCount)
    - shutdownPending: 停机待处理 (stopPendingCount)

    Time range: current time ± 1 day (in epoch milliseconds).
    Requires the user's InS Bearer token for authentication to the external service.
    """
    token = _resolve_access_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="User token not available for workbench API")

    now_ms = int(time.time() * 1000)
    one_day_ms = 24 * 60 * 60 * 1000
    start_time_ms = now_ms - one_day_ms
    end_time_ms = now_ms

    try:
        client = _get_client()
        data = await client.get_stats(
            start_time_ms=start_time_ms,
            end_time_ms=end_time_ms,
            token=token,
        )
        return {
            "anomalyPending": data.get("pendingCount", 0),
            "startupPending": data.get("startPendingCount", 0),
            "shutdownPending": data.get("stopPendingCount", 0),
        }
    except Exception as e:
        logger.exception("Failed to fetch workbench todo stats")
        raise HTTPException(status_code=502, detail=f"Workbench service unavailable: {e}")
