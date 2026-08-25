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
from app.gateway.checkpoint_lineage import (
    CheckpointLineageError,
    CheckpointParentMissingError,
    find_checkpoint_before_message,
    find_checkpoint_before_message_chronologically,
    is_duration_only_checkpoint,
)
from app.gateway.deps import get_checkpointer, get_run_event_store, get_run_manager
from app.gateway.internal_auth import get_trusted_internal_owner_user_id
from app.gateway.services import (
    build_checkpoint_state_accessor,
    build_checkpoint_state_mutation_accessor,
    build_thread_checkpoint_state_accessor,
    build_thread_checkpoint_state_mutation_accessor,
    reserve_checkpoint_write,
    strip_server_owned_state_metadata,
)
from app.gateway.utils import sanitize_log_param
from deerflow.agents.thread_state import THREAD_STATE_REDUCER_FIELDS
from deerflow.config.paths import Paths, get_paths
from deerflow.config.summarization_config import ContextSize
from deerflow.persistence.thread_meta import THREAD_PINNED_METADATA_KEY
from deerflow.runtime import ThreadOperationKind, serialize_channel_values_for_api
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
from deerflow.runtime.journal import build_branch_history_seed_events
from deerflow.runtime.runs.manager import ConflictError
from deerflow.runtime.runs.worker import RUN_MESSAGE_IDS_METADATA_KEY, valid_duration_entry, valid_run_message_id_entry
from deerflow.runtime.secret_context import redact_metadata_secrets
from deerflow.runtime.user_context import get_effective_user_id
from deerflow.utils.file_io import run_file_io
from deerflow.utils.thread_id import ThreadId, resolve_thread_id, validate_thread_id
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
_BRANCH_TITLE_SEQUENCE_METADATA_KEY = "branch_title_sequence"
# Thread-scoped runtime channels a branch must NOT inherit from its parent:
# ``sandbox.sandbox_id`` binds path mappings and the release lifecycle to the
# *parent* thread, so copying it would make the branch read/write the parent's
# workspace (bypassing the per-branch user-data clone) and release the
# parent's sandbox after its first run; the branch lazily acquires its own
# sandbox keyed by its own thread_id instead. ``thread_data`` is recomputed
# from the branch's thread_id by ThreadDataMiddleware on every run.
_BRANCH_EXCLUDED_CHANNELS = frozenset({"sandbox", "thread_data"})
_BRANCH_HISTORY_SCAN_LIMIT = 200
_BRANCH_HISTORY_RAW_SCAN_LIMIT = _BRANCH_HISTORY_SCAN_LIMIT * 2
_BRANCH_TITLE_MAX_LENGTH = 256
_BRANCH_TITLE_SEQUENCE_MAX = 9_007_199_254_740_991
_BRANCH_SIBLING_PAGE_SIZE = 100


def _strip_reserved_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Return ``metadata`` with server-controlled keys removed."""
    if not metadata:
        return metadata or {}
    return {k: v for k, v in metadata.items() if k not in _SERVER_RESERVED_METADATA_KEYS}


def _is_pin_metadata_patch(metadata: dict[str, Any]) -> bool:
    """Return True for the narrow pin/unpin PATCH shape."""
    return set(metadata) == {THREAD_PINNED_METADATA_KEY} and isinstance(metadata.get(THREAD_PINNED_METADATA_KEY), bool)


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


def _branch_target_human_message(messages: list[Any], target_message_ids: set[str]) -> Any | None:
    index_by_id = {_message_id(message): index for index, message in enumerate(messages) if _message_id(message)}
    if not target_message_ids.issubset(index_by_id.keys()):
        return None
    target_start_index = min(index_by_id[message_id] for message_id in target_message_ids)
    return next(
        (message for message in reversed(messages[:target_start_index]) if _message_type(message) == "human" and _is_branch_visible_message(message)),
        None,
    )


async def _find_branch_checkpoint(
    accessor: Any,
    config: dict[str, Any],
    target_message_ids: set[str],
) -> Any:
    try:
        for snapshot in await accessor.ahistory(config, limit=_BRANCH_HISTORY_RAW_SCAN_LIMIT):
            if is_duration_only_checkpoint(snapshot):
                continue
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
        for snapshot in await accessor.ahistory(config, limit=_BRANCH_HISTORY_RAW_SCAN_LIMIT):
            if is_duration_only_checkpoint(snapshot):
                continue
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


async def _find_branch_replay_base(
    accessor: Any,
    config: dict[str, Any],
    snapshot: Any,
    target_human_id: str,
) -> Any | None:
    """Resolve a replay base while preserving unlinked legacy histories."""

    try:
        return await find_checkpoint_before_message(
            accessor,
            snapshot,
            target_human_id,
            max_depth=_BRANCH_HISTORY_RAW_SCAN_LIMIT,
        )
    except CheckpointParentMissingError:
        thread_id = config.get("configurable", {}).get("thread_id", "")
        logger.debug(
            "Could not resolve parent lineage for branch thread %s; falling back to history scan",
            sanitize_log_param(thread_id),
            exc_info=True,
        )
    except CheckpointLineageError as exc:
        thread_id = config.get("configurable", {}).get("thread_id", "")
        logger.warning(
            "Rejected unsafe checkpoint lineage for branch thread %s",
            sanitize_log_param(thread_id),
            exc_info=True,
        )
        raise HTTPException(status_code=409, detail="This turn can no longer be branched from.") from exc

    try:
        history = await accessor.ahistory(config, limit=_BRANCH_HISTORY_RAW_SCAN_LIMIT)
    except _CHECKPOINT_MODE_ERRORS as exc:
        thread_id = config.get("configurable", {}).get("thread_id", "")
        raise _checkpoint_mode_http_error(exc, thread_id) from exc
    except Exception as exc:
        thread_id = config.get("configurable", {}).get("thread_id", "")
        logger.exception("Failed to scan replay checkpoint history for thread %s", sanitize_log_param(thread_id))
        raise HTTPException(status_code=500, detail="Failed to inspect checkpoint history") from exc

    replay_base, target_found = find_checkpoint_before_message_chronologically(history, target_human_id)
    if not target_found:
        logger.warning(
            "Could not locate branch user message %s in chronological history for thread %s",
            sanitize_log_param(target_human_id),
            sanitize_log_param(config.get("configurable", {}).get("thread_id", "")),
        )
    return replay_base


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


def _next_branch_title_sequence(source_sequence: Any, *, source_is_branch: bool) -> int:
    if source_is_branch and isinstance(source_sequence, int) and not isinstance(source_sequence, bool) and 2 <= source_sequence < _BRANCH_TITLE_SEQUENCE_MAX:
        return source_sequence + 1
    return 2


def _format_branch_display_name(base: str, sequence: int) -> str | None:
    suffix = f" ({sequence})"
    truncated_base = base[: _BRANCH_TITLE_MAX_LENGTH - len(suffix)].rstrip()
    return f"{truncated_base}{suffix}" if truncated_base else None


def _default_branch_title(
    source_title: Any,
    *,
    source_is_branch: bool = False,
    source_sequence: Any = None,
    sibling_records: list[dict[str, Any]] | None = None,
) -> tuple[str | None, int | None]:
    if not isinstance(source_title, str):
        return None, None

    display_name = source_title.strip()
    if source_is_branch:
        while display_name.lower().startswith("branch:"):
            display_name = display_name[len("branch:") :].strip()

    if not display_name:
        return None, None

    sequence = _next_branch_title_sequence(source_sequence, source_is_branch=source_is_branch)
    base = display_name
    if sequence > 2:
        source_suffix = f" ({sequence - 1})"
        if display_name.endswith(source_suffix):
            base = display_name[: -len(source_suffix)].rstrip()

    occupied_titles = {sibling.get("display_name") for sibling in sibling_records or [] if isinstance(sibling.get("display_name"), str)}
    display_name = _format_branch_display_name(base, sequence)
    while display_name in occupied_titles:
        if sequence >= _BRANCH_TITLE_SEQUENCE_MAX:
            return None, None
        sequence += 1
        display_name = _format_branch_display_name(base, sequence)
    return display_name, sequence if display_name is not None else None


async def _branch_sibling_records(thread_store: Any, parent_thread_id: str) -> list[dict[str, Any]]:
    siblings: list[dict[str, Any]] = []
    offset = 0
    while True:
        page = await thread_store.search(
            metadata={"branch_parent_thread_id": parent_thread_id},
            limit=_BRANCH_SIBLING_PAGE_SIZE,
            offset=offset,
        )
        siblings.extend(page)
        if len(page) < _BRANCH_SIBLING_PAGE_SIZE:
            return siblings
        offset += len(page)


# ---------------------------------------------------------------------------
# Response / request models
# ---------------------------------------------------------------------------


class ThreadDeleteResponse(BaseModel):
    """Response model for thread cleanup."""

    success: bool
    message: str


class _MetadataRedactingResponse(BaseModel):
    @field_validator("metadata", mode="before", check_fields=False)
    @classmethod
    def _redact_legacy_metadata_secret(cls, value: Any) -> Any:
        return redact_metadata_secrets(value)


class ThreadResponse(_MetadataRedactingResponse):
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

    thread_id: ThreadId | None = Field(default=None, description="Optional thread ID (auto-generated if omitted)")
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


class ThreadStateResponse(_MetadataRedactingResponse):
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
    model_name: str | None = Field(default=None, max_length=128, description="Optional model to summarize with; resolved request override -> custom-agent model -> default, mirroring run model selection")


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


class HistoryEntry(_MetadataRedactingResponse):
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
    # "seeded" | "skipped_empty" | "failed" — whether the parent history was
    # copied into the branch's run-event feed (see branch_thread).
    history_seed_mode: str


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
    run_manager = get_run_manager(request)
    try:
        async with goal_thread_lock(thread_id):
            async with run_manager.reserve_thread_operation(
                thread_id,
                kind=ThreadOperationKind.delete,
                user_id=get_effective_user_id(),
            ):
                return await _delete_thread_data_with_reservation(thread_id, request)
    except ConflictError:
        raise HTTPException(
            status_code=409,
            detail="Thread has work in flight. Delete it after the work finishes.",
        ) from None


async def _delete_thread_data_with_reservation(thread_id: str, request: Request) -> ThreadDeleteResponse:
    """Delete a thread while its durable exclusive reservation is held."""
    from app.gateway.deps import get_thread_store

    # Legacy IDs may predate the canonical filesystem-safe contract. They can
    # still be removed from metadata/checkpoint stores, but must never be
    # interpolated into a host path during cleanup.
    try:
        validate_thread_id(thread_id)
    except ValueError:
        response = ThreadDeleteResponse(
            success=True,
            message="Skipped local data cleanup for legacy thread ID",
        )
    else:
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
    thread_id = resolve_thread_id(body.thread_id)
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
async def branch_thread(thread_id: ThreadId, body: ThreadBranchRequest, request: Request) -> ThreadBranchResponse:
    """Create a new main-thread branch from a completed assistant turn."""
    try:
        async with goal_thread_lock(thread_id):
            async with get_run_manager(request).reserve_thread_operation(
                thread_id,
                kind=ThreadOperationKind.branch,
                user_id=get_effective_user_id(),
            ):
                return await _branch_thread_with_reservation(thread_id, body, request)
    except ConflictError:
        raise HTTPException(
            status_code=409,
            detail="Thread has work in flight. Branch it after the work finishes.",
        ) from None


async def _branch_thread_with_reservation(
    thread_id: ThreadId,
    body: ThreadBranchRequest,
    request: Request,
) -> ThreadBranchResponse:
    """Create a branch while holding the source thread's exclusive reservation."""
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
    target_human = _branch_target_human_message(_checkpoint_messages(snapshot), target_message_ids)
    target_human_id = _message_id(target_human)
    if not target_human_id:
        raise HTTPException(status_code=409, detail="This turn can no longer be branched from.")
    replay_base_tuple = await _find_branch_replay_base(
        source_accessor,
        source_config,
        snapshot,
        target_human_id,
    )

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

    if body.title:
        display_name = body.title
    else:
        sibling_records = await _branch_sibling_records(thread_store, thread_id)
        display_name, title_sequence = _default_branch_title(
            source_record.get("display_name"),
            source_is_branch=source_metadata.get(_BRANCH_METADATA_KEY) is True,
            source_sequence=source_metadata.get(_BRANCH_TITLE_SEQUENCE_METADATA_KEY),
            sibling_records=sibling_records,
        )
        if title_sequence is not None:
            branch_metadata[_BRANCH_TITLE_SEQUENCE_METADATA_KEY] = title_sequence
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

    def branch_values(source_snapshot: Any) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for key, value in dict(source_snapshot.values).items():
            if key in _BRANCH_EXCLUDED_CHANNELS:
                continue
            if key in branch_reducer_fields:
                values[key] = Overwrite(list(value) if key == "messages" and isinstance(value, list) else value)
            else:
                values[key] = value
        if display_name is not None:
            values["title"] = display_name
        return values

    # Stamp both synthetic checkpoints with the branch-creation time because
    # serializers fall back to metadata when snapshot.created_at is absent.
    checkpoint_metadata_updates = {
        **branch_metadata,
        "source": "branch",
        "updated_at": now,
        "created_at": now,
    }
    new_config.setdefault("metadata", {}).update(checkpoint_metadata_updates)
    try:
        head_config = new_config
        if replay_base_tuple is not None:
            head_config = await branch_accessor.aupdate(
                new_config,
                branch_values(replay_base_tuple),
                as_node="branch",
            )
            head_config.setdefault("metadata", {}).update(checkpoint_metadata_updates)
        await branch_accessor.aupdate(
            head_config,
            branch_values(snapshot),
            as_node="branch",
        )
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

    # The thread feed (GET /messages, /messages/page) reads the run-event
    # store, not checkpoints, and a fresh branch has no run_events — so the
    # inherited history would vanish from the UI as soon as the branch's
    # first run refreshes the feed (#4380 problem 2). Seed the branch's
    # run_events from the same checkpoint snapshot the branch was created
    # from. Best-effort: on failure the branch stays usable, with history
    # visible only through the checkpoint overlay until it is re-branched.
    try:
        seed_events = build_branch_history_seed_events(
            _checkpoint_messages(snapshot),
            thread_id=new_thread_id,
            run_id_prefix=f"branch-seed-{new_thread_id}",
            parent_thread_id=thread_id,
        )
        if seed_events:
            await get_run_event_store(request).put_batch(seed_events)
            history_seed_mode = "seeded"
        else:
            history_seed_mode = "skipped_empty"
    except Exception:
        logger.exception("Failed to seed branch history run-events for thread %s", sanitize_log_param(new_thread_id))
        history_seed_mode = "failed"

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
        history_seed_mode=history_seed_mode,
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
async def patch_thread(thread_id: ThreadId, body: ThreadPatchRequest, request: Request) -> ThreadResponse:
    """Merge metadata into a thread record."""
    from app.gateway.deps import get_thread_store

    thread_store = get_thread_store(request)
    record = await thread_store.get(thread_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")

    # ``body.metadata`` already stripped by ``ThreadPatchRequest._strip_reserved``.
    # Pin/unpin is not conversation activity, so it must not bump ``updated_at``.
    # Other metadata PATCH callers keep the public endpoint's existing recency
    # contract unless they get their own explicit no-touch API surface.
    touch = not _is_pin_metadata_patch(body.metadata)
    try:
        await thread_store.update_metadata(thread_id, body.metadata, touch=touch)
    except Exception:
        logger.exception("Failed to patch thread %s", sanitize_log_param(thread_id))
        raise HTTPException(status_code=500, detail="Failed to update thread")

    # Re-read to get the merged metadata and the store's timestamp decision.
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
async def get_thread(thread_id: ThreadId, request: Request) -> ThreadResponse:
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
async def get_thread_goal(thread_id: ThreadId, request: Request) -> ThreadGoalResponse:
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
async def set_thread_goal(thread_id: ThreadId, body: ThreadGoalRequest, request: Request) -> ThreadGoalResponse:
    """Set or replace the active goal for a thread.

    ``/chats/new`` pages already hold a generated UUID before the first run, so
    this endpoint creates the missing thread checkpoint on demand.
    """
    checkpointer = get_checkpointer(request)
    try:
        goal = build_goal_state(body.objective, max_continuations=body.max_continuations)
        async with reserve_checkpoint_write(request, thread_id, user_id=get_effective_user_id()):
            await _ensure_thread_for_goal(thread_id, request)
            await write_thread_goal(checkpointer, thread_id, goal, as_node="goal", create_if_missing=True)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ConflictError:
        raise HTTPException(status_code=409, detail="Thread has a run in flight. Set the goal after the run finishes.") from None
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to set goal for thread %s", sanitize_log_param(thread_id))
        raise HTTPException(status_code=500, detail="Failed to set thread goal") from None
    return ThreadGoalResponse(goal=goal)


@router.delete("/{thread_id}/goal", response_model=ThreadGoalResponse)
@require_permission("threads", "write", owner_check=True)
async def clear_thread_goal(thread_id: ThreadId, request: Request) -> ThreadGoalResponse:
    """Clear the active goal for a thread."""
    checkpointer = get_checkpointer(request)
    try:
        async with reserve_checkpoint_write(request, thread_id, user_id=get_effective_user_id()):
            await write_thread_goal(checkpointer, thread_id, None, as_node="goal")
    except ConflictError:
        raise HTTPException(status_code=409, detail="Thread has a run in flight. Clear the goal after the run finishes.") from None
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
async def compact_thread(thread_id: ThreadId, body: ThreadCompactRequest, request: Request) -> ThreadCompactResponse:
    """Manually summarize old thread context while preserving the visible history."""
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
        async with reserve_checkpoint_write(request, thread_id, user_id=get_effective_user_id()):
            result = await compact_thread_context(
                accessor,
                thread_id,
                keep=keep,
                force=body.force,
                user_id=get_effective_user_id(),
                agent_name=body.agent_name,
                model_name=body.model_name,
            )
    except ConflictError:
        raise HTTPException(status_code=409, detail="Thread has a run in flight. Compact after the run finishes.") from None
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
async def get_thread_state(thread_id: ThreadId, request: Request) -> ThreadStateResponse:
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
async def update_thread_state(thread_id: ThreadId, body: ThreadStateUpdateRequest, request: Request) -> ThreadStateResponse:
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
    # These values go straight into a checkpoint, so they need the same
    # server-owned-metadata stripping the run path gets inside normalize_input.
    # Without it an authenticated client can persist forged provenance and
    # transform trails, which later readers are entitled to treat as facts
    # about what the host itself did.
    values = strip_server_owned_state_metadata(dict(body.values or {}))
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
        async with reserve_checkpoint_write(request, thread_id, user_id=get_effective_user_id()):
            updated_config = await accessor.aupdate(
                read_config,
                updates,
                as_node=mutation_node,
            )
            snapshot = await accessor.aget(updated_config)
    except ConflictError:
        raise HTTPException(status_code=409, detail="Thread has a run in flight. Update state after the run finishes.") from None
    except _CHECKPOINT_MODE_ERRORS as exc:
        raise _checkpoint_mode_http_error(exc, thread_id) from exc
    except Exception:
        logger.exception("Failed to update state for thread %s", sanitize_log_param(thread_id))
        raise HTTPException(status_code=500, detail="Failed to update thread state")

    if thread_store and body.values and "title" in body.values:
        new_title = body.values["title"]
        if new_title:
            try:
                await thread_store.update_display_name(
                    thread_id,
                    new_title,
                    remove_metadata_keys=(_BRANCH_TITLE_SEQUENCE_METADATA_KEY,),
                )
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


def _checkpoint_run_durations(metadata: Any) -> dict[str, int]:
    raw_durations = metadata.get("run_durations") if isinstance(metadata, dict) else None
    if not isinstance(raw_durations, dict):
        return {}
    return {run_id: duration_seconds for run_id, duration_seconds in raw_durations.items() if valid_duration_entry(run_id, duration_seconds)}


def _checkpoint_run_message_ids(metadata: Any) -> dict[str, str]:
    raw_message_run_ids = metadata.get(RUN_MESSAGE_IDS_METADATA_KEY) if isinstance(metadata, dict) else None
    if not isinstance(raw_message_run_ids, dict):
        return {}
    return {message_id: run_id for message_id, run_id in raw_message_run_ids.items() if valid_run_message_id_entry(message_id, run_id)}


async def _load_run_durations(
    *,
    run_manager: Any,
    thread_id: str,
    user_id: str | None,
    run_ids: set[str],
) -> dict[str, int]:
    """Batch-hydrate the requested runs and compute their latest durations."""
    if not run_ids:
        return {}

    from app.gateway.routers.thread_runs import compute_run_durations

    runs = await run_manager.list_by_thread(
        thread_id,
        user_id=user_id,
        limit=max(100, len(run_ids)),
    )
    known_run_ids = {run.run_id for run in runs}
    for run_id in sorted(run_ids - known_run_ids):
        run = await run_manager.get(run_id, user_id=user_id)
        if run is not None:
            runs.append(run)
            known_run_ids.add(run_id)

    computed_durations = compute_run_durations(runs)
    return {run_id: duration for run_id, duration in computed_durations.items() if run_id in run_ids}


async def _persist_run_history_metadata_background(
    *,
    request: Request,
    checkpointer: Any,
    thread_id: str,
    user_id: str | None,
    duration_run_ids: set[str],
    message_run_ids: dict[str, str],
    audited_message_ids: set[str],
) -> None:
    """Best-effort history migration behind durable checkpoint admission."""
    from deerflow.runtime.runs.worker import persist_run_history_metadata

    try:
        async with reserve_checkpoint_write(request, thread_id, user_id=user_id):
            from app.gateway.deps import get_run_event_store, get_run_manager

            authoritative_message_run_ids = dict(message_run_ids)
            authoritative_duration_run_ids = set(duration_run_ids)
            if audited_message_ids:
                exact_after_admission = await get_run_event_store(request).find_latest_ai_message_run_ids(
                    thread_id,
                    audited_message_ids,
                    user_id=user_id,
                )
                for message_id in audited_message_ids:
                    exact_run_id = exact_after_admission.get(message_id)
                    if valid_run_message_id_entry(message_id, exact_run_id):
                        if authoritative_message_run_ids.get(message_id) != exact_run_id:
                            authoritative_duration_run_ids.add(exact_run_id)
                        authoritative_message_run_ids[message_id] = exact_run_id

            authoritative_durations = await _load_run_durations(
                run_manager=get_run_manager(request),
                thread_id=thread_id,
                user_id=user_id,
                run_ids=authoritative_duration_run_ids,
            )

            await persist_run_history_metadata(
                checkpointer=checkpointer,
                thread_id=thread_id,
                durations=authoritative_durations,
                message_run_ids=authoritative_message_run_ids,
            )
    except ConflictError:
        # A live run or another checkpoint writer owns the thread. The mapping
        # is a read-through optimization, so the next history request can retry
        # instead of racing a user-visible state mutation.
        logger.debug("Skipped run-history metadata migration for busy thread %s", sanitize_log_param(thread_id))
    except Exception:
        logger.warning("Failed to persist run-history metadata for thread %s", sanitize_log_param(thread_id), exc_info=True)


@router.post("/{thread_id}/history", response_model=list[HistoryEntry])
@require_permission("threads", "read", owner_check=True)
async def get_thread_history(
    thread_id: ThreadId,
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
                        from app.gateway.routers.thread_runs import stamp_turn_duration_on_last_ai

                        # Human messages define turn boundaries. New checkpoints
                        # carry the completed turns' durations in metadata, so the
                        # messages channel stays unchanged.
                        checkpoint_run_durations = _checkpoint_run_durations(metadata)
                        checkpoint_run_message_ids = _checkpoint_run_message_ids(metadata)
                        current_turn_run_id = None
                        turn_run_ids: set[str] = set()
                        legacy_ai_message_ids: set[str] = set()
                        for msg in serialized_msgs:
                            if msg.get("type") == "human":
                                additional_kwargs = msg.get("additional_kwargs")
                                if isinstance(additional_kwargs, dict):
                                    run_id = additional_kwargs.get("run_id")
                                    if isinstance(run_id, str) and run_id:
                                        current_turn_run_id = run_id
                                continue

                            message_type = msg.get("type")
                            if message_type not in {"ai", "tool"}:
                                continue

                            if message_type == "ai":
                                message_id = msg.get("id")
                                persisted_run_id = checkpoint_run_message_ids.get(message_id) if isinstance(message_id, str) else None
                                if persisted_run_id:
                                    msg["run_id"] = persisted_run_id
                                elif not isinstance(msg.get("run_id"), str) or not msg.get("run_id"):
                                    if current_turn_run_id:
                                        msg["run_id"] = current_turn_run_id
                                    if isinstance(message_id, str) and message_id:
                                        legacy_ai_message_ids.add(message_id)

                                run_id = msg.get("run_id")
                                if isinstance(run_id, str) and run_id:
                                    turn_run_ids.add(run_id)
                            elif current_turn_run_id:
                                msg.setdefault("run_id", current_turn_run_id)

                        # Runs referenced by this checkpoint's AI messages but
                        # absent from duration metadata are either legacy
                        # (never migrated) or just completed. Exact attribution
                        # has its own completeness condition: duration-only
                        # checkpoints written before #4949 still need their AI
                        # IDs correlated and persisted. Correlate once via the
                        # event store, then hydrate only the run rows whose
                        # durations are actually required.
                        resolved_run_durations = dict(checkpoint_run_durations)
                        missing_run_ids = turn_run_ids - set(checkpoint_run_durations)
                        if missing_run_ids or legacy_ai_message_ids:
                            from app.gateway.deps import get_run_event_store, get_run_manager

                            run_mgr = get_run_manager(request)
                            event_store = get_run_event_store(request)
                            user_id = get_effective_user_id()
                            ai_message_ids = set(legacy_ai_message_ids)
                            try:
                                msg_to_run = (
                                    await event_store.find_latest_ai_message_run_ids(
                                        thread_id,
                                        ai_message_ids,
                                        user_id=user_id,
                                    )
                                    if ai_message_ids
                                    else {}
                                )
                            except Exception:
                                # A failed exact lookup must not masquerade as a
                                # successful boundary attribution. Removing the
                                # synthesized ids leaves the response incomplete
                                # rather than deterministically wrong. Durations
                                # backed by persisted mappings remain provable
                                # and should still survive this degraded path.
                                for msg in serialized_msgs:
                                    if msg.get("type") == "ai" and msg.get("id") in ai_message_ids:
                                        msg.pop("run_id", None)
                                stamp_turn_duration_on_last_ai(
                                    serialized_msgs,
                                    checkpoint_run_durations,
                                )
                                raise

                            for msg in serialized_msgs:
                                if msg.get("type") != "ai":
                                    continue
                                exact_run_id = msg_to_run.get(msg.get("id"))
                                if exact_run_id:
                                    msg["run_id"] = exact_run_id

                            # Cache the complete audited attribution, including
                            # boundary fallbacks for IDs with no event. Without
                            # those negative-result entries, every history read
                            # would rescan the same pre-event-store prefix.
                            message_run_ids_to_persist = {
                                message_id: run_id
                                for msg in serialized_msgs
                                if msg.get("type") == "ai" and isinstance((message_id := msg.get("id")), str) and message_id in ai_message_ids and isinstance((run_id := msg.get("run_id")), str) and run_id
                            }
                            required_run_ids = {run_id for msg in serialized_msgs if msg.get("type") == "ai" and isinstance((run_id := msg.get("run_id")), str) and run_id and run_id not in checkpoint_run_durations}
                            run_durations = await _load_run_durations(
                                run_manager=run_mgr,
                                thread_id=thread_id,
                                user_id=user_id,
                                run_ids=required_run_ids,
                            )
                            resolved_run_durations.update(run_durations)

                            # Intentional, best-effort write-on-read migration:
                            # persist both exact attribution and duration after
                            # the response so subsequent reads stay exact without
                            # waiting on an active stream's checkpoint lock.
                            if required_run_ids or message_run_ids_to_persist:
                                background_tasks.add_task(
                                    _persist_run_history_metadata_background,
                                    request=request,
                                    checkpointer=checkpointer,
                                    thread_id=thread_id,
                                    user_id=user_id,
                                    duration_run_ids=required_run_ids,
                                    message_run_ids=message_run_ids_to_persist,
                                    audited_message_ids=ai_message_ids,
                                )

                        # Stamp only after exact attribution is final. Stamping
                        # the synthesized boundary first can leave its duration
                        # attached to a message whose run ID is later corrected.
                        stamp_turn_duration_on_last_ai(
                            serialized_msgs,
                            resolved_run_durations,
                        )

                    except Exception:
                        logger.warning("Failed to inject turn_duration for thread %s", sanitize_log_param(thread_id), exc_info=True)

                    values["messages"] = serialized_msgs

            is_latest_checkpoint = False

            next_tasks = list(snapshot.next or ())

            # Strip LangGraph internal keys from metadata
            user_meta = {k: v for k, v in metadata.items() if k not in ("created_at", "updated_at", "step", "source", "writes", "parents", "run_durations", RUN_MESSAGE_IDS_METADATA_KEY)}
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
