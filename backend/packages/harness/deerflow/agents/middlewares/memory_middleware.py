"""Middleware for memory mechanism."""

import asyncio
import logging
from typing import TYPE_CHECKING, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langgraph.config import get_config
from langgraph.runtime import Runtime

from deerflow.agents.memory.message_processing import detect_correction, detect_reinforcement, filter_messages_for_memory
from deerflow.agents.memory.queue import get_memory_queue
from deerflow.agents.memory.session_queue import get_session_memory_queue
from deerflow.agents.memory.domain_queue import get_domain_memory_queue
from deerflow.config.memory_config import get_memory_config
from deerflow.config.session_memory_config import get_session_memory_config
from deerflow.config.domain_memory_config import get_domain_memory_config
from deerflow.config.tenant import get_current_tenant_id
from deerflow.memory_events import get_memory_event_bus
from deerflow.runtime.user_context import get_effective_user_id

if TYPE_CHECKING:
    from deerflow.config.memory_config import MemoryConfig

logger = logging.getLogger(__name__)


def _emit_sse(tenant_id: str, layer: str, thread_id: str, user_id: str | None) -> None:
    """Fire-and-forget SSE event for memory queue activity."""
    try:
        loop = asyncio.get_running_loop()
        bus = get_memory_event_bus()
        loop.create_task(bus.publish(
            tenant_id=tenant_id,
            event_type="memory_updated",
            data={"layer": layer, "action": "queued", "fact_id": "", "user_id": user_id, "thread_id": thread_id},
        ))
    except RuntimeError:
        pass


class MemoryMiddlewareState(AgentState):
    """Compatible with the `ThreadState` schema."""

    pass


class MemoryMiddleware(AgentMiddleware[MemoryMiddlewareState]):
    """Middleware that queues conversation for memory update after agent execution.

    This middleware:
    1. After each agent execution, queues the conversation for memory update
    2. Only includes user inputs and final assistant responses (ignores tool calls)
    3. The queue uses debouncing to batch multiple updates together
    4. Memory is updated asynchronously via LLM summarization
    """

    state_schema = MemoryMiddlewareState

    def __init__(self, agent_name: str | None = None, *, memory_config: "MemoryConfig | None" = None):
        """Initialize the MemoryMiddleware.

        Args:
            agent_name: If provided, memory is stored per-agent. If None, uses global memory.
            memory_config: Explicit memory config. When omitted, legacy global
                config fallback is used.
        """
        super().__init__()
        self._agent_name = agent_name
        self._memory_config = memory_config

    @override
    def after_agent(self, state: MemoryMiddlewareState, runtime: Runtime) -> dict | None:
        """Queue conversation for memory update after agent completes.

        Args:
            state: The current agent state.
            runtime: The runtime context.

        Returns:
            None (no state changes needed from this middleware).
        """
        config = self._memory_config or get_memory_config()
        if not config.enabled:
            return None

        # Get thread ID from runtime context first, then fall back to LangGraph's configurable metadata
        thread_id = runtime.context.get("thread_id") if runtime.context else None
        if thread_id is None:
            config_data = get_config()
            thread_id = config_data.get("configurable", {}).get("thread_id")
        if not thread_id:
            logger.debug("No thread_id in context, skipping memory update")
            return None

        # Get messages from state
        messages = state.get("messages", [])
        if not messages:
            logger.debug("No messages in state, skipping memory update")
            return None

        # Filter to only keep user inputs and final assistant responses
        filtered_messages = filter_messages_for_memory(messages)

        # Only queue if there's meaningful conversation
        # At minimum need one user message and one assistant response
        user_messages = [m for m in filtered_messages if getattr(m, "type", None) == "human"]
        assistant_messages = [m for m in filtered_messages if getattr(m, "type", None) == "ai"]

        if not user_messages or not assistant_messages:
            return None

        # Queue the filtered conversation for memory update
        correction_detected = detect_correction(filtered_messages)
        reinforcement_detected = not correction_detected and detect_reinforcement(filtered_messages)
        # Capture user_id at enqueue time while the request context is still alive.
        # threading.Timer fires on a different thread where ContextVar values are not
        # propagated, so we must store user_id explicitly in ConversationContext.
        user_id = get_effective_user_id()
        queue = get_memory_queue()
        queue.add(
            thread_id=thread_id,
            messages=filtered_messages,
            agent_name=self._agent_name,
            user_id=user_id,
            correction_detected=correction_detected,
            reinforcement_detected=reinforcement_detected,
        )
        tenant_id = get_current_tenant_id()
        _emit_sse(tenant_id, "user", thread_id, user_id)

        session_config = get_session_memory_config()
        if session_config.enabled:
            try:
                session_queue = get_session_memory_queue()
                session_queue.add(
                    thread_id=thread_id,
                    messages=filtered_messages,
                    user_id=user_id,
                    correction_detected=correction_detected,
                    reinforcement_detected=reinforcement_detected,
                )
                _emit_sse(tenant_id, "session", thread_id, user_id)
            except Exception:
                logger.exception("Failed to queue session memory update for thread %s", thread_id)

        domain_config = get_domain_memory_config()
        if domain_config.enabled:
            try:
                domain_queue = get_domain_memory_queue()
                domain_queue.add(
                    thread_id=thread_id,
                    messages=filtered_messages,
                    tenant_id=tenant_id,
                    user_id=user_id,
                )
                _emit_sse(tenant_id, "domain", thread_id, user_id)
            except Exception:
                logger.exception("Failed to queue domain memory update for thread %s", thread_id)

        return None
