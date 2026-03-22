"""Middleware to enforce turn budget and force output before recursion limit.

Unlike exploration_budget prompt instructions (which models can ignore), this
middleware hard-injects warnings into the conversation at configurable
thresholds, and at the final threshold strips tool calls to force a text
response.

Designed for cheap, fast models (e.g. DeepSeek) that don't reliably self-limit.
"""

import logging
from collections import defaultdict
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, SystemMessage
from langgraph.runtime import Runtime

logger = logging.getLogger(__name__)

# Default thresholds as fractions of max_turns
_DEFAULT_WARN_FRACTION = 0.65  # "Getting close" warning
_DEFAULT_URGENT_FRACTION = 0.85  # "Wrap up NOW" warning
_DEFAULT_FORCE_FRACTION = 0.95  # Strip tool calls, force final answer

_WARN_MSG = (
    "[BUDGET WARNING] You have used {used} of {total} allowed turns. "
    "Start wrapping up. Consolidate your key findings now and "
    "begin producing your final answer."
)

_URGENT_MSG = (
    "[BUDGET CRITICAL] You have used {used} of {total} turns — only {remaining} left! "
    "STOP exploring. Immediately produce your final summary with "
    "everything you have found so far."
)

_FORCE_MSG = (
    "[BUDGET EXHAUSTED] Turn limit nearly reached ({used}/{total}). "
    "Producing final answer with all results collected so far."
)


class BudgetEnforcementMiddleware(AgentMiddleware[AgentState]):
    """Injects budget warnings and forces output before recursion limit.

    Counts before_model invocations directly (not messages in state, which
    can decrease due to summarization).  Each model call ≈ 8 graph steps
    (model node + tools node + middleware nodes), so thresholds are applied
    against max_turns // 8.

    Args:
        max_turns: The recursion limit for this agent.
        warn_fraction: Fraction of max_turns to trigger first warning.
        urgent_fraction: Fraction to trigger urgent warning.
        force_fraction: Fraction to strip tool calls and force answer.
    """

    def __init__(
        self,
        max_turns: int = 50,
        warn_fraction: float = _DEFAULT_WARN_FRACTION,
        urgent_fraction: float = _DEFAULT_URGENT_FRACTION,
        force_fraction: float = _DEFAULT_FORCE_FRACTION,
    ):
        super().__init__()
        self.max_turns = max_turns
        # Each model call consumes ~8 graph steps (model node + tools node +
        # middleware nodes).  Estimate effective model calls from recursion_limit.
        # Derive effective_calls directly from max_turns // 8 without inflating
        # the budget, but ensure at least 4 to avoid degenerate thresholds.
        effective_calls = max(max_turns // 8, 4)
        # Compute thresholds from fractions, then clamp them into [1, effective_calls]
        # so they fire within the actual budget without overstating it.
        self.warn_at = max(1, min(int(effective_calls * warn_fraction), effective_calls))
        self.urgent_at = max(1, min(int(effective_calls * urgent_fraction), effective_calls))
        self.force_at = max(1, min(int(effective_calls * force_fraction), effective_calls))
        # Direct invocation counter per thread (immune to summarization)
        self._call_count: dict[str, int] = defaultdict(int)
        # Track which warnings we've already sent per thread to avoid spam
        self._warned: dict[str, set[str]] = defaultdict(set)

    def _get_thread_id(self, runtime: Runtime) -> str:
        thread_id = runtime.context.get("thread_id")
        return thread_id or "default"

    def _apply(self, state: AgentState, runtime: Runtime) -> dict | None:
        thread_id = self._get_thread_id(runtime)
        self._call_count[thread_id] += 1
        turns_used = self._call_count[thread_id]
        effective_total = max(self.max_turns // 8, 4)
        logger.debug(f"Budget check: {turns_used}/{effective_total} model calls (warn={self.warn_at}, urgent={self.urgent_at}, force={self.force_at})")
        warned = self._warned[thread_id]

        if turns_used >= self.force_at and "force" not in warned:
            warned.add("force")
            logger.warning(
                "Budget exhausted — forcing final answer",
                extra={"thread_id": thread_id, "turns_used": turns_used, "max_turns": effective_total},
            )
            return {"messages": [SystemMessage(content=_FORCE_MSG.format(
                used=turns_used, total=effective_total,
            ))]}

        if turns_used >= self.urgent_at and "urgent" not in warned:
            warned.add("urgent")
            logger.warning(
                "Budget critical — injecting urgent warning",
                extra={"thread_id": thread_id, "turns_used": turns_used, "max_turns": effective_total},
            )
            remaining = effective_total - turns_used
            return {"messages": [SystemMessage(content=_URGENT_MSG.format(
                used=turns_used, total=effective_total, remaining=remaining,
            ))]}

        if turns_used >= self.warn_at and "warn" not in warned:
            warned.add("warn")
            logger.info(
                "Budget warning — injecting early warning",
                extra={"thread_id": thread_id, "turns_used": turns_used, "max_turns": effective_total},
            )
            return {"messages": [SystemMessage(content=_WARN_MSG.format(
                used=turns_used, total=effective_total,
            ))]}

        return None

    def _apply_after_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        """After model responds: if we're past force threshold, strip tool calls."""
        thread_id = self._get_thread_id(runtime)
        turns_used = self._call_count.get(thread_id, 0)
        if turns_used < self.force_at:
            return None

        messages = state.get("messages", [])
        if not messages:
            return None

        last_msg = messages[-1]
        if not isinstance(last_msg, AIMessage):
            return None

        tool_calls = getattr(last_msg, "tool_calls", None)
        if not tool_calls:
            return None

        logger.warning(
            "Budget force-stop — stripping %d tool calls from AI response",
            len(tool_calls),
            extra={"thread_id": thread_id, "turns_used": turns_used},
        )
        effective_total = max(self.max_turns // 8, 4)
        # Safely handle content that may be a list (multimodal) or a string
        existing_content = last_msg.content
        if isinstance(existing_content, list):
            existing_content = " ".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in existing_content
            )
        existing_content = existing_content or ""
        stripped_msg = last_msg.model_copy(update={
            "tool_calls": [],
            "content": existing_content + f"\n\n{_FORCE_MSG.format(used=turns_used, total=effective_total)}",
        })
        return {"messages": [stripped_msg]}

    @override
    def before_agent(self, state: AgentState, runtime: Runtime) -> dict | None:
        """Reset per-thread counters at the start of a new agent run.

        This ensures that cached middleware instances don't carry stale
        _call_count / _warned state across independent agent invocations
        (e.g. when DeerFlowClient caches the agent instance).
        """
        self._reset_thread(runtime)
        return None

    @override
    async def abefore_agent(self, state: AgentState, runtime: Runtime) -> dict | None:
        """Async version of before_agent — reset counters for new run."""
        self._reset_thread(runtime)
        return None

    @override
    def before_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        return self._apply(state, runtime)

    @override
    async def abefore_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        return self._apply(state, runtime)

    @override
    def after_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        return self._apply_after_model(state, runtime)

    @override
    async def aafter_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        return self._apply_after_model(state, runtime)

    def _reset_thread(self, runtime: Runtime) -> None:
        """Clear counters and warnings for the current thread."""
        thread_id = self._get_thread_id(runtime)
        self._call_count.pop(thread_id, None)
        self._warned.pop(thread_id, None)

    def reset(self, thread_id: str | None = None) -> None:
        if thread_id:
            self._warned.pop(thread_id, None)
            self._call_count.pop(thread_id, None)
        else:
            self._warned.clear()
            self._call_count.clear()
