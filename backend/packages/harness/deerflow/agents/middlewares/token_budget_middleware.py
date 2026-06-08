"""Middleware to enforce per-run token budget limits.
Tracks cumulative token usage (input, output, total) across model calls within
a single agent run and enforces configurable soft-warning and hard-stop
thresholds.
Detection strategy:
  1. After each model response, sum the `usage_metadata` of all `AIMessage`s
     in the current thread history. This automatically captures tokens from
     subagents because `TokenUsageMiddleware` retroactively adds them to the
     history.
  2. If the highest fraction (input, output, or total) >= warn_threshold,
     queue a warning.
  3. If the highest fraction >= hard_stop_threshold, strip tool_calls.
Warning injection uses the deferred pattern:
  - after_model queues the warning (does NOT mutate state).
  - wrap_model_call injects it as a HumanMessage at the next model call.
This preserves AIMessage(tool_calls) → ToolMessage pairing.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.runtime import Runtime

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


class TokenBudgetMiddleware(AgentMiddleware[AgentState]):
    """Enforce per-run token budget limits."""

    def __init__(self, config: TokenBudgetConfig) -> None:
        super().__init__()
        self._config = config
        self._lock = threading.Lock()

        # (thread_id, run_id) -> bool (whether warned)
        self._warned: dict[tuple[str, str], bool] = {}

        # (thread_id, run_id) -> list of warning texts to inject
        self._pending_warnings: dict[tuple[str, str], list[str]] = {}

    @classmethod
    def from_config(cls, config: TokenBudgetConfig) -> TokenBudgetMiddleware:
        return cls(config=config)

    def reset(self) -> None:
        with self._lock:
            self._warned.clear()
            self._pending_warnings.clear()

    @staticmethod
    def _get_thread_id(runtime: Runtime) -> str:
        ctx = getattr(runtime, "context", None)
        if isinstance(ctx, dict):
            return ctx.get("thread_id", "default")
        return "default"

    @staticmethod
    def _get_run_id(runtime: Runtime) -> str:
        ctx = getattr(runtime, "context", None)
        if isinstance(ctx, dict):
            return ctx.get("run_id", "default")
        return "default"

    def _clear_run_state(self, key: tuple[str, str]) -> None:
        self._warned.pop(key, None)
        self._pending_warnings.pop(key, None)

    @override
    def before_agent(self, state: AgentState, runtime: Runtime) -> None:

        thread_id = self._get_thread_id(runtime)
        run_id = self._get_run_id(runtime)

        with self._lock:
            # clear any stale state from prior runs on this thread
            stale_keys = [k for k in self._warned if k[0] == thread_id and k[1] != run_id]
            stale_keys.extend([k for k in self._pending_warnings if k[0] == thread_id and k[1] != run_id])
            for key in stale_keys:
                self._clear_run_state(key)

    @override
    async def abefore_agent(self, state: AgentState, runtime: Runtime) -> None:
        self.before_agent(state, runtime)

    @override
    def after_agent(self, state: AgentState, runtime: Runtime) -> None:
        thread_id = self._get_thread_id(runtime)
        run_id = self._get_run_id(runtime)
        with self._lock:
            self._clear_run_state((thread_id, run_id))

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

    def _build_hard_stop_update(self, msg: AIMessage, stop_msg: str) -> dict[str, Any]:
        """Build the state update dictionary for a hard stop."""
        updated_content = self._append_text(msg.content, stop_msg)
        kwargs = dict(msg.additional_kwargs) if msg.additional_kwargs else {}
        if "tool_calls" in kwargs:
            del kwargs["tool_calls"]
        if "function_call" in kwargs:
            del kwargs["function_call"]

        response_metadata = dict(getattr(msg, "response_metadata", {}) or {})

        if response_metadata.get("finish_reason") == "tool_calls":
            response_metadata["finish_reason"] = "stop"

        stopped_msg = msg.model_copy(update={"content": updated_content, "tool_calls": [], "additional_kwargs": kwargs, "response_metadata": response_metadata})
        return {"messages": [stopped_msg]}

    def _apply(self, state: AgentState, runtime: Runtime) -> dict | None:
        messages = state.get("messages", [])
        if not messages:
            return None

        last_msg = messages[-1]
        if not isinstance(last_msg, AIMessage):
            return None

        current = TokenUsage()
        for msg in messages:
            if isinstance(msg, AIMessage) and hasattr(msg, "usage_metadata"):
                usage = msg.usage_metadata or {}

                input_tokens = usage.get("input_tokens", 0)
                output_tokens = usage.get("output_tokens", 0)
                total_tokens = usage.get("total_tokens")

                if total_tokens is None:
                    total_tokens = input_tokens + output_tokens

                current.input += input_tokens
                current.output += output_tokens
                current.total += total_tokens

        if current.total <= 0:
            return None

        thread_id = self._get_thread_id(runtime)
        run_id = self._get_run_id(runtime)
        key = (thread_id, run_id)

        with self._lock:
            fractions = [("total", current.total, self._config.max_tokens)]
            if self._config.max_input_tokens:
                fractions.append(("input", current.input, self._config.max_input_tokens))
            if self._config.max_output_tokens:
                fractions.append(("output", current.output, self._config.max_output_tokens))

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
                logger.warning("Token budget hard stop triggered for thread %s run %s: %s limit exceeded", thread_id, run_id, trigger_reason)
                stop_text = _BUDGET_EXCEEDED_MSG.format(reason=trigger_reason, used=trigger_used, budget=trigger_budget)
                return self._build_hard_stop_update(last_msg, stop_text)

            if highest_fraction >= self._config.warn_threshold and not self._warned.get(key, False):
                self._warned[key] = True
                percent = highest_fraction * 100
                warn_text = _BUDGET_WARNING_MSG.format(reason=trigger_reason, used=trigger_used, budget=trigger_budget, percent=percent)
                logger.info("Token budget warning triggered for thread %s run %s: %s limit at %.1f%%", thread_id, run_id, trigger_reason, percent)
                # queue warning for wrap_model_call
                warnings = self._pending_warnings.setdefault(key, [])
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
        thread_id = self._get_thread_id(runtime)
        run_id = self._get_run_id(runtime)
        key = (thread_id, run_id)

        with self._lock:
            warnings = self._pending_warnings.pop(key, None)
            return warnings or []

    def _inject_warnings(self, request: ModelRequest, warnings: list[str]) -> ModelRequest:
        if not warnings:
            return request

        merged_text = "\n\n".join(warnings)
        warning_msg = HumanMessage(content=merged_text, name="budget_warning")

        messages = getattr(request, "messages", [])
        new_messages = list(messages) + [warning_msg]
        return request.override(messages=new_messages)

    @override
    def wrap_model_call(self, request: ModelRequest, handler: Callable[[ModelRequest], ModelResponse]) -> ModelCallResult:

        warnings = self._drain_pending_warnings(request.runtime)
        request = self._inject_warnings(request, warnings)

        return handler(request)

    @override
    async def awrap_model_call(self, request: ModelRequest, handler: Callable[[ModelRequest], Awaitable[ModelResponse]]) -> ModelCallResult:
        warnings = self._drain_pending_warnings(request.runtime)
        request = self._inject_warnings(request, warnings)
        return await handler(request)
