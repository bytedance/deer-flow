"""Middleware for memory mechanism."""

import asyncio
import concurrent.futures
import logging
import re
from typing import TYPE_CHECKING, Any, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langgraph.config import get_config
from langgraph.runtime import Runtime

from deerflow.agents.memory.queue import get_memory_queue
from deerflow.config.memory_config import get_memory_config

if TYPE_CHECKING:
    from deerflow.identity.agent_identity import AgentIdentity

logger = logging.getLogger(__name__)

# Shared executor for fire-and-forget OV async store calls
_OV_STORE_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="ov-memory")


def _serialize_messages(messages: list[Any]) -> list[dict[str, str]]:
    """Convert LangChain message objects to plain {role, content} dicts for OV API."""
    serialized = []
    for msg in messages:
        msg_type = getattr(msg, "type", None)
        role = {"human": "user", "ai": "assistant", "system": "system"}.get(msg_type, msg_type or "user")
        content = getattr(msg, "content", "")
        if isinstance(content, list):
            content = " ".join(
                block.get("text", "") for block in content if isinstance(block, dict)
            )
        serialized.append({"role": role, "content": str(content)})
    return serialized


def _fire_ov_store(ov_url: str, api_key: str | None, identity: "AgentIdentity", messages: list[dict[str, str]]) -> None:
    """Run OVMemoryBackend.store_memory in a background thread (fire-and-forget)."""
    from deerflow.agents.memory.ov_backend import OVMemoryBackend

    async def _run() -> None:
        backend = OVMemoryBackend(ov_url, api_key, identity)
        try:
            await backend.store_memory(messages)
        except Exception as exc:
            logger.warning("OV memory store failed (non-fatal): %s", exc)

    try:
        asyncio.run(_run())
    except Exception as exc:
        logger.warning("OV memory store executor error (non-fatal): %s", exc)

class MemoryMiddlewareState(AgentState):
    """Compatible with the `ThreadState` schema."""

    pass


def _filter_messages_for_memory(messages: list[Any]) -> list[Any]:
    """Filter messages to keep only user inputs and final assistant responses.

    This filters out:
    - Tool messages (intermediate tool call results)
    - AI messages with tool_calls (intermediate steps, not final responses)
    - The <uploaded_files> block injected by UploadsMiddleware into human messages
      (file paths are session-scoped and must not persist in long-term memory).
      The user's actual question is preserved; only turns whose content is entirely
      the upload block (nothing remains after stripping) are dropped along with
      their paired assistant response.

    Only keeps:
    - Human messages (with the ephemeral upload block removed)
    - AI messages without tool_calls (final assistant responses), unless the
      paired human turn was upload-only and had no real user text.

    Args:
        messages: List of all conversation messages.

    Returns:
        Filtered list containing only user inputs and final assistant responses.
    """
    _UPLOAD_BLOCK_RE = re.compile(r"<uploaded_files>[\s\S]*?</uploaded_files>\n*", re.IGNORECASE)

    filtered = []
    skip_next_ai = False
    for msg in messages:
        msg_type = getattr(msg, "type", None)

        if msg_type == "human":
            content = getattr(msg, "content", "")
            if isinstance(content, list):
                content = " ".join(p.get("text", "") for p in content if isinstance(p, dict))
            content_str = str(content)
            if "<uploaded_files>" in content_str:
                # Strip the ephemeral upload block; keep the user's real question.
                stripped = _UPLOAD_BLOCK_RE.sub("", content_str).strip()
                if not stripped:
                    # Nothing left — the entire turn was upload bookkeeping;
                    # skip it and the paired assistant response.
                    skip_next_ai = True
                    continue
                # Rebuild the message with cleaned content so the user's question
                # is still available for memory summarisation.
                from copy import copy

                clean_msg = copy(msg)
                clean_msg.content = stripped
                filtered.append(clean_msg)
                skip_next_ai = False
            else:
                filtered.append(msg)
                skip_next_ai = False
        elif msg_type == "ai":
            tool_calls = getattr(msg, "tool_calls", None)
            if not tool_calls:
                if skip_next_ai:
                    skip_next_ai = False
                    continue
                filtered.append(msg)
        # Skip tool messages and AI messages with tool_calls

    return filtered


class MemoryMiddleware(AgentMiddleware[MemoryMiddlewareState]):
    """Middleware that queues conversation for memory update after agent execution.

    This middleware:
    1. After each agent execution, queues the conversation for memory update
    2. Only includes user inputs and final assistant responses (ignores tool calls)
    3. The queue uses debouncing to batch multiple updates together
    4. Memory is updated asynchronously via LLM summarization
    """

    state_schema = MemoryMiddlewareState

    def __init__(self, agent_name: str | None = None, identity: "AgentIdentity | None" = None):
        """Initialize the MemoryMiddleware.

        Args:
            agent_name: If provided, memory is stored per-agent. If None, uses global memory.
            identity: Full three-tier identity for identity-scoped memory isolation.
                      When set, takes precedence over agent_name for path resolution.
        """
        super().__init__()
        self._agent_name = agent_name
        self._identity = identity

    @override
    def after_agent(self, state: MemoryMiddlewareState, runtime: Runtime) -> dict | None:
        """Queue conversation for memory update after agent completes.

        Args:
            state: The current agent state.
            runtime: The runtime context.

        Returns:
            None (no state changes needed from this middleware).
        """
        config = get_memory_config()
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
        filtered_messages = _filter_messages_for_memory(messages)

        # Only queue if there's meaningful conversation
        # At minimum need one user message and one assistant response
        user_messages = [m for m in filtered_messages if getattr(m, "type", None) == "human"]
        assistant_messages = [m for m in filtered_messages if getattr(m, "type", None) == "ai"]

        if not user_messages or not assistant_messages:
            return None

        # Route to OV backend and/or local queue based on memory_config.backend
        if config.backend in ("ov", "ov+local") and self._identity is not None:
            serialized = _serialize_messages(filtered_messages)
            _OV_STORE_EXECUTOR.submit(_fire_ov_store, config.ov_url, config.ov_api_key, self._identity, serialized)

        if config.backend in ("local", "ov+local"):
            # Queue the filtered conversation for memory update (identity-scoped when available)
            queue = get_memory_queue()
            queue.add(thread_id=thread_id, messages=filtered_messages, agent_name=self._agent_name, identity=self._identity)

        return None
