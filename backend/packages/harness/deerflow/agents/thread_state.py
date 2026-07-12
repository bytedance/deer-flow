import copy
import uuid
from collections.abc import Mapping, Sequence
from functools import cache
from typing import Annotated, Any, NotRequired, TypedDict, cast, get_type_hints

from langchain.agents import AgentState
from langchain_core.messages import (
    AnyMessage,
    BaseMessageChunk,
    RemoveMessage,
    convert_to_messages,
    message_chunk_to_message,
)
from langgraph.channels import DeltaChannel
from langgraph.graph.message import REMOVE_ALL_MESSAGES

import deerflow.checkpoint_patches as _checkpoint_patches  # noqa: F401 - import-time saver fixes
from deerflow.agents.goal_state import GoalState
from deerflow.config.database_config import CheckpointChannelMode
from deerflow.subagents.status_contract import SUBAGENT_STATUS_VALUES


class SandboxState(TypedDict):
    sandbox_id: NotRequired[str | None]


class ThreadDataState(TypedDict):
    workspace_path: NotRequired[str | None]
    uploads_path: NotRequired[str | None]
    outputs_path: NotRequired[str | None]


class ViewedImageData(TypedDict):
    """Metadata for a viewed image file.

    Only lightweight metadata is persisted in checkpoint state; the actual
    image bytes are read on-demand from disk when the model needs them.
    This avoids duplicating large base64 payloads across every checkpoint
    (see #4138).
    """

    mime_type: str
    size: int
    actual_path: str


def merge_sandbox(existing: SandboxState | None, new: SandboxState | None) -> SandboxState | None:
    """Reducer for sandbox state - accepts idempotent writes only.

    Multiple sandbox tools can initialize lazily in the same graph step and
    emit the same sandbox_id via Command(update=...). LangGraph needs an
    explicit reducer for that shared state key. Different sandbox ids in the
    same thread indicate a lifecycle/isolation bug, so fail closed instead of
    choosing one silently.
    """
    if new is None:
        return existing
    if existing is None:
        return new

    existing_id = existing.get("sandbox_id")
    new_id = new.get("sandbox_id")
    if existing_id == new_id:
        return existing
    raise ValueError(f"Conflicting sandbox state updates: {existing_id!r} != {new_id!r}")


SandboxStateField = Annotated[NotRequired[SandboxState | None], merge_sandbox]


def merge_artifacts(existing: list[str] | None, new: list[str] | None) -> list[str]:
    """Reducer for artifacts list - merges and deduplicates artifacts."""
    if existing is None:
        return new or []
    if new is None:
        return existing
    # Use dict.fromkeys to deduplicate while preserving order
    return list(dict.fromkeys(existing + new))


# Sentinel callers must pass to opt into clearing viewed_images. The default
# "no-op writes are a no-op" invariant (matching merge_todos / merge_goal /
# merge_promoted / merge_delegations / merge_skill_context) is restored so a
# reducer-write of ``{}`` does NOT silently wipe the agent's vision context.
# The legacy "empty dict clears" behavior was a footgun: any node returning
# ``viewed_images={}`` accidentally wiped the entire image history with no log
# line and no compensating re-fetch (D1 in the agent-core hunt).
CLEAR_VIEWED_IMAGES: dict[str, ViewedImageData] = {"__deerflow_clear__": {"base64": "", "mime_type": ""}}
_CLEAR_VIEWED_IMAGES_SENTINEL_KEY = next(iter(CLEAR_VIEWED_IMAGES))


def merge_viewed_images(existing: dict[str, ViewedImageData] | None, new: dict[str, ViewedImageData] | None) -> dict[str, ViewedImageData]:
    """Reducer for viewed_images dict - merges image dictionaries.

    - new is None -> preserve existing (no-op invariant shared with sibling
      reducers like merge_todos / merge_goal / merge_promoted /
      merge_delegations / merge_skill_context).
    - new is an empty dict -> preserve existing (no-op; accidental
      ``Command(update={"viewed_images": {}})`` no longer wipes vision context).
    - new contains the :data:`CLEAR_VIEWED_IMAGES` sentinel key -> caller is
      explicitly opting into clearing the channel; returns ``{}``.
    - otherwise -> merge dicts, new values override existing for same keys.
    """
    if existing is None:
        existing = {}
    if new is None or len(new) == 0:
        return existing
    if _CLEAR_VIEWED_IMAGES_SENTINEL_KEY in new:
        return {}
    return {**existing, **new}


def merge_todos(existing: list | None, new: list | None) -> list | None:
    """Reducer for todos list - keeps the last non-None value.

    Semantics:
    - If `new` is None (node didn't touch todos), preserve `existing`.
    - If `new` is provided (even empty list), it represents an explicit
      update and wins over `existing`.
    """
    if new is None:
        return existing
    return new


def merge_goal(existing: GoalState | None, new: GoalState | None) -> GoalState | None:
    """Reducer for goal state - preserves existing when a node does not touch it."""
    if new is None:
        return existing
    return new


class PromotedTools(TypedDict):
    catalog_hash: str
    names: list[str]


def merge_promoted(existing: PromotedTools | None, new: PromotedTools | None) -> PromotedTools | None:
    """Reducer for deferred-tool promotions, scoped by catalog hash.

    - new None/empty -> preserve existing (node didn't touch promotions).
    - catalog_hash changed -> replace wholesale, dropping stale names (prevents a
      persisted bare name from exposing a different tool after catalog drift).
    - same catalog_hash -> union names, dedupe, preserve order.
    """
    if not new:
        return existing
    if existing is None or existing.get("catalog_hash") != new["catalog_hash"]:
        return {
            "catalog_hash": new["catalog_hash"],
            "names": list(dict.fromkeys(new["names"])),
        }
    return {
        "catalog_hash": existing["catalog_hash"],
        "names": list(dict.fromkeys(existing["names"] + new["names"])),
    }


TERMINAL_STATUSES: frozenset[str] = frozenset(SUBAGENT_STATUS_VALUES)
_DELEGATION_LEDGER_MAX_ENTRIES = 50


class DelegationEntry(TypedDict):
    id: str
    run_id: NotRequired[str]
    description: str
    subagent_type: str
    status: str
    result_brief: NotRequired[str]
    result_sha256: NotRequired[str]
    result_ref: NotRequired[str]
    # Why a guardrail cap ended the run early (#3875 Phase 2): token_capped /
    # turn_capped / loop_capped. The status stays completed/failed; this field
    # is the additive signal that distinguishes a capped run from a clean one.
    stop_reason: NotRequired[str]
    created_at: str


def merge_delegations(existing: list[DelegationEntry] | None, new: list[DelegationEntry] | None) -> list[DelegationEntry]:
    """Reducer for the delegation ledger.

    - new None/empty -> preserve existing.
    - append entries, replacing same id with the latest version while preserving
      first-seen order.
    - terminal status is never overwritten by a non-terminal status.
    - capped at ``_DELEGATION_LEDGER_MAX_ENTRIES``; the truncation is exposed
      to the renderer via the parallel
      :func:`merge_delegations_truncated_count` channel so the model-visible
      rendering can append a "... (+N earlier delegations dropped from this
      ledger)" marker. Without that marker the lead has no signal that
      history was silently dropped and may re-delegate a task whose prior
      completion is no longer in the visible ledger (D2 in the agent-core
      hunt).
    """
    if not new:
        return existing or []

    by_id: dict[str, DelegationEntry] = {}
    order: list[str] = []
    for entry in [*(existing or []), *new]:
        entry_id = entry["id"]
        previous = by_id.get(entry_id)
        if previous is not None and previous["status"] in TERMINAL_STATUSES and entry["status"] not in TERMINAL_STATUSES:
            continue
        if entry_id not in by_id:
            order.append(entry_id)
        elif previous.get("created_at"):
            entry = {**entry, "created_at": previous["created_at"]}
            if previous.get("run_id") and not entry.get("run_id"):
                entry["run_id"] = previous["run_id"]
        by_id[entry_id] = entry
    merged = [by_id[entry_id] for entry_id in order]
    if len(merged) > _DELEGATION_LEDGER_MAX_ENTRIES:
        merged = merged[-_DELEGATION_LEDGER_MAX_ENTRIES:]
    return merged


def merge_delegations_truncated_count(existing: int | None, new: int | None) -> int:
    """Reducer for the parallel ``delegations_truncated_count`` channel.

    Tracks how many delegation entries have been silently dropped from the
    durable ledger because the channel exceeded its cap. Without this signal
    the renderer has no way to tell the model that history was clipped and
    it may re-delegate work it had already completed (D2 in the agent-core
    hunt). The reducer takes the maximum of the two values so older drop
    counts survive a checkpoint round-trip; a node that explicitly declares
    ``new=0`` only zeros the count when the existing count is also 0.
    """
    if existing is None:
        existing = 0
    if new is None:
        return existing
    return max(existing, new)


_SKILL_CONTEXT_MAX_ENTRIES = 8
_SKILL_DESCRIPTION_MAX_CHARS = 500
_SKILL_DESCRIPTION_TRUNCATION_SUFFIX = " ... [truncated]"


def description_for_skill_entry(raw: str) -> tuple[str, bool]:
    """Bound a skill description and surface whether truncation occurred.

    Centralizes the cap that was copy-pasted at four sites in two files:
    ``_normalize_skill_entry`` (reducer), ``_parse_description`` /
    ``read_skill_entry_metadata`` (capture), and ``render_skill_context``
    (render). Without this helper, any new caller that forgets the cap
    leaves the description unbounded (state leak); any unrelated cap bump
    has to touch multiple files. The returned ``truncated`` flag lets the
    caller surface ``... [truncated]`` on render so the model knows the
    description it is reading was clipped (D5 in the agent-core hunt).
    """
    if not isinstance(raw, str):
        return ("", False)
    if len(raw) <= _SKILL_DESCRIPTION_MAX_CHARS:
        return (raw, False)
    cap = _SKILL_DESCRIPTION_MAX_CHARS
    if cap <= len(_SKILL_DESCRIPTION_TRUNCATION_SUFFIX):
        return (raw[:cap], True)
    head = cap - len(_SKILL_DESCRIPTION_TRUNCATION_SUFFIX)
    return (f"{raw[:head]}{_SKILL_DESCRIPTION_TRUNCATION_SUFFIX}", True)


class SkillEntry(TypedDict):
    name: str
    path: str
    description: str
    loaded_at: int


def _normalize_skill_entry(entry: Mapping[str, object]) -> SkillEntry:
    """Drop legacy payload keys before storing skill_context back to state."""
    description = entry.get("description")
    loaded_at = entry.get("loaded_at")
    if isinstance(description, str):
        normalized_description, _truncated = description_for_skill_entry(" ".join(description.split()))
    else:
        normalized_description = ""
    return {
        "name": str(entry.get("name") or ""),
        "path": str(entry["path"]),
        "description": normalized_description,
        "loaded_at": loaded_at if isinstance(loaded_at, int) else 0,
    }


def merge_skill_context(existing: list[SkillEntry] | None, new: list[SkillEntry] | None) -> list[SkillEntry]:
    """Reducer for the skill-context channel.

    - new None/empty -> preserve existing.
    - legacy entries are normalized to references; verbatim body keys are dropped.
    - dedup by ``path``; later reads refresh recency and replace the reference.
    - cap by keeping the most recently read entries. ``loaded_at`` is
      observational only because message indices reset after compaction.
    """
    normalized_existing = [_normalize_skill_entry(entry) for entry in existing or []]
    if not new:
        return normalized_existing

    by_path: dict[str, SkillEntry] = {}
    order: list[str] = []
    for entry in normalized_existing:
        path = entry["path"]
        if path not in by_path:
            order.append(path)
        by_path[path] = entry

    for entry in (_normalize_skill_entry(entry) for entry in new):
        path = entry["path"]
        if path in by_path:
            order.remove(path)
        order.append(path)
        by_path[path] = entry

    merged = [by_path[path] for path in order]
    if len(merged) > _SKILL_CONTEXT_MAX_ENTRIES:
        merged = merged[-_SKILL_CONTEXT_MAX_ENTRIES:]
    return merged


class ThreadState(AgentState):
    sandbox: SandboxStateField
    thread_data: NotRequired[ThreadDataState | None]
    title: NotRequired[str | None]
    artifacts: Annotated[list[str], merge_artifacts]
    todos: Annotated[list | None, merge_todos]
    goal: Annotated[GoalState | None, merge_goal]
    uploaded_files: NotRequired[list[dict] | None]
    viewed_images: Annotated[dict[str, ViewedImageData], merge_viewed_images]  # image_path -> metadata (no base64)
    promoted: Annotated[PromotedTools | None, merge_promoted]
    delegations: Annotated[list[DelegationEntry], merge_delegations]
    # Parallel channel that surfaces how many entries have been silently dropped
    # from :attr:`delegations` because the ledger exceeded its cap. The renderer
    # reads this to append a model-visible "... (+N earlier delegations dropped
    # from this ledger)" marker so the lead does not re-delegate work whose
    # completion is no longer in the visible ledger (D2 in the agent-core hunt).
    delegations_truncated_count: Annotated[int, merge_delegations_truncated_count]
    skill_context: Annotated[list[SkillEntry], merge_skill_context]
    summary_text: NotRequired[str | None]


def _normalize_messages(value: Any) -> list[AnyMessage]:
    values = value if isinstance(value, list) else [value]
    messages = [message_chunk_to_message(cast(BaseMessageChunk, message)) for message in convert_to_messages(values)]
    for message in messages:
        if message.id is None:
            message.id = str(uuid.uuid4())
    return messages


def _index_messages(
    messages: list[AnyMessage | None],
) -> tuple[dict[str, int], dict[str, list[int]]]:
    latest_position: dict[str, int] = {}
    positions_by_id: dict[str, list[int]] = {}
    for position, message in enumerate(messages):
        if message is None:
            continue
        message_id = cast(str, message.id)
        latest_position[message_id] = position
        positions_by_id.setdefault(message_id, []).append(position)
    return latest_position, positions_by_id


def _raise_null_write(has_messages: bool) -> None:
    # ``add_messages(left, None)`` reports only ``left`` when the accumulated
    # message list is non-empty; with an empty list, it reports only ``right``.
    received = "left" if has_messages else "right"
    raise ValueError(f"Must specify non-null arguments for both 'left' and 'right'. Only received: '{received}'.")


def merge_message_writes(state: list[AnyMessage], writes: Sequence[Any]) -> list[AnyMessage]:
    """Fold DeltaChannel writes with ``add_messages`` semantics in linear time.

    LangGraph's private ``_messages_delta_reducer`` is also linear, but does
    not preserve the public reducer's full coercion, ID, removal, and
    ``REMOVE_ALL_MESSAGES`` behavior.
    """
    if not writes:
        return list(state)
    if writes[0] is None:
        _raise_null_write(bool(state))

    messages: list[AnyMessage | None] = _normalize_messages(state)
    latest_position, positions_by_id = _index_messages(messages)

    for write in writes:
        if write is None:
            _raise_null_write(bool(latest_position))
        normalized_write = _normalize_messages(write)
        remove_all_idx = None
        for position, message in enumerate(normalized_write):
            if isinstance(message, RemoveMessage) and message.id == REMOVE_ALL_MESSAGES:
                remove_all_idx = position

        if remove_all_idx is not None:
            messages = list(normalized_write[remove_all_idx + 1 :])
            latest_position, positions_by_id = _index_messages(messages)
            continue

        ids_to_remove: set[str] = set()
        for message in normalized_write:
            message_id = cast(str, message.id)
            existing_position = latest_position.get(message_id)
            if existing_position is not None:
                if isinstance(message, RemoveMessage):
                    ids_to_remove.add(message_id)
                else:
                    ids_to_remove.discard(message_id)
                    messages[existing_position] = message
                continue

            if isinstance(message, RemoveMessage):
                raise ValueError(f"Attempting to delete a message with an ID that doesn't exist ('{message_id}')")

            position = len(messages)
            messages.append(message)
            latest_position[message_id] = position
            positions_by_id[message_id] = [position]

        for message_id in ids_to_remove:
            for position in positions_by_id.pop(message_id):
                messages[position] = None
            del latest_position[message_id]

    return [message for message in messages if message is not None]


DELTA_MESSAGES_FIELD = Annotated[
    list[AnyMessage],
    DeltaChannel(merge_message_writes, snapshot_frequency=1000),
]


class DeltaThreadState(ThreadState):
    messages: DELTA_MESSAGES_FIELD


THREAD_STATE_REDUCER_FIELDS = frozenset(
    {
        "messages",
        "sandbox",
        "artifacts",
        "todos",
        "goal",
        "viewed_images",
        "promoted",
        "delegations",
        "skill_context",
    }
)


def get_thread_state_schema(mode: CheckpointChannelMode) -> type:
    return DeltaThreadState if mode == "delta" else ThreadState


@cache
def adapt_state_schema_for_mode(schema: type, mode: CheckpointChannelMode) -> type:
    if mode == "full":
        return schema
    annotations = get_type_hints(schema, include_extras=True)
    annotations["messages"] = DELTA_MESSAGES_FIELD
    return TypedDict(
        f"Delta{schema.__module__.replace('.', '_')}_{schema.__name__}",
        annotations,
        total=getattr(schema, "__total__", True),
    )


def normalize_middleware_state_schemas(middleware: Sequence[Any], mode: CheckpointChannelMode) -> list[Any]:
    if mode == "full":
        return list(middleware)
    normalized = []
    for item in middleware:
        schema = getattr(item, "state_schema", None)
        if schema is None:
            normalized.append(item)
            continue
        adapted = copy.copy(item)
        adapted.state_schema = adapt_state_schema_for_mode(schema, mode)
        normalized.append(adapted)
    return normalized
