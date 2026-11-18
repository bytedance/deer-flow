"""Middleware to detect and break repetitive tool call loops.

P0 safety: prevents the agent from calling the same tool with the same
arguments indefinitely until the recursion limit kills the run.

Detection strategy:
  1. After each model response, hash the tool calls (name + args).
  2. Track recent hashes in a sliding window.
  3. If the same hash appears >= warn_threshold times, queue a
     "you are repeating yourself — wrap up" warning for the current
     thread/run. The warning is **injected at the next model call** (in
     ``wrap_model_call``) as a ``HumanMessage`` appended to the message
     list, *after* all ToolMessage responses to the previous
     AIMessage(tool_calls).
  4. If it appears >= hard_limit times, strip all tool_calls from the
     response so the agent is forced to produce a final text answer.

Why the warning is injected at ``wrap_model_call`` instead of
``after_model``:

  ``after_model`` fires immediately after the model emits an
  ``AIMessage`` that may carry ``tool_calls``. The tools node has not
  run yet, so no matching ``ToolMessage`` exists in the history. Any
  message we add here lands *between* the assistant's tool_calls and
  their responses. OpenAI/Moonshot reject the next request with
  ``"tool_call_ids did not have response messages"`` because their
  validators require the assistant's tool_calls to be followed
  immediately by tool messages. Anthropic also disallows mid-stream
  ``SystemMessage``. By deferring the warning to ``wrap_model_call``,
  every prior ToolMessage is already present in the request's message
  list and the warning is appended at the end — pairing intact, no
  ``AIMessage`` semantics are mutated.

Queued warnings are intentionally transient. If a run ends before the
next model request drains a queued warning, ``after_agent`` drops it
instead of carrying it into a later invocation for the same thread. The
hard-stop path still forces termination when the configured safety limit
is reached.

Detection histories and warning-suppression state are scoped by
``(thread_id, run_id)`` because one compiled graph can serve many runs for
the same conversation. They deliberately survive ``after_agent``: a
single Gateway run may re-enter that graph for hidden goal continuations,
and those continuations share one loop budget. A later user run receives a
fresh budget even when it reuses the graph. Standalone library invocations
that omit ``run_id`` receive an opaque fallback ID anchored to LangGraph's
run-scoped ``Runtime.control`` object, so replacement ``Runtime`` wrappers
share one budget within an invocation while a later invocation starts fresh.

Per-tool cap:
  A per-tool frequency limit drops only the calls of a response that would
  reach it; the calls within the limit run. The capped tool then stays
  blocked for the rest of the execution. That state cannot live in the
  frequency window (dropped calls are not counted, so other tools would
  evict the capped tool and reopen it) or in memory (an approval resume is
  a new run, possibly on a restarted Gateway). It is a checkpointed record
  in the private ``loop_cap`` state channel, together with the explanation
  the model has not read yet. ``before_agent`` expires a record that
  another run left behind, which is what gives a new task its fresh budget:
  that hook runs when a task enters the graph and not on a resume. See
  ``docs/LOOP_DETECTION.md``.

Stop-reason surfacing (#3875 Phase 2):
  Like the token-budget guard, a loop cap does NOT raise. The hard stop
  strips ``tool_calls`` so the agent loop terminates naturally with a final
  answer, and a per-tool cap lets the run wrap up. To let the caller (the
  subagent executor) distinguish a loop-capped completion from a clean one,
  the capped run is recorded in ``_stop_reason`` and exposed via
  :meth:`consume_stop_reason`. The executor collects that reason alongside
  the token-budget guard's so a loop-capped run surfaces as
  ``completed + loop_capped`` and the lead/ledger can tell it was capped
  without parsing result text. A per-tool cap reports only when the run ends,
  and not at all when another guard stopped the run, because other
  middlewares read ``runtime.context["stop_reason"]`` mid-run as "the run is
  ending" (see ``_report_cap``). A response whose admitted calls another
  middleware discards before they run is undone (see ``_Admission``).
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import uuid
from collections import Counter, OrderedDict, defaultdict, deque
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field, replace
from itertools import islice
from typing import TYPE_CHECKING, Annotated, Literal, NotRequired, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse, PrivateStateAttr
from langchain_core.messages import HumanMessage
from langgraph.runtime import Runtime

from deerflow.agents.middlewares._bounded_dict import BoundedDict
from deerflow.agents.middlewares.audit_context import (
    LOOP_DETECTION_RECORDER_CONTEXT_KEY,
    resolve_audit_recorder,
)
from deerflow.agents.middlewares.tool_call_metadata import clone_ai_message_with_tool_calls
from deerflow.runtime.events.catalog import MIDDLEWARE_LOOP_DETECTION_TAG

if TYPE_CHECKING:
    from deerflow.config.loop_detection_config import LoopDetectionConfig

logger = logging.getLogger(__name__)

# Defaults — can be overridden via constructor
_DEFAULT_WARN_THRESHOLD = 3  # inject warning after 3 identical calls
_DEFAULT_HARD_LIMIT = 5  # force-stop after 5 identical calls
_DEFAULT_WINDOW_SIZE = 20  # track last N tool calls
_DEFAULT_MAX_TRACKED_THREADS = 100  # LRU limit for tracked thread/run scopes
_DEFAULT_TOOL_FREQ_WARN = 30  # warn after 30 calls to the same tool type
_DEFAULT_TOOL_FREQ_HARD_LIMIT = 50  # force-stop after 50 calls to the same tool type
_MAX_PENDING_WARNINGS_PER_RUN = 4
# Stands in for ``read_file``'s omitted ``end_line`` in a call key: the read
# runs to the last line, which is not the same window as any numbered bound.
_OPEN_ENDED_READ = "end"
# Sandbox tools on the generic key path whose ``description`` is only the UI
# explanation of the call. Elsewhere ``description`` can be the operation's
# payload (``update_agent``/``setup_agent`` persist it; MCP tools such as
# ``create_issue`` send it), so it stays in the key.
_UI_NARRATION_TOOLS = frozenset({"bash", "ls", "glob", "grep"})

type _RunScopeKey = tuple[str, str | None]

# State channel holding the tools that reached their per-tool limit. It is
# checkpointed, so the cap outlives an approval pause, a new ``run_id`` on
# resume, a Gateway restart and context compaction. See ``_LoopCap``.
LOOP_CAP_STATE_KEY = "loop_cap"
# Bounds on what a persisted record may name; a larger record is not ours.
_MAX_CAPPED_TOOLS = 64
_MAX_TOOL_NAME_CHARS = 128


class LoopDetectionState(AgentState):
    """Adds the per-tool cap record. Private: a client can neither send nor stream it."""

    loop_cap: NotRequired[Annotated[dict | None, PrivateStateAttr]]


# Deeply nested args cannot be serialized for a key; they collapse to one opaque key.
_UNSERIALIZABLE_ARGS = "<unserializable>"


def _stable_args_key(value: object) -> str | None:
    """Serialize opaque args for a stable key, or None past the recursion limit."""
    try:
        return json.dumps(value, sort_keys=True, default=str)
    except (TypeError, ValueError, RecursionError):
        return None


def _normalize_tool_call_args(raw_args: object) -> tuple[dict, str | None]:
    """Normalize tool call args to a dict plus an optional fallback key.

    Some providers serialize ``args`` as a JSON string instead of a dict.
    We defensively parse those cases so loop detection does not crash while
    still preserving a stable fallback key for non-dict payloads.
    """
    if isinstance(raw_args, dict):
        return raw_args, None

    if isinstance(raw_args, str):
        try:
            parsed = json.loads(raw_args)
        except (TypeError, ValueError, json.JSONDecodeError, RecursionError):
            return {}, raw_args

        if isinstance(parsed, dict):
            return parsed, None
        return {}, _stable_args_key(parsed)

    if raw_args is None:
        return {}, None

    return {}, _stable_args_key(raw_args)


def _coerce_line_number(value: object) -> int | None:
    """Parse one ``read_file`` line bound, or ``None`` when absent or unusable."""
    try:
        line = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        # OverflowError: a model-emitted JSON number such as ``1e999`` parses to
        # a float('inf') that ``int()`` rejects. Treat it like any other
        # unusable bound so key derivation cannot crash the after_model hook.
        return None
    return max(line, 1)


def _normalized_read_range(args: dict) -> tuple[int, int | None]:
    """Normalize ``read_file``'s line range into one comparable window.

    Omitting ``end_line`` reads through the last line, so it normalizes to
    ``None`` (open-ended) rather than collapsing onto ``start_line``: that keeps
    ``read_file(path)`` and ``read_file(path, start_line=1)`` — the same read,
    written two ways — on a single key. A reversed range is ordered, so one
    window written either way also produces a single key.

    The window is otherwise kept exact. Quantizing it into 200-line buckets (the
    original heuristic) collapsed every read shorter than a bucket onto its
    neighbours, so an agent paging a file in 40-line chunks tripped the hard
    stop on its fifth *distinct* read — while ``read_file``'s own truncation
    notice tells the model to page with ``start_line``/``end_line``. Bucketing
    cannot separate progress from repetition in general: equality keys can only
    approximate range overlap, and the approximation was erasing the offset that
    distinguishes the two. An exact window still catches the loop this layer
    exists for — the same read emitted over and over — and a loop that jitters
    its bounds is what Layer 2's per-tool frequency window covers.
    """
    start_line = _coerce_line_number(args.get("start_line"))
    end_line = _coerce_line_number(args.get("end_line"))
    if start_line is None:
        start_line = 1
    if end_line is not None and end_line < start_line:
        start_line, end_line = end_line, start_line
    return start_line, end_line


def _stable_tool_key(name: str, args: dict, fallback_key: str | None) -> str:
    """Derive a stable key from the args that change what a call does."""
    if name == "read_file" and fallback_key is None:
        path = args.get("path") or ""
        if not isinstance(path, str):
            # Formatting a nested structure into the key calls repr(), which
            # recurses past the limit for the same payloads _stable_args_key
            # already treats as opaque.
            path = _stable_args_key(path) or _UNSERIALIZABLE_ARGS
        start_line, end_line = _normalized_read_range(args)
        return f"{path}:{start_line}-{end_line if end_line is not None else _OPEN_ENDED_READ}"

    # write_file / str_replace are content-sensitive: same path may be updated
    # with different payloads during iteration. Using only salient fields (path)
    # can collapse distinct calls, so we hash full args to reduce false positives.
    if name in {"write_file", "str_replace"}:
        if fallback_key is not None:
            return fallback_key
        return _stable_args_key(args) or _UNSERIALIZABLE_ARGS

    if fallback_key is not None:
        return fallback_key

    # Every other argument can change what the call does: keying only a salient
    # field (``path``/``url``/``query``...) collapsed paging a URL or a search
    # (``start_index``, ``page``, ``cursor``) and rewriting one skill file onto a
    # single key, so the fifth *distinct* call hard-stopped the run. A sandbox
    # tool's UI narration is dropped, so rewording it cannot make a repeated
    # call look new (#1905).
    if name in _UI_NARRATION_TOOLS:
        args = {field: value for field, value in args.items() if field != "description"}
    return _stable_args_key(args) or _UNSERIALIZABLE_ARGS


def _hash_tool_calls(tool_calls: list[dict]) -> str:
    """Deterministic hash of a set of tool calls (name + stable key).

    This is intended to be order-independent: the same multiset of tool calls
    should always produce the same hash, regardless of their input order.
    """
    # Normalize each tool call to a stable (name, key) structure.
    normalized: list[str] = []
    for tc in tool_calls:
        name = tc.get("name", "")
        args, fallback_key = _normalize_tool_call_args(tc.get("args", {}))
        key = _stable_tool_key(name, args, fallback_key)

        normalized.append(f"{name}:{key}")

    # Sort so permutations of the same multiset of calls yield the same ordering.
    normalized.sort()
    blob = json.dumps(normalized, sort_keys=True, default=str)
    return hashlib.md5(blob.encode()).hexdigest()[:12]


# Warn-level messages ask the agent to wrap up, but must not make it drop work
# it was asked to persist: a subagent whose task names an output file would
# otherwise stop *all* tool calls, including the write that delivers its
# result, and finish as "completed" with nothing on disk. So the wrap-up
# allows a bounded save/read/retry before the final answer, without reusing
# a looping writer or bypassing the read-before-write gate. It also names
# present_files: an agent told only to stop calling tools skipped presenting
# outputs it had already created, so the run failed its delivery check. The
# hard-stop path below is unchanged (it strips tool calls).
_WRAP_UP_INSTRUCTIONS = (
    "If your task asks you to save results to a file, first write what you have collected so far to that file "
    "with a file-writing tool (for example write_file, unless it is the looping tool). "
    "If the writer is itself looping, use a different available file-writing tool. "
    "If a save is blocked by a read-before-write check, read the target file and retry the save once. "
    "Do not use a tool that this warning tells you to stop, or repeat a failed save loop. "
    "If no permitted save path is available or the retry fails, include the collected results in your final answer "
    "and state that the file was not saved. "
    "If present_files is available, present the files you already created in /mnt/user-data/outputs "
    "with one present_files call before answering, unless it is the looping tool. "
    "Then stop calling tools and produce your final answer. "
    "If you cannot complete the task, summarize what you accomplished so far."
)

_WARNING_MSG = "[LOOP DETECTED] You are repeating the same tool calls. Stop repeating them and wrap up now. " + _WRAP_UP_INSTRUCTIONS

_TOOL_FREQ_WARNING_MSG = "[LOOP DETECTED] You have called {tool_name} {count} times without producing a final answer. Stop calling {tool_name} and wrap up now. " + _WRAP_UP_INSTRUCTIONS

_HARD_STOP_MSG = "[FORCED STOP] Repeated tool calls exceeded the safety limit. Producing final answer with results collected so far."

# Admission is not execution: an admitted call can still be denied by approval,
# a guardrail or the tool itself, so the model is pointed at the results.
_TOOL_FREQ_REJECT_MSG = (
    "[LOOP DETECTED] Loop detection skipped {skipped} of the {total} tool calls in your last response because {tools} reached "
    "the per-tool limit for this run. The other {admitted} were passed on; their results above show which of them actually ran. "
    "Do not call {names} again in this run. " + _WRAP_UP_INSTRUCTIONS
)
# For a drop whose tool the cap record cannot name (see ``_recordable_caps``).
_UNNAMED_TOOL = "a tool"
_UNNAMED_TOOL_AGAIN = "that tool"

_TOOL_FREQ_HARD_STOP_MSG = "[FORCED STOP] Tool {tool_name} called {count} times — exceeded the per-tool safety limit. Producing final answer with results collected so far."

_TOOL_CAPPED_HARD_STOP_MSG = "[FORCED STOP] Tool {tool_name} reached its per-tool safety limit of {limit} calls earlier in this run and cannot run again. Producing final answer with results collected so far."


def _usable_tool_name(name: object) -> bool:
    return isinstance(name, str) and 0 < len(name) <= _MAX_TOOL_NAME_CHARS and name.isprintable() and not any(ch.isspace() for ch in name)


def _positive_int(value: object) -> bool:
    return type(value) is int and value > 0


def _recordable_caps(existing: Mapping[str, int], limits: Mapping[str, int]) -> dict[str, int]:
    """Add newly limited tools to the capped set, keeping only what ``_read_loop_cap`` accepts.

    The names come from the model's response, so one can be longer than the
    reader allows, and a response can limit more tools than a record may hold.
    Such a tool is left out: the window already dropped its calls, and writing
    it would make the next read discard the record with every other cap in it.
    Existing caps are kept first.
    """
    recorded = dict(existing)
    for name, limit in limits.items():
        if name not in recorded and len(recorded) < _MAX_CAPPED_TOOLS and _usable_tool_name(name) and _positive_int(limit):
            recorded[name] = limit
    return recorded


@dataclass(frozen=True)
class _CapNotice:
    """What the model has not been told yet about its last trimmed response."""

    total: int
    skipped: int
    tools: tuple[str, ...]


@dataclass(frozen=True)
class _LoopCap:
    """Tools that reached their per-tool limit in the execution that owns ``run_id``.

    A capped tool stays blocked until a new task enters the graph, even when
    other calls evict its entries from the frequency window. ``run_id`` is the
    run that last carried the cap: an approval resume adopts it, and
    ``before_agent`` expires a cap that another run left behind.

    ``tools`` is empty when calls were dropped only for tools the record cannot
    name. The record then still marks the execution as capped and carries the
    notice.
    """

    run_id: str | None
    tools: dict[str, int]
    notice: _CapNotice | None = None

    def dump(self) -> dict:
        value: dict = {"run_id": self.run_id, "tools": dict(self.tools)}
        if self.notice is not None:
            value["notice"] = {"total": self.notice.total, "skipped": self.notice.skipped, "tools": list(self.notice.tools)}
        return value

    def notice_text(self) -> str | None:
        notice = self.notice
        if notice is None:
            return None
        return _TOOL_FREQ_REJECT_MSG.format(
            skipped=notice.skipped,
            total=notice.total,
            admitted=notice.total - notice.skipped,
            tools=", ".join(f"{name} (limit {self.tools[name]})" for name in notice.tools) or _UNNAMED_TOOL,
            names=", ".join(notice.tools) or _UNNAMED_TOOL_AGAIN,
        )


def _read_loop_cap(value: object) -> _LoopCap | None:
    """Validate a checkpointed cap record; anything malformed reads as no cap.

    The record may come from an older release or a direct checkpoint write, and
    its tool names are quoted to the model, so every field is checked here.
    """
    if not isinstance(value, Mapping):
        return None
    raw_tools = value.get("tools")
    run_id = value.get("run_id")
    if not isinstance(raw_tools, Mapping) or len(raw_tools) > _MAX_CAPPED_TOOLS or not isinstance(run_id, str | None):
        return None
    if not all(_usable_tool_name(name) and _positive_int(limit) for name, limit in raw_tools.items()):
        return None
    tools = dict(raw_tools)

    notice = None
    raw_notice = value.get("notice")
    if isinstance(raw_notice, Mapping):
        total, skipped, names = raw_notice.get("total"), raw_notice.get("skipped"), raw_notice.get("tools")
        if _positive_int(total) and _positive_int(skipped) and skipped < total and isinstance(names, list) and all(isinstance(name, str) and name in tools for name in names):
            notice = _CapNotice(total=total, skipped=skipped, tools=tuple(dict.fromkeys(names)))
    return _LoopCap(run_id=run_id, tools=tools, notice=notice)


@dataclass(frozen=True)
class _Admission:
    """Loop state from before a response whose calls were passed on.

    Another middleware can still discard every one of those calls before they
    run: input admission supersedes the response when the user steers, and
    approval strips calls it cannot address. Calls that never ran must not
    count toward a limit or leave a cap behind, so the state is kept until the
    next model call shows whether any of the calls stood. That check runs in
    ``wrap_model_call`` rather than a ``before_model`` hook, because a hook is
    a graph node: it would cost every turn a super-step of the run's
    recursion limit.
    """

    message_id: str
    call_ids: frozenset[str]
    # The cap record as it would stand had the response made no decision.
    record: dict | None
    history: list[str] | None
    warned: frozenset[str] | None
    names: tuple[str, ...] | None
    counter: dict[str, int] | None
    freq_warned: frozenset[str] | None
    pending_warnings: tuple[str, ...] | None


@dataclass(frozen=True)
class _LoopDecision:
    """A loop-detection transition that may be persisted for audit."""

    message: str
    action: Literal["warn", "hard_stop", "reject_excess"]
    detection_layer: Literal["identical_call_set", "tool_frequency"]
    tool_names: tuple[str, ...]
    count: int
    threshold: int
    # reject_excess only: positions of the calls removed from the batch, the
    # limit of every tool they belong to, the tools that reached their limit in
    # this batch (rather than earlier) as (name, count, threshold), and a
    # warning selected for the admitted calls that is delivered alongside.
    rejected_indices: tuple[int, ...] = ()
    limits: dict[str, int] = field(default_factory=dict)
    crossings: tuple[tuple[str, int, int], ...] = ()
    companion_warning: str | None = None

    @property
    def hard_stop(self) -> bool:
        return self.action == "hard_stop"


class LoopDetectionMiddleware(AgentMiddleware[LoopDetectionState]):
    """Detects and breaks repetitive tool call loops.

    Threshold parameters are validated upstream by :class:`LoopDetectionConfig`;
    construct via :meth:`from_config` to ensure values pass Pydantic validation.

    Args:
        warn_threshold: Number of identical tool call sets before injecting
            a warning message. Default: 3.
        hard_limit: Number of identical tool call sets before stripping
            tool_calls entirely. Default: 5.
        window_size: Size of the sliding window for tracking calls.
            Default: 20.
        max_tracked_threads: Maximum number of thread/run scopes to track before
            evicting the least recently used. The configuration name is retained
            for compatibility. Default: 100.
        tool_freq_warn: Maximum number of same-tool-type calls within a
            sliding window of ``_tool_freq_window`` before injecting a
            frequency warning. Catches cross-file read loops that
            hash-based detection misses. Default: 30 (within a window
            of 50).
        tool_freq_hard_limit: Maximum number of same-tool-type calls within
            a sliding window of ``_tool_freq_window`` before forcing a
            stop. Default: 50 (within a window of 50).
        tool_freq_overrides: Per-tool overrides for frequency thresholds,
            keyed by tool name. Each value is a ``(warn, hard_limit)`` tuple
            that replaces ``tool_freq_warn`` / ``tool_freq_hard_limit`` for
            that specific tool. Tools not listed here fall back to the global
            thresholds. Useful for raising limits on intentionally
            high-frequency tools (e.g. ``bash`` in batch pipelines) without
            weakening protection on all other tools. Default: ``None``
            (no overrides).
    """

    state_schema = LoopDetectionState

    def __init__(
        self,
        warn_threshold: int = _DEFAULT_WARN_THRESHOLD,
        hard_limit: int = _DEFAULT_HARD_LIMIT,
        window_size: int = _DEFAULT_WINDOW_SIZE,
        max_tracked_threads: int = _DEFAULT_MAX_TRACKED_THREADS,
        tool_freq_warn: int = _DEFAULT_TOOL_FREQ_WARN,
        tool_freq_hard_limit: int = _DEFAULT_TOOL_FREQ_HARD_LIMIT,
        tool_freq_overrides: dict[str, tuple[int, int]] | None = None,
    ):
        super().__init__()
        self.warn_threshold = warn_threshold
        self.hard_limit = hard_limit
        self.window_size = window_size
        self.max_tracked_threads = max_tracked_threads
        self.tool_freq_warn = tool_freq_warn
        self.tool_freq_hard_limit = tool_freq_hard_limit
        self._default_tool_freq_thresholds = (tool_freq_warn, tool_freq_hard_limit)
        self._tool_freq_overrides: dict[str, tuple[int, int]] = tool_freq_overrides or {}
        # Layer 2's windowed frequency count can never exceed the deque length,
        # so the deque MUST be at least as long as the largest hard limit it is
        # compared against — otherwise the hard-stop branch is dead code. Do NOT
        # reuse Layer 1's ``window_size`` (which is unrelated and defaults below
        # the freq thresholds, e.g. 20 < hard 50); size the frequency window to
        # the largest hard limit in play (global + every per-tool override) so a
        # tight burst can actually reach it while spread-out calls still decay
        # out of the window. Warn thresholds are intentionally excluded: a sane
        # config enforces warn <= hard (covered by sizing to hard), and a misconfig
        # with warn > hard would hard-stop first anyway, so an unreachable warn
        # is harmless and must not inflate the window.
        self._tool_freq_window = max(
            self.window_size,
            self.tool_freq_hard_limit,
            *(hard for _, hard in self._tool_freq_overrides.values()),
        )
        self._lock = threading.Lock()
        # LangGraph replaces Runtime per graph node but retains one RunControl
        # object for the whole invocation. Map that stable anchor to an opaque
        # token when embedders omit run_id. Keeping the anchor strongly referenced
        # also prevents CPython from reusing its address while the mapping is live;
        # after_agent releases normal invocations and the cap bounds abnormal ones.
        self._fallback_run_ids: OrderedDict[int, tuple[object, str]] = OrderedDict()
        self._max_fallback_run_ids = max(1, self.max_tracked_threads * 2)
        self._history: OrderedDict[_RunScopeKey, list[str]] = OrderedDict()
        self._warned: dict[_RunScopeKey, set[str]] = defaultdict(set)
        # Windowed per-tool-type frequency: recent tool names per run scope,
        # trimmed to ``window_size`` so the count decays instead of growing
        # monotonically (replaces the old monotonic ``_tool_freq`` integer).
        self._tool_name_history: defaultdict[_RunScopeKey, deque[str]] = defaultdict(deque)
        # Per-run Counter mirroring the deque so freq_count is O(1) instead
        # of scanning the whole window on every tool call. A single high
        # per-tool override (e.g. bash: {hard_limit: 1000}) inflates the window
        # globally, so the scan would cost 1000 per call for every tool; Counter
        # increments on append and decrements on popleft.
        self._tool_name_counter: defaultdict[_RunScopeKey, Counter[str]] = defaultdict(Counter)
        # Per-run set of tool names already warned about in Layer 2, so a
        # frequency warning is enqueued once rather than on every subsequent
        # call. Cleared per name when the windowed count decays back below the
        # warn threshold, mirroring the hash-layer ``_warned`` pruning.
        self._tool_freq_warned: dict[_RunScopeKey, set[str]] = defaultdict(set)
        # Per-thread/run queue of warnings to inject at the next model call.
        # Populated by ``after_model`` (detection) and drained by
        # ``wrap_model_call`` (injection); see module docstring.
        self._pending_warnings: dict[_RunScopeKey, list[str]] = defaultdict(list)
        self._pending_warning_touch_order: OrderedDict[_RunScopeKey, None] = OrderedDict()
        self._max_pending_warning_keys = max(1, self.max_tracked_threads * 2)
        # Stop reason set when a hard-stop fires (#3875 Phase 2). Keyed by run_id
        # (matching ``TokenBudgetMiddleware``) and bounded — the lead agent's
        # middleware instance is long-lived across many runs, so without a cap
        # an entry would accumulate for every looped lead run. Intentionally NOT
        # cleared by ``after_agent``/``_clear_current_run_pending_warnings`` so
        # the subagent executor can consume it after the run returns; ``reset()``
        # still drops it. The parallel bounded owner map lets
        # ``reset(thread_id)`` remove only that thread's unconsumed reasons;
        # both maps are written, evicted, and popped together under ``_lock``.
        self._stop_reason: BoundedDict[str | None, str] = BoundedDict(1000)
        self._stop_reason_thread_id: BoundedDict[str | None, str] = BoundedDict(1000)
        # The newest response per run scope whose calls were passed on, with the
        # state from before it (see ``_Admission``). Settled by the next
        # ``before_model``; bounded because a run that pauses for approval
        # resumes under another scope and never settles its entry.
        self._admissions: OrderedDict[_RunScopeKey, _Admission] = OrderedDict()
        # The cap record to use instead of the checkpointed one, set when an
        # admission is undone in ``wrap_model_call`` and written to state by
        # the ``after_model`` of that same model call.
        self._record_overrides: OrderedDict[_RunScopeKey, dict | None] = OrderedDict()
        self._max_admissions = max(1, self.max_tracked_threads * 2)

    def release_policy_parameters(self) -> dict[str, object]:
        return {
            "warn_threshold": self.warn_threshold,
            "hard_limit": self.hard_limit,
            "window_size": self.window_size,
            "max_tracked_threads": self.max_tracked_threads,
            "tool_freq_warn": self.tool_freq_warn,
            "tool_freq_hard_limit": self.tool_freq_hard_limit,
            "tool_freq_overrides": self._tool_freq_overrides,
        }

    @classmethod
    def from_config(cls, config: LoopDetectionConfig) -> LoopDetectionMiddleware:
        """Construct from a Pydantic-validated config, trusting its validation."""
        return cls(
            warn_threshold=config.warn_threshold,
            hard_limit=config.hard_limit,
            window_size=config.window_size,
            max_tracked_threads=config.max_tracked_threads,
            tool_freq_warn=config.tool_freq_warn,
            tool_freq_hard_limit=config.tool_freq_hard_limit,
            tool_freq_overrides={name: (o.warn, o.hard_limit) for name, o in config.tool_freq_overrides.items()},
        )

    def _get_thread_id(self, runtime: Runtime) -> str:
        """Extract thread_id from runtime context for per-thread tracking."""
        thread_id = runtime.context.get("thread_id") if runtime.context else None
        if thread_id:
            return str(thread_id)
        return "default"

    def _get_run_id(self, runtime: Runtime) -> str | None:
        """Extract run_id from runtime context for per-run warning scoping.

        Context presence is authoritative, including an explicit ``None``:
        ``SubagentExecutor`` later consumes the stop reason with its raw,
        possibly-None run_id, so normalizing that value would lose the signal.

        A RunnableConfig run_id exposed through ``Runtime.execution_info`` is
        the next-best stable identifier. If neither source provides one, use
        LangGraph's run-scoped ``Runtime.control`` object as the invocation
        anchor. LangGraph creates replacement Runtime wrappers per graph node,
        but preserves that control object across the invocation. The anchor is
        mapped to an opaque generated token instead of embedding ``id(anchor)``
        in the key, because CPython may reuse an address after garbage
        collection. The bounded map keeps a strong reference while active and
        is released by ``after_agent`` on the normal completion path.
        """
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
        """Release a completed invocation's fallback anchor, if it used one."""
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

    def consume_stop_reason(self, run_id: str | None) -> str | None:
        """Pop and return the stop reason the hard-stop set for this run.

        Returns ``"loop_capped"`` when a repeated tool-call loop tripped the hard
        stop during the run — the run still completed with a forced final answer
        (the hard stop strips ``tool_calls`` rather than raising). The subagent
        executor calls this after the run returns so a loop-capped completion
        carries ``stop_reason=loop_capped`` to the lead instead of looking like
        a clean ``completed``. Mirrors ``TokenBudgetMiddleware.consume_stop_reason``;
        popping keeps the dict from accumulating on a reused instance.
        """
        with self._lock:
            reason = self._stop_reason.pop(run_id, None)
            self._stop_reason_thread_id.pop(run_id, None)
            return reason

    def _run_scope_key(self, runtime: Runtime) -> _RunScopeKey:
        """Return the shared tracking key for the current thread/run."""
        return self._get_thread_id(runtime), self._get_run_id(runtime)

    def _pending_key(self, runtime: Runtime) -> _RunScopeKey:
        """Return the pending-warning key for the current thread/run."""
        return self._run_scope_key(runtime)

    def _evict_if_needed(self) -> None:
        """Evict least recently used thread/run scopes if over the limit.

        Must be called while holding self._lock.
        """
        while len(self._history) > self.max_tracked_threads:
            evicted_key, _ = self._history.popitem(last=False)
            self._warned.pop(evicted_key, None)
            self._tool_name_history.pop(evicted_key, None)
            self._tool_name_counter.pop(evicted_key, None)
            self._tool_freq_warned.pop(evicted_key, None)
            self._admissions.pop(evicted_key, None)
            self._record_overrides.pop(evicted_key, None)
            self._drop_pending_warning_key_locked(evicted_key)
            logger.debug(
                "Evicted loop tracking for thread/run scope (LRU)",
                extra={"thread_id": evicted_key[0], "run_id": evicted_key[1]},
            )

    def _drop_pending_warning_key_locked(self, key: _RunScopeKey) -> None:
        """Drop all pending-warning bookkeeping for one thread/run key.

        Must be called while holding self._lock.
        """
        self._pending_warnings.pop(key, None)
        self._pending_warning_touch_order.pop(key, None)

    def _touch_pending_warning_key_locked(self, key: _RunScopeKey) -> None:
        """Mark a pending-warning key as recently used.

        Must be called while holding self._lock.
        """
        self._pending_warning_touch_order[key] = None
        self._pending_warning_touch_order.move_to_end(key)

    def _prune_pending_warning_state_locked(self, protected_key: _RunScopeKey) -> None:
        """Cap pending-warning state across abnormal or concurrent runs.

        Must be called while holding self._lock.
        """
        overflow = len(self._pending_warning_touch_order) - self._max_pending_warning_keys
        if overflow <= 0:
            return

        candidates = [key for key in self._pending_warning_touch_order if key != protected_key]
        for key in candidates[:overflow]:
            self._drop_pending_warning_key_locked(key)

    def _queue_pending_warning(self, runtime: Runtime, warning: str) -> None:
        """Queue one transient warning for the current thread/run with caps."""
        pending_key = self._pending_key(runtime)
        with self._lock:
            warnings = self._pending_warnings[pending_key]
            if warning not in warnings:
                warnings.append(warning)
            if len(warnings) > _MAX_PENDING_WARNINGS_PER_RUN:
                del warnings[: len(warnings) - _MAX_PENDING_WARNINGS_PER_RUN]
            self._touch_pending_warning_key_locked(pending_key)
            self._prune_pending_warning_state_locked(protected_key=pending_key)

    def _count_after_call(self, scope_key: _RunScopeKey, name: str) -> int:
        """The windowed count of ``name`` if one more call to it were recorded.

        A full window drops its oldest entry for the new one, so a call that
        replaces an older call to the same tool does not raise the count. This
        is the count ``_record_call_locked`` would return, without recording.

        Must be called while holding self._lock.
        """
        history = self._tool_name_history[scope_key]
        overflow = len(history) + 1 - self._tool_freq_window
        evicted = sum(1 for old in islice(history, max(overflow, 0)) if old == name)
        return self._tool_name_counter[scope_key].get(name, 0) + 1 - evicted

    def _record_call_locked(self, scope_key: _RunScopeKey, name: str) -> int:
        """Record one call in the frequency window and return the tool's count.

        Windowed counting: append the name and trim to the frequency window
        (>= the largest threshold) so the count can reach the warn/hard limits
        on a tight burst yet still decay for spread-out calls. A mirrored
        Counter gives an O(1) count even when a per-tool override inflates the
        window globally.

        Must be called while holding self._lock.
        """
        history = self._tool_name_history[scope_key]
        counter = self._tool_name_counter[scope_key]
        history.append(name)
        counter[name] += 1
        while len(history) > self._tool_freq_window:
            old = history.popleft()
            c = counter[old] - 1
            if c <= 0:
                del counter[old]
            else:
                counter[old] = c
            old_warn = self._tool_freq_overrides.get(old, self._default_tool_freq_thresholds)[0]
            if c < old_warn:
                # Any tool can evict an older name from the shared window.
                # Rearm that name as soon as its burst decays, even when the
                # current call belongs to another tool.
                self._tool_freq_warned[scope_key].discard(old)
        return counter.get(name, 0)

    def _track_and_check(
        self,
        state: AgentState,
        runtime: Runtime,
        cap: _LoopCap | None = None,
    ) -> _LoopDecision | None:
        """Track tool calls and check for loops.

        Two detection layers:
          1. **Hash-based** (existing): catches identical tool call sets.
          2. **Frequency-based** (new): catches the same *tool type* being
             called many times with varying arguments (e.g. ``read_file``
             on 40 different files).

        ``cap`` names the tools that already reached their limit in this
        execution; their calls are rejected whatever the window now counts.

        Returns:
            A structured decision when a warning or hard stop is triggered.
        """
        messages = state.get("messages", [])
        if not messages:
            return None

        last_msg = messages[-1]
        if getattr(last_msg, "type", None) != "ai":
            return None

        tool_calls = getattr(last_msg, "tool_calls", None)
        if not tool_calls:
            return None

        scope_key = self._run_scope_key(runtime)
        thread_id, run_id = scope_key
        call_hash = _hash_tool_calls(tool_calls)

        with self._lock:
            # Touch / create entry (move to end for LRU)
            if scope_key in self._history:
                self._history.move_to_end(scope_key)
            else:
                self._history[scope_key] = []
                self._evict_if_needed()

            history = self._history[scope_key]
            history.append(call_hash)
            if len(history) > self.window_size:
                history[:] = history[-self.window_size :]

            warned_hashes = self._warned.get(scope_key)
            if warned_hashes is not None:
                warned_hashes.intersection_update(history)
                if not warned_hashes:
                    self._warned.pop(scope_key, None)

            count = history.count(call_hash)
            tool_names = [str(tc.get("name") or "?") for tc in tool_calls]

            # --- Layer 1: hash-based (identical call sets) ---
            if count >= self.hard_limit:
                logger.error(
                    "Loop hard limit reached — forcing stop",
                    extra={
                        "thread_id": thread_id,
                        "run_id": run_id,
                        "call_hash": call_hash,
                        "count": count,
                        "tools": tool_names,
                    },
                )
                return _LoopDecision(
                    message=_HARD_STOP_MSG,
                    action="hard_stop",
                    detection_layer="identical_call_set",
                    tool_names=tuple(tool_names),
                    count=count,
                    threshold=self.hard_limit,
                )

            # Warnings admit the whole batch, so they must not skip frequency
            # accounting or hide a later hard limit. Keep one candidate (hash
            # warnings retain priority over frequency warnings) until every
            # admitted call has been checked. Only the selected warning is
            # marked/logged; a hard stop may supersede it below.
            warning: _LoopDecision | None = None
            if count >= self.warn_threshold and call_hash not in self._warned.get(scope_key, set()):
                warning = _LoopDecision(
                    message=_WARNING_MSG,
                    action="warn",
                    detection_layer="identical_call_set",
                    tool_names=tuple(tool_names),
                    count=count,
                    threshold=self.warn_threshold,
                )

            # --- Layer 2: per-tool-type frequency (windowed) ---
            name_counter = self._tool_name_counter[scope_key]
            # A call that would reach its tool's hard limit is rejected instead
            # of stopping the whole batch, so calls within the limit still run.
            # Rejected calls never run and are not counted in the window.
            capped = cap.tools if cap is not None else {}
            rejected: list[int] = []
            limited: dict[str, tuple[int, int]] = {}
            # Tools that reach their limit in this response, with the count and
            # threshold of the crossing. One audit row is written for each.
            crossings: list[tuple[str, int, int]] = []
            for index, tc in enumerate(tool_calls):
                name = tc.get("name", "")
                if not name:
                    continue
                if name in capped:
                    # Capped earlier in this execution. The window may have
                    # decayed since, which must not reopen the tool.
                    limited.setdefault(name, (capped[name], capped[name]))
                    rejected.append(index)
                    continue
                if name in limited:
                    rejected.append(index)
                    continue
                eff_warn, eff_hard = self._tool_freq_overrides.get(name, self._default_tool_freq_thresholds)
                # Compare the count the call would leave in the window, after
                # the window has dropped its oldest entry. Counting before that
                # would reject a call that only replaces an older call to the
                # same tool, and cap an interleaved workflow that never reaches
                # the limit.
                prospective = self._count_after_call(scope_key, name)
                if prospective >= eff_hard:
                    limited[name] = (prospective, eff_hard)
                    crossings.append((name, prospective, eff_hard))
                    rejected.append(index)
                    continue
                freq_count = self._record_call_locked(scope_key, name)

                if freq_count >= eff_warn:
                    freq_warned = self._tool_freq_warned[scope_key]
                    if warning is None and name not in freq_warned:
                        warning = _LoopDecision(
                            message=_TOOL_FREQ_WARNING_MSG.format(tool_name=name, count=freq_count),
                            action="warn",
                            detection_layer="tool_frequency",
                            tool_names=(name,),
                            count=freq_count,
                            threshold=eff_warn,
                        )
                else:
                    # Windowed count decayed below the warn threshold; allow a
                    # future burst of this tool to warn again.
                    self._tool_freq_warned[scope_key].discard(name)

            first_limit = next(iter(limited.items()), None)
            if first_limit is not None and len(rejected) == sum(1 for tc in tool_calls if tc.get("name")):
                # No call fits: stop the run as before.
                name, (freq_count, eff_hard) = first_limit
                if name in capped:
                    message = _TOOL_CAPPED_HARD_STOP_MSG.format(tool_name=name, limit=eff_hard)
                else:
                    # Count the call that reached the limit so later checks see
                    # the exhausted window.
                    self._record_call_locked(scope_key, name)
                    message = _TOOL_FREQ_HARD_STOP_MSG.format(tool_name=name, count=freq_count)
                logger.error(
                    "Tool frequency hard limit reached — forcing stop",
                    extra={
                        "thread_id": thread_id,
                        "run_id": run_id,
                        "tool_name": name,
                        "count": freq_count,
                    },
                )
                return _LoopDecision(
                    message=message,
                    action="hard_stop",
                    detection_layer="tool_frequency",
                    tool_names=(name,),
                    count=freq_count,
                    threshold=eff_hard,
                )

            if warning is not None:
                if warning.detection_layer == "identical_call_set":
                    self._warned[scope_key].add(call_hash)
                    logger.warning(
                        "Repetitive tool calls detected — injecting warning",
                        extra={
                            "thread_id": thread_id,
                            "run_id": run_id,
                            "call_hash": call_hash,
                            "count": warning.count,
                            "tools": list(warning.tool_names),
                        },
                    )
                else:
                    warned_name = warning.tool_names[0]
                    # Later calls in this batch may already have decayed this
                    # burst. Do not suppress the next burst with a stale mark.
                    if name_counter.get(warned_name, 0) >= warning.threshold:
                        self._tool_freq_warned[scope_key].add(warned_name)
                    logger.warning(
                        "Tool frequency warning — too many calls to same tool type",
                        extra={
                            "thread_id": thread_id,
                            "run_id": run_id,
                            "tool_name": warned_name,
                            "count": warning.count,
                        },
                    )

            if first_limit is not None:
                # Some calls fit: run them and drop only the calls past a limit.
                _, (freq_count, eff_hard) = first_limit
                logger.warning(
                    "Tool frequency hard limit reached inside a batch — dropping the calls past the limit",
                    extra={
                        "thread_id": thread_id,
                        "run_id": run_id,
                        "tools": list(limited),
                        "rejected": len(rejected),
                        "batch": len(tool_calls),
                    },
                )
                return _LoopDecision(
                    # Not shown to the model: it reads the explanation built
                    # from the cap record in ``wrap_model_call``.
                    message=f"Dropped {len(rejected)} of {len(tool_calls)} tool calls past a per-tool limit",
                    action="reject_excess",
                    detection_layer="tool_frequency",
                    tool_names=tuple(limited),
                    count=freq_count,
                    threshold=eff_hard,
                    rejected_indices=tuple(rejected),
                    limits={name: hard for name, (_, hard) in limited.items()},
                    crossings=tuple(crossings),
                    # A frequency warning for a tool that just hit its limit
                    # says less than the rejection itself, so it is not repeated.
                    companion_warning=None if warning is None or (warning.detection_layer == "tool_frequency" and warning.tool_names[0] in limited) else warning.message,
                )
            return warning

    @staticmethod
    def _append_text(content: str | list | None, text: str) -> str | list:
        """Append *text* to AIMessage content, handling str, list, and None.

        When content is a list of content blocks (e.g. Anthropic thinking mode),
        we append a new ``{"type": "text", ...}`` block instead of concatenating
        a string to a list, which would raise ``TypeError``.
        """
        if content is None:
            return text
        if isinstance(content, list):
            return [*content, {"type": "text", "text": f"\n\n{text}"}]
        if isinstance(content, str):
            return content + f"\n\n{text}"
        # Fallback: coerce unexpected types to str to avoid TypeError
        return str(content) + f"\n\n{text}"

    def _record_audit_event(
        self,
        decision: _LoopDecision,
        runtime: Runtime,
    ) -> None:
        """Persist a loop-detection transition without sensitive tool data."""
        recorder, is_subagent, agent_id = resolve_audit_recorder(
            getattr(runtime, "context", None),
            recorder_key=LOOP_DETECTION_RECORDER_CONTEXT_KEY,
        )
        if recorder is None:
            return

        try:
            recorder.record_middleware(
                tag=MIDDLEWARE_LOOP_DETECTION_TAG,
                name=type(self).__name__,
                hook="after_model",
                action=decision.action,
                changes={
                    "is_subagent": is_subagent,
                    "agent_id": agent_id,
                    "detection_layer": decision.detection_layer,
                    "tool_names": list(decision.tool_names),
                    "count": decision.count,
                    "threshold": decision.threshold,
                },
            )
        except Exception:  # noqa: BLE001
            # Audit persistence must never break the agent run.
            logger.warning(
                "Failed to record middleware:loop_detection event",
                exc_info=True,
            )

    def _record_run_id(self, runtime: Runtime) -> str | None:
        """The current run as the cap record stores it."""
        run_id = self._get_run_id(runtime)
        return None if run_id is None else str(run_id)

    def _report_cap(self, runtime: Runtime, *, terminal: bool) -> None:
        """Surface ``stop_reason=loop_capped`` for the current run (#3875 Phase 2).

        A cap does not raise: the run finishes with an answer, so without this
        the caller would see a clean completion. There are two channels. The
        subagent executor reads ``consume_stop_reason`` after the run returns;
        the lead worker (#4176) and Goal continuation read
        ``runtime.context["stop_reason"]`` when the run is over. Run-input
        admission, the todo middleware and the end-of-graph input handling also
        read that key while the run goes on, as "the run is ending: skip your
        checks".

        ``terminal`` is a response with no call left, which ends the run: both
        channels are written now, replacing another guard's reason as every
        hard stop does. Otherwise the run goes on and its admitted calls must
        pass those checks, so ``_finish`` reports when the run ends, and only
        when no other guard has already given the reason it stopped. Both
        channels then name the same guard. Written under the lock to match
        ``TokenBudgetMiddleware``: the lead agent's middleware instance is
        shared across concurrent Gateway threads.
        """
        thread_id, run_id = self._run_scope_key(runtime)
        ctx = getattr(runtime, "context", None)
        ctx = ctx if isinstance(ctx, dict) else None
        if not terminal and ctx is not None and ctx.get("stop_reason") not in (None, "loop_capped"):
            return
        with self._lock:
            self._stop_reason[run_id] = "loop_capped"
            self._stop_reason_thread_id[run_id] = thread_id
        if ctx is not None:
            ctx["stop_reason"] = "loop_capped"

    def _snapshot_locked(self, scope_key: _RunScopeKey) -> dict:
        """Copy the loop state of one run scope. Must be called while holding self._lock."""
        names = self._tool_name_history.get(scope_key)
        counter = self._tool_name_counter.get(scope_key)
        warned = self._warned.get(scope_key)
        freq_warned = self._tool_freq_warned.get(scope_key)
        pending = self._pending_warnings.get(scope_key)
        history = self._history.get(scope_key)
        return {
            "history": list(history) if history is not None else None,
            "warned": frozenset(warned) if warned is not None else None,
            "names": tuple(names) if names is not None else None,
            "counter": dict(counter) if counter is not None else None,
            "freq_warned": frozenset(freq_warned) if freq_warned is not None else None,
            "pending_warnings": tuple(pending) if pending is not None else None,
        }

    def _restore_locked(self, scope_key: _RunScopeKey, admission: _Admission) -> None:
        """Put back the loop state from before ``admission``. Must be called while holding self._lock."""
        if admission.history is None:
            self._history.pop(scope_key, None)
        else:
            self._history[scope_key] = list(admission.history)
        for mapping, value in (
            (self._warned, admission.warned),
            (self._tool_freq_warned, admission.freq_warned),
        ):
            if value is None:
                mapping.pop(scope_key, None)
            else:
                mapping[scope_key] = set(value)
        if admission.names is None:
            self._tool_name_history.pop(scope_key, None)
            self._tool_name_counter.pop(scope_key, None)
        else:
            self._tool_name_history[scope_key] = deque(admission.names)
            self._tool_name_counter[scope_key] = Counter(admission.counter or {})
        if admission.pending_warnings is None:
            self._drop_pending_warning_key_locked(scope_key)
        else:
            self._pending_warnings[scope_key] = list(admission.pending_warnings)
            self._touch_pending_warning_key_locked(scope_key)

    def _settle_admission(self, state: object, runtime: Runtime) -> None:
        """Undo the accounting of a response whose admitted calls were all discarded.

        Runs as the next model call starts. If none of the calls this
        middleware passed on is still in that response, another middleware
        discarded them before they ran, so the response counts as if it had not
        been made: the frequency window, the warning state and the cap record go
        back to what they were before it. Caps from earlier responses stay. A
        response that is no longer in the history (compaction) keeps its
        accounting.
        """
        scope_key = self._run_scope_key(runtime)
        with self._lock:
            admission = self._admissions.pop(scope_key, None)
        if admission is None or not isinstance(state, Mapping):
            return
        source = next((m for m in reversed(state.get("messages") or []) if getattr(m, "id", None) == admission.message_id), None)
        if source is None:
            return
        standing = {tc.get("id") for tc in (getattr(source, "tool_calls", None) or [])}
        if standing & admission.call_ids:
            return
        with self._lock:
            self._restore_locked(scope_key, admission)
            self._record_overrides[scope_key] = admission.record
            self._record_overrides.move_to_end(scope_key)
            while len(self._record_overrides) > self._max_admissions:
                self._record_overrides.popitem(last=False)
        thread_id, run_id = scope_key
        logger.info(
            "Loop detection undid the accounting of a response whose calls were discarded before they ran",
            extra={"thread_id": thread_id, "run_id": run_id, "calls": len(admission.call_ids)},
        )

    def _current_record(self, scope_key: _RunScopeKey, state: object, *, consume: bool) -> object:
        """The cap record in force: an undone admission's record, else the checkpointed one."""
        with self._lock:
            if scope_key in self._record_overrides:
                return self._record_overrides.pop(scope_key) if consume else self._record_overrides[scope_key]
        return state.get(LOOP_CAP_STATE_KEY) if isinstance(state, Mapping) else None

    @staticmethod
    def _admitted_calls(last_msg, decision: _LoopDecision) -> list[dict]:
        """The calls of a trimmed response that go on to the tools node."""
        calls = last_msg.tool_calls
        rejected = set(decision.rejected_indices)
        # Provider surfaces are synced by call id, so a call that shares its id
        # with a rejected call cannot be kept on its own.
        rejected_ids = {call_id for index in rejected if isinstance(call_id := calls[index].get("id"), str) and call_id}
        return [tc for index, tc in enumerate(calls) if index not in rejected and tc.get("id") not in rejected_ids]

    def _apply(self, state: AgentState, runtime: Runtime) -> dict | None:
        stored = state.get(LOOP_CAP_STATE_KEY)
        scope_key = self._run_scope_key(runtime)
        cap = _read_loop_cap(self._current_record(scope_key, state, consume=True))
        messages = state.get("messages", [])
        last_msg = messages[-1] if messages else None
        calls = list(getattr(last_msg, "tool_calls", None) or []) if getattr(last_msg, "type", None) == "ai" else []
        snapshot = None
        if calls:
            with self._lock:
                snapshot = self._snapshot_locked(scope_key)
        decision = self._track_and_check(state, runtime, cap)

        next_cap = cap
        if cap is not None:
            # The run carries a cap from an earlier response, possibly from
            # before an approval pause. The model has now answered the request
            # that explained the cap, so the notice is delivered.
            next_cap = replace(cap, run_id=self._record_run_id(runtime), notice=None)
        baseline = next_cap.dump() if next_cap is not None else None
        admitted = calls

        update: dict = {}
        if decision is not None:
            # Keep the shared loop-detection lock's critical section bounded; the
            # journal append is cheap and non-blocking but does not belong under
            # it. A dropped batch is audited once per tool that reached its limit
            # in it, with that tool's own count and threshold; a repeated
            # rejection of an already capped tool is no transition.
            if decision.action == "reject_excess":
                for name, count, threshold in decision.crossings:
                    self._record_audit_event(replace(decision, tool_names=(name,), count=count, threshold=threshold), runtime)
            else:
                self._record_audit_event(decision, runtime)

            if decision.action == "warn":
                # Defer injection to the next model call. We must NOT alter the
                # AIMessage(tool_calls=...) here (would put framework words in
                # the model's mouth, polluting downstream consumers like
                # MemoryMiddleware), nor insert a separate non-tool message
                # (would break OpenAI/Moonshot tool-call pairing because the
                # tools node has not produced ToolMessage responses yet). The
                # warning is delivered via ``wrap_model_call`` below.
                self._queue_pending_warning(runtime, decision.message)
            else:
                kept = self._admitted_calls(last_msg, decision) if decision.action == "reject_excess" else []
                admitted = kept
                capped_tools = _recordable_caps(cap.tools if cap is not None else {}, decision.limits)
                if not kept:
                    self._report_cap(runtime, terminal=True)
                if kept:
                    # Run the calls within the limit and drop the rest. Like a
                    # warning, the explanation reaches the model on its next
                    # call; it is read from the cap record, so it survives a
                    # pause between this response and that call.
                    total = len(last_msg.tool_calls)
                    notice = _CapNotice(total=total, skipped=total - len(kept), tools=tuple(name for name in decision.tool_names if name in capped_tools))
                    next_cap = _LoopCap(run_id=self._record_run_id(runtime), tools=capped_tools, notice=notice)
                    if decision.companion_warning:
                        self._queue_pending_warning(runtime, decision.companion_warning)
                    update["messages"] = [clone_ai_message_with_tool_calls(last_msg, kept)]
                else:
                    # Strip tool calls from every provider surface of the last
                    # AIMessage (structured, raw, and content blocks) to force
                    # text output. With no call left on any surface, the
                    # AIMessage no longer requires matching ToolMessage
                    # responses, so replacing it here is safe for strict
                    # provider pairing validators.
                    if decision.hard_stop:
                        text = decision.message or _HARD_STOP_MSG
                    else:
                        text = _TOOL_FREQ_HARD_STOP_MSG.format(tool_name=decision.tool_names[0], count=decision.threshold)
                        next_cap = _LoopCap(run_id=self._record_run_id(runtime), tools=capped_tools)
                    content = self._append_text(last_msg.content, text)
                    update["messages"] = [clone_ai_message_with_tool_calls(last_msg, [], content=content)]

        call_ids = frozenset(call_id for tc in admitted if isinstance(call_id := tc.get("id"), str) and call_id)
        message_id = getattr(last_msg, "id", None)
        if snapshot is not None and call_ids and isinstance(message_id, str) and message_id:
            with self._lock:
                self._admissions[scope_key] = _Admission(message_id=message_id, call_ids=call_ids, record=baseline, **snapshot)
                self._admissions.move_to_end(scope_key)
                while len(self._admissions) > self._max_admissions:
                    self._admissions.popitem(last=False)

        value = next_cap.dump() if next_cap is not None else None
        if value != stored:
            update[LOOP_CAP_STATE_KEY] = value
        return update or None

    def _expire_cap(self, state: AgentState, runtime: Runtime) -> dict | None:
        """Give a new task a fresh budget.

        ``before_agent`` runs when a task enters the graph and not when a
        paused run resumes, so a cap that another run left behind belongs to an
        earlier, finished execution. A later entry of the run that owns the cap
        (a hidden goal continuation) keeps it.
        """
        stored = state.get(LOOP_CAP_STATE_KEY)
        if stored is None:
            return None
        cap = _read_loop_cap(stored)
        run_id = self._record_run_id(runtime)
        if cap is not None and run_id is not None and cap.run_id == run_id:
            return None
        return {LOOP_CAP_STATE_KEY: None}

    def _finish(self, state: AgentState, runtime: Runtime) -> dict | None:
        update = None
        cap = _read_loop_cap(state.get(LOOP_CAP_STATE_KEY))
        if cap is not None:
            # The run is over, so the report no longer suspends any check.
            # ``after_agent`` hooks run in reverse middleware order, so the
            # end-of-graph input handling appended after this middleware has
            # already run. This also covers a resumed run that ends without
            # another model call, and it hands the cap to this run for any
            # later entry of it.
            self._report_cap(runtime, terminal=False)
            run_id = self._record_run_id(runtime)
            if cap.run_id != run_id:
                update = {LOOP_CAP_STATE_KEY: replace(cap, run_id=run_id).dump()}
        # Resolved before taking the lock: a fallback run id takes it too.
        scope_key = self._run_scope_key(runtime)
        with self._lock:
            self._admissions.pop(scope_key, None)
            self._record_overrides.pop(scope_key, None)
        self._clear_current_run_pending_warnings(runtime)
        self._release_fallback_run_id(runtime)
        return update

    def _clear_current_run_pending_warnings(self, runtime: Runtime) -> None:
        """Drop pending warnings owned by the current thread/run."""
        pending_key = self._pending_key(runtime)
        with self._lock:
            self._drop_pending_warning_key_locked(pending_key)

    @staticmethod
    def _format_warning_message(warnings: list[str]) -> str:
        """Merge pending warnings into one prompt message."""
        deduped = list(dict.fromkeys(warnings))
        return "\n\n".join(deduped)

    @override
    def before_agent(self, state: AgentState, runtime: Runtime) -> dict | None:
        # Pending warnings are already run-scoped; touching sibling runs here
        # would break overlapping invocations, while after_agent and the bounded
        # queue own cleanup. Only the checkpointed cap is expired here.
        return self._expire_cap(state, runtime)

    @override
    async def abefore_agent(self, state: AgentState, runtime: Runtime) -> dict | None:
        # Async topology must mirror the sync hook above.
        return self._expire_cap(state, runtime)

    @override
    def after_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        return self._apply(state, runtime)

    @override
    async def aafter_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        return self._apply(state, runtime)

    @override
    def after_agent(self, state: AgentState, runtime: Runtime) -> dict | None:
        return self._finish(state, runtime)

    @override
    async def aafter_agent(self, state: AgentState, runtime: Runtime) -> dict | None:
        return self._finish(state, runtime)

    def _drain_pending_warnings(self, runtime: Runtime) -> list[str]:
        """Pop and return all queued warnings for *runtime*'s thread/run."""
        pending_key = self._pending_key(runtime)
        with self._lock:
            warnings = self._pending_warnings.pop(pending_key, [])
            self._pending_warning_touch_order.pop(pending_key, None)
        return warnings

    def _restore_pending_warnings(self, runtime: Runtime, warnings: list[str]) -> None:
        """Requeue warnings taken for a model call that raised.

        LLMErrorHandlingMiddleware sits outside this middleware and retries a
        failed call by running this wrap again, so the retry must still find
        the warning. It would not be queued again: it is already marked warned.
        """
        if not warnings:
            return
        pending_key = self._pending_key(runtime)
        with self._lock:
            queued = self._pending_warnings[pending_key]
            queued[:0] = [warning for warning in warnings if warning not in queued]
            # Keep the restored warnings at the front; trim what came after them.
            del queued[_MAX_PENDING_WARNINGS_PER_RUN:]
            self._touch_pending_warning_key_locked(pending_key)
            self._prune_pending_warning_state_locked(protected_key=pending_key)

    def _inject_warnings(self, request: ModelRequest, warnings: list[str]) -> ModelRequest:
        """Append *warnings* to the outgoing message list.

        The warning is placed *after* every existing message, including the
        ToolMessage responses to the previous AIMessage(tool_calls). This
        keeps ``assistant tool_calls -> tool_messages`` pairing intact for
        OpenAI/Moonshot, avoids the Anthropic mid-stream SystemMessage
        restriction (we use HumanMessage), and never mutates an existing
        AIMessage.
        """
        if not warnings:
            return request
        new_messages = [
            *request.messages,
            HumanMessage(content=self._format_warning_message(warnings), name="loop_warning"),
        ]
        return request.override(messages=new_messages)

    def _cap_notice(self, request: ModelRequest) -> list[str]:
        """The explanation of a trimmed response, read from the checkpointed cap.

        It is derived on every call rather than queued, so a retried call and a
        call made after an approval resume or a restart still carry it.
        ``after_model`` clears it once the model has answered.
        """
        state = getattr(request, "state", None)
        cap = _read_loop_cap(self._current_record(self._run_scope_key(request.runtime), state, consume=False))
        if cap is None:
            return []
        text = cap.notice_text()
        return [text] if text else []

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        self._settle_admission(getattr(request, "state", None), request.runtime)
        notice = self._cap_notice(request)
        warnings = self._drain_pending_warnings(request.runtime)
        try:
            return handler(self._inject_warnings(request, [*notice, *warnings]))
        except Exception:
            self._restore_pending_warnings(request.runtime, warnings)
            raise

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        self._settle_admission(getattr(request, "state", None), request.runtime)
        notice = self._cap_notice(request)
        warnings = self._drain_pending_warnings(request.runtime)
        try:
            return await handler(self._inject_warnings(request, [*notice, *warnings]))
        except Exception:
            self._restore_pending_warnings(request.runtime, warnings)
            raise

    def reset(self, thread_id: str | None = None) -> None:
        """Clear tracking state. If thread_id given, clear only that thread."""
        with self._lock:
            if thread_id:
                for mapping in (
                    self._history,
                    self._warned,
                    self._tool_name_history,
                    self._tool_name_counter,
                    self._tool_freq_warned,
                    self._admissions,
                    self._record_overrides,
                ):
                    for key in list(mapping):
                        if key[0] == thread_id:
                            mapping.pop(key, None)
                pending_keys = set(self._pending_warnings) | set(self._pending_warning_touch_order)
                for key in pending_keys:
                    if key[0] == thread_id:
                        self._drop_pending_warning_key_locked(key)
                for run_id, owner_thread_id in list(self._stop_reason_thread_id.items()):
                    if owner_thread_id == thread_id:
                        self._stop_reason.pop(run_id, None)
                        self._stop_reason_thread_id.pop(run_id, None)
            else:
                self._history.clear()
                self._warned.clear()
                self._tool_name_history.clear()
                self._tool_name_counter.clear()
                self._tool_freq_warned.clear()
                self._pending_warnings.clear()
                self._pending_warning_touch_order.clear()
                self._stop_reason.clear()
                self._stop_reason_thread_id.clear()
                self._fallback_run_ids.clear()
                self._admissions.clear()
                self._record_overrides.clear()
