"""Middleware to enforce per-run token budget limits.
Tracks cumulative token usage (input, output, total) across model calls within
a single agent run and enforces configurable soft-warning and hard-stop
thresholds.
Detection strategy:
  1. Confirm each observed model response in graph state and count its native
     usage once. Scan per-message usage deltas for later subagent additions;
     provider message IDs alone cannot identify distinct model calls.
     Attempts discarded by outer retry middleware are intentionally not charged;
     this budget tracks accepted responses, not all billable provider attempts.
  2. If the highest fraction (input, output, or total) >= warn_threshold,
     queue a warning.
  3. If the highest fraction >= hard_stop_threshold, strip unexecuted calls
     from every provider surface, preserving already-returned structured results.
Warning injection uses the deferred pattern:
  - after_model queues the warning (does NOT mutate state).
  - wrap_model_call injects it as a HumanMessage at the next model call.
This preserves AIMessage(tool_calls) → ToolMessage pairing.

Run scope:
  Usage and warning state are keyed by ``run_id`` and survive ``after_agent``.
  A single Gateway run may re-enter the graph for hidden goal continuations,
  and those continuations share one budget; a later user run gets a new
  ``run_id`` and a fresh budget. Only the per-message ``seen`` map is dropped
  (``before_agent`` rebuilds it). Invocations without a non-empty string
  ``run_id`` are keyed by LangGraph's run-scoped ``Runtime.control`` object
  (each graph node gets its own ``Runtime`` wrapper, but they share it) and
  clear their usage/warning state in ``after_agent``.

Stop-reason surfacing (#3875 Phase 2):
  The hard stop does NOT raise — it strips tool_calls so the agent loop
  terminates naturally and produces a final answer. To let the caller (e.g.
  the subagent executor) distinguish a budget-capped completion from a clean
  one, the run that triggered the hard stop is recorded in ``_stop_reason``
  and exposed via :meth:`consume_stop_reason`. It is keyed by the context
  ``run_id`` exactly as given, ``None`` included, because that is what the
  executor passes back. That dict is intentionally NOT
  cleared by ``after_agent``/``_clear_run_state`` so the executor can read it
  after the run returns; the bounded dict prevents unbounded growth on
  abandoned runs, and each subagent run builds a fresh middleware instance so
  there is no cross-run contamination.
"""

from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.runtime import Runtime

from deerflow.agents.middlewares._bounded_dict import BoundedDict
from deerflow.agents.middlewares.model_response import last_ai_message
from deerflow.agents.middlewares.tool_call_metadata import clone_ai_message_with_tool_calls
from deerflow.config.token_budget_config import TokenBudgetConfig

logger = logging.getLogger(__name__)

_BUDGET_WARNING_MSG = (
    "[TOKEN BUDGET WARNING] You have used {used:,} of your {budget:,} {reason} token budget ({percent:.0f}%). Wrap up your current work and produce a final answer. Avoid starting new tool calls unless absolutely necessary."
)
_BUDGET_EXCEEDED_MSG = "[TOKEN BUDGET EXCEEDED] The {reason} token usage ({used:,}) has exceeded the safety limit ({budget:,}). Producing final answer with results collected so far."


@dataclass
class TokenUsage:
    input: int = 0
    output: int = 0
    total: int = 0


@dataclass(slots=True)
class _PendingModelCall:
    """A model call observation recorded by ``wrap_model_call`` and confirmed
    by ``_apply``.  Holds an immutable usage snapshot and message identity so
    each independent model call is counted once even when the provider reuses
    the same ``AIMessage.id`` (which makes the diff-based scan see zero delta).
    """

    message: AIMessage | None  # short-lived ref for identity matching
    message_id: str | None  # original provider ID (may differ from state)
    input_tokens: int  # immutable snapshot — never mutated after construction
    output_tokens: int
    completed_call_ids: frozenset[str]


class TokenBudgetMiddleware(AgentMiddleware[AgentState]):
    """Enforce per-run token budget limits."""

    def __init__(self, config: TokenBudgetConfig) -> None:
        super().__init__()
        self._config = config
        self._lock = threading.Lock()

        # Keyed strictly by run_id (clobber-safe) and bounded (leak-safe)
        self._warned: BoundedDict[str, bool] = BoundedDict(1000)
        self._pending_warnings: BoundedDict[str, list[str]] = BoundedDict(1000)
        self._seen_messages: BoundedDict[str, dict[str, tuple[int, int]]] = BoundedDict(1000)
        self._cumulative_usage: BoundedDict[str, TokenUsage] = BoundedDict(1000)
        # Per-run pending model-call observations recorded by wrap_model_call
        # and consumed by _apply.  Keyed by run_id and bounded so abandoned
        # runs cannot leak.  See ``_PendingModelCall``.
        self._pending_model_calls: BoundedDict[str, _PendingModelCall] = BoundedDict(1000)
        # Stop reason set when the hard-stop fires. NOT cleared by
        # ``_clear_run_state``/``after_agent`` so the executor can consume it
        # after the run returns; bounded so abandoned runs cannot leak.
        self._stop_reason: BoundedDict[str | None, str] = BoundedDict(1000)
        # id(Runtime.control) -> (control, generated key) for invocations
        # without a context run_id; released in ``after_agent``.
        self._fallback_run_ids: BoundedDict[int, tuple[object, str]] = BoundedDict(1000)

    def release_policy_parameters(self) -> dict[str, object]:
        return {"config": self._config.model_dump(mode="python")}

    @classmethod
    def from_config(cls, config: TokenBudgetConfig) -> TokenBudgetMiddleware:
        return cls(config=config)

    def reset(self) -> None:
        with self._lock:
            self._warned.clear()
            self._pending_warnings.clear()
            self._seen_messages.clear()
            self._cumulative_usage.clear()
            self._stop_reason.clear()
            self._fallback_run_ids.clear()
            self._pending_model_calls.clear()

    def consume_stop_reason(self, run_id: str | None) -> str | None:
        """Pop and return the stop reason the hard-stop set for this run.

        Returns ``"token_capped"`` when the budget hard-stop fired during the
        run, otherwise ``None``. The executor calls this after the run returns
        to decide whether a completed subagent was actually budget-capped
        (and should carry ``stop_reason=token_capped`` to the lead). Popping
        keeps the dict from accumulating across runs on a reused instance.
        """
        with self._lock:
            return self._stop_reason.pop(run_id, None)

    @staticmethod
    def _context_run_id(runtime: Runtime) -> str | None:
        """Resolve the explicit identity shared by continuation invocations."""
        ctx = getattr(runtime, "context", None)
        run_id = ctx.get("run_id") if isinstance(ctx, dict) else None
        return run_id if isinstance(run_id, str) and run_id else None

    def _get_run_id(self, runtime: Runtime) -> str:
        run_id = self._context_run_id(runtime)
        if run_id is not None:
            return run_id
        # Same anchor as LoopDetectionMiddleware: ``id(runtime)`` changes from
        # one graph node to the next, ``Runtime.control`` does not. The key is a
        # generated token rather than the address, which can be reused once the
        # object is collected. Unlike loop detection, ``execution_info.run_id``
        # is skipped on purpose: without a context run_id the budget is per
        # invocation, not per RunnableConfig run.
        control = getattr(runtime, "control", None)
        anchor = control if control is not None else runtime
        with self._lock:
            entry = self._fallback_run_ids.get(id(anchor))
            if entry is None or entry[0] is not anchor:
                entry = (anchor, f"__invocation__:{uuid.uuid4().hex}")
                self._fallback_run_ids[id(anchor)] = entry
            # Least recently used goes first, so a full map never evicts an active invocation.
            self._fallback_run_ids.move_to_end(id(anchor))
            return entry[1]

    def _release_fallback_run_id(self, runtime: Runtime) -> None:
        control = getattr(runtime, "control", None)
        anchor = control if control is not None else runtime
        with self._lock:
            entry = self._fallback_run_ids.get(id(anchor))
            if entry is not None and entry[0] is anchor:
                del self._fallback_run_ids[id(anchor)]

    @staticmethod
    def _stop_reason_key(runtime: Runtime, run_id: str) -> str | None:
        # SubagentExecutor consumes the stop reason with its raw run_id, which
        # is None when the parent run has none.
        ctx = getattr(runtime, "context", None)
        if isinstance(ctx, dict) and "run_id" in ctx and (ctx["run_id"] is None or isinstance(ctx["run_id"], str)):
            return ctx["run_id"]
        return run_id

    def _clear_run_state(self, run_id: str) -> None:
        with self._lock:
            self._warned.pop(run_id, None)
            self._pending_warnings.pop(run_id, None)
            self._seen_messages.pop(run_id, None)
            self._cumulative_usage.pop(run_id, None)
            self._pending_model_calls.pop(run_id, None)

    @override
    def before_agent(self, state: AgentState, runtime: Runtime) -> None:
        if not self._config.enabled:
            return

        # Mark all old messages from previous runs as 'seen' so they don't count toward THIS run's budget
        messages = state.get("messages", [])
        run_id = self._get_run_id(runtime)
        with self._lock:
            # A new invocation must not reuse a pending observation from the
            # previous invocation (which may have ended without ``after_model``).
            self._pending_model_calls.pop(run_id, None)
            if not messages:
                return
            seen = self._seen_messages.setdefault(run_id, {})
            self._cumulative_usage.setdefault(run_id, TokenUsage())

            for msg in messages:
                if isinstance(msg, AIMessage) and msg.id and hasattr(msg, "usage_metadata"):
                    usage = msg.usage_metadata or {}
                    input_tokens = usage.get("input_tokens", 0)
                    output_tokens = usage.get("output_tokens", 0)
                    seen[msg.id] = (input_tokens, output_tokens)

    @override
    async def abefore_agent(self, state: AgentState, runtime: Runtime) -> None:
        self.before_agent(state, runtime)

    @override
    def after_agent(self, state: AgentState, runtime: Runtime) -> None:
        if not self._config.enabled:
            return
        run_id = self._get_run_id(runtime)
        if self._context_run_id(runtime) is not None:
            # A Gateway run re-enters the graph for hidden goal continuations
            # under the same run_id, and they share this run's budget. Keep the
            # usage and warning state; before_agent rebuilds the seen map.
            # Clear only the pending observation — a continuation must not
            # reuse the previous invocation's unconfirmed model call.
            with self._lock:
                self._seen_messages.pop(run_id, None)
                self._pending_model_calls.pop(run_id, None)
            return
        self._clear_run_state(run_id)
        self._release_fallback_run_id(runtime)

    @override
    async def aafter_agent(self, state: AgentState, runtime: Runtime) -> None:
        self.after_agent(state, runtime)

    @staticmethod
    def _append_text(content: str | list[dict | None] | None, stop_msg: str) -> str | list[dict | str]:
        """Append a stop message to an AIMessage.content field."""
        if content is None:
            return stop_msg
        if isinstance(content, str):
            if content:
                return f"{content}\n\n{stop_msg}"
            return f"\n\n{stop_msg}"
        if isinstance(content, list):
            new_content = list(content)
            new_content.append({"type": "text", "text": f"\n\n{stop_msg}"})
            return new_content
        return f"{content}\n\n{stop_msg}"

    def _build_hard_stop_update(self, msg: AIMessage, stop_msg: str, *, completed_call_ids: frozenset[str] = frozenset()) -> dict[str, Any]:
        """Build the state update dictionary for a hard stop."""
        # Structured-output handlers can return an AIMessage and its completed
        # ToolMessage together. Dropping those calls would orphan their results
        # in the next model request; only unexecuted calls need suppression.
        retained = [call for call in msg.tool_calls if isinstance(call.get("id"), str) and call["id"] in completed_call_ids] if completed_call_ids else []
        stopped_msg = clone_ai_message_with_tool_calls(msg, retained, content=self._append_text(msg.content, stop_msg))
        return {"messages": [stopped_msg]}

    def _apply(self, state: AgentState, runtime: Runtime) -> dict | None:
        if not self._config.enabled:
            return None

        messages = state.get("messages", [])
        run_id = self._get_run_id(runtime)

        with self._lock:
            pending = self._pending_model_calls.pop(run_id, None)
            last = messages[-1] if messages else None
            # The outer error handler may discard the observed response and
            # publish a new fallback. Do not match that discarded response to
            # an old same-ID message still present in history.
            if isinstance(last, AIMessage) and last.additional_kwargs.get("deerflow_error_fallback") is True and pending is not None and not self._matches_pending(last, pending):
                pending = None
            # Reducers replace a reused ID at its original position (A,B,A),
            # so neither the last item nor the last AIMessage identifies the
            # current response. Prefer its object anywhere before trying IDs.
            current = None
            if pending is not None:
                current = next((msg for msg in messages if isinstance(msg, AIMessage) and msg is pending.message), None)
                if current is None:
                    current = next((msg for msg in reversed(messages) if isinstance(msg, AIMessage) and self._matches_pending(msg, pending)), None)
            confirmed = current is not None
            if current is None:
                current = last if isinstance(last, AIMessage) else None
            if current is None:
                return None

            seen = self._seen_messages.setdefault(run_id, {})
            usage_accum = self._cumulative_usage.setdefault(run_id, TokenUsage())

            # Confirm the pending model-call observation recorded by
            # ``wrap_model_call``.  When the provider reuses the same
            # ``AIMessage.id`` across distinct calls, the diff-based scan
            # below sees zero delta for the second call and silently drops its
            # tokens.  The pending observation accounts for the call's full
            # native usage once, independent of the diff.  The ``seen`` baseline
            # is then set to this call's native usage so the scan does not
            # re-count it; the scan still catches retroactive subagent-usage
            # increments (usage that grows after the message enters state).
            if confirmed and pending is not None:
                usage_accum.input += pending.input_tokens
                usage_accum.output += pending.output_tokens
                usage_accum.total += pending.input_tokens + pending.output_tokens
                seen_key = current.id or pending.message_id
                if seen_key:
                    seen[seen_key] = (pending.input_tokens, pending.output_tokens)

            for msg in messages:
                if isinstance(msg, AIMessage) and msg.id and hasattr(msg, "usage_metadata"):
                    usage = msg.usage_metadata or {}

                    input_tokens = usage.get("input_tokens", 0)
                    output_tokens = usage.get("output_tokens", 0)

                    # Check what previously recorded for this exact message
                    prev_input, prev_output = seen.get(msg.id, (0, 0))

                    # Calculate if any new tokens were added (handles retroactive subagent tokens)
                    diff_input = max(0, input_tokens - prev_input)
                    diff_output = max(0, output_tokens - prev_output)

                    if diff_input > 0 or diff_output > 0:
                        usage_accum.input += diff_input
                        usage_accum.output += diff_output
                        usage_accum.total += diff_input + diff_output
                        seen[msg.id] = (input_tokens, output_tokens)

            if usage_accum.total <= 0:
                return None

            fractions = [("total", usage_accum.total, self._config.max_tokens)]
            if self._config.max_input_tokens:
                fractions.append(("input", usage_accum.input, self._config.max_input_tokens))
            if self._config.max_output_tokens:
                fractions.append(("output", usage_accum.output, self._config.max_output_tokens))

            highest_fraction = 0.0
            trigger_reason = ""
            trigger_used = 0
            trigger_budget = 0

            for reason, used, limit in fractions:
                frac = used / limit
                if frac > highest_fraction:
                    highest_fraction = frac
                    trigger_reason = reason
                    trigger_used = used
                    trigger_budget = limit

            if highest_fraction >= self._config.hard_stop_threshold:
                logger.warning("Token budget hard stop triggered for run %s: %s limit exceeded", run_id, trigger_reason)
                # Record the stop reason so the executor can surface
                # ``stop_reason=token_capped`` to the lead after the run
                # returns (the hard stop itself does not raise). See
                # ``consume_stop_reason``.
                self._stop_reason[self._stop_reason_key(runtime, run_id)] = "token_capped"
                # Also write to runtime.context so the lead worker can read it
                # without needing a reference to this middleware instance (#4176).
                ctx = getattr(runtime, "context", None)
                if isinstance(ctx, dict):
                    ctx["stop_reason"] = "token_capped"
                stop_text = _BUDGET_EXCEEDED_MSG.format(reason=trigger_reason, used=trigger_used, budget=trigger_budget)
                completed_call_ids = pending.completed_call_ids if confirmed and pending is not None else frozenset()
                return self._build_hard_stop_update(current, stop_text, completed_call_ids=completed_call_ids)

            if highest_fraction >= self._config.warn_threshold and not self._warned.get(run_id, False):
                self._warned[run_id] = True
                percent = highest_fraction * 100
                warn_text = _BUDGET_WARNING_MSG.format(reason=trigger_reason, used=trigger_used, budget=trigger_budget, percent=percent)
                logger.info("Token budget warning triggered for run %s: %s limit at %.1f%%", run_id, trigger_reason, percent)
                # queue warning for wrap_model_call
                warnings = self._pending_warnings.setdefault(run_id, [])
                warnings.append(warn_text)
                return None

            return None

    @override
    def after_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        return self._apply(state, runtime)

    @override
    async def aafter_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        return self._apply(state, runtime)

    def _drain_pending_warnings(self, runtime: Runtime) -> list[str]:
        if not self._config.enabled:
            return []

        run_id = self._get_run_id(runtime)
        with self._lock:
            warnings = self._pending_warnings.pop(run_id, None)
        return warnings or []

    def _restore_pending_warnings(self, runtime: Runtime, warnings: list[str]) -> None:
        """Requeue warnings taken for a model call that raised.

        LLMErrorHandlingMiddleware sits outside this middleware and retries a
        failed call by running this wrap again, so the retry must still find
        the warning. It is not queued twice: ``_warned`` is already set.
        """
        if not warnings:
            return
        run_id = self._get_run_id(runtime)
        with self._lock:
            queued = self._pending_warnings.setdefault(run_id, [])
            queued[:0] = [warning for warning in warnings if warning not in queued]

    def _inject_warnings(self, request: ModelRequest, warnings: list[str]) -> ModelRequest:
        if not warnings:
            return request

        merged_text = "\n\n".join(warnings)
        warning_msg = HumanMessage(content=merged_text, name="budget_warning")

        messages = getattr(request, "messages", [])
        new_messages = list(messages) + [warning_msg]
        return request.override(messages=new_messages)

    def _record_pending_model_call(self, runtime: Runtime, response: ModelCallResult) -> None:
        """Snapshot the last AIMessage's native usage after a successful model call.

        The observation is confirmed later by ``_apply`` against the message
        that actually enters graph state.  This decouples budget accounting from
        the diff-based ``seen`` scan, which sees zero delta when the provider
        reuses the same ``AIMessage.id`` across distinct calls.

        The usage values are an immutable snapshot taken at call time; the
        message reference is consumed in ``after_model`` and uses the same
        bounded per-run storage as the other guards. Nothing is added to the
        message — no public marker, no content/tool-call/metadata mutation.
        """
        if not self._config.enabled:
            return
        self._discard_pending_model_call(runtime)
        message = last_ai_message(response)
        if message is None:
            return
        usage = message.usage_metadata or {}
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)
        if not isinstance(input_tokens, int) or not isinstance(output_tokens, int):
            return
        returned = getattr(response, "result", ())
        completed_call_ids: frozenset[str] = frozenset()
        if isinstance(returned, (list, tuple)):
            position = next((index for index in range(len(returned) - 1, -1, -1) if returned[index] is message), len(returned))
            completed_call_ids = frozenset(result.tool_call_id for result in returned[position + 1 :] if isinstance(result, ToolMessage) and isinstance(result.tool_call_id, str))
        run_id = self._get_run_id(runtime)
        with self._lock:
            self._pending_model_calls[run_id] = _PendingModelCall(
                message=message,
                message_id=message.id,
                # Match the delta scan: malformed negative usage must never
                # subtract tokens already charged to this run.
                input_tokens=max(0, input_tokens),
                output_tokens=max(0, output_tokens),
                completed_call_ids=completed_call_ids,
            )

    @staticmethod
    def _matches_pending(message: AIMessage, pending: _PendingModelCall) -> bool:
        """Check whether a state message is the pending call's result.

        Matching is by object identity first (the reducer may keep the same
        object), then by provider message ID (covers ``model_copy`` and
        in-place reducer replacement).  Content alone is never compared: two
        independent calls can produce identical text.
        The ID fallback assumes the observed response entered graph state; it
        cannot distinguish a discarded response from historical same-ID state.
        """
        if message is pending.message:
            return True
        pending_id = pending.message_id or (pending.message.id if pending.message is not None else None)
        if pending_id is not None and message.id == pending_id:
            return True
        return False

    def _discard_pending_model_call(self, runtime: Runtime) -> None:
        if self._config.enabled:
            run_id = self._get_run_id(runtime)
            with self._lock:
                self._pending_model_calls.pop(run_id, None)

    @override
    def wrap_model_call(self, request: ModelRequest, handler: Callable[[ModelRequest], ModelResponse]) -> ModelCallResult:
        warnings = self._drain_pending_warnings(request.runtime)
        try:
            response = handler(self._inject_warnings(request, warnings))
            self._record_pending_model_call(request.runtime, response)
            return response
        except BaseException as exc:
            self._discard_pending_model_call(request.runtime)
            if isinstance(exc, Exception):
                self._restore_pending_warnings(request.runtime, warnings)
            raise

    @override
    async def awrap_model_call(self, request: ModelRequest, handler: Callable[[ModelRequest], Awaitable[ModelResponse]]) -> ModelCallResult:
        warnings = self._drain_pending_warnings(request.runtime)
        try:
            response = await handler(self._inject_warnings(request, warnings))
            self._record_pending_model_call(request.runtime, response)
            return response
        except BaseException as exc:
            self._discard_pending_model_call(request.runtime)
            if isinstance(exc, Exception):
                self._restore_pending_warnings(request.runtime, warnings)
            raise
