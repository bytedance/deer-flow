"""Workbench API router — proxies todo statistics through SmsAdapter."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request

from deerflow.integrations.adapters.base import AuthContext
from deerflow.integrations.sms_adapter_resolver import ensure_sms_adapter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/workbench", tags=["workbench"])


def _resolve_access_token(request: Request) -> str | None:
    """Extract the user's Bearer token from the incoming request."""
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
    """
    token = _resolve_access_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="User token not available for workbench API")

    adapter = await ensure_sms_adapter()
    try:
        result = await adapter.call(
            capability_key="todo_stats.get",
            query=None,
            auth_context=AuthContext(
                tenant_id="default",
                token=token,
            ),
        )
        return result
    except Exception as e:
        logger.exception("Failed to fetch workbench todo stats via SMS adapter")
        raise HTTPException(status_code=502, detail=f"Workbench service unavailable: {e}")
