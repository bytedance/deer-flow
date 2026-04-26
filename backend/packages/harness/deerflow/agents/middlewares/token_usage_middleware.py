"""Middleware for logging LLM token usage."""

import logging
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langgraph.runtime import Runtime

logger = logging.getLogger(__name__)


class TokenUsageMiddleware(AgentMiddleware):
    """Logs token usage from model response usage_metadata."""

    @override
    def after_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        return self._log_usage(state)

    @override
    async def aafter_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        return self._log_usage(state)

    def _log_usage(self, state: AgentState) -> None:
        messages = state.get("messages", [])
        if not messages:
            return None
        last = messages[-1]
        usage = getattr(last, "usage_metadata", None)
        if usage:
            logger.info(
                "LLM token usage: input=%s output=%s total=%s",
                usage.get("input_tokens", "?"),
                usage.get("output_tokens", "?"),
                usage.get("total_tokens", "?"),
            )
        return None
