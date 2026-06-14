"""Partial-message persistence helpers for cancelled streaming runs.

When a streaming run is cancelled mid-response, the LLM has produced tokens
that the frontend has displayed but the backend has not persisted:

- LangGraph checkpoints only fire when a graph node completes. A cancel
  mid-token aborts before the node returns, so the partial AIMessage never
  reaches the checkpoint.
- ``RunJournal.on_llm_end`` is the only path that writes ``llm.ai.response``
  events to the ``run_events`` store. It fires when the LLM call ends; a
  mid-stream cancel skips it.

The worker therefore needs to (a) accumulate streaming ``AIMessageChunk``
objects in parallel with the SSE pipeline, and (b) on cancel, finalize the
buffer, synthesize closure ``ToolMessage`` objects for any tool_calls that
never executed, and persist the result to **both** stores. See the design
in ``docs/plans/2026-06-14-partial-stream-persistence-proposal.md``.

This module holds the pure helpers and the checkpoint-append routine. The
``RunJournal`` integration lives in
:mod:`deerflow.runtime.journal`; the worker wiring lives in
:mod:`deerflow.runtime.runs.worker`.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, ToolMessage
from langgraph.checkpoint.base import uuid6

from deerflow.agents.middlewares.dangling_tool_call_middleware import INTERRUPTED_TOOL_MESSAGE_CONTENT
from deerflow.utils.time import now_iso

if TYPE_CHECKING:
    from deerflow.runtime.journal import RunJournal

logger = logging.getLogger(__name__)

# Marker keys placed on persisted partial messages. Today only the worker
# writes them; consumers (frontend, analytics) can opt in later without a
# schema change.
PARTIAL_KWARG = "interrupted"
SYNTHETIC_KWARG = "synthetic"
PARTIAL_FINISH_REASON = "interrupted"

# Source string used in checkpoint metadata.writes so summarization / replay
# can distinguish partial inserts from regular node writes.
CHECKPOINT_WRITE_SOURCE = "partial_persist"


def closure_tool_message_id(tool_call_id: str) -> str:
    """Derive a stable id for a synthetic closure ToolMessage.

    Two stores (checkpoint + run_events) must produce the same identity so
    the frontend's ``mergeMessages`` dedup works. Deriving from
    ``tool_call_id`` makes the id deterministic per (run, tool_call).
    """
    return f"tm_interrupted_{tool_call_id}"


def is_middleware_chunk(metadata: dict | None) -> bool:
    """Return True when the stream chunk belongs to a middleware sub-call.

    LangChain tags middleware-driven model invocations with
    ``middleware:<name>`` so they can be distinguished from the lead
    agent's response. Such chunks must not be persisted as partial user-
    visible messages — they would surface inside the chat history as
    ghost replies (e.g. half-generated thread titles).
    """
    if not metadata:
        return False
    tags = metadata.get("tags") or ()
    for tag in tags:
        if isinstance(tag, str) and tag.startswith("middleware:"):
            return True
    return False


class PartialMessageAccumulator:
    """Streaming buffer that aggregates ``AIMessageChunk`` objects by id.

    Each ``feed()`` call merges the chunk into the bucket for its
    ``message_id``. The merge uses ``AIMessageChunk.__add__`` which
    correctly concatenates content, deep-merges ``additional_kwargs``
    (covering Anthropic ``thinking`` blocks and reasoning content), merges
    ``tool_call_chunks`` by index, and sums ``usage_metadata``.

    Middleware chunks (identified by ``middleware:*`` tags) are dropped
    at feed time so they never end up persisted.
    """

    def __init__(self) -> None:
        self._chunks: dict[str, AIMessageChunk] = {}

    def feed(self, chunk: Any, metadata: dict | None = None) -> None:
        """Merge an ``AIMessageChunk`` into its message bucket.

        No-op when:
        - ``chunk`` is not an ``AIMessageChunk``
        - the chunk has no stable ``id``
        - the chunk originated from a middleware sub-call
        """
        if not isinstance(chunk, AIMessageChunk):
            return
        if is_middleware_chunk(metadata):
            return
        msg_id = getattr(chunk, "id", None)
        if not msg_id:
            return
        existing = self._chunks.get(msg_id)
        if existing is None:
            self._chunks[msg_id] = chunk
            return
        try:
            self._chunks[msg_id] = existing + chunk
        except Exception:
            # Defensive: chunk merge can fail on malformed input. Replace
            # with the latest chunk rather than corrupting the buffer.
            logger.warning("Failed to merge AIMessageChunk for id=%s; replacing with latest chunk", msg_id, exc_info=True)
            self._chunks[msg_id] = chunk

    def finalize(self, *, skip_ids: Iterable[str] | None = None) -> list[AIMessage]:
        """Convert buffered chunks into persistable ``AIMessage`` objects.

        Messages whose id is in ``skip_ids`` are dropped — used to avoid
        re-emitting messages whose ``on_llm_end`` already fired and was
        recorded by the journal in a prior model turn within this run.
        """
        skip = set(skip_ids or ())
        finalized: list[AIMessage] = []
        for msg_id, chunk in self._chunks.items():
            if msg_id in skip:
                continue
            finalized.append(_chunk_to_ai_message(chunk))
        return finalized

    def is_empty(self) -> bool:
        return not self._chunks

    def clear(self) -> None:
        self._chunks.clear()

    @property
    def tracked_message_ids(self) -> set[str]:
        """AIMessage ids that have been fed (regardless of finalize/skip).

        Used by the cancel orchestrator to scope closure synthesis to
        tool_calls that belong to AIMessages **emitted in this run**.
        Without this scope, tool_calls left dangling by prior runs (or
        HITL interrupts waiting to resume) would be silently closed.
        """
        return set(self._chunks.keys())


def _chunk_to_ai_message(chunk: AIMessageChunk) -> AIMessage:
    """Materialize a merged ``AIMessageChunk`` into an ``AIMessage``.

    Hand-built rather than using ``langchain_core.messages.message_chunk_to_message``
    so we can carry through ``invalid_tool_calls`` (truncated JSON), which
    is exactly the case we need closure ToolMessages for.
    """
    return AIMessage(
        id=chunk.id,
        content=chunk.content,
        tool_calls=list(chunk.tool_calls or []),
        invalid_tool_calls=list(chunk.invalid_tool_calls or []),
        additional_kwargs=dict(chunk.additional_kwargs or {}),
        response_metadata=dict(chunk.response_metadata or {}),
        usage_metadata=chunk.usage_metadata,
        name=chunk.name,
    )


def _normalize_tool_call_ids(ai_message: AIMessage) -> None:
    """Allocate fallback ids in place for any tool_call missing one.

    Some provider adapters omit ``id`` on truncated tool_call_chunks. The
    resulting AIMessage's ``tool_calls[i].id`` would then be ``None`` and
    the closure ``ToolMessage.tool_call_id`` would have to invent a new
    id of its own — leaving the AIMessage and its closure unable to be
    matched. Writing the fallback id back onto the AIMessage's own
    tool_call dict keeps the (AIMessage, ToolMessage) pair linkable on
    the next turn (so :class:`DanglingToolCallMiddleware` does not
    re-inject an ephemeral copy).
    """
    for tc in getattr(ai_message, "tool_calls", None) or []:
        if isinstance(tc, dict) and not tc.get("id"):
            tc["id"] = f"tc_interrupted_{uuid.uuid4().hex}"
    for itc in getattr(ai_message, "invalid_tool_calls", None) or []:
        if isinstance(itc, dict) and not itc.get("id"):
            itc["id"] = f"tc_interrupted_{uuid.uuid4().hex}"


def mark_partial(ai_message: AIMessage, *, abort_action: str | None = None) -> AIMessage:
    """Return ``ai_message`` with interrupted markers set.

    The original object is mutated in place (and returned) to avoid an
    extra copy — partial messages are constructed by us and are not
    shared with other consumers. Also normalizes any missing tool_call
    ids so closure ToolMessages can reference them.
    """
    _normalize_tool_call_ids(ai_message)

    extra_kwargs = dict(ai_message.additional_kwargs or {})
    extra_kwargs[PARTIAL_KWARG] = True
    extra_kwargs["partial"] = True
    ai_message.additional_kwargs = extra_kwargs

    response_metadata = dict(ai_message.response_metadata or {})
    # Preserve a provider-supplied finish_reason if present — its absence
    # is the actual signal that the stream was cut off — otherwise stamp
    # our sentinel so downstream consumers have something to read.
    response_metadata.setdefault("finish_reason", PARTIAL_FINISH_REASON)
    if abort_action:
        response_metadata["abort_action"] = abort_action
    ai_message.response_metadata = response_metadata
    return ai_message


def find_open_tool_calls(messages: Iterable[BaseMessage]) -> list[dict]:
    """Return tool_call dicts that lack a matching ``ToolMessage``.

    Looks at the union of ``tool_calls`` and ``invalid_tool_calls`` on
    every AIMessage in ``messages``, then filters out any whose
    ``tool_call_id`` already appears on a ``ToolMessage``. The result is
    the set that needs synthetic closure.

    Tool calls with no id are skipped — they cannot be linked to a closure
    ToolMessage and silently drop out. Callers needing fallback id
    allocation should run :func:`_normalize_tool_call_ids` on the
    AIMessages first (``mark_partial`` does this for the cancel path).

    Each returned dict carries:
    - ``id``: tool_call_id (string, guaranteed non-empty)
    - ``name``: tool name (or "unknown")
    - ``args``: dict, empty when the source was invalid
    - ``invalid``: True for tool_calls that came from ``invalid_tool_calls``
    - ``error``: original parse error string (invalid case only)
    """
    messages = list(messages)
    tool_msg_ids: set[str] = set()
    for msg in messages:
        if isinstance(msg, ToolMessage) and msg.tool_call_id:
            tool_msg_ids.add(msg.tool_call_id)

    seen: set[str] = set()
    open_calls: list[dict] = []
    for msg in messages:
        if not _is_ai_message(msg):
            continue
        for tc in _iter_tool_calls(msg):
            tc_id = tc.get("id")
            if not (isinstance(tc_id, str) and tc_id):
                continue
            if tc_id in tool_msg_ids:
                continue
            if tc_id in seen:
                continue
            seen.add(tc_id)
            open_calls.append(tc)
    return open_calls


def _is_ai_message(msg: Any) -> bool:
    return isinstance(msg, AIMessage) or getattr(msg, "type", None) == "ai"


def _iter_tool_calls(ai_message: Any) -> list[dict]:
    """Yield structured + invalid tool_calls from an AIMessage.

    Mirrors ``DanglingToolCallMiddleware._message_tool_calls`` but limited
    to the fields the worker actually needs. Note: provider-only raw
    ``additional_kwargs['tool_calls']`` are intentionally NOT walked here
    because the only time we use this function is on a freshly-finalized
    partial AIMessage where ``tool_calls`` and ``invalid_tool_calls`` are
    the authoritative output of chunk merging.
    """
    result: list[dict] = []
    for tc in getattr(ai_message, "tool_calls", None) or []:
        if isinstance(tc, dict):
            result.append(dict(tc))
    for itc in getattr(ai_message, "invalid_tool_calls", None) or []:
        if not isinstance(itc, dict):
            continue
        result.append(
            {
                "id": itc.get("id"),
                "name": itc.get("name") or "unknown",
                "args": {},
                "invalid": True,
                "error": itc.get("error"),
            }
        )
    return result


def build_closure_tool_messages(open_tool_calls: Iterable[dict]) -> list[ToolMessage]:
    """Construct closure ``ToolMessage`` objects for the given open calls.

    The body is :data:`INTERRUPTED_TOOL_MESSAGE_CONTENT` for every closure:
    in the cancel context, both complete tool_calls and invalid ones (args
    JSON truncated mid-stream) share the same root cause: interruption.
    Using the canonical text keeps the user-visible message consistent with
    what :class:`DanglingToolCallMiddleware` would emit on the next turn if
    it ever had to re-patch the same gap.
    """
    messages: list[ToolMessage] = []
    for tc in open_tool_calls:
        tc_id = tc.get("id")
        if not tc_id:
            continue
        messages.append(
            ToolMessage(
                id=closure_tool_message_id(tc_id),
                content=INTERRUPTED_TOOL_MESSAGE_CONTENT,
                tool_call_id=tc_id,
                name=tc.get("name") or "unknown",
                status="error",
                additional_kwargs={
                    PARTIAL_KWARG: True,
                    SYNTHETIC_KWARG: True,
                    "reason": "tool_call_interrupted_before_execution",
                },
            )
        )
    return messages


async def append_messages_to_checkpoint(
    checkpointer: Any,
    *,
    thread_id: str,
    new_messages: list[BaseMessage],
    abort_action: str | None = None,
) -> bool:
    """Insert a new checkpoint with ``new_messages`` appended to ``messages``.

    Follows the uuid6-INSERT pattern from
    :func:`app.gateway.routers.threads.update_thread_state` — a fresh
    ``checkpoint["id"]`` is assigned so the saver writes a new row rather
    than overwriting the last completed checkpoint, preserving rollback
    and history-replay semantics.

    No-op (and returns False) when:
    - ``checkpointer`` is None
    - ``new_messages`` is empty
    - the thread has no checkpoint yet (a partial without prior state is
      meaningless — there is no run context to attach it to)
    """
    if checkpointer is None or not new_messages:
        return False

    read_config: dict[str, Any] = {
        "configurable": {
            "thread_id": thread_id,
            "checkpoint_ns": "",
        }
    }
    try:
        ckpt_tuple = await checkpointer.aget_tuple(read_config)
    except Exception:
        logger.warning("partial_persist: aget_tuple failed for thread %s", thread_id, exc_info=True)
        return False
    if ckpt_tuple is None:
        logger.debug("partial_persist: no existing checkpoint for thread %s; skipping", thread_id)
        return False

    checkpoint: dict[str, Any] = dict(getattr(ckpt_tuple, "checkpoint", {}) or {})
    metadata: dict[str, Any] = dict(getattr(ckpt_tuple, "metadata", {}) or {})
    channel_values: dict[str, Any] = dict(checkpoint.get("channel_values", {}))

    existing_messages = list(channel_values.get("messages", []) or [])
    existing_ids = {getattr(m, "id", None) for m in existing_messages if hasattr(m, "id")}
    deduped_new = [m for m in new_messages if getattr(m, "id", None) not in existing_ids]
    if not deduped_new:
        logger.debug("partial_persist: all partial messages already in checkpoint for thread %s", thread_id)
        return False

    channel_values["messages"] = existing_messages + deduped_new
    checkpoint["channel_values"] = channel_values
    checkpoint["id"] = str(uuid6())

    # Bump the ``messages`` channel version and tell the saver which channels
    # changed via ``new_versions``. Without this InMemorySaver (and the SQLite /
    # Postgres savers, which model channel storage similarly) discard the new
    # ``messages`` payload on read because they treat the channel as unchanged.
    current_versions = dict(checkpoint.get("channel_versions") or {})
    current_messages_version = current_versions.get("messages")
    try:
        next_messages_version = checkpointer.get_next_version(current_messages_version, None)
    except Exception:
        # Fallback for savers that don't expose get_next_version — use a
        # monotonically-greater string than the current one. Lexicographic
        # ordering on uuid6 satisfies the saver's "newest wins" rule.
        next_messages_version = str(uuid6())
    current_versions["messages"] = next_messages_version
    checkpoint["channel_versions"] = current_versions

    metadata["updated_at"] = now_iso()
    metadata["source"] = "update"
    metadata["step"] = metadata.get("step", 0) + 1
    metadata["writes"] = {CHECKPOINT_WRITE_SOURCE: {"messages": deduped_new}}
    if abort_action:
        metadata["abort_action"] = abort_action

    write_config: dict[str, Any] = {
        "configurable": {
            "thread_id": thread_id,
            "checkpoint_ns": "",
        }
    }
    try:
        await checkpointer.aput(write_config, checkpoint, metadata, {"messages": next_messages_version})
    except Exception:
        logger.warning("partial_persist: aput failed for thread %s", thread_id, exc_info=True)
        return False
    return True


async def _read_checkpoint_messages(checkpointer: Any, thread_id: str) -> list[BaseMessage]:
    """Read the current ``messages`` channel from the latest checkpoint.

    Returns an empty list if the thread has no checkpoint or the read
    fails — callers fall back to "treat all partial tool_calls as open"
    which is the safe default.
    """
    if checkpointer is None:
        return []
    config: dict[str, Any] = {
        "configurable": {
            "thread_id": thread_id,
            "checkpoint_ns": "",
        }
    }
    try:
        ckpt_tuple = await checkpointer.aget_tuple(config)
    except Exception:
        logger.warning("partial_persist: read checkpoint failed for thread %s", thread_id, exc_info=True)
        return []
    if ckpt_tuple is None:
        return []
    checkpoint = getattr(ckpt_tuple, "checkpoint", {}) or {}
    channel_values = checkpoint.get("channel_values", {}) or {}
    messages = channel_values.get("messages", []) or []
    return [m for m in messages if isinstance(m, BaseMessage)]


async def persist_partial_on_cancel(
    *,
    accumulator: PartialMessageAccumulator,
    journal: RunJournal | None,
    checkpointer: Any | None,
    thread_id: str,
    abort_action: str | None = None,
) -> bool:
    """Finalize the accumulator and persist partial state to both stores.

    Orchestrates the full cancel-time path:

    1. Snapshot ``accumulator.tracked_message_ids`` — every AIMessage id
       this run streamed. Used as the scope for closure synthesis so we
       never touch tool_calls owned by prior runs / pending HITL state.
    2. Finalize accumulator into ``AIMessage`` objects, skipping those
       whose id was already recorded via ``RunJournal.on_llm_end``.
    3. Mark each finalized AIMessage with interrupted markers and
       normalize missing tool_call ids in place.
    4. Read existing checkpoint messages so we can both (a) detect
       already-closed tool_calls and (b) find AIMessages from this run
       whose tool was executing when cancel landed (their id is in
       ``skip_ids`` AND in ``tracked_message_ids`` AND they appear in
       ``existing_messages`` because ``on_chain_end`` already checkpointed
       them).
    5. Compute open tool_calls in the combined view, then **scope** to
       only those owned by this-run AIMessages.
    6. Split scoped closures into two groups:
       - owned by a finalized AIMessage  → journaled via
         ``record_partial_response`` so the AIMessage + closures land
         together (consistent trace causality)
       - orphan (owner is already-recorded and lives only in
         ``existing_messages``) → journaled via
         ``record_synthetic_closures`` (no associated partial AIMessage
         — the AIMessage event already exists in ``run_events``)
    7. Append ``finalized + scoped closures`` to the checkpoint.

    Returns True iff at least one event or message was persisted. All
    failures are swallowed — partial persistence is best-effort and must
    never re-raise into the worker's cancel path.
    """
    if accumulator.is_empty():
        return False

    # Snapshot before finalize() so we still know what ids this run
    # streamed even after the accumulator is cleared later.
    this_run_ai_ids = accumulator.tracked_message_ids

    skip_ids: set[str] = set()
    if journal is not None:
        try:
            skip_ids = set(journal.recorded_ai_message_ids)
        except Exception:
            logger.debug("partial_persist: journal.recorded_ai_message_ids unavailable", exc_info=True)

    finalized = accumulator.finalize(skip_ids=skip_ids)

    # Mark + normalize ids in place BEFORE find_open_tool_calls so the
    # AIMessage's tool_call.id and the closure's tool_call_id refer to
    # the same id when the provider omitted one originally.
    for ai_msg in finalized:
        mark_partial(ai_msg, abort_action=abort_action)

    try:
        existing_messages = await _read_checkpoint_messages(checkpointer, thread_id)
    except Exception:
        logger.warning("partial_persist: read existing messages raised for thread %s", thread_id, exc_info=True)
        existing_messages = []

    # Detect open tool_calls in the combined view, then scope to only
    # tool_calls owned by AIMessages emitted in this run. Historical
    # dangling tool_calls (prior runs, HITL pending state) belong to
    # someone else; ``DanglingToolCallMiddleware`` will patch them
    # ephemerally on the next turn if needed.
    combined = list(existing_messages) + list(finalized)
    all_open = find_open_tool_calls(combined)
    this_run_owned_tc_ids: set[str] = set()
    for msg in combined:
        msg_id = getattr(msg, "id", None)
        if not (isinstance(msg_id, str) and msg_id in this_run_ai_ids):
            continue
        for tc in _iter_tool_calls(msg):
            tc_id = tc.get("id")
            if isinstance(tc_id, str) and tc_id:
                this_run_owned_tc_ids.add(tc_id)
    scoped_open_calls = [tc for tc in all_open if tc.get("id") in this_run_owned_tc_ids]
    closures = build_closure_tool_messages(scoped_open_calls)

    # Nothing to persist: accumulator had only already-recorded AIMessages
    # (their tools all completed too) — true no-op.
    if not finalized and not closures:
        accumulator.clear()
        return False

    closures_by_tool_call_id: dict[str, ToolMessage] = {c.tool_call_id: c for c in closures}

    if journal is not None:
        # 1. Closures owned by finalized AIMessages — bundle with the AIMessage.
        used_closure_ids: set[str] = set()
        for ai_msg in finalized:
            owned_ids: list[str] = []
            for tc in _iter_tool_calls(ai_msg):
                tc_id = tc.get("id")
                if isinstance(tc_id, str) and tc_id in closures_by_tool_call_id:
                    owned_ids.append(tc_id)
            ai_closures = [closures_by_tool_call_id[tid] for tid in owned_ids]
            used_closure_ids.update(owned_ids)
            try:
                journal.record_partial_response(
                    ai_msg,
                    ai_closures,
                    abort_action=abort_action,
                )
            except Exception:
                logger.warning(
                    "partial_persist: journal.record_partial_response failed for message %s",
                    getattr(ai_msg, "id", None),
                    exc_info=True,
                )

        # 2. Orphan closures — owner AIMessage already recorded via on_llm_end,
        #    but its tool was still executing when cancel landed. The AIMessage
        #    stays as-is in run_events; we only need to add the missing
        #    ``llm.tool.result`` event so the pair is well-formed.
        orphan_closures = [c for tc_id, c in closures_by_tool_call_id.items() if tc_id not in used_closure_ids]
        if orphan_closures:
            try:
                journal.record_synthetic_closures(orphan_closures, abort_action=abort_action)
            except Exception:
                logger.warning(
                    "partial_persist: journal.record_synthetic_closures failed for %d closure(s)",
                    len(orphan_closures),
                    exc_info=True,
                )

    # Write to checkpoint AFTER journal so a journal failure doesn't
    # leave the checkpoint with messages that have no run_events
    # counterpart (which would surface as duplicates after the next
    # successful run when ``mergeMessages`` sees the same checkpoint
    # message without a corresponding history entry). Only writes
    # scoped closures (Fix 2) so historical dangling state stays intact.
    to_append: list[BaseMessage] = list(finalized) + list(closures)
    try:
        await append_messages_to_checkpoint(
            checkpointer,
            thread_id=thread_id,
            new_messages=to_append,
            abort_action=abort_action,
        )
    except Exception:
        logger.warning("partial_persist: checkpoint append failed for thread %s", thread_id, exc_info=True)

    accumulator.clear()
    return True
