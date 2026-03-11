"""Middleware for automatic thread title generation."""

import asyncio
from typing import NotRequired, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langgraph.runtime import Runtime

from src.config.title_config import get_title_config
from src.models import create_chat_model

# Strong references to background tasks to prevent premature GC
_background_tasks: set[asyncio.Task] = set()


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

        # Ensure content is string (LangChain messages can have list content)
        user_msg = str(user_msg_content) if user_msg_content else ""
        assistant_msg = str(assistant_msg_content) if assistant_msg_content else ""

        # Use a lightweight model to generate title
        model = create_chat_model(thinking_enabled=False)

        prompt = config.prompt_template.format(
            max_words=config.max_words,
            user_msg=user_msg[:500],
            assistant_msg=assistant_msg[:500],
        )

        try:
            response = await model.ainvoke(prompt)
            # Ensure response content is string
            title_content = str(response.content) if response.content else ""
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

    async def _generate_and_patch_title(self, state: TitleMiddlewareState, thread_id: str) -> None:
        """Generate title in background and patch it into the thread state.

        Uses the in-process LangGraph client (ASGI transport) when running inside the
        LangGraph server, so no extra HTTP round-trip is needed. Falls back to a no-op
        with a warning if the client cannot connect (e.g. embedded / test mode).
        """
        try:
            title = await self._generate_title(state)
            print(f"Generated thread title: {title}")
            from langgraph_sdk import get_client

            # url=None → in-process ASGI connection when inside LangGraph server
            client = get_client()
            await client.threads.update_state(thread_id, values={"title": title})
        except Exception as e:
            print(f"[TitleMiddleware] Failed to generate/patch thread title: {e}")

    @override
    async def aafter_model(self, state: TitleMiddlewareState, runtime: Runtime) -> dict | None:
        """Schedule title generation as a non-blocking background task.

        Previously this awaited the LLM call directly, causing a 5-10 s delay before
        the run stream ended and blocking the user from sending the next message.
        Now we fire-and-forget: the run completes immediately and the title is patched
        into the thread state asynchronously after generation finishes.
        """
        if self._should_generate_title(state):
            thread_id = runtime.context.get("thread_id") if runtime.context is not None else None
            if thread_id:
                task = asyncio.create_task(self._generate_and_patch_title(state, thread_id))
                _background_tasks.add(task)
                task.add_done_callback(_background_tasks.discard)

        return None
