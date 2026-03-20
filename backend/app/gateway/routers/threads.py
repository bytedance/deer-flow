"""Conversation history management router.

Provides API endpoints for listing, viewing, and deleting conversation threads
backed by the LangGraph server's checkpointer storage.

Addresses GitHub issue #175 — no way to browse past conversations.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from langgraph_sdk import get_client
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/threads", tags=["threads"])

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_DEFAULT_LANGGRAPH_URL = "http://localhost:2024"


def _langgraph_url() -> str:
    return os.getenv("LANGGRAPH_URL", _DEFAULT_LANGGRAPH_URL)


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class ThreadSummary(BaseModel):
    """Lightweight representation of a conversation thread."""

    thread_id: str = Field(..., description="Unique thread identifier")
    status: str = Field(default="idle", description="Thread status: idle / busy / interrupted / error")
    created_at: str | None = Field(default=None, description="ISO 8601 creation timestamp")
    updated_at: str | None = Field(default=None, description="ISO 8601 last-update timestamp")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Thread metadata (e.g. title)")
    message_count: int = Field(default=0, description="Number of messages in the conversation")
    last_message_preview: str | None = Field(default=None, description="Truncated preview of the last human message")


class ThreadDetail(ThreadSummary):
    """Full thread details including conversation messages."""

    messages: list[dict[str, Any]] = Field(default_factory=list, description="Ordered message list")


class ThreadsListResponse(BaseModel):
    """Paginated list of conversation threads."""

    threads: list[ThreadSummary] = Field(default_factory=list)
    total: int = Field(default=0, description="Total number of threads (before pagination)")
    limit: int = Field(default=20, description="Page size")
    offset: int = Field(default=0, description="Current offset")


class ExportResponse(BaseModel):
    """Markdown export of a conversation thread."""

    thread_id: str
    title: str
    markdown: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MAX_PREVIEW = 120


def _truncate(text: str, max_len: int = _MAX_PREVIEW) -> str:
    text = text.strip().replace("\n", " ")
    return text[: max_len - 1] + "…" if len(text) > max_len else text


def _extract_text(content: Any) -> str:
    """Extract plain text from message content (string or list-of-blocks)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                btype = block.get("type", "")
                if btype in ("text", "tool_result"):
                    text = block.get("text", "")
                    if isinstance(text, str) and text.strip():
                        parts.append(text)
                elif btype == "tool_use":
                    name = block.get("name", "tool")
                    parts.append(f"[Tool: {name}]")
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts)
    return str(content)


def _summarise_messages(messages: list[dict]) -> tuple[int, str | None]:
    """Return (message_count, last_human_preview)."""
    count = len(messages)
    last_human: str | None = None
    for msg in reversed(messages):
        if msg.get("type") == "human":
            last_human = _truncate(_extract_text(msg.get("content", "")))
            break
    return count, last_human


def _to_summary(thread_data: dict) -> ThreadSummary:
    """Convert a LangGraph SDK thread dict into a ThreadSummary."""
    messages = thread_data.get("values", {}).get("messages", [])
    msg_count, last_preview = _summarise_messages(messages)

    return ThreadSummary(
        thread_id=thread_data.get("thread_id", ""),
        status=thread_data.get("status", "idle"),
        created_at=thread_data.get("created_at"),
        updated_at=thread_data.get("updated_at"),
        metadata=thread_data.get("metadata", {}) or {},
        message_count=msg_count,
        last_message_preview=last_preview,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=ThreadsListResponse,
    summary="List conversation threads",
    description="Paginated listing of all conversation threads with metadata. "
    "Sorted by most recently updated first.",
)
async def list_threads(
    limit: int = Query(default=20, ge=1, le=100, description="Page size"),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
    status: str | None = Query(default=None, description="Filter by status: idle / busy / interrupted / error"),
) -> ThreadsListResponse:
    try:
        client = get_client(url=_langgraph_url())
        threads_raw = await client.threads.search(
            limit=limit,
            offset=offset,
            sort_by="updated_at",
            sort_order="desc",
            status=status,  # type: ignore[arg-type]
        )
        total = await client.threads.count()
    except Exception as exc:
        logger.error("Failed to list threads: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"Cannot reach LangGraph server: {exc}") from exc

    summaries: list[ThreadSummary] = []
    for t in threads_raw:
        try:
            summaries.append(_to_summary(t))
        except Exception:
            logger.debug("Skipping unparseable thread entry", exc_info=True)

    return ThreadsListResponse(
        threads=summaries,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{thread_id}",
    response_model=ThreadDetail,
    summary="Get thread details",
    description="Retrieve full details and messages for a specific conversation thread.",
)
async def get_thread(thread_id: str) -> ThreadDetail:
    try:
        client = get_client(url=_langgraph_url())
        thread_data = await client.threads.get(thread_id)
    except Exception as exc:
        logger.error("Failed to get thread %s: %s", thread_id, exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"Cannot reach LangGraph server: {exc}") from exc

    if not thread_data:
        raise HTTPException(status_code=404, detail=f"Thread '{thread_id}' not found")

    messages = thread_data.get("values", {}).get("messages", [])
    msg_count, last_preview = _summarise_messages(messages)

    return ThreadDetail(
        thread_id=thread_data.get("thread_id", thread_id),
        status=thread_data.get("status", "idle"),
        created_at=thread_data.get("created_at"),
        updated_at=thread_data.get("updated_at"),
        metadata=thread_data.get("metadata", {}) or {},
        message_count=msg_count,
        last_message_preview=last_preview,
        messages=messages,
    )


@router.delete(
    "/{thread_id}",
    status_code=204,
    summary="Delete a thread",
    description="Permanently delete a conversation thread and all its checkpoints.",
)
async def delete_thread(thread_id: str) -> None:
    try:
        client = get_client(url=_langgraph_url())
        await client.threads.delete(thread_id)
    except Exception as exc:
        logger.error("Failed to delete thread %s: %s", thread_id, exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"Cannot reach LangGraph server: {exc}") from exc


@router.get(
    "/{thread_id}/export",
    response_model=ExportResponse,
    summary="Export thread as Markdown",
    description="Export a conversation thread as a downloadable Markdown document.",
)
async def export_thread(thread_id: str) -> ExportResponse:
    try:
        client = get_client(url=_langgraph_url())
        thread_data = await client.threads.get(thread_id)
    except Exception as exc:
        logger.error("Failed to export thread %s: %s", thread_id, exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"Cannot reach LangGraph server: {exc}") from exc

    if not thread_data:
        raise HTTPException(status_code=404, detail=f"Thread '{thread_id}' not found")

    metadata = thread_data.get("metadata", {}) or {}
    title = metadata.get("title", f"Conversation {thread_id[:8]}")
    messages = thread_data.get("values", {}).get("messages", [])

    md_lines = [f"# {title}", ""]

    for msg in messages:
        msg_type = msg.get("type", "unknown")
        content = _extract_text(msg.get("content", ""))
        tool_calls = msg.get("tool_calls", [])

        if msg_type == "human":
            md_lines.append(f"## User\n\n{content}\n")
        elif msg_type == "ai":
            md_lines.append(f"## Assistant\n\n{content}\n")
            for tc in tool_calls:
                md_lines.append(f"> **Tool call:** `{tc.get('name', '?')}`")
                args = tc.get("args", {})
                if args:
                    md_lines.append(f"> ```json\n> {args}\n> ```\n")
        elif msg_type == "tool":
            tool_name = msg.get("name", "unknown")
            md_lines.append(f"### Tool: `{tool_name}`\n\n```\n{content}\n```\n")

    markdown = "\n".join(md_lines)

    return ExportResponse(thread_id=thread_id, title=title, markdown=markdown)
