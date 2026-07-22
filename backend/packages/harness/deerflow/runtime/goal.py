"""Thread-scoped goal state and evaluator helpers.

This module implements the Claude Code-style goal loop primitives used by
Gateway runs and thin API surfaces. It intentionally lives in ``deerflow`` so
the harness can evaluate and continue runs without importing the FastAPI app.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import inspect
import json
import logging
import os
import threading
import weakref
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Literal, NamedTuple

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.checkpoint.base import empty_checkpoint, uuid6

import deerflow.utils.llm_text as llm_text
from deerflow.agents.goal_state import GoalBlocker, GoalEvaluation, GoalState
from deerflow.models import create_chat_model
from deerflow.tracing import inject_langfuse_metadata
from deerflow.utils.messages import message_to_text
from deerflow.utils.time import now_iso

logger = logging.getLogger(__name__)

DEFAULT_MAX_GOAL_CONTINUATIONS = 8
DEFAULT_MAX_NO_PROGRESS_CONTINUATIONS = 2
MAX_GOAL_OBJECTIVE_CHARS = 4000
MAX_GOAL_REASON_CHARS = 1000
MAX_GOAL_EVIDENCE_CHARS = 1000
MAX_GOAL_CONVERSATION_CHARS = 12000
MAX_GOAL_CONVERSATION_MESSAGES = 30

GOAL_BLOCKERS: set[GoalBlocker] = {
    "none",
    "missing_evidence",
    "needs_user_input",
    "run_failed",
    "external_wait",
    "goal_not_met_yet",
}
CONTINUABLE_GOAL_BLOCKERS: set[GoalBlocker] = {"goal_not_met_yet"}

GOAL_CLEAR_ALIASES = frozenset({"clear", "reset", "off"})

_extract_response_text = llm_text.extract_response_text
_strip_markdown_code_fence = llm_text.strip_markdown_code_fence
_strip_think_blocks = llm_text.strip_think_blocks

_goal_locks_guard = threading.Lock()
_goal_locks_by_loop: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict[str, asyncio.Lock]] = weakref.WeakKeyDictionary()


class GoalWriteConflict(RuntimeError):
    """Raised when a goal write is based on a stale checkpoint."""


@asynccontextmanager
async def goal_thread_lock(thread_id: str) -> AsyncIterator[None]:
    """Serialize goal read-modify-write sequences within the current event loop."""
    loop = asyncio.get_running_loop()
    with _goal_locks_guard:
        locks = _goal_locks_by_loop.get(loop)
        if locks is None:
            locks = {}
            _goal_locks_by_loop[loop] = locks
        lock = locks.get(thread_id)
        if lock is None:
            lock = asyncio.Lock()
            locks[thread_id] = lock

    async with lock:
        yield


class GoalCommand(NamedTuple):
    """Parsed intent of a ``/goal`` slash command argument string."""

    kind: Literal["status", "clear", "set"]
    objective: str = ""


def parse_goal_command(args: str) -> GoalCommand:
    """Parse the argument string of a ``/goal`` command into an intent.

    Shared by the TUI and IM-channel surfaces so the three-way semantics stay in
    one place: empty shows the active goal, ``clear``/``reset``/``off`` clears it,
    and anything else sets the goal to that (trimmed) objective. The frontend
    keeps a parallel TypeScript copy in ``input-box-helpers.ts``.
    """
    stripped = args.strip()
    if not stripped:
        return GoalCommand("status")
    if stripped.lower() in GOAL_CLEAR_ALIASES:
        return GoalCommand("clear")
    return GoalCommand("set", stripped)


def normalize_goal_objective(objective: str) -> str:
    """Normalize and validate user-provided goal text."""
    normalized = " ".join(objective.strip().split())
    if not normalized:
        raise ValueError("Goal objective must not be empty.")
    if len(normalized) > MAX_GOAL_OBJECTIVE_CHARS:
        raise ValueError(f"Goal objective must be at most {MAX_GOAL_OBJECTIVE_CHARS} characters.")
    return normalized


def build_goal_state(
    objective: str,
    *,
    max_continuations: int = DEFAULT_MAX_GOAL_CONTINUATIONS,
    max_no_progress_continuations: int = DEFAULT_MAX_NO_PROGRESS_CONTINUATIONS,
    now: str | None = None,
) -> GoalState:
    """Create a fresh active goal state for a thread."""
    objective = normalize_goal_objective(objective)
    capped_max = max(0, min(int(max_continuations), DEFAULT_MAX_GOAL_CONTINUATIONS))
    timestamp = now or now_iso()
    return GoalState(
        objective=objective,
        status="active",
        created_at=timestamp,
        updated_at=timestamp,
        continuation_count=0,
        max_continuations=capped_max,
        no_progress_count=0,
        max_no_progress_continuations=max(0, int(max_no_progress_continuations)),
    )


def parse_goal_evaluation_response(text: str) -> GoalEvaluation:
    """Parse the evaluator's JSON object response."""
    candidate = _strip_markdown_code_fence(_strip_think_blocks(text))
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("Goal evaluator response did not contain a JSON object.")
    try:
        payload = json.loads(candidate[start : end + 1])
    except Exception as exc:
        raise ValueError("Goal evaluator response was not valid JSON.") from exc
    if not isinstance(payload, dict):
        raise ValueError("Goal evaluator JSON must be an object.")
    satisfied = payload.get("satisfied")
    if not isinstance(satisfied, bool):
        raise ValueError("Goal evaluator JSON must include boolean 'satisfied'.")
    reason = _normalize_evaluation_text(payload.get("reason"), max_chars=MAX_GOAL_REASON_CHARS)
    evidence_summary = _normalize_evaluation_text(payload.get("evidence_summary"), max_chars=MAX_GOAL_EVIDENCE_CHARS)
    blocker = _normalize_goal_blocker(payload.get("blocker"), satisfied=satisfied)
    return GoalEvaluation(
        satisfied=satisfied,
        blocker=blocker,
        reason=reason,
        evidence_summary=evidence_summary,
    )


def _normalize_evaluation_text(value: object, *, max_chars: int) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.strip().split())[:max_chars]


def _normalize_goal_blocker(value: object, *, satisfied: bool) -> GoalBlocker:
    if satisfied:
        return "none"
    if isinstance(value, str) and value in GOAL_BLOCKERS and value != "none":
        return value
    return "missing_evidence"


def _message_type(message: Any) -> str | None:
    value = getattr(message, "type", None)
    if value is None and isinstance(message, dict):
        value = message.get("type") or message.get("role")
    if value == "assistant":
        return "ai"
    if value == "user":
        return "human"
    return str(value) if value else None


def _additional_kwargs(message: Any) -> dict[str, Any]:
    value = getattr(message, "additional_kwargs", None)
    if value is None and isinstance(message, dict):
        value = message.get("additional_kwargs")
    return dict(value) if isinstance(value, dict) else {}


def _is_visible_message(message: Any) -> bool:
    if _additional_kwargs(message).get("hide_from_ui") is True:
        return False
    return _message_type(message) in {"human", "ai"}


def has_visible_assistant_evidence(messages: list[Any]) -> bool:
    """Return true when the evaluator can inspect at least one visible AI reply."""
    return any(_is_visible_message(message) and _message_type(message) == "ai" and bool(message_to_text(message).strip()) for message in messages)


def visible_conversation_signature(messages: list[Any]) -> str:
    """Return a stable lightweight signature for the visible evaluator evidence."""
    visible = []
    for message in messages:
        if not _is_visible_message(message):
            continue
        visible.append(
            {
                "role": _message_type(message),
                "text": message_to_text(message).strip(),
            }
        )
    return json.dumps(visible[-MAX_GOAL_CONVERSATION_MESSAGES:], ensure_ascii=False, sort_keys=True)


def format_visible_conversation(messages: list[Any]) -> str:
    """Return the user-visible conversation evidence for goal evaluation."""
    lines: list[str] = []
    visible = [message for message in messages if _is_visible_message(message)]
    for message in visible[-MAX_GOAL_CONVERSATION_MESSAGES:]:
        text = message_to_text(message).strip()
        if not text:
            continue
        role = "User" if _message_type(message) == "human" else "Assistant"
        lines.append(f"{role}: {text}")
    conversation = "\n\n".join(lines)
    if len(conversation) > MAX_GOAL_CONVERSATION_CHARS:
        conversation = conversation[-MAX_GOAL_CONVERSATION_CHARS:]
    return conversation


def create_goal_evaluator_model(
    *,
    model_name: str | None = None,
    app_config: Any | None = None,
) -> Any:
    """Create the non-thinking chat model used by the goal evaluator.

    The evaluator runs from ``runtime/runs/worker.py`` after the main graph
    run has already completed, so — unlike ``make_lead_agent``/
    ``DeerFlowClient.stream``, which attach ``build_tracing_callbacks()`` at
    the graph root and correctly pass ``attach_tracing=False`` to avoid
    double-attaching — there is no graph root here for the evaluator's model
    call to inherit tracing from. It must attach its own model-level tracing
    callbacks, same as the other standalone, non-graph callers
    (``oneshot_llm.run_oneshot_llm``, ``MemoryUpdater``).
    """
    return create_chat_model(
        name=model_name,
        thinking_enabled=False,
        app_config=app_config,
        attach_tracing=True,
    )


def _resolve_environment() -> str | None:
    return os.environ.get("DEER_FLOW_ENV") or os.environ.get("ENVIRONMENT")


async def evaluate_goal_completion(
    goal: GoalState,
    messages: list[Any],
    *,
    model: Any | None = None,
    model_name: str | None = None,
    app_config: Any | None = None,
    thread_id: str | None = None,
    user_id: str | None = None,
    deerflow_trace_id: str | None = None,
) -> GoalEvaluation:
    """Ask a small non-thinking model whether the active goal is satisfied.

    ``thread_id``/``user_id``/``deerflow_trace_id`` are forwarded to Langfuse
    trace metadata only (mirrors ``oneshot_llm.run_oneshot_llm``): this is a
    standalone model call outside the main graph, so it must inject its own
    Langfuse session/user attribution instead of relying on graph-root
    callbacks to lift it — same fix as PR #2944 (main graph) and PR #3902
    (memory_agent/suggest_agent).
    """
    conversation = format_visible_conversation(messages)
    if not conversation or not has_visible_assistant_evidence(messages):
        return GoalEvaluation(
            satisfied=False,
            blocker="missing_evidence",
            reason="No visible assistant evidence is available yet.",
            evidence_summary="",
        )

    system_instruction = (
        "You are a strict completion evaluator for an AI coding assistant.\n"
        "Decide whether the active goal is fully satisfied using ONLY the visible conversation evidence.\n"
        "Do not assume files, commands, tests, or external state changed unless the conversation explicitly shows it.\n"
        "If the visible evidence is too weak to prove progress, fail closed with blocker missing_evidence.\n"
        "Use blocker needs_user_input when the assistant is waiting on the user, run_failed when the turn failed, "
        "external_wait when work is waiting on an outside system, goal_not_met_yet when useful autonomous work can continue, "
        "and none only when satisfied is true.\n"
        'Output exactly one JSON object: {"satisfied": boolean, "blocker": string, "reason": string, "evidence_summary": string}.'
    )
    user_content = f"Active goal:\n{goal['objective']}\n\nVisible conversation evidence:\n{conversation}\n\nIs the active goal fully satisfied?"

    if model is None:
        model = create_goal_evaluator_model(model_name=model_name, app_config=app_config)
    invoke_config: dict[str, Any] = {"run_name": "goal_evaluator"}
    inject_langfuse_metadata(
        invoke_config,
        thread_id=thread_id,
        user_id=user_id,
        assistant_id="goal_evaluator",
        model_name=model_name,
        environment=_resolve_environment(),
        deerflow_trace_id=deerflow_trace_id,
    )
    response = await model.ainvoke(
        [SystemMessage(content=system_instruction), HumanMessage(content=user_content)],
        config=invoke_config,
    )
    return parse_goal_evaluation_response(_extract_response_text(response.content))


def should_continue_goal(goal: GoalState, evaluation: GoalEvaluation, *, no_progress_count: int | None = None) -> bool:
    """Return whether another hidden continuation turn should run."""
    if evaluation["satisfied"]:
        return False
    if evaluation["blocker"] not in CONTINUABLE_GOAL_BLOCKERS:
        return False
    if int(goal.get("continuation_count", 0)) >= int(goal.get("max_continuations", DEFAULT_MAX_GOAL_CONTINUATIONS)):
        return False
    current_no_progress = int(goal.get("no_progress_count", 0) if no_progress_count is None else no_progress_count)
    max_no_progress = int(goal.get("max_no_progress_continuations", DEFAULT_MAX_NO_PROGRESS_CONTINUATIONS))
    return current_no_progress < max_no_progress


def latest_visible_assistant_signature(messages: list[Any]) -> str:
    """Return a stable signature of the latest visible assistant evidence.

    The "no progress" breaker keys on what the agent actually produced — the
    text of the most recent user-visible assistant message — not on the
    evaluator's free-text ``reason``/``evidence_summary`` (which an LLM rewords
    on every turn, so it almost never repeats byte-for-byte). When a
    continuation adds no new visible assistant output, the signature is
    unchanged and the breaker can recognise the stalled turn.
    """
    for message in reversed(messages):
        if not _is_visible_message(message) or _message_type(message) != "ai":
            continue
        text = message_to_text(message).strip()
        if text:
            return hashlib.sha256(text.encode("utf-8")).hexdigest()
    return ""


def compute_goal_progress_key(evaluation: GoalEvaluation, *, evidence_signature: str = "") -> str:
    """Return a stable key used to detect repeated non-progress evaluations.

    Keyed on the typed ``blocker`` plus a signature of the visible assistant
    evidence, so a stalled goal is detected even when the evaluator rewords its
    free-text ``reason``/``evidence_summary``.
    """
    return json.dumps(
        {
            "satisfied": evaluation["satisfied"],
            "blocker": evaluation["blocker"],
            "evidence_signature": evidence_signature,
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def compute_no_progress_count(goal: GoalState, evaluation: GoalEvaluation, *, evidence_signature: str = "") -> int:
    """Increment repeated-progress count when visible evidence has not advanced."""
    if evaluation["satisfied"]:
        return 0
    progress_key = compute_goal_progress_key(evaluation, evidence_signature=evidence_signature)
    previous = goal.get("last_evaluation", {})
    if isinstance(previous, dict) and previous.get("progress_key") == progress_key:
        return int(goal.get("no_progress_count", 0)) + 1
    return 0


def make_goal_continuation_message(goal: GoalState, evaluation: GoalEvaluation) -> HumanMessage:
    """Build the hidden user message that asks the agent to keep working."""
    content = (
        "<goal_continuation>\n"
        f"Active goal: {goal['objective']}\n"
        f"Evaluator result: not satisfied. Blocker: {evaluation['blocker']}. Reason: {evaluation['reason'] or 'No reason provided.'}\n"
        f"Visible evidence: {evaluation.get('evidence_summary') or 'No evidence summary provided.'}\n"
        "Continue working toward the active goal. Use the available tools and conversation context. "
        "Do not ask the user to continue unless you are genuinely blocked.\n"
        "</goal_continuation>"
    )
    return HumanMessage(
        content=content,
        additional_kwargs={
            "hide_from_ui": True,
            "deerflow_goal_continuation": True,
        },
    )


async def _call_checkpointer_method(checkpointer: Any, async_name: str, sync_name: str, *args: Any, **kwargs: Any) -> Any:
    async_method = getattr(checkpointer, async_name, None)
    if async_method is not None:
        result = async_method(*args, **kwargs)
        return await result if inspect.isawaitable(result) else result
    sync_method = getattr(checkpointer, sync_name, None)
    if sync_method is None:
        raise AttributeError(f"Missing checkpointer method: {async_name}/{sync_name}")
    # Offload the synchronous checkpointer call so its blocking IO never runs on
    # the event loop (backend/AGENTS.md blocking-IO gate).
    result = await asyncio.to_thread(sync_method, *args, **kwargs)
    return await result if inspect.isawaitable(result) else result


def _next_channel_version(checkpointer: Any, current_version: Any) -> Any:
    get_next_version = getattr(checkpointer, "get_next_version", None)
    if callable(get_next_version):
        return get_next_version(current_version, None)
    if isinstance(current_version, int):
        return current_version + 1
    return 1


async def ensure_thread_checkpoint(checkpointer: Any, thread_id: str) -> None:
    """Create an empty root checkpoint for *thread_id* when none exists."""
    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    checkpoint_tuple = await _call_checkpointer_method(checkpointer, "aget_tuple", "get_tuple", config)
    if checkpoint_tuple is not None:
        return
    metadata = {
        "step": -1,
        "source": "input",
        "writes": None,
        "parents": {},
        "created_at": now_iso(),
    }
    await _call_checkpointer_method(checkpointer, "aput", "put", config, empty_checkpoint(), metadata, {})


def _checkpoint_id_from_tuple(checkpoint_tuple: Any) -> str | None:
    config = getattr(checkpoint_tuple, "config", {}) or {}
    configurable = config.get("configurable", {}) if isinstance(config, dict) else {}
    checkpoint_id = configurable.get("checkpoint_id") if isinstance(configurable, dict) else None
    if isinstance(checkpoint_id, str):
        return checkpoint_id
    checkpoint = getattr(checkpoint_tuple, "checkpoint", {}) or {}
    if isinstance(checkpoint, dict) and isinstance(checkpoint.get("id"), str):
        return checkpoint["id"]
    return None


async def read_thread_goal(checkpointer: Any, thread_id: str) -> GoalState | None:
    """Read the latest thread goal from checkpoint state."""
    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    checkpoint_tuple = await _call_checkpointer_method(checkpointer, "aget_tuple", "get_tuple", config)
    if checkpoint_tuple is None:
        return None
    checkpoint = getattr(checkpoint_tuple, "checkpoint", {}) or {}
    channel_values = checkpoint.get("channel_values", {}) if isinstance(checkpoint, dict) else {}
    raw_goal = channel_values.get("goal") if isinstance(channel_values, dict) else None
    return copy.deepcopy(raw_goal) if isinstance(raw_goal, dict) else None


async def write_thread_goal(
    checkpointer: Any,
    thread_id: str,
    goal: GoalState | None,
    *,
    as_node: str = "goal",
    create_if_missing: bool = False,
    expected_checkpoint_id: str | None = None,
) -> dict[str, Any]:
    """Write a new checkpoint with the thread goal set or cleared.

    Returns the updated channel values.
    """
    if create_if_missing:
        await ensure_thread_checkpoint(checkpointer, thread_id)

    read_config: dict[str, Any] = {
        "configurable": {
            "thread_id": thread_id,
            "checkpoint_ns": "",
        }
    }
    checkpoint_tuple = await _call_checkpointer_method(checkpointer, "aget_tuple", "get_tuple", read_config)
    if checkpoint_tuple is None:
        raise LookupError(f"Thread {thread_id} checkpoint not found")
    if expected_checkpoint_id is not None and _checkpoint_id_from_tuple(checkpoint_tuple) != expected_checkpoint_id:
        raise GoalWriteConflict(f"Thread {thread_id} goal checkpoint changed while preparing write")

    checkpoint: dict[str, Any] = dict(getattr(checkpoint_tuple, "checkpoint", {}) or {})
    metadata: dict[str, Any] = dict(getattr(checkpoint_tuple, "metadata", {}) or {})
    channel_values: dict[str, Any] = dict(checkpoint.get("channel_values", {}) or {})

    if goal is None:
        channel_values.pop("goal", None)
    else:
        channel_values["goal"] = copy.deepcopy(goal)

    channel_versions = dict(checkpoint.get("channel_versions", {}) or {})
    current_version = channel_versions.get("goal")
    next_version = _next_channel_version(checkpointer, current_version)
    channel_versions["goal"] = next_version

    checkpoint["channel_values"] = channel_values
    checkpoint["channel_versions"] = channel_versions
    checkpoint["id"] = str(uuid6())
    metadata["updated_at"] = now_iso()
    metadata["source"] = "update"
    metadata["step"] = metadata.get("step", 0) + 1
    metadata["writes"] = {as_node: {"goal": goal}}

    write_config = {
        "configurable": {
            "thread_id": thread_id,
            "checkpoint_ns": "",
            # Parent the new checkpoint to the one it was derived from.
            # Without this the saver stores a parentless checkpoint, which
            # severs Delta-channel replay ancestry (and truncates history
            # walks in full mode too).
            "checkpoint_id": _checkpoint_id_from_tuple(checkpoint_tuple),
        }
    }
    await _call_checkpointer_method(checkpointer, "aput", "put", write_config, checkpoint, metadata, {"goal": next_version})
    return channel_values


def attach_goal_evaluation(
    goal: GoalState,
    evaluation: GoalEvaluation,
    *,
    run_id: str,
    continuation_count: int | None = None,
    no_progress_count: int | None = None,
    stand_down_reason: str | None = None,
    evidence_signature: str = "",
) -> GoalState:
    """Return a goal copy with the latest evaluator result attached."""
    next_goal = copy.deepcopy(goal)
    if continuation_count is not None:
        next_goal["continuation_count"] = continuation_count
    if no_progress_count is not None:
        next_goal["no_progress_count"] = no_progress_count
    next_goal["updated_at"] = now_iso()
    next_goal["last_evaluation"] = {
        "satisfied": evaluation["satisfied"],
        "blocker": evaluation["blocker"],
        "reason": evaluation["reason"],
        "evidence_summary": evaluation.get("evidence_summary", ""),
        "run_id": run_id,
        "evaluated_at": next_goal["updated_at"],
        "progress_key": compute_goal_progress_key(evaluation, evidence_signature=evidence_signature),
    }
    if stand_down_reason:
        next_goal["last_evaluation"]["stand_down_reason"] = stand_down_reason
    return next_goal
