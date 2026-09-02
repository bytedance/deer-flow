"""Owner-scoped progress and control API for durable subagent batches."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.gateway.authz import require_permission
from app.gateway.deps import (
    get_current_user,
    get_subagent_batch_repo,
    get_subagent_batch_service,
)
from deerflow.utils.thread_id import ThreadId

router = APIRouter(prefix="/api/threads/{thread_id}/subagent-batches", tags=["subagent-batches"])
_ITEM_STATUSES = {"pending", "queued", "leased", "running", "succeeded", "failed", "cancelled"}


async def _user_id(request: Request) -> str:
    user_id = await get_current_user(request)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user_id


async def _owned_batch(request: Request, thread_id: str, batch_id: str) -> tuple[object, str, dict]:
    repo = get_subagent_batch_repo(request)
    user_id = await _user_id(request)
    batch = await repo.get_batch(batch_id, user_id=user_id)
    if batch is None or batch["thread_id"] != thread_id:
        raise HTTPException(status_code=404, detail="Subagent batch not found")
    return repo, user_id, batch


@router.get("")
@require_permission("threads", "read", owner_check=True)
async def list_batches(thread_id: ThreadId, request: Request, limit: int = Query(20, ge=1, le=100)) -> list[dict]:
    repo = get_subagent_batch_repo(request)
    return await repo.list_by_thread(thread_id, user_id=await _user_id(request), limit=limit)


@router.get("/{batch_id}")
@require_permission("threads", "read", owner_check=True)
async def get_batch(thread_id: ThreadId, batch_id: str, request: Request) -> dict:
    _repo, _user_id_value, batch = await _owned_batch(request, thread_id, batch_id)
    return batch


@router.get("/{batch_id}/items")
@require_permission("threads", "read", owner_check=True)
async def list_batch_items(
    thread_id: ThreadId,
    batch_id: str,
    request: Request,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    status: str | None = Query(None),
) -> list[dict]:
    if status is not None and status not in _ITEM_STATUSES:
        raise HTTPException(status_code=422, detail="Unknown batch item status")
    repo, user_id, _batch = await _owned_batch(request, thread_id, batch_id)
    return await repo.list_items(batch_id, user_id=user_id, offset=offset, limit=limit, status=status) or []


@router.post("/{batch_id}/pause")
@require_permission("threads", "write", owner_check=True)
async def pause_batch(thread_id: ThreadId, batch_id: str, request: Request) -> dict:
    repo, user_id, _batch = await _owned_batch(request, thread_id, batch_id)
    return await repo.pause_batch(batch_id, user_id=user_id)


@router.post("/{batch_id}/resume")
@require_permission("threads", "write", owner_check=True)
async def resume_batch(thread_id: ThreadId, batch_id: str, request: Request) -> dict:
    repo, user_id, _batch = await _owned_batch(request, thread_id, batch_id)
    return await repo.resume_batch(batch_id, user_id=user_id)


@router.post("/{batch_id}/cancel")
@require_permission("threads", "write", owner_check=True)
async def cancel_batch(thread_id: ThreadId, batch_id: str, request: Request) -> dict:
    if not getattr(request.app.state, "subagent_batches_available", False):
        raise HTTPException(status_code=503, detail="Subagent batch worker is not running")
    _repo, user_id, _batch = await _owned_batch(request, thread_id, batch_id)
    result = await get_subagent_batch_service(request).cancel_batch(batch_id=batch_id, user_id=user_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Subagent batch not found")
    return result


@router.post("/{batch_id}/items/{item_id}/retry")
@require_permission("threads", "write", owner_check=True)
async def retry_batch_item(thread_id: ThreadId, batch_id: str, item_id: str, request: Request) -> dict:
    repo, user_id, _batch = await _owned_batch(request, thread_id, batch_id)
    item = await repo.retry_item(batch_id, item_id, user_id=user_id)
    if item is None:
        raise HTTPException(status_code=409, detail="Only failed items can be retried")
    return item


@router.get("/{batch_id}/results.jsonl")
@require_permission("threads", "read", owner_check=True)
async def export_batch_results(thread_id: ThreadId, batch_id: str, request: Request) -> StreamingResponse:
    repo, user_id, _batch = await _owned_batch(request, thread_id, batch_id)

    async def lines() -> AsyncIterator[bytes]:
        offset = 0
        while True:
            page = await repo.list_items(
                batch_id,
                user_id=user_id,
                offset=offset,
                limit=500,
                include_result=True,
            )
            if not page:
                break
            for item in page:
                yield (json.dumps(item, ensure_ascii=False, default=str) + "\n").encode()
            offset += len(page)

    return StreamingResponse(
        lines(),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": f'attachment; filename="{batch_id}-results.jsonl"'},
    )
