"""LLM-scored progress-aware loop detection middleware (#2805 MVP).

Experimental, default-off companion to ``LoopDetectionMiddleware``. Where the
loop detector is a call-pattern guard (identical call sets / per-tool
frequency → warn → hard stop), this middleware asks the model to self-score
each step *in-band* — a compact fenced block appended to its own response
after tool results — and combines that score with harness-observable
objective signals before intervening.

Two separate signals, per the issue:

- ``task_progress`` (0-3): is the overall task closer to the user's goal?
- ``tool_usefulness`` (0-3): did the latest tool results satisfy the
  immediate intent of the calls that produced them?

``task_progress`` is the stagnation signal; ``tool_usefulness`` is diagnostic
only (surfaced in logs/audit and in the intervention text) so a
useful-but-stalled loop still triggers a replan while a wrong-tool loop
points at tool choice instead.

Objective signals cross-check the self-score (the model is never the sole
authority): per step the harness records the paired AIMessage's tool-call
keys, the ToolMessage result hashes, and status/error-type signatures from
``deerflow_tool_meta``. A window is stagnant only when *all three* hold:

1. average ``task_progress`` < ``progress_floor`` (self-scored),
2. repeated tool-key or result-hash share > ``repetition_threshold``
   (objective), and
3. no observable change: the dominant result hash covers all but one entry
   of the window (share-based, so a single noisy byte — a timestamp, a
   counter, an id — cannot veto an otherwise stagnant window) and the
   status/error signature is unchanged (objective). Varied tool calls with
   identical results are deliberately NOT observable change — the issue's
   signals are result-side (new output pattern, artifact change,
   verification advance), and varied-but-unproductive calls are exactly the
   slow-burn stagnation this middleware exists to catch.

The default ``repetition_threshold`` (0.6) makes an exactly-repeating window
fire on its third step — alongside LoopDetectionMiddleware's warn (3
identical sets) and strictly before its hard stop (5), so the replan hint
precedes any forced termination.

Division of labor with the existing guards:

- The first (and only) intervention here is a *replan-required hint* injected
  at the next model call — never stripping tool_calls, never hard-stopping.
- Hard stops for repeated identical calls and repeated failed/no-op calls
  remain ``LoopDetectionMiddleware``'s job (per the issue's non-goals:
  resource budgets and hard stops are not replaced).
- The intervention fires at most once per stagnation episode and re-arms when
  window progress recovers to ``rearm_progress`` or an observable change
  appears, so a long legitimate workflow that replans is not nagged.

The evaluation block is hidden at every boundary, not just in graph state:
``after_model`` parses and strips it from the persisted AIMessage; the run
journal strips it from ``llm.ai.response`` events; and
:class:`ProgressEvalStreamRedactor` (wired into the run worker's live
``messages`` stream) removes it from token chunks, which are published before
``after_model`` ever runs. The injected protocol instructions themselves ride
on a transient ``hide_from_ui`` HumanMessage, so the journal's first-human-
input scan cannot mistake them for the user's request. The presentation-side
redaction is gated on the feature flag: a literal fence a user asked the model
to quote must not be redacted with the feature disabled.

A model that stops emitting the block cannot silently disable the guard:
after ``noncompliance_threshold`` consecutive tool-result steps without a
parseable evaluation, one bounded signal (warning log + audit event) fires
per streak. And the drained replan hint is re-queued when the model call
raises, so an outer error-handling retry still delivers it — the stagnation
episode is already marked intervened and would not re-queue it.

The protocol payload helpers (tag, fenced-block regex, content stripping,
streaming redactor) live in :mod:`progress_eval_protocol`, a dependency-light
module, so the runtime layer can import them without this module's
agent-framework imports — importing those from the runtime would form an
import cycle (``runtime.__init__`` → ``runs.worker`` → middleware →
``loop_detection`` → ``runtime``).
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import uuid
from collections import Counter, OrderedDict, deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.runtime import Runtime

from deerflow.agents.middlewares.audit_context import LOOP_DETECTION_RECORDER_CONTEXT_KEY
from deerflow.agents.middlewares.loop_detection_middleware import _normalize_tool_call_args, _stable_tool_key
from deerflow.agents.middlewares.progress_eval_protocol import (
    _EVAL_BLOCK_RE,
    PROGRESS_EVAL_TAG,
    strip_progress_eval_blocks,
)
from deerflow.agents.middlewares.tool_result_meta import TOOL_META_KEY
from deerflow.runtime.events.catalog import MIDDLEWARE_PROGRESS_SCORING_TAG

if TYPE_CHECKING:
    from deerflow.config.progress_scoring_config import ProgressScoringConfig

logger = logging.getLogger(__name__)

_SCORE_MIN = 0
_SCORE_MAX = 3
_MAX_EVIDENCE_ITEMS = 3
_MAX_EVIDENCE_LENGTH = 120

type _RunScopeKey = tuple[str, str | None]

_INSTRUCTION_TEXT = f"""[PROGRESS EVALUATION PROTOCOL]
After every response that follows tool results, append one fenced block exactly of this form at the end of your reply:
```{PROGRESS_EVAL_TAG}
{{"tool_usefulness": <0-3>, "task_progress": <0-3>, "progress_type": "<none|uncertainty_reduction|hypothesis_elimination|evidence_found|verification|other>", "evidence": ["<short line>"], "should_change_strategy": <true|false>}}
```
task_progress answers: is the overall task closer to the user's goal after the latest tool results? tool_usefulness answers: did those results satisfy the immediate intent of the calls?
Do NOT give progress credit for reading, searching, or running a command unless it produced new evidence, changed an artifact, eliminated a hypothesis, or advanced verification.
The block is machine-read and removed from the conversation; it never replaces your normal reply."""

_INTERVENTION_TEXT = (
    "[PROGRESS STALLED] Over the last {steps} steps, self-reported task progress averaged {avg:.1f}/3 "
    "while {repeated:.0%} of the tool calls and results kept repeating with no observable change. "
    "Do not repeat the same calls again. Replan now: state what is established, what remains unknown, "
    "and choose a different strategy (different tools, different arguments, or produce your final answer "
    "from the evidence collected so far)."
)


@dataclass(frozen=True, slots=True)
class StepEvaluation:
    """One parsed in-band self-evaluation emitted by the model."""

    tool_usefulness: int
    task_progress: int
    progress_type: str = "other"
    evidence: tuple[str, ...] = ()
    should_change_strategy: bool = False


def _coerce_score(value: object) -> int | None:
    """Return the score as an int in [0, 3], or None if untrustworthy.

    Floats that are whole numbers (``2.0``) are accepted — JSON numbers from
    some providers arrive that way — but truncated floats (``1.5``) and
    out-of-range values reject the whole evaluation rather than being
    clamped: a hallucinated score must not silently become a valid one.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float):
        if not value.is_integer():
            return None
        value = int(value)
    if not _SCORE_MIN <= value <= _SCORE_MAX:
        return None
    return int(value)


def _sanitize_evidence(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    items: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        text = item.strip()[:_MAX_EVIDENCE_LENGTH]
        if text:
            items.append(text)
        if len(items) >= _MAX_EVIDENCE_ITEMS:
            break
    return tuple(items)


def parse_step_evaluation(content: str | list | None) -> StepEvaluation | None:
    """Extract the model's self-evaluation block from AIMessage content.

    Returns ``None`` unless the block parses as JSON and both scores pass
    :func:`_coerce_score`; a malformed or partially hallucinated block is
    discarded wholesale instead of half-trusted.
    """
    for match in _EVAL_BLOCK_RE.finditer(_content_to_text(content)):
        try:
            data = json.loads(match.group(1))
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        task_progress = _coerce_score(data.get("task_progress"))
        tool_usefulness = _coerce_score(data.get("tool_usefulness"))
        if task_progress is None or tool_usefulness is None:
            continue
        progress_type = data.get("progress_type")
        should_change = data.get("should_change_strategy")
        return StepEvaluation(
            tool_usefulness=tool_usefulness,
            task_progress=task_progress,
            progress_type=progress_type if isinstance(progress_type, str) and progress_type else "other",
            evidence=_sanitize_evidence(data.get("evidence")),
            should_change_strategy=True if should_change is True else False,
        )
    return None


def _content_to_text(content: str | list | None) -> str:
    """Flatten AIMessage content (str or content-block list) to plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts)
    return ""


def _result_hash(msg: ToolMessage) -> str:
    """Deterministic short hash of a tool result's content."""
    text = msg.content if isinstance(msg.content, str) else json.dumps(msg.content, sort_keys=True, default=str)
    return hashlib.md5(text.encode("utf-8", errors="replace")).hexdigest()[:12]


def _tool_meta_signature(msg: ToolMessage) -> tuple[str, str | None]:
    """The (status, error_type) pair from deerflow_tool_meta, if stamped."""
    meta = (msg.additional_kwargs or {}).get(TOOL_META_KEY)
    if isinstance(meta, dict):
        status = meta.get("status")
        error_type = meta.get("error_type")
        return (str(status) if status is not None else "", error_type if isinstance(error_type, str) else None)
    return ("", None)


@dataclass(frozen=True, slots=True)
class _StepRecord:
    """One model turn's step: self-evaluation plus objective signals."""

    evaluation: StepEvaluation | None
    tool_keys: tuple[str, ...] = ()
    result_hashes: tuple[str, ...] = ()
    meta_signatures: tuple[tuple[str, str | None], ...] = ()


@dataclass(frozen=True, slots=True)
class _WindowStats:
    """Aggregates a window of step records for the stagnation policy."""

    steps: int
    evals: int
    avg_task_progress: float | None
    repeated_tool_key_ratio: float
    repeated_result_hash_ratio: float
    observable_change: bool


def _repeated_ratio(values: tuple[str, ...]) -> float:
    """Share of values that are duplicates of an earlier value in *values*."""
    if not values:
        return 0.0
    distinct = len(set(values))
    return 1.0 - distinct / len(values)


def _window_stats(window: deque[_StepRecord]) -> _WindowStats:
    tool_keys: list[str] = []
    result_hashes: list[str] = []
    signatures: list[tuple[tuple[str, str | None], ...]] = []
    scores: list[int] = []
    for record in window:
        tool_keys.extend(record.tool_keys)
        result_hashes.extend(record.result_hashes)
        signatures.append(record.meta_signatures)
        if record.evaluation is not None:
            scores.append(record.evaluation.task_progress)

    # Observable change proxies for the issue's artifact-change /
    # new-output-pattern / verification-advance signals. Result-side variety
    # is measured by *share*, matching how repetition is measured: the window
    # counts as unchanged while the dominant result hash covers all but one
    # entry, so a single noisy byte (timestamp, counter, id) cannot veto an
    # otherwise stagnant window. Two or more deviant hashes — or any change
    # in the status/error signature — are real observable change. Varied
    # tool calls alone do NOT count as change: the issue's signals are
    # result-side, and varied calls producing identical results is exactly
    # the stagnation shape this middleware must catch (call-key variety is
    # folded into the repetition ratios above instead).
    if result_hashes:
        dominant_count = max(Counter(result_hashes).values())
        no_result_change = len(result_hashes) - dominant_count <= 1
    else:
        no_result_change = True
    observable_change = not no_result_change or len(set(signatures)) > 1

    return _WindowStats(
        steps=len(window),
        evals=len(scores),
        avg_task_progress=(sum(scores) / len(scores)) if scores else None,
        repeated_tool_key_ratio=_repeated_ratio(tuple(tool_keys)),
        repeated_result_hash_ratio=_repeated_ratio(tuple(result_hashes)),
        observable_change=observable_change,
    )


@dataclass
class _RunScopeState:
    """Per-(thread, run) tracking state."""

    window: deque[_StepRecord] = field(default_factory=deque)
    intervened: bool = False
    # Protocol non-compliance: consecutive steps with tool results but no
    # parseable evaluation block, and whether the bounded signal already
    # fired for the current streak. Reset when a valid evaluation arrives.
    missing_eval_streak: int = 0
    noncompliance_reported: bool = False


class ProgressScoringMiddleware(AgentMiddleware[AgentState]):
    """LLM-scored progress-aware loop detection (#2805 MVP).

    Args:
        window_size: sliding window of recent steps.
        min_evals: minimum valid self-evaluations in the window before a
            stagnation decision is allowed.
        progress_floor: window-average ``task_progress`` below this counts
            as low progress.
        rearm_progress: window average at or above this re-arms the
            intervention after one fired.
        repetition_threshold: repeated tool-key or result-hash share that
            counts as high repetition. Default 0.6 so an exactly-repeating
            window fires on its third step — level with
            LoopDetectionMiddleware's warn (3) and before its hard stop (5).
        noncompliance_threshold: consecutive steps with tool results but no
            parseable evaluation before one bounded non-compliance signal
            (log + audit event) is emitted per streak. Does not fire the
            intervention.
        max_tracked_threads: LRU cap on tracked thread/run scopes.
    """

    def __init__(
        self,
        *,
        window_size: int = 8,
        min_evals: int = 3,
        progress_floor: float = 1.0,
        rearm_progress: float = 2.0,
        repetition_threshold: float = 0.6,
        noncompliance_threshold: int = 3,
        max_tracked_threads: int = 100,
    ):
        super().__init__()
        self.window_size = window_size
        self.min_evals = min_evals
        self.progress_floor = progress_floor
        self.rearm_progress = rearm_progress
        self.repetition_threshold = repetition_threshold
        self.noncompliance_threshold = noncompliance_threshold
        self.max_tracked_threads = max_tracked_threads
        self._lock = threading.Lock()
        # Mirrors LoopDetectionMiddleware's run-scope anchoring: embedders
        # that omit run_id get an opaque per-invocation token derived from
        # LangGraph's stable Runtime.control object, so replacement Runtime
        # wrappers share one window within an invocation while a later
        # invocation starts fresh.
        self._fallback_run_ids: OrderedDict[int, tuple[object, str]] = OrderedDict()
        self._max_fallback_run_ids = max(1, self.max_tracked_threads * 2)
        self._scopes: OrderedDict[_RunScopeKey, _RunScopeState] = OrderedDict()
        self._pending_hints: dict[_RunScopeKey, str] = {}

    @classmethod
    def from_config(cls, config: ProgressScoringConfig) -> ProgressScoringMiddleware:
        """Construct from a Pydantic-validated config, trusting its validation."""
        return cls(
            window_size=config.window_size,
            min_evals=config.min_evals,
            progress_floor=config.progress_floor,
            rearm_progress=config.rearm_progress,
            repetition_threshold=config.repetition_threshold,
            noncompliance_threshold=config.noncompliance_threshold,
            max_tracked_threads=config.max_tracked_threads,
        )

    def release_policy_parameters(self) -> dict[str, object]:
        return {
            "window_size": self.window_size,
            "min_evals": self.min_evals,
            "progress_floor": self.progress_floor,
            "rearm_progress": self.rearm_progress,
            "repetition_threshold": self.repetition_threshold,
            "noncompliance_threshold": self.noncompliance_threshold,
            "max_tracked_threads": self.max_tracked_threads,
        }

    # ------------------------------------------------------------------
    # Run-scope bookkeeping
    # ------------------------------------------------------------------

    def _get_thread_id(self, runtime: Runtime) -> str:
        thread_id = runtime.context.get("thread_id") if runtime.context else None
        return str(thread_id) if thread_id else "default"

    def _get_run_id(self, runtime: Runtime) -> str | None:
        ctx = getattr(runtime, "context", None)
        if isinstance(ctx, dict) and "run_id" in ctx:
            return ctx["run_id"]

        execution_info = getattr(runtime, "execution_info", None)
        execution_run_id = getattr(execution_info, "run_id", None)
        if execution_run_id is not None:
            return str(execution_run_id)

        control = getattr(runtime, "control", None)
        anchor = control if control is not None else runtime
        anchor_id = id(anchor)
        with self._lock:
            existing = self._fallback_run_ids.get(anchor_id)
            if existing is not None and existing[0] is anchor:
                self._fallback_run_ids.move_to_end(anchor_id)
                return existing[1]
            fallback_run_id = f"__invocation__:{uuid.uuid4().hex}"
            self._fallback_run_ids[anchor_id] = (anchor, fallback_run_id)
            self._fallback_run_ids.move_to_end(anchor_id)
            while len(self._fallback_run_ids) > self._max_fallback_run_ids:
                self._fallback_run_ids.popitem(last=False)
            return fallback_run_id

    def _release_fallback_run_id(self, runtime: Runtime) -> None:
        ctx = getattr(runtime, "context", None)
        if isinstance(ctx, dict) and "run_id" in ctx:
            return
        execution_info = getattr(runtime, "execution_info", None)
        if getattr(execution_info, "run_id", None) is not None:
            return
        control = getattr(runtime, "control", None)
        anchor = control if control is not None else runtime
        anchor_id = id(anchor)
        with self._lock:
            existing = self._fallback_run_ids.get(anchor_id)
            if existing is not None and existing[0] is anchor:
                self._fallback_run_ids.pop(anchor_id, None)

    def _run_scope_key(self, runtime: Runtime) -> _RunScopeKey:
        return self._get_thread_id(runtime), self._get_run_id(runtime)

    def _scope_state(self, key: _RunScopeKey) -> _RunScopeState:
        """Return (touching for LRU) the tracking state for one scope."""
        with self._lock:
            state = self._scopes.get(key)
            if state is None:
                state = _RunScopeState(window=deque(maxlen=self.window_size))
                self._scopes[key] = state
                while len(self._scopes) > self.max_tracked_threads:
                    evicted_key, _ = self._scopes.popitem(last=False)
                    self._pending_hints.pop(evicted_key, None)
            else:
                self._scopes.move_to_end(key)
            return state

    # ------------------------------------------------------------------
    # Step extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _step_context(messages: list) -> tuple[list[ToolMessage], list[dict]] | None:
        """Return the ToolMessages since the previous AIMessage and the
        tool_calls of that previous AIMessage, or None when the current turn
        produced no tool results (nothing to evaluate).

        Expects *messages* to end with the AIMessage just produced, which is
        excluded from the backwards scan.
        """
        tool_messages: list[ToolMessage] = []
        requesting_calls: list[dict] = []
        for msg in reversed(messages[:-1]):
            if isinstance(msg, AIMessage):
                requesting_calls = list(msg.tool_calls or [])
                break
            if isinstance(msg, ToolMessage):
                tool_messages.insert(0, msg)
            # Non-AI, non-tool messages (e.g. HumanMessage interruptions)
            # still belong to the same span between assistant turns.
        if not tool_messages:
            return None
        return tool_messages, requesting_calls

    def _build_step_record(self, messages: list) -> tuple[_StepRecord, StepEvaluation | None]:
        """Parse the evaluation and objective signals for the current turn."""
        last_msg = messages[-1]
        evaluation = parse_step_evaluation(last_msg.content)

        step = _StepRecord(evaluation=evaluation)
        context = self._step_context(messages)
        if context is not None:
            tool_messages, requesting_calls = context
            tool_keys: list[str] = []
            tool_by_id = {str(tc.get("id")): tc for tc in requesting_calls if tc.get("id") is not None}
            for msg in tool_messages:
                call = tool_by_id.get(str(msg.tool_call_id))
                if call is None:
                    # Unpaired result (e.g. synthetic): fall back to name only.
                    tool_keys.append(str(msg.name or "?"))
                    continue
                args, fallback_key = _normalize_tool_call_args(call.get("args", {}))
                tool_keys.append(f"{call.get('name')}:{_stable_tool_key(str(call.get('name', '')), args, fallback_key)}")
            step = _StepRecord(
                evaluation=evaluation,
                tool_keys=tuple(tool_keys),
                result_hashes=tuple(_result_hash(msg) for msg in tool_messages),
                meta_signatures=tuple(_tool_meta_signature(msg) for msg in tool_messages),
            )
        return step, evaluation

    # ------------------------------------------------------------------
    # Policy
    # ------------------------------------------------------------------

    def _check_policy(self, state: _RunScopeState, stats: _WindowStats) -> str | None:
        """Return the intervention hint when the window is stagnant.

        Re-arm first so a recovered window can trigger again on a *later*
        slump; then require all three conditions (low self-scored progress,
        high objective repetition, no observable change) before firing at
        most one replan hint per episode.
        """
        if stats.evals == 0 or stats.avg_task_progress is None:
            return None

        if state.intervened and (stats.avg_task_progress >= self.rearm_progress or stats.observable_change):
            state.intervened = False

        if state.intervened:
            return None

        low_progress = stats.avg_task_progress < self.progress_floor
        high_repetition = stats.repeated_tool_key_ratio > self.repetition_threshold or stats.repeated_result_hash_ratio > self.repetition_threshold
        if stats.evals >= self.min_evals and low_progress and high_repetition and not stats.observable_change:
            state.intervened = True
            repeated = max(stats.repeated_tool_key_ratio, stats.repeated_result_hash_ratio)
            return _INTERVENTION_TEXT.format(steps=stats.steps, avg=stats.avg_task_progress, repeated=repeated)
        return None

    def _record_audit_event(self, runtime: Runtime, stats: _WindowStats, action: str, *, extra_changes: dict[str, object] | None = None) -> None:
        """Persist a progress-scoring transition without sensitive tool data."""
        context = getattr(runtime, "context", None)
        recorder = context.get(LOOP_DETECTION_RECORDER_CONTEXT_KEY) if isinstance(context, dict) else None
        if recorder is None and isinstance(context, dict):
            recorder = context.get("__run_journal")
        if recorder is None:
            return
        changes: dict[str, object] = {
            "is_subagent": isinstance(context, dict) and context.get("is_subagent") is True,
            "steps": stats.steps,
            "evals": stats.evals,
            "avg_task_progress": stats.avg_task_progress,
            "repeated_tool_key_ratio": stats.repeated_tool_key_ratio,
            "repeated_result_hash_ratio": stats.repeated_result_hash_ratio,
            "observable_change": stats.observable_change,
        }
        if extra_changes:
            changes.update(extra_changes)
        try:
            recorder.record_middleware(
                tag=MIDDLEWARE_PROGRESS_SCORING_TAG,
                name=type(self).__name__,
                hook="after_model",
                action=action,
                changes=changes,
            )
        except Exception:  # noqa: BLE001
            logger.warning("Failed to record middleware:progress_scoring event", exc_info=True)

    def _apply(self, state: AgentState, runtime: Runtime) -> dict | None:
        messages = state.get("messages", [])
        if not messages or not isinstance(messages[-1], AIMessage):
            return None

        step, evaluation = self._build_step_record(messages)

        scope_key = self._run_scope_key(runtime)
        scope_state = self._scope_state(scope_key)
        noncompliance = False
        if step.tool_keys or step.result_hashes:
            scope_state.window.append(step)
            # Protocol non-compliance: a step that produced tool results but
            # carried no parseable evaluation block. Without a bounded signal
            # here, a model that stops emitting the block turns the feature
            # into a silent no-op (protocol compliance decays — the
            # instruction is only re-sent in-band — and a truncation that
            # loses the closing fence also loses the parse). One signal per
            # streak; a valid evaluation resets the streak.
            if evaluation is None:
                scope_state.missing_eval_streak += 1
                if scope_state.missing_eval_streak >= self.noncompliance_threshold and not scope_state.noncompliance_reported:
                    scope_state.noncompliance_reported = True
                    noncompliance = True
            else:
                scope_state.missing_eval_streak = 0
                scope_state.noncompliance_reported = False

        stats = _window_stats(scope_state.window)
        with self._lock:
            hint = self._check_policy(scope_state, stats)
            if hint is not None:
                self._pending_hints[scope_key] = hint

        if hint is not None:
            logger.warning(
                "Progress stagnation detected — queueing replan hint",
                extra={
                    "thread_id": scope_key[0],
                    "run_id": scope_key[1],
                    "steps": stats.steps,
                    "evals": stats.evals,
                    "avg_task_progress": stats.avg_task_progress,
                    "repeated_tool_key_ratio": stats.repeated_tool_key_ratio,
                    "repeated_result_hash_ratio": stats.repeated_result_hash_ratio,
                    "tool_usefulness": evaluation.tool_usefulness if evaluation is not None else None,
                },
            )
            self._record_audit_event(runtime, stats, action="replan_required")

        if noncompliance:
            logger.warning(
                "Progress-scoring protocol not followed — no parseable evaluation block for %d consecutive steps",
                scope_state.missing_eval_streak,
                extra={
                    "thread_id": scope_key[0],
                    "run_id": scope_key[1],
                    "missing_eval_streak": scope_state.missing_eval_streak,
                    "noncompliance_threshold": self.noncompliance_threshold,
                },
            )
            self._record_audit_event(
                runtime,
                stats,
                action="eval_noncompliance",
                extra_changes={"missing_eval_streak": scope_state.missing_eval_streak, "noncompliance_threshold": self.noncompliance_threshold},
            )

        stripped = strip_progress_eval_blocks(messages[-1].content)
        if stripped is messages[-1].content:
            return None
        new_msg = messages[-1].model_copy(update={"content": stripped})
        return {"messages": [new_msg]}

    # ------------------------------------------------------------------
    # Hooks
    # ------------------------------------------------------------------

    @override
    def after_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        return self._apply(state, runtime)

    @override
    async def aafter_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        return self._apply(state, runtime)

    @override
    def after_agent(self, state: AgentState, runtime: Runtime) -> dict | None:
        self._drop_pending_hint(runtime)
        self._release_fallback_run_id(runtime)
        return None

    @override
    async def aafter_agent(self, state: AgentState, runtime: Runtime) -> dict | None:
        self._drop_pending_hint(runtime)
        self._release_fallback_run_id(runtime)
        return None

    def _drop_pending_hint(self, runtime: Runtime) -> None:
        scope_key = self._run_scope_key(runtime)
        with self._lock:
            self._pending_hints.pop(scope_key, None)

    def _drain_pending_hint(self, runtime: Runtime) -> str | None:
        """Pop and return the queued replan hint for *runtime*'s thread/run."""
        scope_key = self._run_scope_key(runtime)
        with self._lock:
            return self._pending_hints.pop(scope_key, None)

    def _restore_pending_hint(self, runtime: Runtime, hint: str | None) -> None:
        """Re-queue a hint taken for a model call that raised.

        LLMErrorHandlingMiddleware sits outside this middleware and retries a
        failed call by running this wrap again, so the retry must still find
        the hint. It would not be re-queued by the policy: the stagnation
        episode is already marked ``intervened``, so without the restore a
        single retriable failure (429, empty response, provider 5xx) between
        queueing and delivery silently drops the middleware's only
        intervention. Mirrors LoopDetectionMiddleware's
        ``_restore_pending_warnings``.
        """
        if not hint:
            return
        scope_key = self._run_scope_key(runtime)
        with self._lock:
            self._pending_hints[scope_key] = hint

    def _augment_request(self, request: ModelRequest, hint: str | None) -> ModelRequest:
        """Append the evaluation protocol (plus the drained hint) to the
        outgoing message list as one transient HumanMessage.

        The hint is drained by the caller (``wrap_model_call`` /
        ``awrap_model_call``) so a failed model call can restore it before
        the error-handling middleware retries.

        Transient by design: the protocol text is re-sent on every model call
        (self-evaluation compliance decays if the model only saw it once) and
        the hint is delivered exactly once, so neither is persisted into the
        thread history. Appending after all ToolMessages keeps provider
        tool-call pairing intact, mirroring LoopDetectionMiddleware.

        The message is marked ``hide_from_ui`` — the journal's existing rule
        for framework-injected HumanMessages — so ``on_chat_model_start``'s
        backward scan for the first persistable user message cannot mistake
        this synthetic prompt for the run's human input (it is appended last,
        so without the marker it would always win that scan on the first
        lead-agent call).
        """
        parts = [_INSTRUCTION_TEXT]
        if hint:
            parts.append(hint)
        new_messages = [
            *request.messages,
            HumanMessage(
                content="\n\n".join(parts),
                name="progress_scoring",
                additional_kwargs={"hide_from_ui": True},
            ),
        ]
        return request.override(messages=new_messages)

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        hint = self._drain_pending_hint(request.runtime)
        try:
            return handler(self._augment_request(request, hint))
        except Exception:
            self._restore_pending_hint(request.runtime, hint)
            raise

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        hint = self._drain_pending_hint(request.runtime)
        try:
            return await handler(self._augment_request(request, hint))
        except Exception:
            self._restore_pending_hint(request.runtime, hint)
            raise

    def reset(self, thread_id: str | None = None) -> None:
        """Clear tracking state. If thread_id given, clear only that thread."""
        with self._lock:
            if thread_id:
                for key in [k for k in self._scopes if k[0] == thread_id]:
                    self._scopes.pop(key, None)
                    self._pending_hints.pop(key, None)
            else:
                self._scopes.clear()
                self._pending_hints.clear()
                self._fallback_run_ids.clear()
