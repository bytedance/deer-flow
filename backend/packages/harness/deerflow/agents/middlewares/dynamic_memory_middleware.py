"""Middleware for dynamic user-isolated memory injection.

This middleware injects user-specific memory into the system prompt at runtime,
ensuring memory isolation between users in multi-tenant mode.
"""

from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langgraph.runtime import Runtime

from deerflow.agents.memory import format_memory_for_injection, get_memory_data
from deerflow.config.memory_config import get_memory_config


class DynamicMemoryMiddlewareState(AgentState):
    """Compatible with the `ThreadState` schema."""

    pass


class DynamicMemoryMiddleware(AgentMiddleware[DynamicMemoryMiddlewareState]):
    """Middleware that injects user-isolated memory into system prompt at runtime.

    This middleware runs before the model call and injects the user's memory
    into the system prompt, ensuring memory isolation in multi-tenant mode.
    """

    state_schema = DynamicMemoryMiddlewareState

    def __init__(self, agent_name: str | None = None):
        """Initialize the DynamicMemoryMiddleware.

        Args:
            agent_name: If provided, loads per-agent memory. If None, uses per-user memory.
        """
        super().__init__()
        self._agent_name = agent_name

    @override
    def before_model(self, state: DynamicMemoryMiddlewareState, runtime: Runtime) -> dict | None:
        """Inject user-isolated memory into system prompt before model call.

        Args:
            state: The current agent state.
            runtime: The runtime context.

        Returns:
            State updates with injected memory, or None if memory is disabled.
        """
        config = get_memory_config()
        if not config.enabled or not config.injection_enabled:
            return None

        # Extract user_id from thread metadata
        user_id = None
        configurable = runtime.context.get("configurable", {})
        if isinstance(configurable, dict):
            metadata = configurable.get("metadata", {})
            if isinstance(metadata, dict):
                user_id = metadata.get("user_id")

        # Get user-specific memory
        try:
            # Priority: agent_name > user_id > global memory
            memory_data = get_memory_data(agent_name=self._agent_name, user_id=user_id)
            memory_content = format_memory_for_injection(
                memory_data, max_tokens=config.max_injection_tokens
            )

            if not memory_content.strip():
                return None

            # Inject memory into system prompt
            memory_section = f"<memory>\n{memory_content}\n</memory>"

            # Get existing system prompt from messages
            messages = state.get("messages", [])
            if not messages:
                return None

            # Find and update the system message
            for msg in messages:
                if hasattr(msg, "type") and msg.type == "system":
                    current_content = msg.content
                    if isinstance(current_content, str):
                        # Check if memory already exists
                        if "<memory>" in current_content:
                            # Replace existing memory section
                            import re

                            updated_content = re.sub(
                                r"<memory>[\s\S]*?</memory>",
                                memory_section,
                                current_content,
                            )
                            msg.content = updated_content
                        else:
                            # Append memory section
                            msg.content = current_content + "\n\n" + memory_section
                    break

            return None

        except Exception as e:
            print(f"DynamicMemoryMiddleware: Failed to inject memory: {e}")
            return None
