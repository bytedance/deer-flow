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
import re
import time
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from app.gateway.authz import require_permission
from app.gateway.deps import get_checkpointer, get_current_user, get_feedback_repo, get_run_event_store
from app.gateway.utils import sanitize_log_param
from deerflow.config.paths import Paths, get_paths
from deerflow.runtime import serialize_channel_values

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/threads", tags=["threads"])


# Metadata keys that the server controls; clients are not allowed to set
# them. Pydantic ``@field_validator("metadata")`` strips them on every
# inbound model below so a malicious client cannot reflect a forged
# owner identity through the API surface. Defense-in-depth — the
# row-level invariant is still ``threads_meta.user_id`` populated from
# the auth contextvar; this list closes the metadata-blob echo gap.
_SERVER_RESERVED_METADATA_KEYS: frozenset[str] = frozenset({"owner_id", "user_id"})


def _strip_reserved_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Return ``metadata`` with server-controlled keys removed."""
    if not metadata:
        return metadata or {}
    return {k: v for k, v in metadata.items() if k not in _SERVER_RESERVED_METADATA_KEYS}


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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _delete_thread_data(thread_id: str, paths: Paths | None = None) -> ThreadDeleteResponse:
    """Delete local persisted filesystem data for a thread."""
    path_manager = paths or get_paths()
    try:
        path_manager.delete_thread_dir(thread_id)
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
    response = _delete_thread_data(thread_id)

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
    now = time.time()
    # ``body.metadata`` is already stripped of server-reserved keys by
    # ``ThreadCreateRequest._strip_reserved`` — see the model definition.

    # Idempotency: return existing record when already present
    existing_record = await thread_store.get(thread_id)
    if existing_record is not None:
        return ThreadResponse(
            thread_id=thread_id,
            status=existing_record.get("status", "idle"),
            created_at=str(existing_record.get("created_at", "")),
            updated_at=str(existing_record.get("updated_at", "")),
            metadata=existing_record.get("metadata", {}),
        )

    # Write thread_meta so the thread appears in /threads/search immediately
    try:
        await thread_store.create(
            thread_id,
            assistant_id=getattr(body, "assistant_id", None),
            metadata=body.metadata,
        )
    except Exception:
        logger.exception("Failed to write thread_meta for %s", sanitize_log_param(thread_id))
        raise HTTPException(status_code=500, detail="Failed to create thread")

    # Write an empty checkpoint so state endpoints work immediately
    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    try:
        from langgraph.checkpoint.base import empty_checkpoint

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
        created_at=str(now),
        updated_at=str(now),
        metadata=body.metadata,
    )


@router.post("/search", response_model=list[ThreadResponse])
async def search_threads(body: ThreadSearchRequest, request: Request) -> list[ThreadResponse]:
    """Search and list threads.

    Delegates to the configured ThreadMetaStore implementation
    (SQL-backed for sqlite/postgres, Store-backed for memory mode).
    """
    from app.gateway.deps import get_thread_store

    repo = get_thread_store(request)
    rows = await repo.search(
        metadata=body.metadata or None,
        status=body.status,
        limit=body.limit,
        offset=body.offset,
    )
    return [
        ThreadResponse(
            thread_id=r["thread_id"],
            status=r.get("status", "idle"),
            created_at=r.get("created_at", ""),
            updated_at=r.get("updated_at", ""),
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
        created_at=str(record.get("created_at", "")),
        updated_at=str(record.get("updated_at", "")),
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
            "created_at": ckpt_meta.get("created_at", ""),
            "updated_at": ckpt_meta.get("updated_at", ckpt_meta.get("created_at", "")),
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
        created_at=str(record.get("created_at", "")),
        updated_at=str(record.get("updated_at", "")),
        metadata=record.get("metadata", {}),
        values=serialize_channel_values(channel_values),
    )


# ---------------------------------------------------------------------------
# Event-store-backed message loader
# ---------------------------------------------------------------------------

_LEGACY_CMD_INNER_CONTENT_RE = re.compile(
    r"ToolMessage\(content=(?P<q>['\"])(?P<inner>.*?)(?P=q)",
    re.DOTALL,
)


def _sanitize_legacy_command_repr(content_field: Any) -> Any:
    """Recover the inner ToolMessage text from a legacy ``str(Command(...))`` repr.

    Runs captured before the ``on_tool_end`` fix in ``journal.py`` stored
    ``str(Command(update={'messages':[ToolMessage(content='X', ...)]}))`` as the
    tool_result content. New runs store ``'X'`` directly. For legacy rows, try
    to extract ``'X'`` defensively; return the original string if extraction
    fails (still no worse than the checkpoint fallback for summarized threads).
    """
    if not isinstance(content_field, str) or not content_field.startswith("Command(update="):
        return content_field
    match = _LEGACY_CMD_INNER_CONTENT_RE.search(content_field)
    return match.group("inner") if match else content_field


async def _get_event_store_messages(request: Request, thread_id: str) -> list[dict] | None:
    """Load the full message stream for ``thread_id`` from the event store.

    The event store is append-only and unaffected by summarization — the
    checkpoint's ``channel_values["messages"]`` is rewritten in-place when the
    SummarizationMiddleware runs, which drops all pre-summarize messages. The
    event store retains the full transcript, so callers in Gateway mode should
    prefer it for rendering the conversation history.

    In addition to the core message content, this helper attaches two extra
    fields to every returned dict:

    - ``run_id``: the ``run_id`` of the event that produced this message.
      Always present.
    - ``feedback``: thumbs-up/down data. Present only on the **final
      ``ai_message`` of each run** (matching the per-run feedback semantics
      of ``POST /api/threads/{id}/runs/{run_id}/feedback``). The frontend uses
      the presence of this field to decide whether to render the feedback
      button, which sidesteps the positional-index mapping bug that an
      out-of-band ``/messages`` fetch exhibited.

    Behaviour contract:

    - **Full pagination.** ``RunEventStore.list_messages`` returns the newest
      ``limit`` records when no cursor is given, so a fixed limit silently
      drops older messages on long threads. We size the read from
      ``count_messages()`` and then page forward with ``after_seq`` cursors.
    - **Copy-on-read.** Each content dict is copied before ``id`` is patched
      so the live store object is never mutated; ``MemoryRunEventStore``
      returns live references.
    - **Stable ids.** Messages with ``id=None`` (human + tool_result) receive
      a deterministic ``uuid5(NAMESPACE_URL, f"{thread_id}:{seq}")`` so React
      keys are stable across requests without altering stored data. AI messages
      retain their LLM-assigned ``lc_run--*`` ids.
    - **Legacy Command repr.** Rows captured before the ``journal.py``
      ``on_tool_end`` fix stored ``str(Command(update={...}))`` as the tool
      result content. ``_sanitize_legacy_command_repr`` extracts the inner
      ToolMessage text.
    - **User context.** ``DbRunEventStore`` is user-scoped by default via
      ``resolve_user_id(AUTO)`` in ``runtime/user_context.py``. This helper
      must run inside a request where ``@require_permission`` has populated
      the user contextvar. Both callers below are decorated appropriately.
      Do not call this helper from CLI or migration scripts without passing
      ``user_id=None`` explicitly to the underlying store methods.

    Returns ``None`` when the event store is not configured or has no message
    events for this thread, so callers fall back to checkpoint messages.
    """
    try:
        event_store = get_run_event_store(request)
    except Exception:
        return None

    try:
        total = await event_store.count_messages(thread_id)
    except Exception:
        logger.exception("count_messages failed for thread %s", sanitize_log_param(thread_id))
        return None
    if not total:
        return None

    # Batch by page_size to keep memory bounded for very long threads.
    page_size = 500
    collected: list[dict] = []
    after_seq: int | None = None
    while True:
        try:
            page = await event_store.list_messages(thread_id, limit=page_size, after_seq=after_seq)
        except Exception:
            logger.exception("list_messages failed for thread %s", sanitize_log_param(thread_id))
            return None
        if not page:
            break
        collected.extend(page)
        if len(page) < page_size:
            break
        next_cursor = page[-1].get("seq")
        if next_cursor is None or (after_seq is not None and next_cursor <= after_seq):
            break
        after_seq = next_cursor

    # Build the message list; track the final ``ai_message`` index per run so
    # feedback can be attached at the right position (matches thread_runs.py).
    messages: list[dict] = []
    last_ai_per_run: dict[str, int] = {}
    for evt in collected:
        raw = evt.get("content")
        if not isinstance(raw, dict) or "type" not in raw:
            continue
        content = dict(raw)
        if content.get("id") is None:
            content["id"] = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{thread_id}:{evt['seq']}"))
        if content.get("type") == "tool":
            content["content"] = _sanitize_legacy_command_repr(content.get("content"))
        run_id = evt.get("run_id")
        if run_id:
            content["run_id"] = run_id
        if evt.get("event_type") == "ai_message" and run_id:
            last_ai_per_run[run_id] = len(messages)
        messages.append(content)

    if not messages:
        return None

    # Attach feedback to the final ai_message of each run. If the feedback
    # subsystem is unavailable, leave the ``feedback`` field absent entirely
    # so the frontend hides the button rather than showing it over a broken
    # write path.
    feedback_available = False
    feedback_map: dict[str, dict] = {}
    try:
        feedback_repo = get_feedback_repo(request)
        user_id = await get_current_user(request)
        feedback_map = await feedback_repo.list_by_thread_grouped(thread_id, user_id=user_id)
        feedback_available = True
    except Exception:
        logger.exception("feedback lookup failed for thread %s", sanitize_log_param(thread_id))

    if feedback_available:
        for run_id, idx in last_ai_per_run.items():
            fb = feedback_map.get(run_id)
            messages[idx]["feedback"] = (
                {
                    "feedback_id": fb["feedback_id"],
                    "rating": fb["rating"],
                    "comment": fb.get("comment"),
                }
                if fb
                else None
            )

    return messages


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

    values = serialize_channel_values(channel_values)

    # Prefer event-store messages: append-only, immune to summarization.
    es_messages = await _get_event_store_messages(request, thread_id)
    if es_messages is not None:
        values["messages"] = es_messages

    return ThreadStateResponse(
        values=values,
        next=next_tasks,
        metadata=metadata,
        checkpoint={"id": checkpoint_id, "ts": str(metadata.get("created_at", ""))},
        checkpoint_id=checkpoint_id,
        parent_checkpoint_id=parent_checkpoint_id,
        created_at=str(metadata.get("created_at", "")),
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
    metadata["updated_at"] = time.time()

    if body.as_node:
        metadata["source"] = "update"
        metadata["step"] = metadata.get("step", 0) + 1
        metadata["writes"] = {body.as_node: body.values}

    # aput requires checkpoint_ns in the config — use the same config used for the
    # read (which always includes checkpoint_ns="").  Do NOT include checkpoint_id
    # so that aput generates a fresh checkpoint ID for the new snapshot.
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
    if body.values and "title" in body.values:
        new_title = body.values["title"]
        if new_title:  # Skip empty strings and None
            try:
                await thread_store.update_display_name(thread_id, new_title)
            except Exception:
                logger.debug("Failed to sync title to thread_meta for %s (non-fatal)", sanitize_log_param(thread_id))

    return ThreadStateResponse(
        values=serialize_channel_values(channel_values),
        next=[],
        metadata=metadata,
        checkpoint_id=new_checkpoint_id,
        created_at=str(metadata.get("created_at", "")),
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

    # Load the full event-store message stream once; attach to the latest
    # checkpoint entry only (matching the prior semantics). The event store
    # is append-only and immune to summarization.
    es_messages = await _get_event_store_messages(request, thread_id)

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

            # Attach messages only to the latest checkpoint. Prefer the
            # event-store stream (complete and unaffected by summarization);
            # fall back to checkpoint channel_values when the event store is
            # unavailable or empty.
            if is_latest_checkpoint:
                if es_messages is not None:
                    values["messages"] = es_messages
                else:
                    messages = channel_values.get("messages")
                    if messages:
                        values["messages"] = serialize_channel_values({"messages": messages}).get("messages", [])
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
                    created_at=str(metadata.get("created_at", "")),
                    next=next_tasks,
                )
            )
    except Exception:
        logger.exception("Failed to get history for thread %s", sanitize_log_param(thread_id))
        raise HTTPException(status_code=500, detail="Failed to get thread history")

    return entries
