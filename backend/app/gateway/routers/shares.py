"""Public conversation share endpoints."""

from __future__ import annotations

import logging
import secrets
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.gateway.authz import require_permission
from app.gateway.deps import get_checkpointer, get_store
from app.gateway.utils import sanitize_log_param
from deerflow.runtime import serialize_channel_values
from deerflow.utils.time import now_iso

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/shares", tags=["shares"])

_SHARES_NS = ("shares",)
_SHARE_ID_BYTES = 16


class ShareCreateRequest(BaseModel):
    """Request body for creating a public share snapshot."""

    message_ids: list[str] = Field(
        min_length=1,
        description="Message IDs to include in the public share.",
    )
    title: str | None = Field(default=None, max_length=256, description="Optional share title")


class ShareCreateResponse(BaseModel):
    share_id: str
    title: str | None = None
    created_at: str


class ShareResponse(BaseModel):
    share_id: str
    title: str | None = None
    messages: list[dict[str, Any]] = Field(default_factory=list)
    created_at: str


def _extract_message_id(message: dict[str, Any]) -> str | None:
    message_id = message.get("id")
    return message_id if isinstance(message_id, str) and message_id else None


def _has_displayable_content(message: dict[str, Any]) -> bool:
    content = message.get("content")
    if isinstance(content, str):
        return bool(content.strip())
    if isinstance(content, list):
        return len(content) > 0
    return content is not None


def _is_shareable_message(message: dict[str, Any]) -> bool:
    message_type = message.get("type")
    if message_type == "human":
        return _has_displayable_content(message)
    if message_type == "ai":
        return _has_displayable_content(message) and not message.get("tool_calls") and not message.get("invalid_tool_calls")
    return False


async def _put_unique_share(store, value: dict[str, Any]) -> str:
    for _ in range(4):
        share_id = secrets.token_urlsafe(_SHARE_ID_BYTES)
        if await store.aget(_SHARES_NS, share_id) is None:
            await store.aput(_SHARES_NS, share_id, value)
            return share_id
    raise HTTPException(status_code=500, detail="Failed to create share")


@router.post("/threads/{thread_id}", response_model=ShareCreateResponse)
@require_permission("threads", "read", owner_check=True, require_existing=True)
async def create_thread_share(thread_id: str, body: ShareCreateRequest, request: Request) -> ShareCreateResponse:
    """Create a public immutable snapshot from an owned thread."""
    store = get_store(request)
    if store is None:
        raise HTTPException(status_code=503, detail="Store not available")

    checkpointer = get_checkpointer(request)
    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    try:
        checkpoint_tuple = await checkpointer.aget_tuple(config)
    except Exception:
        logger.exception("Failed to get state for share source thread %s", sanitize_log_param(thread_id))
        raise HTTPException(status_code=500, detail="Failed to create share")

    if checkpoint_tuple is None:
        raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")

    checkpoint = getattr(checkpoint_tuple, "checkpoint", {}) or {}
    channel_values = checkpoint.get("channel_values", {}) or {}
    serialized_values = serialize_channel_values(channel_values)
    all_messages = serialized_values.get("messages", [])
    if not isinstance(all_messages, list) or not all_messages:
        raise HTTPException(status_code=400, detail="Thread has no messages to share")

    requested_ids = [message_id for message_id in body.message_ids if message_id]
    if not requested_ids:
        raise HTTPException(status_code=400, detail="No message IDs selected")

    requested_id_set = set(requested_ids)
    selected_messages = [message for message in all_messages if isinstance(message, dict) and _extract_message_id(message) in requested_id_set]
    selected_id_set = {message_id for message in selected_messages if (message_id := _extract_message_id(message)) is not None}
    missing_ids = [message_id for message_id in requested_ids if message_id not in selected_id_set]
    if missing_ids:
        raise HTTPException(status_code=400, detail=f"Message IDs not found: {', '.join(missing_ids)}")

    non_shareable_ids = [message_id for message in selected_messages if (message_id := _extract_message_id(message)) is not None and not _is_shareable_message(message)]
    if non_shareable_ids:
        raise HTTPException(status_code=400, detail=f"Message IDs are not shareable: {', '.join(non_shareable_ids)}")

    created_at = now_iso()
    title = body.title or serialized_values.get("title")
    if not isinstance(title, str):
        title = None

    share_id = await _put_unique_share(
        store,
        {
            "title": title,
            "messages": selected_messages,
            "created_at": created_at,
        },
    )
    return ShareCreateResponse(share_id=share_id, title=title, created_at=created_at)


@router.get("/{share_id}", response_model=ShareResponse)
async def get_share(share_id: str, request: Request) -> ShareResponse:
    """Read a public share snapshot without requiring authentication."""
    store = get_store(request)
    if store is None:
        raise HTTPException(status_code=503, detail="Store not available")

    item = await store.aget(_SHARES_NS, share_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Share not found")

    value = item.value or {}
    messages = value.get("messages", [])
    if not isinstance(messages, list):
        messages = []
    title = value.get("title")
    return ShareResponse(
        share_id=share_id,
        title=title if isinstance(title, str) else None,
        messages=messages,
        created_at=value.get("created_at", ""),
    )
