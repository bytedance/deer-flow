"""Minimal current-date middleware for built-in subagents.

Subagents need the same framework-owned ``<current_date>`` anchor as the lead
agent, but not the lead middleware's memory lookup, frozen-conversation ID
swap, midnight refresh, or run-journal bookkeeping. Each subagent graph is
one-shot and starts from fresh state, so a single hidden ``SystemMessage`` is
injected at the start of the run. ``SystemMessageCoalescingMiddleware``
merges it with the leading subagent prompt before the request reaches the
provider, so strict backends still receive exactly one leading system block.
"""

from __future__ import annotations

from datetime import datetime
from typing import override

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.runtime import Runtime

from deerflow.agents.middlewares.dynamic_context_middleware import (
    _DYNAMIC_CONTEXT_REMINDER_KEY,
    _REMINDER_DATE_KEY,
    is_dynamic_context_reminder,
)


class SubagentDateContextMiddleware(AgentMiddleware):
    """Inject a hidden current-date reminder once per subagent execution.

    The middleware deliberately does not reuse ``DynamicContextMiddleware``:
    date-only mode would still carry its memory loading, HumanMessage ID swap,
    midnight-crossing bookkeeping, thread-offloaded injection, and run-journal
    recording, none of which apply to a one-shot subagent run.
    """

    @staticmethod
    def _make_reminder() -> SystemMessage:
        current_date = datetime.now().strftime("%Y-%m-%d, %A")
        content = "\n".join(
            [
                "<system-reminder>",
                f"<current_date>{current_date}</current_date>",
                "</system-reminder>",
            ]
        )
        return SystemMessage(
            content=content,
            additional_kwargs={
                "hide_from_ui": True,
                _DYNAMIC_CONTEXT_REMINDER_KEY: True,
                _REMINDER_DATE_KEY: current_date,
            },
        )

    def _inject(self, state, runtime: Runtime) -> dict | None:
        messages = list(state.get("messages", []))
        if not messages:
            return None
        if any(is_dynamic_context_reminder(message) for message in messages):
            return None
        if not any(isinstance(message, HumanMessage) for message in messages):
            return None
        return {"messages": [self._make_reminder()]}

    @override
    def before_agent(self, state, runtime: Runtime) -> dict | None:
        return self._inject(state, runtime)

    @override
    async def abefore_agent(self, state, runtime: Runtime) -> dict | None:
        return self._inject(state, runtime)
