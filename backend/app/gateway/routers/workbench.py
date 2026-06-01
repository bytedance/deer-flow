"""Workbench API router — proxies todo statistics through the integration adapter."""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, HTTPException, Request

from deerflow.integrations.adapters.base import AuthContext
from deerflow.integrations.adapters.workbench import WorkbenchAdapter
from deerflow.integrations.config import IntegrationSystemConfig

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/workbench", tags=["workbench"])

_adapter: WorkbenchAdapter | None = None
_adapter_initialized: bool = False


def _get_adapter() -> WorkbenchAdapter:
    global _adapter
    if _adapter is None:
        _adapter = WorkbenchAdapter(
            IntegrationSystemConfig(
                system_key="workbench",
                system_type="workbench",
                display_name="服务平台",
                base_url="http://182.92.187.198",
                auth_type="bearer",
                auth_mode="user_token",
                timeout_seconds=30.0,
            )
        )
    return _adapter


async def _ensure_adapter() -> WorkbenchAdapter:
    global _adapter_initialized
    adapter = _get_adapter()
    if not _adapter_initialized:
        await adapter.initialize()
        _adapter_initialized = True
    return adapter


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

    try:
        adapter = await _ensure_adapter()
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
        logger.exception("Failed to fetch workbench todo stats")
        raise HTTPException(status_code=502, detail=f"Workbench service unavailable: {e}")
