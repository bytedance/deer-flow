"""Middleware for automatic thread title generation."""

from typing import NotRequired, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langgraph.runtime import Runtime

from src.agents.title.queue import get_title_queue
from src.config.title_config import get_title_config


class TitleMiddlewareState(AgentState):
    """Compatible with the `ThreadState` schema."""

    title: NotRequired[str | None]


class TitleMiddleware(AgentMiddleware[TitleMiddlewareState]):
    """Automatically generate a title for the thread after the first user message."""

    state_schema = TitleMiddlewareState

    def _should_generate_title(self, state: TitleMiddlewareState) -> bool:
        """Check if we should generate a title for this thread."""
        config = get_title_config()
        if not config.enabled:
            return False

        # Check if thread already has a title in state
        if state.get("title"):
            return False

        # Check if this is the first turn (has at least one user message and one assistant response)
        messages = state.get("messages", [])
        if len(messages) < 2:
            return False

        # Count user and assistant messages
        user_messages = [m for m in messages if m.type == "human"]
        assistant_messages = [m for m in messages if m.type == "ai"]

        # Generate title after first complete exchange
        return len(user_messages) == 1 and len(assistant_messages) >= 1

    @override
    def after_agent(self, state: TitleMiddlewareState, runtime: Runtime) -> dict | None:
        """Queue asynchronous title generation after the first exchange."""
        if self._should_generate_title(state):
            context = runtime.context or {}
            thread_id = context.get("thread_id") if hasattr(context, "get") else None
            if not thread_id:
                return None
            queue = get_title_queue()
            queue.add(thread_id=thread_id, messages=state.get("messages", []))

        return None
