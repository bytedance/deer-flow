from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from src.config.app_config import get_app_config

router = APIRouter(prefix="/api/threads", tags=["threads"])
logger = logging.getLogger(__name__)

SortBy = Literal["updated_at", "created_at"]
SortOrder = Literal["desc", "asc"]


class ThreadSummary(BaseModel):
    """Lean thread payload for list UIs."""

    thread_id: str
    updated_at: str | None = None
    values: dict[str, str] = Field(default_factory=dict)


class ThreadSummariesResponse(BaseModel):
    """Paginated summaries response."""

    threads: list[ThreadSummary]
    next_offset: int | None = None


ThreadSummary.model_rebuild()
ThreadSummariesResponse.model_rebuild()


def _resolve_langgraph_url() -> str:
    config = get_app_config()
    extra = config.model_extra or {}
    channels_cfg = extra.get("channels")
    if isinstance(channels_cfg, Mapping):
        langgraph_url = channels_cfg.get("langgraph_url")
        if isinstance(langgraph_url, str) and langgraph_url.strip():
            return langgraph_url
    return "http://localhost:2024"


def _pick_title(values: Any) -> str:
    if isinstance(values, Mapping):
        title = values.get("title")
        if isinstance(title, str) and title.strip():
            return title
    return "Untitled"


def _to_thread_summary(raw: Any) -> ThreadSummary | None:
    if not isinstance(raw, Mapping):
        return None
    thread_id = raw.get("thread_id")
    if not isinstance(thread_id, str) or not thread_id.strip():
        return None
    updated_at = raw.get("updated_at")
    return ThreadSummary(
        thread_id=thread_id,
        updated_at=updated_at if isinstance(updated_at, str) else None,
        values={"title": _pick_title(raw.get("values"))},
    )


@router.get(
    "/summaries",
    response_model=ThreadSummariesResponse,
    summary="List Thread Summaries",
    description="Return paginated thread summaries for list UIs with minimal payload.",
)
async def list_thread_summaries(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    sort_by: SortBy = Query(default="updated_at"),
    sort_order: SortOrder = Query(default="desc"),
) -> ThreadSummariesResponse:
    """Fetch thread list from LangGraph and return compact title-only summaries."""

    try:
        from langgraph_sdk import get_client

        client = get_client(url=_resolve_langgraph_url())
        rows = await client.threads.search(
            {
                "limit": limit,
                "offset": offset,
                "sortBy": sort_by,
                "sortOrder": sort_order,
                "select": ["thread_id", "updated_at", "values"],
            }
        )
    except Exception as e:
        logger.exception("Failed to query LangGraph thread summaries")
        raise HTTPException(status_code=502, detail=f"Failed to query LangGraph threads: {e}") from e

    summaries: list[ThreadSummary] = []
    row_count = 0
    if isinstance(rows, list):
        row_count = len(rows)
        for row in rows:
            summary = _to_thread_summary(row)
            if summary is not None:
                summaries.append(summary)

    next_offset = offset + row_count if row_count >= limit else None
    return ThreadSummariesResponse(threads=summaries, next_offset=next_offset)


__all__ = [
    "ThreadSummary",
    "ThreadSummariesResponse",
    "list_thread_summaries",
    "_pick_title",
    "_resolve_langgraph_url",
    "_to_thread_summary",
    "router",
]
