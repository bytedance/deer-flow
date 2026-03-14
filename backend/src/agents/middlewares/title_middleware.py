"""Middleware for automatic thread title generation."""

from typing import NotRequired, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langgraph.runtime import Runtime

from src.config.title_config import get_title_config
from src.models import create_chat_model


def _extract_text_content(content) -> str:
    """Extract text from message content, handling both string and list[dict] formats.

    When using the OpenAI Responses API, message content may be a list of content
    parts like: [{"type": "text", "text": "actual content", "index": 0, "id": "msg_..."}]
    instead of a plain string. This helper normalizes both formats to a string.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                parts.append(part.get("text", ""))
            elif isinstance(part, str):
                parts.append(part)
        return " ".join(parts) if parts else ""
    return str(content) if content else ""


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

    async def _generate_title(self, state: TitleMiddlewareState) -> str:
        """Generate a concise title based on the conversation."""
        config = get_title_config()
        messages = state.get("messages", [])

        # Get first user message and first assistant response
        user_msg_content = next((m.content for m in messages if m.type == "human"), "")
        assistant_msg_content = next((m.content for m in messages if m.type == "ai"), "")

        # Extract text content (handles both string and list[dict] formats from Responses API)
        user_msg = _extract_text_content(user_msg_content)
        assistant_msg = _extract_text_content(assistant_msg_content)

        # Use a lightweight model to generate title
        model = create_chat_model(thinking_enabled=False)

        prompt = config.prompt_template.format(
            max_words=config.max_words,
            user_msg=user_msg[:500],
            assistant_msg=assistant_msg[:500],
        )

        try:
            response = await model.ainvoke(prompt)
            # Extract text from response (handles both string and list[dict] formats)
            title_content = _extract_text_content(response.content)
            title = title_content.strip().strip('"').strip("'")
            # Limit to max characters
            return title[: config.max_chars] if len(title) > config.max_chars else title
        except Exception as e:
            print(f"Failed to generate title: {e}")
            # Fallback: use first part of user message (by character count)
            fallback_chars = min(config.max_chars, 50)  # Use max_chars or 50, whichever is smaller
            if len(user_msg) > fallback_chars:
                return user_msg[:fallback_chars].rstrip() + "..."
            return user_msg if user_msg else "New Conversation"

    @override
    async def aafter_model(self, state: TitleMiddlewareState, runtime: Runtime) -> dict | None:
        """Generate and set thread title after the first agent response."""
        if self._should_generate_title(state):
            title = await self._generate_title(state)
            print(f"Generated thread title: {title}")

            # Store title in state (will be persisted by checkpointer if configured)
            return {"title": title}

        return None
