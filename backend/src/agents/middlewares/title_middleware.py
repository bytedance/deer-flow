"""Middleware for automatic thread title generation."""

import logging
from typing import NotRequired, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langgraph.runtime import Runtime

from src.config.title_config import get_title_config
from src.models import create_chat_model

logger = logging.getLogger(__name__)


class TitleMiddlewareState(AgentState):
    """Compatible with the `ThreadState` schema."""

    title: NotRequired[str | None]


class TitleMiddleware(AgentMiddleware[TitleMiddlewareState]):
    """Automatically generate a title for the thread before the agent runs.

    Title is generated in abefore_agent so it is persisted even when the
    agent workflow is interrupted (user stop, exceptions, timeouts).
    """

    state_schema = TitleMiddlewareState

    def _should_generate_title(self, state: TitleMiddlewareState) -> bool:
        """Check if we should generate a title for this thread."""
        config = get_title_config()
        if not config.enabled:
            return False

        # Check if thread already has a title in state
        if state.get("title"):
            return False

        messages = state.get("messages", [])
        if not messages:
            return False

        # Generate only on the first turn (exactly one user message)
        user_messages = [m for m in messages if m.type == "human"]
        return len(user_messages) == 1

    async def _generate_title(self, state: TitleMiddlewareState) -> str:
        """Generate a concise title based on the user's first message."""
        config = get_title_config()
        messages = state.get("messages", [])

        # Get first user message
        user_msg_content = next((m.content for m in messages if m.type == "human"), "")

        # Ensure content is string (LangChain messages can have list content)
        user_msg = str(user_msg_content) if user_msg_content else ""

        # Use a lightweight model to generate title
        model = create_chat_model(thinking_enabled=False)

        prompt = (
            f"Generate a concise title (max {config.max_words} words) for a conversation "
            f"that starts with this user message.\n"
            f"User: {user_msg[:500]}\n\n"
            f"Return ONLY the title, no quotes, no explanation."
        )

        try:
            response = await model.ainvoke(prompt)
            # Ensure response content is string
            title_content = str(response.content) if response.content else ""
            title = title_content.strip().strip('"').strip("'")
            # Limit to max characters
            return title[: config.max_chars] if len(title) > config.max_chars else title
        except Exception as e:
            logger.warning("Failed to generate title: %s", e)
            # Fallback: use first part of user message (by character count)
            fallback_chars = min(config.max_chars, 50)
            if len(user_msg) > fallback_chars:
                return user_msg[:fallback_chars].rstrip() + "..."
            return user_msg if user_msg else "New Conversation"

    @override
    async def abefore_agent(self, state: TitleMiddlewareState, runtime: Runtime) -> dict | None:
        """Generate and set thread title before the agent runs.

        By generating the title here rather than in aafter_agent, the title
        is persisted even when the agent workflow is interrupted (user stop,
        exceptions, timeouts).
        """
        if self._should_generate_title(state):
            title = await self._generate_title(state)
            logger.info("Generated thread title: %s", title)
            return {"title": title}

        return None
