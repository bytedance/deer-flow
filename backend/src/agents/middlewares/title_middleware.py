"""Middleware for automatic thread title generation."""

from datetime import datetime, timezone
from typing import NotRequired, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langgraph.runtime import Runtime

from src.config.title_config import get_title_config
from src.models import create_chat_model


class TitleMiddlewareState(AgentState):
    """Compatible with the `ThreadState` schema."""

    title: NotRequired[str | None]
    token_usage: NotRequired[list | None]


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

    @staticmethod
    def _extract_text(content) -> str:
        """Extract plain text from message content (str or list of content blocks)."""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    return part.get("text", "")
        return str(content) if content else ""

    async def _generate_title(self, state: TitleMiddlewareState) -> tuple[str, dict | None]:
        """Generate a concise title based on the conversation.

        Returns:
            Tuple of (title_str, token_usage_entry_or_None).
        """
        config = get_title_config()
        messages = state.get("messages", [])

        # Get first user message and first assistant response
        user_msg_content = next((m.content for m in messages if m.type == "human"), "")
        assistant_msg_content = next((m.content for m in messages if m.type == "ai"), "")

        # Properly extract text from structured content blocks
        user_msg = self._extract_text(user_msg_content)
        assistant_msg = self._extract_text(assistant_msg_content)

        # Use a lightweight model to generate title
        model = create_chat_model(thinking_enabled=False)

        prompt = config.prompt_template.format(
            max_words=config.max_words,
            user_msg=user_msg[:500],
            assistant_msg=assistant_msg[:500],
        )

        try:
            response = await model.ainvoke(prompt)
            # Extract plain text from response (handles thinking models that return list content)
            title_content = self._extract_text(response.content) if response.content else ""
            title = title_content.strip().strip('"').strip("'")
            # Limit to max characters
            title = title[: config.max_chars] if len(title) > config.max_chars else title

            # Capture token usage from the title model call
            usage_entry = None
            usage = getattr(response, "usage_metadata", None)
            if usage is not None:
                if isinstance(usage, dict):
                    in_tok = usage.get("input_tokens", 0) or 0
                    out_tok = usage.get("output_tokens", 0) or 0
                else:
                    in_tok = getattr(usage, "input_tokens", 0) or 0
                    out_tok = getattr(usage, "output_tokens", 0) or 0
                if in_tok or out_tok:
                    usage_entry = {
                        "process": "title",
                        "input_tokens": in_tok,
                        "output_tokens": out_tok,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }

            return title, usage_entry
        except Exception as e:
            print(f"Failed to generate title: {e}")
            # Fallback: use first part of user message (by character count)
            fallback_chars = min(config.max_chars, 50)  # Use max_chars or 50, whichever is smaller
            if len(user_msg) > fallback_chars:
                return user_msg[:fallback_chars].rstrip() + "...", None
            return (user_msg if user_msg else "New Conversation"), None

    @override
    async def aafter_model(self, state: TitleMiddlewareState, runtime: Runtime) -> dict | None:
        """Generate and set thread title after the first agent response."""
        if self._should_generate_title(state):
            title, usage_entry = await self._generate_title(state)
            print(f"Generated thread title: {title}")

            state_update: dict = {"title": title}
            if usage_entry is not None:
                state_update["token_usage"] = [usage_entry]

            return state_update

        return None
