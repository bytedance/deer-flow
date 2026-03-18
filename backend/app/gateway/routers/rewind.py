import logging
import os
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from deerflow.config.app_config import get_app_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["threads"])


class RewindRequest(BaseModel):
    anchor_user_message_id: str = Field(..., min_length=1)


class RewindResponse(BaseModel):
    thread_id: str
    backup_thread_id: str | None
    filled_text: str
    rewound_to_message_count: int


def _resolve_langgraph_url() -> str:
    for key in ("LANGGRAPH_URL", "DEERFLOW_LANGGRAPH_URL"):
        value = os.getenv(key)
        if value and value.strip():
            return value.strip().rstrip("/")

    try:
        extra = (get_app_config().model_extra or {}).get("channels")
        if isinstance(extra, dict):
            value = extra.get("langgraph_url")
            if isinstance(value, str) and value.strip():
                return value.strip().rstrip("/")
    except Exception as exc:
        logger.error("Failed to resolve langgraph_url from app config: %s", exc, exc_info=exc)

    if Path("/.dockerenv").exists():
        return "http://langgraph:2024"
    return "http://localhost:2024"


def _extract_text_from_message(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts).strip()
    return ""


async def _langgraph_request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    json: dict[str, Any] | None = None,
) -> Any:
    try:
        response = await client.request(method, url, json=json)
    except Exception as exc:
        logger.error("LangGraph request failed: %s %s err=%s", method, url, exc, exc_info=exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="LangGraph request failed")
    if response.status_code >= 400:
        body_preview = response.text[:1000]
        logger.error(
            "LangGraph response error: %s %s status=%s body=%s",
            method,
            url,
            response.status_code,
            body_preview,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"LangGraph response error (status={response.status_code})",
        )
    try:
        data = response.json()
    except Exception as exc:
        logger.error("LangGraph response JSON decode failed: %s %s err=%s", method, url, exc, exc_info=exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="LangGraph response invalid JSON")
    if not isinstance(data, (dict, list)):
        logger.error(
            "LangGraph response unexpected type: %s %s type=%s",
            method,
            url,
            type(data),
        )
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="LangGraph response invalid format")
    return data


@router.post(
    "/threads/{thread_id}/rewind",
    response_model=RewindResponse,
    summary="Rewind Conversation to Before a Turn",
    description="Rewind the thread state to before a given human message, while creating a hidden backup thread with the previous messages/title/todos.",
)
async def rewind_thread(thread_id: str, request: RewindRequest) -> RewindResponse:
    langgraph_url = _resolve_langgraph_url()
    async with httpx.AsyncClient(base_url=langgraph_url, timeout=30.0) as client:
        runs_data = await _langgraph_request(client, "GET", f"/threads/{thread_id}/runs")
        runs: list[Any] | None = None
        if isinstance(runs_data, list):
            runs = runs_data
        elif isinstance(runs_data, dict) and isinstance(runs_data.get("runs"), list):
            runs = runs_data.get("runs")
        if isinstance(runs, list):
            for run in runs:
                if not isinstance(run, dict):
                    continue
                status_value = run.get("status")
                if isinstance(status_value, str) and status_value.lower() in {
                    "running",
                    "pending",
                    "in_progress",
                    "queued",
                }:
                    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Thread is running")

        state = await _langgraph_request(client, "GET", f"/threads/{thread_id}/state")
        values = state.get("values")
        if not isinstance(values, dict):
            logger.error("Invalid thread state values: thread_id=%s", thread_id)
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Invalid thread state")

        messages = values.get("messages")
        if not isinstance(messages, list):
            logger.error("Invalid thread messages: thread_id=%s type=%s", thread_id, type(messages))
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Invalid thread messages")

        anchor_index = -1
        anchor_message: dict[str, Any] | None = None
        for i, msg in enumerate(messages):
            if not isinstance(msg, dict):
                continue
            if msg.get("type") != "human":
                continue
            if msg.get("id") == request.anchor_user_message_id:
                anchor_index = i
                anchor_message = msg
                break

        if anchor_index < 0 or anchor_message is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Anchor message not found")

        filled_text = _extract_text_from_message(anchor_message)
        title = values.get("title") if isinstance(values.get("title"), str) else ""

        backup_thread_id: str | None = None

        history_data = await _langgraph_request(
            client,
            "POST",
            f"/threads/{thread_id}/history",
            json={"limit": 100},
        )
        if not isinstance(history_data, list):
            logger.error("Invalid history response: thread_id=%s type=%s", thread_id, type(history_data))
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Invalid thread history")

        def _state_has_anchor(state_item: Any) -> bool:
            if not isinstance(state_item, dict):
                return False
            values = state_item.get("values")
            if not isinstance(values, dict):
                return False
            msgs = values.get("messages")
            if not isinstance(msgs, list):
                return False
            for m in msgs:
                if isinstance(m, dict) and m.get("type") == "human" and m.get("id") == request.anchor_user_message_id:
                    return True
            return False

        has_anchor_flags = [_state_has_anchor(st) for st in history_data]

        base_idx: int | None = None

        # Case A: history is ordered newest -> oldest
        # Find boundary where anchor disappears.
        for i in range(len(has_anchor_flags) - 1):
            if has_anchor_flags[i] and not has_anchor_flags[i + 1]:
                base_idx = i + 1
                break

        # Case B: history is ordered oldest -> newest
        # Find boundary where anchor appears.
        if base_idx is None:
            for i in range(len(has_anchor_flags) - 1):
                if not has_anchor_flags[i] and has_anchor_flags[i + 1]:
                    base_idx = i
                    break

        if base_idx is None:
            if any(has_anchor_flags):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Anchor found but history window does not include a pre-anchor checkpoint (increase history limit)",
                )
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Anchor message not found in history")

        base_state = history_data[base_idx]
        if _state_has_anchor(base_state):
            logger.error("Selected base_state still contains anchor: thread_id=%s base_idx=%s", thread_id, base_idx)
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Invalid rewind base state")
        checkpoint = base_state.get("checkpoint") if isinstance(base_state, dict) else None
        checkpoint_id = checkpoint.get("checkpoint_id") if isinstance(checkpoint, dict) else None
        if not isinstance(checkpoint_id, str) or not checkpoint_id.strip():
            logger.error("Invalid checkpoint_id in history: thread_id=%s", thread_id)
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Invalid checkpoint")

        await _langgraph_request(
            client,
            "POST",
            f"/threads/{thread_id}/state",
            json={
                "checkpoint_id": checkpoint_id,
                "values": {
                    "title": title,
                    "todos": [],
                },
            },
        )

        base_values = base_state.get("values") if isinstance(base_state, dict) else None
        base_messages = base_values.get("messages") if isinstance(base_values, dict) else None
        rewound_to_message_count = len(base_messages) if isinstance(base_messages, list) else 0

        return RewindResponse(
            thread_id=thread_id,
            backup_thread_id=backup_thread_id,
            filled_text=filled_text,
            rewound_to_message_count=rewound_to_message_count,
        )
