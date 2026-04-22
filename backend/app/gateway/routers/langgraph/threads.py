"""Thread management endpoints.

Provides CRUD operations for threads and checkpoint state management.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.gateway.dependencies import CurrentCheckpointer, CurrentRunRepository, CurrentThreadMetaStorage
from app.infra.storage import ThreadMetaStorage
from app.plugins.auth.security.actor_context import bind_request_actor_context, resolve_request_user_id
from deerflow.config.paths import Paths, get_paths
from deerflow.runtime import serialize_channel_values

logger = logging.getLogger(__name__)
router = APIRouter(tags=["threads"])


# ---------------------------------------------------------------------------
# Request / Response Models
# ---------------------------------------------------------------------------


class ThreadCreateRequest(BaseModel):
    thread_id: str | None = Field(default=None, description="Optional thread ID (auto-generated if omitted)")
    assistant_id: str | None = Field(default=None, description="Associate thread with an assistant")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Initial metadata")


class ThreadSearchRequest(BaseModel):
    metadata: dict[str, Any] = Field(default_factory=dict, description="Metadata filter (exact match)")
    limit: int = Field(default=100, ge=1, le=1000, description="Maximum results")
    offset: int = Field(default=0, ge=0, description="Pagination offset")
    status: str | None = Field(default=None, description="Filter by thread status")
    user_id: str | None = Field(default=None, description="Filter by user ID")
    assistant_id: str | None = Field(default=None, description="Filter by assistant ID")


class ThreadResponse(BaseModel):
    thread_id: str = Field(description="Unique thread identifier")
    status: str = Field(default="idle", description="Thread status")
    created_at: str = Field(default="", description="ISO timestamp")
    updated_at: str = Field(default="", description="ISO timestamp")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Thread metadata")
    values: dict[str, Any] = Field(default_factory=dict, description="Current state values")
    interrupts: dict[str, Any] = Field(default_factory=dict, description="Pending interrupts")


class ThreadDeleteResponse(BaseModel):
    success: bool
    message: str


class ThreadStateUpdateRequest(BaseModel):
    values: dict[str, Any] | None = Field(default=None, description="Channel values to merge")
    checkpoint_id: str | None = Field(default=None, description="Checkpoint to branch from")
    checkpoint: dict[str, Any] | None = Field(default=None, description="Full checkpoint object")
    as_node: str | None = Field(default=None, description="Node identity for the update")


class ThreadStateResponse(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict, description="Current channel values")
    next: list[str] = Field(default_factory=list, description="Next nodes to execute")
    tasks: list[dict[str, Any]] = Field(default_factory=list, description="Interrupted task details")
    checkpoint: dict[str, Any] = Field(default_factory=dict, description="Checkpoint info")
    checkpoint_id: str | None = Field(default=None, description="Current checkpoint ID")
    parent_checkpoint_id: str | None = Field(default=None, description="Parent checkpoint ID")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Checkpoint metadata")
    created_at: str | None = Field(default=None, description="Checkpoint timestamp")


class ThreadHistoryRequest(BaseModel):
    limit: int = Field(default=10, ge=1, le=100, description="Maximum entries")
    before: str | None = Field(default=None, description="Cursor for pagination (checkpoint_id)")


class HistoryEntry(BaseModel):
    checkpoint_id: str
    parent_checkpoint_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    values: dict[str, Any] = Field(default_factory=dict)
    created_at: str | None = None
    next: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def sanitize_log_param(value: str) -> str:
    """Strip control characters to prevent log injection."""

    return value.replace("\n", "").replace("\r", "").replace("\x00", "")


def _delete_thread_data(thread_id: str, paths: Paths | None = None) -> ThreadDeleteResponse:
    """Delete local filesystem data for a thread."""
    path_manager = paths or get_paths()
    try:
        path_manager.delete_thread_dir(thread_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except FileNotFoundError:
        logger.debug("No local thread data to delete for %s", sanitize_log_param(thread_id))
        return ThreadDeleteResponse(success=True, message=f"No local data for {thread_id}")
    except Exception as exc:
        logger.exception("Failed to delete thread data for %s", sanitize_log_param(thread_id))
        raise HTTPException(status_code=500, detail="Failed to delete local thread data.") from exc

    logger.info("Deleted local thread data for %s", sanitize_log_param(thread_id))
    return ThreadDeleteResponse(success=True, message=f"Deleted local thread data for {thread_id}")


async def _thread_or_run_exists(
    *,
    request: Request,
    thread_id: str,
    thread_meta_storage: ThreadMetaStorage,
    run_repo,
) -> bool:
    request_user_id = resolve_request_user_id(request)

    if request_user_id is None:
        thread = await thread_meta_storage.get_thread(thread_id, user_id=None)
        if thread is not None:
            return True
        runs = await run_repo.list_by_thread(thread_id, limit=1, user_id=None)
        return bool(runs)

    with bind_request_actor_context(request):
        thread = await thread_meta_storage.get_thread(thread_id)
        if thread is not None:
            return True
        runs = await run_repo.list_by_thread(thread_id, limit=1)
        return bool(runs)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("", response_model=ThreadResponse)
async def create_thread(
    body: ThreadCreateRequest,
    request: Request,
    thread_meta_storage: CurrentThreadMetaStorage,
) -> ThreadResponse:
    """Create a new thread."""
    thread_id = body.thread_id or str(uuid.uuid4())

    request_user_id = resolve_request_user_id(request)
    if request_user_id is None:
        existing = await thread_meta_storage.get_thread(thread_id, user_id=None)
    else:
        with bind_request_actor_context(request):
            existing = await thread_meta_storage.get_thread(thread_id)
    if existing is not None:
        return ThreadResponse(
            thread_id=thread_id,
            status=existing.status,
            created_at=existing.created_time.isoformat() if existing.created_time else "",
            updated_at=existing.updated_time.isoformat() if existing.updated_time else "",
            metadata=existing.metadata,
        )

    try:
        if request_user_id is None:
            created = await thread_meta_storage.ensure_thread(
                thread_id=thread_id,
                assistant_id=body.assistant_id,
                metadata=body.metadata,
                user_id=None,
            )
        else:
            with bind_request_actor_context(request):
                created = await thread_meta_storage.ensure_thread(
                    thread_id=thread_id,
                    assistant_id=body.assistant_id,
                    metadata=body.metadata,
                )
    except Exception:
        logger.exception("Failed to create thread %s", sanitize_log_param(thread_id))
        raise HTTPException(status_code=500, detail="Failed to create thread")

    logger.info("Thread created: %s", sanitize_log_param(thread_id))
    return ThreadResponse(
        thread_id=thread_id,
        status=created.status,
        created_at=created.created_time.isoformat() if created.created_time else "",
        updated_at=created.updated_time.isoformat() if created.updated_time else "",
        metadata=created.metadata,
    )


@router.post("/search", response_model=list[ThreadResponse])
async def search_threads(
    body: ThreadSearchRequest,
    request: Request,
    thread_meta_storage: CurrentThreadMetaStorage,
) -> list[ThreadResponse]:
    """Search threads with filters."""
    try:
        request_user_id = resolve_request_user_id(request)
        if request_user_id is None:
            threads = await thread_meta_storage.search_threads(
                metadata=body.metadata or None,
                status=body.status,
                user_id=body.user_id,
                assistant_id=body.assistant_id,
                limit=body.limit,
                offset=body.offset,
            )
        else:
            with bind_request_actor_context(request):
                threads = await thread_meta_storage.search_threads(
                    metadata=body.metadata or None,
                    status=body.status,
                    assistant_id=body.assistant_id,
                    limit=body.limit,
                    offset=body.offset,
                )
    except Exception:
        logger.exception("Failed to search threads")
        raise HTTPException(status_code=500, detail="Failed to search threads")

    return [
        ThreadResponse(
            thread_id=t.thread_id,
            status=t.status,
            created_at=t.created_time.isoformat() if t.created_time else "",
            updated_at=t.updated_time.isoformat() if t.updated_time else "",
            metadata=t.metadata,
            values={"title": t.display_name} if t.display_name else {},
            interrupts={},
        )
        for t in threads
    ]


@router.delete("/{thread_id}", response_model=ThreadDeleteResponse)
async def delete_thread(
    thread_id: str,
    checkpointer: CurrentCheckpointer,
    thread_meta_storage: CurrentThreadMetaStorage,
) -> ThreadDeleteResponse:
    """Delete a thread and all associated data."""
    response = _delete_thread_data(thread_id)

    # Remove checkpoints (best-effort)
    try:
        if hasattr(checkpointer, "adelete_thread"):
            await checkpointer.adelete_thread(thread_id)
    except Exception:
        logger.debug("Could not delete checkpoints for thread %s", sanitize_log_param(thread_id))

    # Remove thread_meta (best-effort)
    try:
        await thread_meta_storage.delete_thread(thread_id)
    except Exception:
        logger.debug("Could not delete thread_meta for %s", sanitize_log_param(thread_id))

    return response


@router.get("/{thread_id}/state", response_model=ThreadStateResponse)
async def get_thread_state(
    thread_id: str,
    request: Request,
    checkpointer: CurrentCheckpointer,
    thread_meta_storage: CurrentThreadMetaStorage,
    run_repo: CurrentRunRepository,
) -> ThreadStateResponse:
    """Get the latest state snapshot for a thread."""
    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}

    try:
        checkpoint_tuple = await checkpointer.aget_tuple(config)
    except Exception:
        logger.exception("Failed to get state for thread %s", sanitize_log_param(thread_id))
        raise HTTPException(status_code=500, detail="Failed to get thread state")

    if checkpoint_tuple is None:
        if await _thread_or_run_exists(
            request=request,
            thread_id=thread_id,
            thread_meta_storage=thread_meta_storage,
            run_repo=run_repo,
        ):
            return ThreadStateResponse()
        raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")

    checkpoint = getattr(checkpoint_tuple, "checkpoint", {}) or {}
    metadata = getattr(checkpoint_tuple, "metadata", {}) or {}
    channel_values = checkpoint.get("channel_values", {})

    ckpt_config = getattr(checkpoint_tuple, "config", {}) or {}
    checkpoint_id = ckpt_config.get("configurable", {}).get("checkpoint_id")

    parent_config = getattr(checkpoint_tuple, "parent_config", None)
    parent_checkpoint_id = parent_config.get("configurable", {}).get("checkpoint_id") if parent_config else None

    tasks_raw = getattr(checkpoint_tuple, "tasks", []) or []
    next_nodes = [t.name for t in tasks_raw if hasattr(t, "name")]
    tasks = [{"id": getattr(t, "id", ""), "name": getattr(t, "name", "")} for t in tasks_raw]

    return ThreadStateResponse(
        values=serialize_channel_values(channel_values),
        next=next_nodes,
        tasks=tasks,
        checkpoint={"id": checkpoint_id, "ts": str(metadata.get("created_at", ""))},
        checkpoint_id=checkpoint_id,
        parent_checkpoint_id=parent_checkpoint_id,
        metadata=metadata,
        created_at=str(metadata.get("created_at", "")),
    )


@router.post("/{thread_id}/state", response_model=ThreadStateResponse)
async def update_thread_state(
    thread_id: str,
    body: ThreadStateUpdateRequest,
    checkpointer: CurrentCheckpointer,
    thread_meta_storage: CurrentThreadMetaStorage,
) -> ThreadStateResponse:
    """Update thread state (human-in-the-loop or title rename)."""
    read_config: dict[str, Any] = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    if body.checkpoint_id:
        read_config["configurable"]["checkpoint_id"] = body.checkpoint_id

    try:
        checkpoint_tuple = await checkpointer.aget_tuple(read_config)
    except Exception:
        logger.exception("Failed to get state for thread %s", sanitize_log_param(thread_id))
        raise HTTPException(status_code=500, detail="Failed to get thread state")

    if checkpoint_tuple is None:
        raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")

    checkpoint: dict[str, Any] = dict(getattr(checkpoint_tuple, "checkpoint", {}) or {})
    metadata: dict[str, Any] = dict(getattr(checkpoint_tuple, "metadata", {}) or {})
    channel_values: dict[str, Any] = dict(checkpoint.get("channel_values", {}))

    if body.values:
        channel_values.update(body.values)

    checkpoint["channel_values"] = channel_values
    metadata["updated_at"] = time.time()

    if body.as_node:
        metadata["source"] = "update"
        metadata["step"] = metadata.get("step", 0) + 1
        metadata["writes"] = {body.as_node: body.values}

    write_config: dict[str, Any] = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    try:
        new_config = await checkpointer.aput(write_config, checkpoint, metadata, {})
    except Exception:
        logger.exception("Failed to update state for thread %s", sanitize_log_param(thread_id))
        raise HTTPException(status_code=500, detail="Failed to update thread state")

    new_checkpoint_id: str | None = None
    if isinstance(new_config, dict):
        new_checkpoint_id = new_config.get("configurable", {}).get("checkpoint_id")

    # Sync title to thread_meta
    if body.values and "title" in body.values:
        new_title = body.values["title"]
        if new_title:
            try:
                await thread_meta_storage.sync_thread_title(
                    thread_id=thread_id,
                    title=new_title,
                )
            except Exception:
                logger.debug("Failed to sync title for %s", sanitize_log_param(thread_id))

    return ThreadStateResponse(
        values=serialize_channel_values(channel_values),
        next=[],
        metadata=metadata,
        checkpoint_id=new_checkpoint_id,
        created_at=str(metadata.get("created_at", "")),
    )


@router.post("/{thread_id}/history", response_model=list[HistoryEntry])
async def get_thread_history(
    thread_id: str,
    body: ThreadHistoryRequest,
    request: Request,
    checkpointer: CurrentCheckpointer,
    thread_meta_storage: CurrentThreadMetaStorage,
    run_repo: CurrentRunRepository,
) -> list[HistoryEntry]:
    """Get checkpoint history for a thread."""
    config: dict[str, Any] = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    if body.before:
        config["configurable"]["checkpoint_id"] = body.before

    entries: list[HistoryEntry] = []
    is_first = True

    try:
        async for checkpoint_tuple in checkpointer.alist(config, limit=body.limit):
            ckpt_config = getattr(checkpoint_tuple, "config", {}) or {}
            parent_config = getattr(checkpoint_tuple, "parent_config", None)
            metadata = getattr(checkpoint_tuple, "metadata", {}) or {}
            checkpoint = getattr(checkpoint_tuple, "checkpoint", {}) or {}

            checkpoint_id = ckpt_config.get("configurable", {}).get("checkpoint_id", "")
            parent_id = parent_config.get("configurable", {}).get("checkpoint_id") if parent_config else None
            channel_values = checkpoint.get("channel_values", {})

            values: dict[str, Any] = {}
            if title := channel_values.get("title"):
                values["title"] = title
            if is_first and (messages := channel_values.get("messages")):
                values["messages"] = serialize_channel_values({"messages": messages}).get("messages", [])
            is_first = False

            tasks_raw = getattr(checkpoint_tuple, "tasks", []) or []
            next_nodes = [t.name for t in tasks_raw if hasattr(t, "name")]

            entries.append(
                HistoryEntry(
                    checkpoint_id=checkpoint_id,
                    parent_checkpoint_id=parent_id,
                    metadata=metadata,
                    values=values,
                    created_at=str(metadata.get("created_at", "")),
                    next=next_nodes,
                )
            )
    except Exception:
        logger.exception("Failed to get history for thread %s", sanitize_log_param(thread_id))
        raise HTTPException(status_code=500, detail="Failed to get thread history")

    if not entries and await _thread_or_run_exists(
        request=request,
        thread_id=thread_id,
        thread_meta_storage=thread_meta_storage,
        run_repo=run_repo,
    ):
        return []

    return entries
