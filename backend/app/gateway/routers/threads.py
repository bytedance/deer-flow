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

import logging
import shutil
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.types import Overwrite
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.exc import IntegrityError

from app.gateway.authz import require_permission
from app.gateway.deps import get_checkpointer, get_run_manager
from app.gateway.internal_auth import get_trusted_internal_owner_user_id
from app.gateway.services import (
    build_checkpoint_state_accessor,
    build_checkpoint_state_mutation_accessor,
    build_thread_checkpoint_state_accessor,
    build_thread_checkpoint_state_mutation_accessor,
)
from app.gateway.utils import sanitize_log_param
from deerflow.agents.thread_state import THREAD_STATE_REDUCER_FIELDS
from deerflow.config.paths import Paths, get_paths
from deerflow.config.summarization_config import ContextSize
from deerflow.runtime import serialize_channel_values_for_api
from deerflow.runtime.checkpoint_mode import CheckpointModeMismatchError, CheckpointModeReconfigurationError
from deerflow.runtime.checkpoint_state import graph_reducer_channels, graph_state_schema, graph_writable_channels
from deerflow.runtime.context_compaction import (
    ContextCompactionDisabled,
    ContextCompactionFailed,
    ThreadCompactionResult,
    compact_thread_context,
)
from deerflow.runtime.goal import (
    DEFAULT_MAX_GOAL_CONTINUATIONS,
    build_goal_state,
    ensure_thread_checkpoint,
    goal_thread_lock,
    read_thread_goal,
    write_thread_goal,
)
from deerflow.runtime.runs.worker import valid_duration_entry
from deerflow.runtime.user_context import get_effective_user_id
from deerflow.utils.file_io import run_file_io
from deerflow.utils.time import coerce_iso, now_iso

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/threads", tags=["threads"])

_CHECKPOINT_MODE_ERRORS = (CheckpointModeMismatchError, CheckpointModeReconfigurationError)


def _checkpoint_mode_http_error(exc: Exception, thread_id: str) -> HTTPException:
    """Map checkpoint-mode guard failures to precise HTTP statuses.

    A mismatch means the thread's persisted checkpoints conflict with the
    process's frozen mode (operator-actionable, 409); a reconfiguration means
    the process itself is mid mode-flip (transient, 503). Both must surface
    their message — a generic 500 would force operators to grep logs to
    discover the root cause after a mode flip.
    """
    if isinstance(exc, CheckpointModeMismatchError):
        return HTTPException(status_code=409, detail=f"Thread {thread_id}: {exc}")
    return HTTPException(status_code=503, detail=str(exc))


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


def _checkpoint_messages(snapshot: Any) -> list[Any]:
    values = getattr(snapshot, "values", None) or {}
    messages = values.get("messages") if isinstance(values, dict) else None
    return list(messages) if isinstance(messages, list) else []


def _checkpoint_id(snapshot: Any) -> str | None:
    config = getattr(snapshot, "config", {}) or {}
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


async def _find_branch_checkpoint(
    accessor: Any,
    config: dict[str, Any],
    target_message_ids: set[str],
) -> Any:
    try:
        for snapshot in await accessor.ahistory(config, limit=_BRANCH_HISTORY_SCAN_LIMIT):
            if _matches_branch_target(_checkpoint_messages(snapshot), target_message_ids):
                return snapshot
    except _CHECKPOINT_MODE_ERRORS as exc:
        raise _checkpoint_mode_http_error(exc, config.get("configurable", {}).get("thread_id", "")) from exc
    except Exception:
        thread_id = config.get("configurable", {}).get("thread_id", "")
        logger.exception("Failed to scan branch checkpoint history for thread %s", sanitize_log_param(thread_id))
        raise HTTPException(status_code=500, detail="Failed to find branch checkpoint")
    raise HTTPException(status_code=409, detail="This turn can no longer be branched from.")


async def _branch_targets_latest_turn(
    accessor: Any,
    config: dict[str, Any],
    target_message_ids: set[str],
) -> bool:
    """Return whether the target turn is the final visible turn."""
    try:
        for snapshot in await accessor.ahistory(config, limit=_BRANCH_HISTORY_SCAN_LIMIT):
            messages = _checkpoint_messages(snapshot)
            if not messages:
                continue
            return _matches_branch_target(messages, target_message_ids)
    except Exception:
        thread_id = config.get("configurable", {}).get("thread_id", "")
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


class ThreadCompactRequest(BaseModel):
    """Request body for manually compacting a thread's active context."""

    force: bool = Field(default=True, description="Run compaction even if automatic summarization thresholds are not met")
    keep: ContextSize | None = Field(default=None, description="Optional retention policy for this compaction only")
    agent_name: str | None = Field(default=None, max_length=128, description="Optional custom agent name for memory attribution")


class ThreadCompactResponse(BaseModel):
    """Response model for manual thread-context compaction."""

    thread_id: str
    compacted: bool
    reason: str | None = None
    removed_message_count: int = 0
    preserved_message_count: int = 0
    summary_updated: bool = False
    checkpoint_id: str | None = None
    total_tokens: int = 0


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


async def _fetch_raw_pending_writes(checkpointer: Any, config: dict[str, Any]) -> list[Any]:
    """Fetch pending writes attached to a specific checkpoint.

    Snapshot ``tasks`` only reflect writes that were pending while a task was
    still scheduled; writes attached to the latest checkpoint afterwards
    (rollback reattachment, worker error fallback) never surface there, so the
    status derivation needs one raw tuple fetch on the resolved checkpoint.
    """
    raw_tuple = await checkpointer.aget_tuple(config)
    if raw_tuple is None:
        return []
    return list(getattr(raw_tuple, "pending_writes", ()) or ())


def _derive_thread_status(snapshot: Any, pending_writes: list[Any], *, fallback_status: str = "idle") -> str:
    """Derive thread status from the materialized snapshot plus the raw
    pending writes attached to the resolved checkpoint."""
    if snapshot is None:
        return "idle"

    for write in pending_writes:
        if isinstance(write, (list, tuple)) and len(write) >= 2 and write[1] == "__error__":
            return "error"

    tasks = getattr(snapshot, "tasks", None) or ()
    for task in tasks:
        if getattr(task, "error", None) is not None:
            return "error"

    if not getattr(snapshot, "tasks_known", True):
        return fallback_status

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

    # Tear down any live browser session (best-effort). Sessions are keyed only
    # by thread_id, so leaving one alive after the owner deletes the thread lets
    # a later caller who guesses the id reuse the retained page/cookies.
    try:
        from deerflow.community.browser_automation import get_browser_session_manager

        await get_browser_session_manager().close_session(thread_id)
    except ImportError:
        pass  # Playwright is an optional dependency.
    except Exception:
        logger.debug("Could not close browser session for %s (not critical)", sanitize_log_param(thread_id))

    return response


async def _resolve_existing_thread(
    thread_store: Any,
    thread_id: str,
    thread_owner_user_id: str | None,
    thread_owner_kwargs: dict[str, Any],
) -> dict | None:
    """Return the existing thread_meta record for an idempotent create.

    When the caller carries a trusted internal owner but only a legacy unscoped
    (``user_id=None``) row exists, claim it for that owner before returning.
    Both the fast path and the insert-race recovery path resolve through here so
    a thread's ownership does not diverge based on which path found the record.
    """
    existing_record = await thread_store.get(thread_id, **thread_owner_kwargs)
    if existing_record is None and thread_owner_user_id:
        unscoped_record = await thread_store.get(thread_id, user_id=None)
        if unscoped_record is not None:
            if unscoped_record.get("user_id") != thread_owner_user_id:
                await thread_store.update_owner(thread_id, thread_owner_user_id, user_id=None)
            existing_record = await thread_store.get(thread_id, **thread_owner_kwargs)
    return existing_record


def _existing_thread_response(thread_id: str, record: dict) -> ThreadResponse:
    return ThreadResponse(
        thread_id=thread_id,
        status=record.get("status", "idle"),
        created_at=coerce_iso(record.get("created_at", "")),
        updated_at=coerce_iso(record.get("updated_at", "")),
        metadata=record.get("metadata", {}),
    )


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
    existing_record = await _resolve_existing_thread(thread_store, thread_id, thread_owner_user_id, thread_owner_kwargs)
    if existing_record is not None:
        return _existing_thread_response(thread_id, existing_record)

    # Write thread_meta so the thread appears in /threads/search immediately
    try:
        await thread_store.create(
            thread_id,
            assistant_id=getattr(body, "assistant_id", None),
            **thread_owner_kwargs,
            metadata=body.metadata,
        )
    except IntegrityError:
        # The idempotency read above and this insert are not atomic: a
        # concurrent request for the same thread_id can commit in between, so
        # the SQL-backed store rejects ours on the duplicate primary key.
        # Honour the documented idempotency contract by resolving the
        # now-existing record — running the same owner reconciliation the fast
        # path does — instead of surfacing the conflict as a 500. (The memory
        # store overwrites rather than raising, so it never reaches here.)
        existing_record = await _resolve_existing_thread(thread_store, thread_id, thread_owner_user_id, thread_owner_kwargs)
        if existing_record is not None:
            return _existing_thread_response(thread_id, existing_record)
        # A duplicate-key error with no row we can read back is a real failure.
        logger.exception("Failed to write thread_meta for %s", sanitize_log_param(thread_id))
        raise HTTPException(status_code=500, detail="Failed to create thread")
    except Exception:
        # Any non-race failure must surface, not be silently swallowed as a 200.
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

    thread_store = get_thread_store(request)

    source_record = await thread_store.get(thread_id)
    if source_record is None:
        raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")

    source_metadata = source_record.get("metadata") or {}
    if source_metadata.get(_SIDECAR_METADATA_KEY) is True:
        raise HTTPException(status_code=409, detail="Branching is only available in the main conversation.")
    source_accessor, source_config = build_checkpoint_state_accessor(
        request,
        thread_id=thread_id,
        assistant_id=source_record.get("assistant_id"),
    )

    target_message_ids = {body.message_id, *body.message_ids}
    snapshot = await _find_branch_checkpoint(source_accessor, source_config, target_message_ids)
    parent_checkpoint_id = _checkpoint_id(snapshot)
    if not parent_checkpoint_id:
        raise HTTPException(status_code=409, detail="This turn can no longer be branched from.")

    # Workspace files are not checkpointed, so they only reflect the *current* thread
    # state. Cloning them onto a branch from an older turn would leak files created
    # after that turn (message history rolls back, workspace would not). Restrict the
    # best-effort clone to branches taken from the latest turn so history and workspace
    # stay consistent.
    branch_from_latest_turn = await _branch_targets_latest_turn(source_accessor, source_config, target_message_ids)

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

    # Copy materialized values with replace semantics: reducer channels must
    # not re-merge an already-aggregated value, so every copied reducer value
    # is wrapped in Overwrite (not just messages).
    branch_accessor, new_config = build_checkpoint_state_mutation_accessor(
        request,
        thread_id=new_thread_id,
        as_node="branch",
        # The branch write carries the full materialized snapshot; use the
        # source assistant's effective schema so extension middleware channels
        # survive instead of being silently discarded as unknown channels.
        state_schema=graph_state_schema(getattr(source_accessor, "graph", None)),
    )
    branch_reducer_fields = graph_reducer_channels(getattr(branch_accessor, "graph", None))
    if branch_reducer_fields is None:
        branch_reducer_fields = THREAD_STATE_REDUCER_FIELDS
    branch_values = {}
    for key, value in dict(snapshot.values).items():
        if key in branch_reducer_fields:
            branch_values[key] = Overwrite(list(value) if key == "messages" and isinstance(value, list) else value)
        else:
            branch_values[key] = value
    new_config.setdefault("metadata", {}).update(
        {
            **branch_metadata,
            "source": "branch",
        }
    )
    try:
        await branch_accessor.aupdate(new_config, branch_values, as_node="branch")
    except _CHECKPOINT_MODE_ERRORS as exc:
        raise _checkpoint_mode_http_error(exc, new_thread_id) from exc
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
    """Get thread info from metadata plus the graph's materialized state."""
    from app.gateway.deps import get_thread_store

    thread_store = get_thread_store(request)
    checkpointer = get_checkpointer(request)
    record: dict | None = await thread_store.get(thread_id)
    try:
        accessor, config = build_checkpoint_state_accessor(
            request,
            thread_id=thread_id,
            assistant_id=record.get("assistant_id") if record is not None else None,
        )
    except _CHECKPOINT_MODE_ERRORS as exc:
        raise _checkpoint_mode_http_error(exc, thread_id) from exc

    try:
        snapshot = await accessor.aget(config)
        checkpoint_id = (snapshot.config or {}).get("configurable", {}).get("checkpoint_id")
        pending_writes = await _fetch_raw_pending_writes(checkpointer, snapshot.config) if checkpoint_id else []
    except _CHECKPOINT_MODE_ERRORS as exc:
        raise _checkpoint_mode_http_error(exc, thread_id) from exc
    except Exception:
        logger.exception("Failed to get checkpoint for thread %s", sanitize_log_param(thread_id))
        raise HTTPException(status_code=500, detail="Failed to get thread")

    if record is None and not checkpoint_id:
        raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")

    metadata = snapshot.metadata or {}
    if record is None:
        record = {
            "thread_id": thread_id,
            "status": "idle",
            "created_at": coerce_iso(snapshot.created_at or metadata.get("created_at", "")),
            "updated_at": coerce_iso(metadata.get("updated_at", snapshot.created_at or metadata.get("created_at", ""))),
            "metadata": {key: value for key, value in metadata.items() if key not in ("created_at", "updated_at", "step", "source", "writes", "parents")},
        }
    stored_status = record.get("status", "idle")
    status = _derive_thread_status(snapshot, pending_writes, fallback_status=stored_status) if checkpoint_id else stored_status

    return ThreadResponse(
        thread_id=thread_id,
        status=status,
        created_at=coerce_iso(record.get("created_at", "")),
        updated_at=coerce_iso(record.get("updated_at", "")),
        metadata=record.get("metadata", {}),
        values=serialize_channel_values_for_api(snapshot.values),
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


def _thread_compact_response(result: ThreadCompactionResult) -> ThreadCompactResponse:
    return ThreadCompactResponse(
        thread_id=result.thread_id,
        compacted=result.compacted,
        reason=result.reason,
        removed_message_count=result.removed_message_count,
        preserved_message_count=result.preserved_message_count,
        summary_updated=result.summary_updated,
        checkpoint_id=result.checkpoint_id,
        total_tokens=result.total_tokens,
    )


@router.post("/{thread_id}/compact", response_model=ThreadCompactResponse)
@require_permission("threads", "write", owner_check=True, require_existing=True)
async def compact_thread(thread_id: str, body: ThreadCompactRequest, request: Request) -> ThreadCompactResponse:
    """Manually summarize old thread context while preserving the visible history."""
    run_manager = get_run_manager(request)
    # Compaction writes only base-schema channels (messages + summary_text);
    # every other channel — including middleware-contributed ones — is carried
    # forward by checkpoint fork inheritance, so the base-schema mutation
    # graph is sufficient (and avoids building the full lead graph per call).
    try:
        accessor, _ = build_checkpoint_state_mutation_accessor(
            request,
            thread_id=thread_id,
            as_node="manual_compaction",
        )
    except _CHECKPOINT_MODE_ERRORS as exc:
        raise _checkpoint_mode_http_error(exc, thread_id) from exc
    keep = body.keep.to_tuple() if body.keep is not None else None
    try:
        async with goal_thread_lock(thread_id):
            if await run_manager.has_inflight(thread_id):
                raise HTTPException(status_code=409, detail="Thread has a run in flight. Compact after the run finishes.")
            result = await compact_thread_context(
                accessor,
                thread_id,
                keep=keep,
                force=body.force,
                user_id=get_effective_user_id(),
                agent_name=body.agent_name,
            )
    except _CHECKPOINT_MODE_ERRORS as exc:
        raise _checkpoint_mode_http_error(exc, thread_id) from exc
    except ContextCompactionDisabled:
        raise HTTPException(status_code=409, detail="Context compaction is disabled.") from None
    except ContextCompactionFailed:
        raise HTTPException(status_code=500, detail="Failed to compact thread context.") from None
    except LookupError:
        raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found") from None
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to compact thread %s", sanitize_log_param(thread_id))
        raise HTTPException(status_code=500, detail="Failed to compact thread context.") from None
    return _thread_compact_response(result)


# ---------------------------------------------------------------------------
@router.get("/{thread_id}/state", response_model=ThreadStateResponse)
@require_permission("threads", "read", owner_check=True)
async def get_thread_state(thread_id: str, request: Request) -> ThreadStateResponse:
    """Get the latest materialized graph state for a thread."""
    # Resolve through the thread's assistant so custom middleware channels
    # appear in the response instead of being dropped by the default schema.
    try:
        accessor, config = await build_thread_checkpoint_state_accessor(request, thread_id=thread_id)
    except _CHECKPOINT_MODE_ERRORS as exc:
        raise _checkpoint_mode_http_error(exc, thread_id) from exc
    try:
        snapshot = await accessor.aget(config)
    except _CHECKPOINT_MODE_ERRORS as exc:
        raise _checkpoint_mode_http_error(exc, thread_id) from exc
    except Exception:
        logger.exception("Failed to get state for thread %s", sanitize_log_param(thread_id))
        raise HTTPException(status_code=500, detail="Failed to get thread state")

    snapshot_config = snapshot.config or {}
    checkpoint_id = snapshot_config.get("configurable", {}).get("checkpoint_id")
    if not checkpoint_id:
        raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")

    parent_config = snapshot.parent_config or {}
    parent_checkpoint_id = parent_config.get("configurable", {}).get("checkpoint_id")
    metadata = snapshot.metadata or {}
    created_at = snapshot.created_at or metadata.get("created_at", "")
    tasks_raw = snapshot.tasks or ()
    tasks = [{"id": getattr(task, "id", ""), "name": getattr(task, "name", "")} for task in tasks_raw]

    return ThreadStateResponse(
        values=serialize_channel_values_for_api(snapshot.values),
        next=list(snapshot.next or ()),
        metadata=metadata,
        checkpoint={"id": checkpoint_id, "ts": coerce_iso(created_at)},
        checkpoint_id=checkpoint_id,
        parent_checkpoint_id=parent_checkpoint_id,
        created_at=coerce_iso(created_at),
        tasks=tasks,
    )


@router.post("/{thread_id}/state", response_model=ThreadStateResponse)
@require_permission("threads", "write", owner_check=True, require_existing=True)
async def update_thread_state(thread_id: str, body: ThreadStateUpdateRequest, request: Request) -> ThreadStateResponse:
    """Replace selected thread-state fields through the materialized graph."""
    from app.gateway.deps import get_thread_store

    thread_store = get_thread_store(request)
    if body.checkpoint_id is not None:
        if not body.checkpoint_id:
            raise HTTPException(status_code=404, detail="Checkpoint not found")
        selected_config = {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": "",
                "checkpoint_id": body.checkpoint_id,
            }
        }
        try:
            checkpoint_tuple = await get_checkpointer(request).aget_tuple(selected_config)
        except Exception:
            logger.exception("Failed to get state for thread %s", sanitize_log_param(thread_id))
            raise HTTPException(status_code=500, detail="Failed to get thread state")
        if checkpoint_tuple is None:
            raise HTTPException(status_code=404, detail=f"Checkpoint {body.checkpoint_id} not found")

    mutation_node = body.as_node or "manual_state_update"
    # Resolve through the shared boundary (thread metadata -> assistant_id ->
    # effective schema) so extension middleware channels stay writable.
    accessor, read_config = await build_thread_checkpoint_state_mutation_accessor(
        request,
        thread_id=thread_id,
        as_node=mutation_node,
        checkpoint_id=body.checkpoint_id,
    )
    values = dict(body.values or {})
    writable_channels = graph_writable_channels(getattr(accessor, "graph", None))
    if writable_channels is not None:
        unknown_fields = sorted(set(values) - writable_channels)
        if unknown_fields:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown thread-state field(s): {', '.join(unknown_fields)}",
            )
    reducer_fields = graph_reducer_channels(getattr(accessor, "graph", None))
    if reducer_fields is None:
        reducer_fields = THREAD_STATE_REDUCER_FIELDS
    updates = {key: Overwrite(value) if key in reducer_fields else value for key, value in values.items()}
    try:
        updated_config = await accessor.aupdate(
            read_config,
            updates,
            as_node=mutation_node,
        )
        snapshot = await accessor.aget(updated_config)
    except _CHECKPOINT_MODE_ERRORS as exc:
        raise _checkpoint_mode_http_error(exc, thread_id) from exc
    except Exception:
        logger.exception("Failed to update state for thread %s", sanitize_log_param(thread_id))
        raise HTTPException(status_code=500, detail="Failed to update thread state")

    if thread_store and body.values and "title" in body.values:
        new_title = body.values["title"]
        if new_title:
            try:
                await thread_store.update_display_name(thread_id, new_title)
            except Exception:
                logger.debug("Failed to sync title to thread_meta for %s (non-fatal)", sanitize_log_param(thread_id))

    snapshot_config = snapshot.config or {}
    checkpoint_id = snapshot_config.get("configurable", {}).get("checkpoint_id")
    parent_config = snapshot.parent_config or {}
    parent_checkpoint_id = parent_config.get("configurable", {}).get("checkpoint_id")
    metadata = snapshot.metadata or {}
    created_at = snapshot.created_at or metadata.get("created_at", "")
    tasks_raw = snapshot.tasks or ()
    tasks = [{"id": getattr(task, "id", ""), "name": getattr(task, "name", "")} for task in tasks_raw]

    return ThreadStateResponse(
        values=serialize_channel_values_for_api(snapshot.values),
        next=list(snapshot.next or ()),
        metadata=metadata,
        checkpoint={"id": checkpoint_id, "ts": coerce_iso(created_at)},
        checkpoint_id=checkpoint_id,
        parent_checkpoint_id=parent_checkpoint_id,
        created_at=coerce_iso(created_at),
        tasks=tasks,
    )


def _ai_message_lacks_duration(message: dict[str, Any]) -> bool:
    additional_kwargs = message.get("additional_kwargs")
    return message.get("type") == "ai" and (not isinstance(additional_kwargs, dict) or "turn_duration" not in additional_kwargs)


def _checkpoint_run_durations(metadata: Any) -> dict[str, int]:
    raw_durations = metadata.get("run_durations") if isinstance(metadata, dict) else None
    if not isinstance(raw_durations, dict):
        return {}
    return {run_id: duration_seconds for run_id, duration_seconds in raw_durations.items() if valid_duration_entry(run_id, duration_seconds)}


def _set_message_turn_duration(message: dict[str, Any], run_id: str, run_durations: dict[str, int]) -> None:
    if message.get("type") != "ai" or run_id not in run_durations:
        return
    additional_kwargs = message.get("additional_kwargs")
    if not isinstance(additional_kwargs, dict):
        additional_kwargs = {}
        message["additional_kwargs"] = additional_kwargs
    additional_kwargs.setdefault("turn_duration", run_durations[run_id])


@router.post("/{thread_id}/history", response_model=list[HistoryEntry])
@require_permission("threads", "read", owner_check=True)
async def get_thread_history(
    thread_id: str,
    body: ThreadHistoryRequest,
    request: Request,
    background_tasks: BackgroundTasks,
) -> list[HistoryEntry]:
    """Get materialized graph state history for a thread.

    Only the latest (first) checkpoint carries the ``messages`` key to
    avoid duplicating the complete conversation across every entry.
    """
    checkpointer = get_checkpointer(request)
    try:
        accessor, config = await build_thread_checkpoint_state_accessor(
            request,
            thread_id=thread_id,
            checkpoint_id=body.before,
        )
    except _CHECKPOINT_MODE_ERRORS as exc:
        raise _checkpoint_mode_http_error(exc, thread_id) from exc

    entries: list[HistoryEntry] = []
    is_latest_checkpoint = True
    try:
        snapshots = await accessor.ahistory(config, limit=body.limit)
        for snapshot in snapshots:
            snapshot_config = snapshot.config or {}
            parent_config = snapshot.parent_config or {}
            metadata = snapshot.metadata or {}
            materialized_values = snapshot.values if isinstance(snapshot.values, dict) else {}

            checkpoint_id = snapshot_config.get("configurable", {}).get("checkpoint_id", "")
            parent_id = parent_config.get("configurable", {}).get("checkpoint_id")

            values: dict[str, Any] = {}
            if title := materialized_values.get("title"):
                values["title"] = title
            if thread_data := materialized_values.get("thread_data"):
                values["thread_data"] = thread_data

            if is_latest_checkpoint:
                messages = materialized_values.get("messages")
                if messages:
                    serialized_msgs = serialize_channel_values_for_api({"messages": messages}).get("messages", [])
                    try:
                        # Human messages define turn boundaries. New checkpoints
                        # carry the completed turns' durations in metadata, so the
                        # messages channel stays unchanged.
                        checkpoint_run_durations = _checkpoint_run_durations(metadata)
                        current_turn_run_id = None
                        for msg in serialized_msgs:
                            if msg.get("type") == "human":
                                additional_kwargs = msg.get("additional_kwargs")
                                if isinstance(additional_kwargs, dict):
                                    run_id = additional_kwargs.get("run_id")
                                    if isinstance(run_id, str) and run_id:
                                        current_turn_run_id = run_id
                                continue

                            if msg.get("type") not in {"ai", "tool"} or not current_turn_run_id:
                                continue

                            msg.setdefault("run_id", current_turn_run_id)
                            _set_message_turn_duration(msg, current_turn_run_id, checkpoint_run_durations)

                        # Legacy checkpoints without duration metadata are
                        # correlated once via event-store + run-manager, then
                        # upgraded by a metadata-only checkpoint write.
                        if any(_ai_message_lacks_duration(msg) for msg in serialized_msgs):
                            from app.gateway.deps import get_run_event_store, get_run_manager
                            from app.gateway.routers.thread_runs import compute_run_durations
                            from deerflow.runtime.runs.worker import persist_run_durations

                            run_mgr = get_run_manager(request)
                            event_store = get_run_event_store(request)

                            runs = await run_mgr.list_by_thread(thread_id)
                            events = await event_store.list_messages(thread_id, limit=1000)

                            if runs:
                                run_durations = compute_run_durations(runs)
                                msg_to_run = {}
                                for event in events:
                                    content = event.get("content", {})
                                    run_id = event.get("run_id")
                                    if isinstance(content, dict) and content.get("type") == "ai" and "id" in content and isinstance(run_id, str) and run_id:
                                        msg_to_run[content["id"]] = run_id

                                current_turn_run_id = None
                                for msg in serialized_msgs:
                                    if msg.get("type") == "human":
                                        additional_kwargs = msg.get("additional_kwargs")
                                        if isinstance(additional_kwargs, dict):
                                            run_id = additional_kwargs.get("run_id")
                                            if isinstance(run_id, str) and run_id:
                                                current_turn_run_id = run_id
                                        continue

                                    if msg.get("type") not in {"ai", "tool"}:
                                        continue
                                    run_id = msg_to_run.get(msg.get("id")) or current_turn_run_id
                                    if run_id:
                                        msg["run_id"] = run_id
                                        _set_message_turn_duration(msg, run_id, run_durations)

                                # Intentional, best-effort write-on-read migration:
                                # persist legacy metadata after the response so the
                                # history request never waits on an active stream's
                                # same-thread checkpoint lock.
                                background_tasks.add_task(
                                    persist_run_durations,
                                    checkpointer=checkpointer,
                                    thread_id=thread_id,
                                    durations=run_durations,
                                )

                    except Exception:
                        logger.warning("Failed to inject turn_duration for thread %s", thread_id, exc_info=True)

                    values["messages"] = serialized_msgs

            is_latest_checkpoint = False

            next_tasks = list(snapshot.next or ())

            # Strip LangGraph internal keys from metadata
            user_meta = {k: v for k, v in metadata.items() if k not in ("created_at", "updated_at", "step", "source", "writes", "parents", "run_durations")}
            # Keep step for ordering context
            if "step" in metadata:
                user_meta["step"] = metadata["step"]

            entries.append(
                HistoryEntry(
                    checkpoint_id=checkpoint_id,
                    parent_checkpoint_id=parent_id,
                    metadata=user_meta,
                    values=values,
                    created_at=coerce_iso(snapshot.created_at or metadata.get("created_at", "")),
                    next=next_tasks,
                )
            )
    except _CHECKPOINT_MODE_ERRORS as exc:
        raise _checkpoint_mode_http_error(exc, thread_id) from exc
    except Exception:
        logger.exception("Failed to get history for thread %s", sanitize_log_param(thread_id))
        raise HTTPException(status_code=500, detail="Failed to get thread history")

    return entries
