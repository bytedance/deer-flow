"""Per-user activity feed over the run-change clock.

``GET /api/thread-activity`` tells an open sidebar which threads changed
because the server ran something for the caller (a schedule, an IM channel, a
GitHub agent, an extension, an MCP notification), so it can refetch its thread
list without a reload. It lives on its own prefix so it can never be captured
by ``GET /api/threads/{thread_id}``.

The cursor is the ``(change_seq, run_id)`` position of the last run change the
caller has seen. The clock is database-global and monotonic
(``runs.change_seq``), so the feed is exact across workers and independent of
wall-clock time. An idle poll is one index seek on ``ix_runs_user_change_seq``
plus one primary-key lookup of the caller's read clock.
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.gateway.authz import require_permission
from deerflow.runtime.user_context import get_effective_user_id

router = APIRouter(prefix="/api/thread-activity", tags=["threads"])

_CURSOR_RE = re.compile(r"(0|[1-9][0-9]{0,18}):([^\s:]{0,64})")
# runs.change_seq is a BIGINT: a larger position would fail inside the database
# (Postgres) instead of reading as a malformed cursor.
_MAX_CHANGE_SEQ = 2**63 - 1
_SEED_CURSOR = "0:"


class ThreadActivityItem(BaseModel):
    """One thread with a server-originated run change since the cursor."""

    thread_id: str
    origin_kind: str | None = Field(description="Server-owned origin of the latest changed run (never null in this list)")
    status: str = Field(description="Status of the thread's latest changed run")


class ThreadActivityResponse(BaseModel):
    """A page of the caller's run changes, reduced to the threads that matter."""

    cursor: str = Field(description="Opaque position to pass back on the next poll")
    threads: list[ThreadActivityItem] = Field(default_factory=list)
    truncated: bool = Field(default=False, description="More run changes than `limit` were pending; poll again soon")
    read_version: int = Field(default=0, description="Per-user read clock; it changes when a thread is marked read on any device")


def thread_activity_available(state: Any) -> bool:
    """SQL persistence only: the feed needs the run-change clock and the read tables."""
    run_store = getattr(state, "run_store", None)
    return getattr(state, "thread_read_repo", None) is not None and callable(getattr(run_store, "latest_change", None))


def _parse_cursor(cursor: str) -> tuple[int, str]:
    match = _CURSOR_RE.fullmatch(cursor)
    if match is None or int(match.group(1)) > _MAX_CHANGE_SEQ:
        raise HTTPException(status_code=422, detail={"code": "invalid_cursor", "message": "Invalid activity cursor"})
    return int(match.group(1)), match.group(2)


def _format_cursor(change_seq: int, run_id: str) -> str:
    return f"{change_seq}:{run_id}"


@router.get("", response_model=ThreadActivityResponse)
@require_permission("threads", "read")
async def list_thread_activity(
    request: Request,
    # No max_length: an overlong cursor must read as ``invalid_cursor`` too,
    # and the pattern bounds what is accepted.
    cursor: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
) -> ThreadActivityResponse:
    """Threads changed by server-originated runs of the caller since ``cursor``.

    Without a cursor the call only seeds: it returns the caller's current head
    and no threads. The caller's own interactive runs (``origin_kind`` NULL)
    advance the cursor but are not returned.
    """
    state = request.app.state
    if not thread_activity_available(state):
        raise HTTPException(status_code=503, detail="Thread activity is not available")
    run_store = state.run_store
    read_repo = state.thread_read_repo
    # Always an explicit owner id: None would disable the owner filter.
    user_id = str(get_effective_user_id())

    if cursor is None:
        head = await run_store.latest_change(user_id=user_id)
        next_cursor = _format_cursor(*head) if head is not None else _SEED_CURSOR
        return ThreadActivityResponse(cursor=next_cursor, read_version=await read_repo.read_version(user_id=user_id))

    after_change_seq, after_run_id = _parse_cursor(cursor)
    rows = await run_store.list_changed(after_change_seq=after_change_seq, after_run_id=after_run_id, user_id=user_id, limit=limit + 1)
    truncated = len(rows) > limit
    used = rows[:limit]
    # Advance to the last row used, never to the head: a truncated page
    # continues on the next poll without skipping changes.
    next_cursor = _format_cursor(int(used[-1]["change_seq"]), str(used[-1]["run_id"])) if used else _format_cursor(after_change_seq, after_run_id)

    latest: dict[str, ThreadActivityItem] = {}
    for row in used:
        origin_kind = row.get("origin_kind")
        if origin_kind is None:
            continue
        thread_id = str(row["thread_id"])
        latest.pop(thread_id, None)
        latest[thread_id] = ThreadActivityItem(thread_id=thread_id, origin_kind=origin_kind, status=str(row.get("status") or ""))

    return ThreadActivityResponse(
        cursor=next_cursor,
        threads=list(latest.values()),
        truncated=truncated,
        read_version=await read_repo.read_version(user_id=user_id),
    )
