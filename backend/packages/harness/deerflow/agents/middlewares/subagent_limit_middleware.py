"""Middleware to enforce subagent tool-call limits."""

import logging
from typing import Any, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langgraph.runtime import Runtime

from deerflow.agents.middlewares.tool_call_metadata import clone_ai_message_with_tool_calls
from deerflow.config.subagents_config import (
    DEFAULT_MAX_TOTAL_SUBAGENTS_PER_RUN,
    MAX_CONCURRENT_SUBAGENT_CALLS,
    MAX_TOTAL_SUBAGENTS_PER_RUN,
    MIN_CONCURRENT_SUBAGENT_CALLS,
    MIN_TOTAL_SUBAGENTS_PER_RUN,
    clamp_subagent_concurrency,
    clamp_total_subagents_per_run,
)
from deerflow.subagents.executor import MAX_CONCURRENT_SUBAGENTS

logger = logging.getLogger(__name__)

# Valid range for max_concurrent_subagents
MIN_SUBAGENT_LIMIT = MIN_CONCURRENT_SUBAGENT_CALLS
MAX_SUBAGENT_LIMIT = MAX_CONCURRENT_SUBAGENT_CALLS
DEFAULT_MAX_TOTAL_SUBAGENTS = DEFAULT_MAX_TOTAL_SUBAGENTS_PER_RUN
MIN_SUBAGENT_TOTAL_LIMIT = MIN_TOTAL_SUBAGENTS_PER_RUN
MAX_SUBAGENT_TOTAL_LIMIT = MAX_TOTAL_SUBAGENTS_PER_RUN

_TOTAL_LIMIT_STOP_MSG = (
    "[SUBAGENT LIMIT REACHED] The subagent delegation limit for this run has been reached. "
    "Continue using the subagent results already collected, execute remaining simple work "
    "directly, or summarize the remaining work instead of launching more subagents."
)


def _clamp_subagent_limit(value: int) -> int:
    """Clamp subagent limit to valid range [2, 4]."""
    return clamp_subagent_concurrency(value)


def _clamp_total_subagent_limit(value: int) -> int:
    """Clamp total subagent limit to a bounded positive range."""
    return clamp_total_subagents_per_run(value)


def _append_text(content: Any, text: str) -> Any:
    if content is None:
        return text
    if isinstance(content, str):
        if content:
            return f"{content}\n\n{text}"
        return text
    if isinstance(content, list):
        return [*content, {"type": "text", "text": f"\n\n{text}"}]
    return f"{content}\n\n{text}"


def _delegation_id(entry: object) -> str | None:
    if not isinstance(entry, dict):
        return None
    entry_id = entry.get("id")
    return str(entry_id) if entry_id else None


def _delegation_run_id(entry: object) -> str | None:
    if not isinstance(entry, dict):
        return None
    run_id = entry.get("run_id")
    return str(run_id) if run_id else None


def _runtime_run_id(runtime: Runtime | None) -> str | None:
    context = getattr(runtime, "context", None)
    if not isinstance(context, dict):
        return None
    run_id = context.get("run_id")
    return str(run_id) if run_id else None


def _count_prior_delegations(delegations: object, *, run_id: str | None) -> int:
    if not isinstance(delegations, list):
        return 0
    ids = set()
    for entry in delegations:
        if run_id is not None and _delegation_run_id(entry) != run_id:
            continue
        delegation_id = _delegation_id(entry)
        if delegation_id is not None:
            ids.add(delegation_id)
    return len(ids)


class SubagentLimitMiddleware(AgentMiddleware[AgentState]):
    """Truncates excess 'task' tool calls from a single model response/run.

    When an LLM generates more than max_concurrent parallel task tool calls
    in one response, this middleware keeps only the first max_concurrent and
    discards the rest. It also enforces a total per-run cap using entries in
    the durable delegation ledger tagged with the current run_id, so repeated
    planning checkpoints in one run cannot keep launching more legal-sized
    batches indefinitely. This is more reliable than prompt-based limits.

    Args:
        max_concurrent: Maximum number of concurrent subagent calls allowed.
            Defaults to MAX_CONCURRENT_SUBAGENTS (3). Clamped to [2, 4].
        max_total: Maximum number of subagent calls allowed across the run.
            Defaults to 6. Clamped to [1, 50].
    """

    def __init__(self, max_concurrent: int = MAX_CONCURRENT_SUBAGENTS, max_total: int = DEFAULT_MAX_TOTAL_SUBAGENTS):
        super().__init__()
        self.max_concurrent = _clamp_subagent_limit(max_concurrent)
        self.max_total = _clamp_total_subagent_limit(max_total)

    def _truncate_task_calls(self, state: AgentState, runtime: Runtime | None = None) -> dict | None:
        messages = state.get("messages", [])
        if not messages:
            return None

        last_msg = messages[-1]
        if getattr(last_msg, "type", None) != "ai":
            return None

        tool_calls = getattr(last_msg, "tool_calls", None)
        if not tool_calls:
            return None

        # Count task tool calls
        task_indices = [i for i, tc in enumerate(tool_calls) if tc.get("name") == "task"]
        if not task_indices:
            return None

        run_id = _runtime_run_id(runtime)
        if run_id is None:
            logger.warning("Subagent limit middleware received no run_id; counting all thread delegations as prior usage. Pass run_id in runtime context to enforce the total cap per run.")
        prior_delegation_count = _count_prior_delegations(state.get("delegations"), run_id=run_id)
        remaining_total = max(0, self.max_total - prior_delegation_count)
        allowed_task_calls = min(self.max_concurrent, remaining_total)

        if len(task_indices) <= allowed_task_calls:
            return None

        # Build set of indices to drop (excess task calls beyond the limit)
        indices_to_drop = set(task_indices[allowed_task_calls:])
        truncated_tool_calls = [tc for i, tc in enumerate(tool_calls) if i not in indices_to_drop]
        dropped_count = len(indices_to_drop)
        logger.warning(
            "Truncated %s excess task tool call(s) from model response (concurrent limit: %s; total limit: %s; prior delegations: %s)",
            dropped_count,
            self.max_concurrent,
            self.max_total,
            prior_delegation_count,
        )

        # Replace the AIMessage with truncated tool_calls (same id triggers replacement)
        content = _append_text(last_msg.content, _TOTAL_LIMIT_STOP_MSG) if remaining_total == 0 else None
        updated_msg = clone_ai_message_with_tool_calls(last_msg, truncated_tool_calls, content=content)
        return {"messages": [updated_msg]}

    @override
    def after_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        return self._truncate_task_calls(state, runtime)

    @override
    async def aafter_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        return self._truncate_task_calls(state, runtime)
