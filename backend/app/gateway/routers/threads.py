"""Thread CRUD, state, and history endpoints.

Combines the existing thread-local filesystem cleanup with LangGraph
Platform-compatible thread management backed by the checkpointer.

Channel values returned in state responses are serialized through
:func:`deerflow.runtime.serialization.serialize_channel_values` to
ensure LangChain message objects are converted to JSON-safe dicts
matching the LangGraph Platform wire format expected by the
``useStream`` React hook.
"""

from __future__ import annotations

import copy
import logging
import shutil
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from langgraph.checkpoint.base import empty_checkpoint, uuid6
from pydantic import BaseModel, Field, field_validator

from app.gateway.authz import require_permission
from app.gateway.deps import get_checkpointer
from app.gateway.internal_auth import get_trusted_internal_owner_user_id
from app.gateway.utils import sanitize_log_param
from deerflow.config.paths import Paths, get_paths
from deerflow.runtime import serialize_channel_values_for_api
from deerflow.runtime.goal import DEFAULT_MAX_GOAL_CONTINUATIONS, build_goal_state, ensure_thread_checkpoint, goal_thread_lock, read_thread_goal, write_thread_goal
from deerflow.runtime.user_context import get_effective_user_id
from deerflow.utils.file_io import run_file_io
from deerflow.utils.time import coerce_iso, now_iso

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/threads", tags=["threads"])


# Metadata keys that the server controls; clients are not allowed to set
# them. Pydantic ``@field_validator("metadata")`` strips them on every
# inbound model below so a malicious client cannot reflect a forged
# owner identity through the API surface. Defense-in-depth — the
# row-level invariant is still ``threads_meta.user_id`` populated from
# the auth contextvar; this list closes the metadata-blob echo gap.
_SERVER_RESERVED_METADATA_KEYS: frozenset[str] = frozenset({"owner_id", "user_id"})
_SIDECAR_METADATA_KEY = "deerflow_sidecar"
_BRANCH_METADATA_KEY = "deerflow_branch"
_BRANCH_HISTORY_SCAN_LIMIT = 200


def _strip_reserved_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Return ``metadata`` with server-controlled keys removed."""
    if not metadata:
        return metadata or {}
    return {k: v for k, v in metadata.items() if k not in _SERVER_RESERVED_METADATA_KEYS}


def _message_id(message: Any) -> str | None:
    if isinstance(message, dict):
        raw = message.get("id")
    else:
        raw = getattr(message, "id", None)
    return raw if isinstance(raw, str) and raw else None


def _message_type(message: Any) -> str | None:
    if isinstance(message, dict):
        raw = message.get("type")
    else:
        raw = getattr(message, "type", None)
    return raw if isinstance(raw, str) and raw else None


def _message_additional_kwargs(message: Any) -> dict[str, Any]:
    if isinstance(message, dict):
        raw = message.get("additional_kwargs")
    else:
        raw = getattr(message, "additional_kwargs", None)
    return raw if isinstance(raw, dict) else {}


def _is_branch_visible_message(message: Any) -> bool:
    if _message_additional_kwargs(message).get("hide_from_ui") is True:
        return False
    return _message_type(message) in {"human", "ai"}


def _is_branch_assistant_message(message: Any) -> bool:
    return _message_type(message) == "ai"


def _checkpoint_messages(checkpoint_tuple: Any) -> list[Any]:
    checkpoint = getattr(checkpoint_tuple, "checkpoint", {}) or {}
    channel_values = checkpoint.get("channel_values", {}) or {}
    messages = channel_values.get("messages") or []
    return list(messages) if isinstance(messages, list) else []


def _checkpoint_id(checkpoint_tuple: Any) -> str | None:
    config = getattr(checkpoint_tuple, "config", {}) or {}
    raw = config.get("configurable", {}).get("checkpoint_id")
    return raw if isinstance(raw, str) and raw else None


def _matches_branch_target(messages: list[Any], target_message_ids: set[str]) -> bool:
    if not target_message_ids:
        return False

    index_by_id = {_message_id(message): index for index, message in enumerate(messages) if _message_id(message)}
    if not target_message_ids.issubset(index_by_id.keys()):
        return False
    if any(not _is_branch_assistant_message(messages[index_by_id[message_id]]) for message_id in target_message_ids):
        return False

    target_end_index = max(index_by_id[message_id] for message_id in target_message_ids)
    return not any(_is_branch_visible_message(message) for message in messages[target_end_index + 1 :])


async def _find_branch_checkpoint(checkpointer: Any, thread_id: str, target_message_ids: set[str]) -> Any:
    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    try:
        async for checkpoint_tuple in checkpointer.alist(config, limit=_BRANCH_HISTORY_SCAN_LIMIT):
            if _matches_branch_target(_checkpoint_messages(checkpoint_tuple), target_message_ids):
                return checkpoint_tuple
    except Exception:
        logger.exception("Failed to scan branch checkpoint history for thread %s", sanitize_log_param(thread_id))
        raise HTTPException(status_code=500, detail="Failed to find branch checkpoint")
    raise HTTPException(status_code=409, detail="This turn can no longer be branched from.")


async def _branch_targets_latest_turn(checkpointer: Any, thread_id: str, target_message_ids: set[str]) -> bool:
    """Return True when the target turn is the final visible turn in the current state.

    ``alist`` yields newest-first; we take the newest checkpoint that actually holds
    messages (thread creation writes an empty checkpoint that must be skipped) and
    reuse ``_matches_branch_target`` to check the target turn is its tail. Used to
    decide whether cloning the (uncheckpointed) workspace onto a branch is safe: only
    a branch from the latest turn shares the current workspace timeline. On any lookup
    failure we fail closed (treat as historical) so a branch from an older turn never
    inherits a later timeline's workspace files.
    """
    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    try:
        async for checkpoint_tuple in checkpointer.alist(config, limit=_BRANCH_HISTORY_SCAN_LIMIT):
            messages = _checkpoint_messages(checkpoint_tuple)
            if not messages:
                continue
            return _matches_branch_target(messages, target_message_ids)
    except Exception:
        logger.warning(
            "Failed to resolve latest turn for thread %s; treating branch as historical",
            sanitize_log_param(thread_id),
            exc_info=True,
        )
    return False


def _ignore_branch_user_data(directory: str, names: list[str]) -> set[str]:
    ignored: set[str] = set()
    base = Path(directory)
    for name in names:
        path = base / name
        if name.startswith(".upload-") and name.endswith(".part"):
            ignored.add(name)
        elif path.is_symlink():
            ignored.add(name)
    return ignored


def _copy_branch_user_data_sync(paths: Paths, source_thread_id: str, target_thread_id: str, *, user_id: str) -> str:
    source = paths.sandbox_user_data_dir(source_thread_id, user_id=user_id)
    target = paths.sandbox_user_data_dir(target_thread_id, user_id=user_id)
    if not source.exists():
        return "not_found"

    shutil.copytree(source, target, ignore=_ignore_branch_user_data, dirs_exist_ok=True)
    return "current_thread_best_effort"


async def _copy_branch_user_data(source_thread_id: str, target_thread_id: str) -> str:
    paths = get_paths()
    user_id = get_effective_user_id()
    try:
        return await run_file_io(_copy_branch_user_data_sync, paths, source_thread_id, target_thread_id, user_id=user_id)
    except Exception:
        logger.warning(
            "Failed to copy user-data for branch %s -> %s",
            sanitize_log_param(source_thread_id),
            sanitize_log_param(target_thread_id),
            exc_info=True,
        )
        return "failed"


def _default_branch_display_name(source_title: Any, *, source_is_branch: bool = False) -> str | None:
    if not isinstance(source_title, str):
        return None

    display_name = source_title.strip()
    if source_is_branch:
        while display_name.lower().startswith("branch:"):
            display_name = display_name[len("branch:") :].strip()

    return display_name or None


# ---------------------------------------------------------------------------
# Response / request models
# ---------------------------------------------------------------------------


class ThreadDeleteResponse(BaseModel):
    """Response model for thread cleanup."""

    success: bool
    message: str


class ThreadResponse(BaseModel):
    """Response model for a single thread."""

    thread_id: str = Field(description="Unique thread identifier")
    status: str = Field(default="idle", description="Thread status: idle, busy, interrupted, error")
    created_at: str = Field(default="", description="ISO timestamp")
    updated_at: str = Field(default="", description="ISO timestamp")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Thread metadata")
    values: dict[str, Any] = Field(default_factory=dict, description="Current state channel values")
    interrupts: dict[str, Any] = Field(default_factory=dict, description="Pending interrupts")


class ThreadCreateRequest(BaseModel):
    """Request body for creating a thread."""

    thread_id: str | None = Field(default=None, description="Optional thread ID (auto-generated if omitted)")
    assistant_id: str | None = Field(default=None, description="Associate thread with an assistant")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Initial metadata")

    _strip_reserved = field_validator("metadata")(classmethod(lambda cls, v: _strip_reserved_metadata(v)))


class ThreadSearchRequest(BaseModel):
    """Request body for searching threads."""

    metadata: dict[str, Any] = Field(default_factory=dict, description="Metadata filter (exact match)")
    limit: int = Field(default=100, ge=1, le=1000, description="Maximum results")
    offset: int = Field(default=0, ge=0, description="Pagination offset")
    status: str | None = Field(default=None, description="Filter by thread status")

    @field_validator("metadata")
    @classmethod
    def _validate_metadata_filters(cls, v: dict[str, Any]) -> dict[str, Any]:
        """Reject filter entries the SQL backend cannot compile.

        Enforces consistent behaviour across SQL and memory backends.
        See ``deerflow.persistence.json_compat`` for the shared validators.
        """
        if not v:
            return v
        from deerflow.persistence.json_compat import validate_metadata_filter_key, validate_metadata_filter_value

        bad_entries: list[str] = []
        for key, value in v.items():
            if not validate_metadata_filter_key(key):
                bad_entries.append(f"{key!r} (unsafe key)")
            elif not validate_metadata_filter_value(value):
                bad_entries.append(f"{key!r} (unsupported value type {type(value).__name__})")
        if bad_entries:
            raise ValueError(f"Invalid metadata filter entries: {', '.join(bad_entries)}")
        return v


class ThreadStateResponse(BaseModel):
    """Response model for thread state."""

    values: dict[str, Any] = Field(default_factory=dict, description="Current channel values")
    next: list[str] = Field(default_factory=list, description="Next tasks to execute")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Checkpoint metadata")
    checkpoint: dict[str, Any] = Field(default_factory=dict, description="Checkpoint info")
    checkpoint_id: str | None = Field(default=None, description="Current checkpoint ID")
    parent_checkpoint_id: str | None = Field(default=None, description="Parent checkpoint ID")
    created_at: str | None = Field(default=None, description="Checkpoint timestamp")
    tasks: list[dict[str, Any]] = Field(default_factory=list, description="Interrupted task details")


class ThreadPatchRequest(BaseModel):
    """Request body for patching thread metadata."""

    metadata: dict[str, Any] = Field(default_factory=dict, description="Metadata to merge")

    _strip_reserved = field_validator("metadata")(classmethod(lambda cls, v: _strip_reserved_metadata(v)))


class ThreadStateUpdateRequest(BaseModel):
    """Request body for updating thread state (human-in-the-loop resume)."""

    values: dict[str, Any] | None = Field(default=None, description="Channel values to merge")
    checkpoint_id: str | None = Field(default=None, description="Checkpoint to branch from")
    checkpoint: dict[str, Any] | None = Field(default=None, description="Full checkpoint object")
    as_node: str | None = Field(default=None, description="Node identity for the update")


class ThreadGoalRequest(BaseModel):
    """Request body for setting a thread-scoped goal."""

    objective: str = Field(..., min_length=1, max_length=4000, description="Completion condition for the agent to keep pursuing")
    max_continuations: int = Field(
        default=DEFAULT_MAX_GOAL_CONTINUATIONS,
        ge=0,
        le=DEFAULT_MAX_GOAL_CONTINUATIONS,
        description="Maximum automatic hidden continuation turns before stopping",
    )


class ThreadGoalResponse(BaseModel):
    """Response model for a thread goal."""

    goal: dict[str, Any] | None = Field(default=None, description="Current goal state, or null when no goal is active")


class HistoryEntry(BaseModel):
    """Single checkpoint history entry."""

    checkpoint_id: str
    parent_checkpoint_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    values: dict[str, Any] = Field(default_factory=dict)
    created_at: str | None = None
    next: list[str] = Field(default_factory=list)


class ThreadHistoryRequest(BaseModel):
    """Request body for checkpoint history."""

    limit: int = Field(default=10, ge=1, le=100, description="Maximum entries")
    before: str | None = Field(default=None, description="Cursor for pagination")


class ThreadBranchRequest(BaseModel):
    """Request body for creating a branch from a completed assistant turn."""

    message_id: str = Field(..., min_length=1, description="Target assistant message ID to branch from")
    message_ids: list[str] = Field(default_factory=list, description="All assistant message IDs in the target turn")
    title: str | None = Field(default=None, max_length=256, description="Optional title for the branched thread")


class ThreadBranchResponse(BaseModel):
    """Response model for a thread branch."""

    thread_id: str
    parent_thread_id: str
    parent_checkpoint_id: str
    branched_from_message_id: str
    workspace_clone_mode: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _delete_thread_data(thread_id: str, paths: Paths | None = None, *, user_id: str | None = None) -> ThreadDeleteResponse:
    """Delete local persisted filesystem data for a thread."""
    path_manager = paths or get_paths()
    try:
        path_manager.delete_thread_dir(thread_id, user_id=user_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except FileNotFoundError:
        # Not critical — thread data may not exist on disk
        logger.debug("No local thread data to delete for %s", sanitize_log_param(thread_id))
        return ThreadDeleteResponse(success=True, message=f"No local data for {thread_id}")
    except Exception as exc:
        logger.exception("Failed to delete thread data for %s", sanitize_log_param(thread_id))
        raise HTTPException(status_code=500, detail="Failed to delete local thread data.") from exc

    logger.info("Deleted local thread data for %s", sanitize_log_param(thread_id))
    return ThreadDeleteResponse(success=True, message=f"Deleted local thread data for {thread_id}")


def _derive_thread_status(checkpoint_tuple) -> str:
    """Derive thread status from checkpoint metadata."""
    if checkpoint_tuple is None:
        return "idle"
    pending_writes = getattr(checkpoint_tuple, "pending_writes", None) or []

    # Check for error in pending writes
    for pw in pending_writes:
        if len(pw) >= 2 and pw[1] == "__error__":
            return "error"

    # Check for pending next tasks (indicates interrupt)
    tasks = getattr(checkpoint_tuple, "tasks", None)
    if tasks:
        return "interrupted"

    return "idle"


async def _ensure_thread_for_goal(thread_id: str, request: Request) -> None:
    """Ensure a thread_meta row and root checkpoint exist for goal commands."""
    from app.gateway.deps import get_thread_store

    thread_store = get_thread_store(request)
    checkpointer = get_checkpointer(request)
    thread_owner_user_id = get_trusted_internal_owner_user_id(request)
    thread_owner_kwargs = {"user_id": thread_owner_user_id} if thread_owner_user_id else {}

    record = await thread_store.get(thread_id, **thread_owner_kwargs)
    if record is None and thread_owner_user_id:
        unscoped_record = await thread_store.get(thread_id, user_id=None)
        if unscoped_record is not None:
            if unscoped_record.get("user_id") != thread_owner_user_id:
                await thread_store.update_owner(thread_id, thread_owner_user_id, user_id=None)
            record = await thread_store.get(thread_id, **thread_owner_kwargs)
    if record is None:
        try:
            await thread_store.create(thread_id, metadata={}, **thread_owner_kwargs)
        except Exception:
            logger.exception("Failed to create thread_meta for goal thread %s", sanitize_log_param(thread_id))
            raise HTTPException(status_code=500, detail="Failed to create thread") from None

    try:
        await ensure_thread_checkpoint(checkpointer, thread_id)
    except Exception:
        logger.exception("Failed to create goal checkpoint for thread %s", sanitize_log_param(thread_id))
        raise HTTPException(status_code=500, detail="Failed to create thread checkpoint") from None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.delete("/{thread_id}", response_model=ThreadDeleteResponse)
@require_permission("threads", "delete", owner_check=True, require_existing=True)
async def delete_thread_data(thread_id: str, request: Request) -> ThreadDeleteResponse:
    """Delete local persisted filesystem data for a thread.

    Cleans DeerFlow-managed thread directories, removes checkpoint data,
    and removes the thread_meta row from the configured ThreadMetaStore
    (sqlite or memory).
    """
    from app.gateway.deps import get_thread_store

    # Clean local filesystem
    response = _delete_thread_data(thread_id, user_id=get_effective_user_id())

    # Remove checkpoints (best-effort)
    checkpointer = getattr(request.app.state, "checkpointer", None)
    if checkpointer is not None:
        try:
            if hasattr(checkpointer, "adelete_thread"):
                await checkpointer.adelete_thread(thread_id)
        except Exception:
            logger.debug("Could not delete checkpoints for thread %s (not critical)", sanitize_log_param(thread_id))

    # Remove thread_meta row (best-effort) — required for sqlite backend
    # so the deleted thread no longer appears in /threads/search.
    try:
        thread_store = get_thread_store(request)
        await thread_store.delete(thread_id)
    except Exception:
        logger.debug("Could not delete thread_meta for %s (not critical)", sanitize_log_param(thread_id))

    return response


@router.post("", response_model=ThreadResponse)
async def create_thread(body: ThreadCreateRequest, request: Request) -> ThreadResponse:
    """Create a new thread.

    Writes a thread_meta record (so the thread appears in /threads/search)
    and an empty checkpoint (so state endpoints work immediately).
    Idempotent: returns the existing record when ``thread_id`` already exists.
    """
    from app.gateway.deps import get_thread_store

    checkpointer = get_checkpointer(request)
    thread_store = get_thread_store(request)
    thread_id = body.thread_id or str(uuid.uuid4())
    now = now_iso()
    thread_owner_user_id = get_trusted_internal_owner_user_id(request)
    thread_owner_kwargs = {"user_id": thread_owner_user_id} if thread_owner_user_id else {}
    # ``body.metadata`` is already stripped of server-reserved keys by
    # ``ThreadCreateRequest._strip_reserved`` — see the model definition.

    # Idempotency: return existing record when already present
    existing_record = await thread_store.get(thread_id, **thread_owner_kwargs)
    if existing_record is None and thread_owner_user_id:
        unscoped_record = await thread_store.get(thread_id, user_id=None)
        if unscoped_record is not None:
            if unscoped_record.get("user_id") != thread_owner_user_id:
                await thread_store.update_owner(thread_id, thread_owner_user_id, user_id=None)
            existing_record = await thread_store.get(thread_id, **thread_owner_kwargs)
    if existing_record is not None:
        return ThreadResponse(
            thread_id=thread_id,
            status=existing_record.get("status", "idle"),
            created_at=coerce_iso(existing_record.get("created_at", "")),
            updated_at=coerce_iso(existing_record.get("updated_at", "")),
            metadata=existing_record.get("metadata", {}),
        )

    # Write thread_meta so the thread appears in /threads/search immediately
    try:
        await thread_store.create(
            thread_id,
            assistant_id=getattr(body, "assistant_id", None),
            **thread_owner_kwargs,
            metadata=body.metadata,
        )
    except Exception:
        logger.exception("Failed to write thread_meta for %s", sanitize_log_param(thread_id))
        raise HTTPException(status_code=500, detail="Failed to create thread")

    # Write an empty checkpoint so state endpoints work immediately
    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    try:
        ckpt_metadata = {
            "step": -1,
            "source": "input",
            "writes": None,
            "parents": {},
            **body.metadata,
            "created_at": now,
        }
        await checkpointer.aput(config, empty_checkpoint(), ckpt_metadata, {})
    except Exception:
        logger.exception("Failed to create checkpoint for thread %s", sanitize_log_param(thread_id))
        raise HTTPException(status_code=500, detail="Failed to create thread")

    logger.info("Thread created: %s", sanitize_log_param(thread_id))
    return ThreadResponse(
        thread_id=thread_id,
        status="idle",
        created_at=now,
        updated_at=now,
        metadata=body.metadata,
    )


@router.post("/{thread_id}/branches", response_model=ThreadBranchResponse)
@require_permission("threads", "write", owner_check=True, require_existing=True)
async def branch_thread(thread_id: str, body: ThreadBranchRequest, request: Request) -> ThreadBranchResponse:
    """Create a new main-thread branch from a completed assistant turn."""
    from app.gateway.deps import get_thread_store

    checkpointer = get_checkpointer(request)
    thread_store = get_thread_store(request)

    source_record = await thread_store.get(thread_id)
    if source_record is None:
        raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")

    source_metadata = source_record.get("metadata") or {}
    if source_metadata.get(_SIDECAR_METADATA_KEY) is True:
        raise HTTPException(status_code=409, detail="Branching is only available in the main conversation.")

    target_message_ids = {body.message_id, *body.message_ids}
    checkpoint_tuple = await _find_branch_checkpoint(checkpointer, thread_id, target_message_ids)
    parent_checkpoint_id = _checkpoint_id(checkpoint_tuple)
    if not parent_checkpoint_id:
        raise HTTPException(status_code=409, detail="This turn can no longer be branched from.")

    # Workspace files are not checkpointed, so they only reflect the *current* thread
    # state. Cloning them onto a branch from an older turn would leak files created
    # after that turn (message history rolls back, workspace would not). Restrict the
    # best-effort clone to branches taken from the latest turn so history and workspace
    # stay consistent.
    branch_from_latest_turn = await _branch_targets_latest_turn(checkpointer, thread_id, target_message_ids)

    new_thread_id = str(uuid.uuid4())
    now = now_iso()
    branch_metadata = {
        _BRANCH_METADATA_KEY: True,
        "branch_parent_thread_id": thread_id,
        "branch_parent_checkpoint_id": parent_checkpoint_id,
        "branch_parent_message_id": body.message_id,
        "branch_created_at": now,
    }

    display_name = body.title or _default_branch_display_name(
        source_record.get("display_name"),
        source_is_branch=source_metadata.get(_BRANCH_METADATA_KEY) is True,
    )
    thread_owner_user_id = get_trusted_internal_owner_user_id(request)
    thread_owner_kwargs = {"user_id": thread_owner_user_id} if thread_owner_user_id else {}

    checkpoint = copy.deepcopy(getattr(checkpoint_tuple, "checkpoint", {}) or {})
    metadata = copy.deepcopy(getattr(checkpoint_tuple, "metadata", {}) or {})
    checkpoint["id"] = str(uuid6())
    metadata.update(
        {
            "source": "branch",
            "updated_at": now,
            "created_at": now,
            **branch_metadata,
        }
    )

    write_config = {"configurable": {"thread_id": new_thread_id, "checkpoint_ns": ""}}
    new_versions = dict(checkpoint.get("channel_versions", {}) or {})
    try:
        await checkpointer.aput(write_config, checkpoint, metadata, new_versions)
    except Exception:
        logger.exception("Failed to write branch checkpoint for thread %s", sanitize_log_param(new_thread_id))
        raise HTTPException(status_code=500, detail="Failed to create branch") from None

    try:
        await thread_store.create(
            new_thread_id,
            assistant_id=source_record.get("assistant_id"),
            display_name=display_name,
            metadata=branch_metadata,
            **thread_owner_kwargs,
        )
    except Exception:
        logger.exception("Failed to write branch thread_meta for %s", sanitize_log_param(new_thread_id))
        raise HTTPException(status_code=500, detail="Failed to create branch") from None

    if branch_from_latest_turn:
        workspace_clone_mode = await _copy_branch_user_data(thread_id, new_thread_id)
    else:
        workspace_clone_mode = "skipped_historical_turn"
    return ThreadBranchResponse(
        thread_id=new_thread_id,
        parent_thread_id=thread_id,
        parent_checkpoint_id=parent_checkpoint_id,
        branched_from_message_id=body.message_id,
        workspace_clone_mode=workspace_clone_mode,
    )


@router.post("/search", response_model=list[ThreadResponse])
async def search_threads(body: ThreadSearchRequest, request: Request) -> list[ThreadResponse]:
    """Search and list threads.

    Delegates to the configured ThreadMetaStore implementation
    (SQL-backed for sqlite/postgres, Store-backed for memory mode).
    """
    from app.gateway.deps import get_thread_store
    from deerflow.persistence.thread_meta import InvalidMetadataFilterError

    repo = get_thread_store(request)
    try:
        rows = await repo.search(
            metadata=body.metadata or None,
            status=body.status,
            limit=body.limit,
            offset=body.offset,
        )
    except InvalidMetadataFilterError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return [
        ThreadResponse(
            thread_id=r["thread_id"],
            status=r.get("status", "idle"),
            # ``coerce_iso`` heals legacy unix-second values that
            # ``MemoryThreadMetaStore`` historically wrote with ``time.time()``;
            # SQL-backed rows already arrive as ISO strings and pass through.
            created_at=coerce_iso(r.get("created_at", "")),
            updated_at=coerce_iso(r.get("updated_at", "")),
            metadata=r.get("metadata", {}),
            values={"title": r["display_name"]} if r.get("display_name") else {},
            interrupts={},
        )
        for r in rows
    ]


@router.patch("/{thread_id}", response_model=ThreadResponse)
@require_permission("threads", "write", owner_check=True, require_existing=True)
async def patch_thread(thread_id: str, body: ThreadPatchRequest, request: Request) -> ThreadResponse:
    """Merge metadata into a thread record."""
    from app.gateway.deps import get_thread_store

    thread_store = get_thread_store(request)
    record = await thread_store.get(thread_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")

    # ``body.metadata`` already stripped by ``ThreadPatchRequest._strip_reserved``.
    try:
        await thread_store.update_metadata(thread_id, body.metadata)
    except Exception:
        logger.exception("Failed to patch thread %s", sanitize_log_param(thread_id))
        raise HTTPException(status_code=500, detail="Failed to update thread")

    # Re-read to get the merged metadata + refreshed updated_at
    record = await thread_store.get(thread_id) or record
    return ThreadResponse(
        thread_id=thread_id,
        status=record.get("status", "idle"),
        created_at=coerce_iso(record.get("created_at", "")),
        updated_at=coerce_iso(record.get("updated_at", "")),
        metadata=record.get("metadata", {}),
    )


@router.get("/{thread_id}", response_model=ThreadResponse)
@require_permission("threads", "read", owner_check=True)
async def get_thread(thread_id: str, request: Request) -> ThreadResponse:
    """Get thread info.

    Reads metadata from the ThreadMetaStore and derives the accurate
    execution status from the checkpointer.  Falls back to the checkpointer
    alone for threads that pre-date ThreadMetaStore adoption (backward compat).
    """
    from app.gateway.deps import get_thread_store

    thread_store = get_thread_store(request)
    checkpointer = get_checkpointer(request)

    record: dict | None = await thread_store.get(thread_id)

    # Derive accurate status from the checkpointer
    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    try:
        checkpoint_tuple = await checkpointer.aget_tuple(config)
    except Exception:
        logger.exception("Failed to get checkpoint for thread %s", sanitize_log_param(thread_id))
        raise HTTPException(status_code=500, detail="Failed to get thread")

    if record is None and checkpoint_tuple is None:
        raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")

    # If the thread exists in the checkpointer but not in thread_meta (e.g.
    # legacy data created before thread_meta adoption), synthesize a minimal
    # record from the checkpoint metadata.
    if record is None and checkpoint_tuple is not None:
        ckpt_meta = getattr(checkpoint_tuple, "metadata", {}) or {}
        record = {
            "thread_id": thread_id,
            "status": "idle",
            "created_at": coerce_iso(ckpt_meta.get("created_at", "")),
            "updated_at": coerce_iso(ckpt_meta.get("updated_at", ckpt_meta.get("created_at", ""))),
            "metadata": {k: v for k, v in ckpt_meta.items() if k not in ("created_at", "updated_at", "step", "source", "writes", "parents")},
        }

    if record is None:
        raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")

    status = _derive_thread_status(checkpoint_tuple) if checkpoint_tuple is not None else record.get("status", "idle")
    checkpoint = getattr(checkpoint_tuple, "checkpoint", {}) or {} if checkpoint_tuple is not None else {}
    channel_values = checkpoint.get("channel_values", {})

    return ThreadResponse(
        thread_id=thread_id,
        status=status,
        created_at=coerce_iso(record.get("created_at", "")),
        updated_at=coerce_iso(record.get("updated_at", "")),
        metadata=record.get("metadata", {}),
        values=serialize_channel_values_for_api(channel_values),
    )


@router.get("/{thread_id}/goal", response_model=ThreadGoalResponse)
@require_permission("threads", "read", owner_check=True)
async def get_thread_goal(thread_id: str, request: Request) -> ThreadGoalResponse:
    """Return the active Claude-style goal for a thread, if any."""
    checkpointer = get_checkpointer(request)
    try:
        goal = await read_thread_goal(checkpointer, thread_id)
    except Exception:
        logger.exception("Failed to read goal for thread %s", sanitize_log_param(thread_id))
        raise HTTPException(status_code=500, detail="Failed to read thread goal") from None
    return ThreadGoalResponse(goal=goal)


@router.put("/{thread_id}/goal", response_model=ThreadGoalResponse)
@require_permission("threads", "write", owner_check=True)
async def set_thread_goal(thread_id: str, body: ThreadGoalRequest, request: Request) -> ThreadGoalResponse:
    """Set or replace the active goal for a thread.

    ``/chats/new`` pages already hold a generated UUID before the first run, so
    this endpoint creates the missing thread checkpoint on demand.
    """
    checkpointer = get_checkpointer(request)
    await _ensure_thread_for_goal(thread_id, request)
    try:
        goal = build_goal_state(body.objective, max_continuations=body.max_continuations)
        async with goal_thread_lock(thread_id):
            await write_thread_goal(checkpointer, thread_id, goal, as_node="goal", create_if_missing=True)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception:
        logger.exception("Failed to set goal for thread %s", sanitize_log_param(thread_id))
        raise HTTPException(status_code=500, detail="Failed to set thread goal") from None
    return ThreadGoalResponse(goal=goal)


@router.delete("/{thread_id}/goal", response_model=ThreadGoalResponse)
@require_permission("threads", "write", owner_check=True)
async def clear_thread_goal(thread_id: str, request: Request) -> ThreadGoalResponse:
    """Clear the active goal for a thread."""
    checkpointer = get_checkpointer(request)
    try:
        async with goal_thread_lock(thread_id):
            await write_thread_goal(checkpointer, thread_id, None, as_node="goal")
    except LookupError:
        return ThreadGoalResponse(goal=None)
    except Exception:
        logger.exception("Failed to clear goal for thread %s", sanitize_log_param(thread_id))
        raise HTTPException(status_code=500, detail="Failed to clear thread goal") from None
    return ThreadGoalResponse(goal=None)


# ---------------------------------------------------------------------------
@router.get("/{thread_id}/state", response_model=ThreadStateResponse)
@require_permission("threads", "read", owner_check=True)
async def get_thread_state(thread_id: str, request: Request) -> ThreadStateResponse:
    """Get the latest state snapshot for a thread.

    Channel values are serialized to ensure LangChain message objects
    are converted to JSON-safe dicts.
    """
    checkpointer = get_checkpointer(request)

    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    try:
        checkpoint_tuple = await checkpointer.aget_tuple(config)
    except Exception:
        logger.exception("Failed to get state for thread %s", sanitize_log_param(thread_id))
        raise HTTPException(status_code=500, detail="Failed to get thread state")

    if checkpoint_tuple is None:
        raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")

    checkpoint = getattr(checkpoint_tuple, "checkpoint", {}) or {}
    metadata = getattr(checkpoint_tuple, "metadata", {}) or {}
    checkpoint_id = None
    ckpt_config = getattr(checkpoint_tuple, "config", {})
    if ckpt_config:
        checkpoint_id = ckpt_config.get("configurable", {}).get("checkpoint_id")

    channel_values = checkpoint.get("channel_values", {})

    parent_config = getattr(checkpoint_tuple, "parent_config", None)
    parent_checkpoint_id = None
    if parent_config:
        parent_checkpoint_id = parent_config.get("configurable", {}).get("checkpoint_id")

    tasks_raw = getattr(checkpoint_tuple, "tasks", []) or []
    next_tasks = [t.name for t in tasks_raw if hasattr(t, "name")]
    tasks = [{"id": getattr(t, "id", ""), "name": getattr(t, "name", "")} for t in tasks_raw]

    values = serialize_channel_values_for_api(channel_values)

    return ThreadStateResponse(
        values=values,
        next=next_tasks,
        metadata=metadata,
        checkpoint={"id": checkpoint_id, "ts": coerce_iso(metadata.get("created_at", ""))},
        checkpoint_id=checkpoint_id,
        parent_checkpoint_id=parent_checkpoint_id,
        created_at=coerce_iso(metadata.get("created_at", "")),
        tasks=tasks,
    )


@router.post("/{thread_id}/state", response_model=ThreadStateResponse)
@require_permission("threads", "write", owner_check=True, require_existing=True)
async def update_thread_state(thread_id: str, body: ThreadStateUpdateRequest, request: Request) -> ThreadStateResponse:
    """Update thread state (e.g. for human-in-the-loop resume or title rename).

    Writes a new checkpoint that merges *body.values* into the latest
    channel values, then syncs any updated ``title`` field through the
    ThreadMetaStore abstraction so that ``/threads/search`` reflects the
    change immediately in both sqlite and memory backends.
    """
    from app.gateway.deps import get_thread_store

    checkpointer = get_checkpointer(request)
    thread_store = get_thread_store(request)

    # checkpoint_ns must be present in the config for aput — default to ""
    # (the root graph namespace).  checkpoint_id is optional; omitting it
    # fetches the latest checkpoint for the thread.
    read_config: dict[str, Any] = {
        "configurable": {
            "thread_id": thread_id,
            "checkpoint_ns": "",
        }
    }
    if body.checkpoint_id:
        read_config["configurable"]["checkpoint_id"] = body.checkpoint_id

    try:
        checkpoint_tuple = await checkpointer.aget_tuple(read_config)
    except Exception:
        logger.exception("Failed to get state for thread %s", sanitize_log_param(thread_id))
        raise HTTPException(status_code=500, detail="Failed to get thread state")

    if checkpoint_tuple is None:
        raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")

    # Work on mutable copies so we don't accidentally mutate cached objects.
    checkpoint: dict[str, Any] = dict(getattr(checkpoint_tuple, "checkpoint", {}) or {})
    metadata: dict[str, Any] = dict(getattr(checkpoint_tuple, "metadata", {}) or {})
    channel_values: dict[str, Any] = dict(checkpoint.get("channel_values", {}))

    if body.values:
        channel_values.update(body.values)

    checkpoint["channel_values"] = channel_values
    metadata["updated_at"] = now_iso()

    if body.as_node:
        metadata["source"] = "update"
        metadata["step"] = metadata.get("step", 0) + 1
        metadata["writes"] = {body.as_node: body.values}

    # Assign a new checkpoint ID so aput performs an INSERT rather than an
    # in-place REPLACE of the existing row.  Use uuid6 (time-ordered) rather
    # than uuid4 (random) so the new ID is always lexicographically greater
    # than the previous one — LangGraph's checkpointers determine the "latest"
    # checkpoint by max(checkpoint_ids) string order, matching the uuid6 epoch.
    checkpoint["id"] = str(uuid6())

    # aput requires checkpoint_ns in the config — use the same config used for the
    # read (which always includes checkpoint_ns=""). The fresh checkpoint ID is
    # assigned above via checkpoint["id"]; keep checkpoint_id out of the config so
    # the write is keyed by the new checkpoint payload rather than the prior read.
    # All supported savers (InMemorySaver, AsyncSqliteSaver, AsyncPostgresSaver)
    # persist and echo back checkpoint["id"] verbatim — none mint their own — so
    # the new_config below carries the uuid6 we assigned here. (Regression-locked
    # by test_update_thread_state_inserts_new_checkpoint_each_call.)
    write_config: dict[str, Any] = {
        "configurable": {
            "thread_id": thread_id,
            "checkpoint_ns": "",
        }
    }
    try:
        new_config = await checkpointer.aput(write_config, checkpoint, metadata, {})
    except Exception:
        logger.exception("Failed to update state for thread %s", sanitize_log_param(thread_id))
        raise HTTPException(status_code=500, detail="Failed to update thread state")

    new_checkpoint_id: str | None = None
    if isinstance(new_config, dict):
        new_checkpoint_id = new_config.get("configurable", {}).get("checkpoint_id")

    # Sync title changes through the ThreadMetaStore abstraction so /threads/search
    # reflects them immediately in both sqlite and memory backends.
    if thread_store and body.values and "title" in body.values:
        new_title = body.values["title"]
        if new_title:  # Skip empty strings and None
            try:
                await thread_store.update_display_name(thread_id, new_title)
            except Exception:
                logger.debug("Failed to sync title to thread_meta for %s (non-fatal)", sanitize_log_param(thread_id))

    return ThreadStateResponse(
        values=serialize_channel_values_for_api(channel_values),
        next=[],
        metadata=metadata,
        checkpoint_id=new_checkpoint_id,
        created_at=coerce_iso(metadata.get("created_at", "")),
    )


@router.post("/{thread_id}/history", response_model=list[HistoryEntry])
@require_permission("threads", "read", owner_check=True)
async def get_thread_history(thread_id: str, body: ThreadHistoryRequest, request: Request) -> list[HistoryEntry]:
    """Get checkpoint history for a thread.

    Messages are read from the checkpointer's channel values (the
    authoritative source) and serialized via
    :func:`~deerflow.runtime.serialization.serialize_channel_values`.
    Only the latest (first) checkpoint carries the ``messages`` key to
    avoid duplicating them across every entry.
    """
    checkpointer = get_checkpointer(request)

    config: dict[str, Any] = {"configurable": {"thread_id": thread_id}}
    if body.before:
        config["configurable"]["checkpoint_id"] = body.before

    entries: list[HistoryEntry] = []
    is_latest_checkpoint = True
    try:
        async for checkpoint_tuple in checkpointer.alist(config, limit=body.limit):
            ckpt_config = getattr(checkpoint_tuple, "config", {})
            parent_config = getattr(checkpoint_tuple, "parent_config", None)
            metadata = getattr(checkpoint_tuple, "metadata", {}) or {}
            checkpoint = getattr(checkpoint_tuple, "checkpoint", {}) or {}

            checkpoint_id = ckpt_config.get("configurable", {}).get("checkpoint_id", "")
            parent_id = None
            if parent_config:
                parent_id = parent_config.get("configurable", {}).get("checkpoint_id")

            channel_values = checkpoint.get("channel_values", {})

            # Build values from checkpoint channel_values
            values: dict[str, Any] = {}
            if title := channel_values.get("title"):
                values["title"] = title
            if thread_data := channel_values.get("thread_data"):
                values["thread_data"] = thread_data

            # Attach messages only to the latest checkpoint entry.
            if is_latest_checkpoint:
                messages = channel_values.get("messages")
                if messages:
                    serialized_msgs = serialize_channel_values_for_api({"messages": messages}).get("messages", [])
                    try:
                        from app.gateway.deps import get_run_event_store, get_run_manager
                        from app.gateway.routers.thread_runs import compute_run_durations

                        run_mgr = get_run_manager(request)
                        event_store = get_run_event_store(request)

                        runs = await run_mgr.list_by_thread(thread_id)

                        # FIXME: Fetching limit=1000 silently drops durations for messages older than the cap on long threads.
                        # We do this full fetch because raw LangGraph messages lack a native run_id link.

                        events = await event_store.list_messages(thread_id, limit=1000)

                        if runs and serialized_msgs:
                            # 1. Map each run_id to its actual duration
                            run_durations = compute_run_durations(runs)

                            # 2. Map every message id directly to its parent run_id
                            msg_to_run = {}
                            for e in events:
                                content = e.get("content", {})
                                if isinstance(content, dict) and content.get("type") == "ai" and "id" in content:
                                    msg_to_run[content["id"]] = e["run_id"]

                            # 3. Attach the owning run_id to replayed messages.
                            # Raw LangGraph checkpoint messages do not carry a
                            # native run link. Message events are exact when
                            # present, but historical/runtime stores can miss
                            # them; the user-input message already records the
                            # run id for the whole turn, so use it as the
                            # fallback for following AI/tool messages.
                            current_turn_run_id = None
                            for msg in serialized_msgs:
                                if msg.get("type") == "human":
                                    additional_kwargs = msg.get("additional_kwargs")
                                    if isinstance(additional_kwargs, dict):
                                        run_id = additional_kwargs.get("run_id")
                                        if isinstance(run_id, str) and run_id:
                                            current_turn_run_id = run_id
                                    continue

                                if msg.get("type") in {"ai", "tool"}:
                                    msg_id = msg.get("id")
                                    run_id = msg_to_run.get(msg_id) or current_turn_run_id
                                    if run_id:
                                        msg["run_id"] = run_id
                                        if msg.get("type") == "ai" and run_id in run_durations:
                                            if "additional_kwargs" not in msg:
                                                msg["additional_kwargs"] = {}
                                            msg["additional_kwargs"]["turn_duration"] = run_durations[run_id]

                    except Exception:
                        logger.warning("Failed to inject turn_duration for thread %s", thread_id, exc_info=True)

                    values["messages"] = serialized_msgs

            is_latest_checkpoint = False

            # Derive next tasks
            tasks_raw = getattr(checkpoint_tuple, "tasks", []) or []
            next_tasks = [t.name for t in tasks_raw if hasattr(t, "name")]

            # Strip LangGraph internal keys from metadata
            user_meta = {k: v for k, v in metadata.items() if k not in ("created_at", "updated_at", "step", "source", "writes", "parents")}
            # Keep step for ordering context
            if "step" in metadata:
                user_meta["step"] = metadata["step"]

            entries.append(
                HistoryEntry(
                    checkpoint_id=checkpoint_id,
                    parent_checkpoint_id=parent_id,
                    metadata=user_meta,
                    values=values,
                    created_at=coerce_iso(metadata.get("created_at", "")),
                    next=next_tasks,
                )
            )
    except Exception:
        logger.exception("Failed to get history for thread %s", sanitize_log_param(thread_id))
        raise HTTPException(status_code=500, detail="Failed to get thread history")

    return entries
