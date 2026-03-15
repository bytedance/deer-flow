"""
Image task callback receiver and status polling endpoint.

kie.ai posts task completion callbacks to:
  POST /api/image-tasks/{task_id}/callback

The generate_image tool polls:
  GET /api/image-tasks/{task_id}
"""

import asyncio
import logging
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/image-tasks", tags=["image-tasks"])

# In-memory store: task_id -> {"status": "pending"|"success"|"fail", "urls": [...], "error": "..."}
# Entries expire after TASK_TTL seconds to prevent unbounded growth.
_task_store: dict[str, dict[str, Any]] = {}
TASK_TTL = 600  # 10 minutes
_timestamps: dict[str, float] = {}


def _purge_old() -> None:
    now = time.time()
    expired = [k for k, t in _timestamps.items() if now - t > TASK_TTL]
    for k in expired:
        _task_store.pop(k, None)
        _timestamps.pop(k, None)


def register_task(task_id: str) -> None:
    """Called by the tool when a task is created so we can track it."""
    _purge_old()
    _task_store[task_id] = {"status": "pending", "urls": [], "error": None}
    _timestamps[task_id] = time.time()


@router.post("/{task_id}/register")
async def register_task_endpoint(task_id: str) -> dict:
    """Register a newly-created task so the gateway can track its callback."""
    register_task(task_id)
    return {"ok": True}


@router.post("/{task_id}/callback")
async def receive_callback(task_id: str, request: Request) -> dict:
    """Receive completion callback from kie.ai."""
    try:
        body = await request.json()
    except Exception:
        body = {}

    logger.info("Image task callback received: task_id=%s code=%s", task_id, body.get("code"))

    task_data = body.get("data", {})
    state = task_data.get("state", "")

    if state == "success":
        import json as _json

        result_raw = task_data.get("resultJson", "{}")
        result = _json.loads(result_raw) if isinstance(result_raw, str) else result_raw
        urls = result.get("resultUrls", [])
        _task_store[task_id] = {"status": "success", "urls": urls, "error": None}
        logger.info("Image task %s succeeded: %s", task_id, urls)
    elif state == "fail":
        fail_msg = task_data.get("failMsg") or body.get("msg", "Unknown error")
        _task_store[task_id] = {"status": "fail", "urls": [], "error": fail_msg}
        logger.warning("Image task %s failed: %s", task_id, fail_msg)
    else:
        # Unexpected payload — store raw for debugging
        _task_store[task_id] = {"status": "unknown", "urls": [], "error": str(body)[:200]}

    _timestamps[task_id] = time.time()
    return {"ok": True}


@router.get("/{task_id}")
async def get_task_status(task_id: str) -> dict:
    """Poll task status. Returns pending until callback arrives."""
    result = _task_store.get(task_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return result
