"""Middleware for memory mechanism."""

import asyncio
import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langgraph.config import get_config
from langgraph.runtime import Runtime

from deerflow.agents.human_input import HUMAN_INPUT_RESPONSE_KEY
from deerflow.agents.memory import get_memory_manager
from deerflow.agents.middlewares.pii_redaction_middleware import _make_redactor, _redact_content, _Redactor
from deerflow.config.memory_config import get_memory_config
from deerflow.config.pii_redaction_config import PiiRedactionConfig
from deerflow.runtime.user_context import resolve_runtime_user_id
from deerflow.trace_context import DEERFLOW_TRACE_METADATA_KEY, resolve_trace_id
from deerflow.utils.messages import ORIGINAL_USER_CONTENT_KEY

if TYPE_CHECKING:
    from deerflow.config.memory_config import MemoryConfig

logger = logging.getLogger(__name__)


def redact_queued_messages(messages: list, pii_redaction_config: PiiRedactionConfig | None) -> list:
    """Redact a conversation payload queued for memory extraction (#3190 vector 5).

    Shared by MemoryMiddleware's enqueue boundary and the compaction-triggered
    ``memory_flush_hook``: placeholders are value-derived, so the same identity
    renders the same token across the batch, across enqueues, and across
    seams; message objects are rebuilt rather than mutated. Structured
    tool-call arguments are covered too — backends like OpenViking retain the full
    message object, including ``tool_calls`` and provider-format arguments in
    ``additional_kwargs``. Text-bearing provenance metadata is covered as
    well: UploadsMiddleware preserves the raw user turn in
    ``original_user_content``, and clarification replies keep the raw answer
    in ``human_input_response.value`` — DeerMem reads that mapping — so a
    redacted ``content`` alone would still leak either one to the memory
    backend.
    """
    redactor = _make_redactor(pii_redaction_config)

    redacted = []
    for message in messages:
        updates: dict = {}
        content, changed = _redact_content(message.content, redactor)
        if changed:
            updates["content"] = content
        tool_calls = getattr(message, "tool_calls", None)
        if tool_calls:
            rewritten = [_redact_tool_call(call, redactor) for call in tool_calls]
            if rewritten != tool_calls:
                updates["tool_calls"] = rewritten
        additional_kwargs = getattr(message, "additional_kwargs", None)
        if isinstance(additional_kwargs, dict):
            new_additional_kwargs = additional_kwargs
            if additional_kwargs.get("tool_calls"):
                rewritten = _redact_strings(additional_kwargs["tool_calls"], redactor)
                if rewritten != additional_kwargs["tool_calls"]:
                    new_additional_kwargs = {**new_additional_kwargs, "tool_calls": rewritten}
            original_content = additional_kwargs.get(ORIGINAL_USER_CONTENT_KEY)
            if isinstance(original_content, str) and original_content:
                redacted_original = redactor.redact(original_content)
                if redacted_original != original_content:
                    new_additional_kwargs = {**new_additional_kwargs, ORIGINAL_USER_CONTENT_KEY: redacted_original}
            human_input = additional_kwargs.get(HUMAN_INPUT_RESPONSE_KEY)
            if isinstance(human_input, Mapping) and isinstance(human_input.get("value"), str) and human_input["value"]:
                redacted_value = redactor.redact(human_input["value"])
                if redacted_value != human_input["value"]:
                    new_additional_kwargs = {**new_additional_kwargs, HUMAN_INPUT_RESPONSE_KEY: {**human_input, "value": redacted_value}}
            if new_additional_kwargs is not additional_kwargs:
                updates["additional_kwargs"] = new_additional_kwargs
        redacted.append(message.model_copy(update=updates) if updates else message)
    return redacted


def _redact_tool_call(call: dict, redactor: _Redactor) -> dict:
    """Redact PII inside one parsed tool-call dict (args values recursively)."""
    rewritten = dict(call)
    args = rewritten.get("args")
    if args is not None:
        rewritten["args"] = _redact_strings(args, redactor)
    return rewritten


def _redact_strings(value: object, redactor: _Redactor) -> object:
    """Redact every string leaf in a JSON-like *value* tree, keys included.

    Tool arguments can carry user data in mapping keys (e.g.
    ``{"contacts": {"alice@example.com": "manager"}}``), so string keys are
    redacted along with values. Two distinct raw keys redacting to the same
    token would require a sha256 collision; if a redacted key does equal
    another key already present in the rebuilt dict, the entries merge —
    accepted, since at 128 bits that only happens for identical identities.
    """
    if isinstance(value, str):
        return redactor.redact(value)
    if isinstance(value, list):
        return [_redact_strings(item, redactor) for item in value]
    if isinstance(value, dict):
        rebuilt = {}
        for key, item in value.items():
            new_key = redactor.redact(key) if isinstance(key, str) else key
            rebuilt[new_key] = _redact_strings(item, redactor)
        return rebuilt
    return value


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

    def __init__(
        self,
        agent_name: str | None = None,
        *,
        memory_config: "MemoryConfig | None" = None,
        pii_redaction_config: PiiRedactionConfig | None = None,
    ):
        """Initialize the MemoryMiddleware.

        Args:
            agent_name: If provided, memory is stored per-agent. If None, uses global memory.
            memory_config: Explicit memory config. When omitted, legacy global
                config fallback is used.
            pii_redaction_config: When enabled, the queued conversation payload
                is redacted at the enqueue boundary (#3190 vector 5) — request-scoped
                redaction leaves originals in thread state, and the buffered payload
                is durable, so the extraction model's input and the persisted facts
                would otherwise carry raw PII.
        """
        super().__init__()
        self._agent_name = agent_name
        self._memory_config = memory_config
        self._pii_redaction_config = pii_redaction_config

    def _resolve_add_args(self, state: MemoryMiddlewareState, runtime: Runtime) -> tuple[str, list, str, str] | None:
        """Resolve one write request without invoking the manager."""
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

        # Capture user_id at enqueue time while the request context is still alive.
        # threading.Timer fires on a different thread where ContextVar values are not
        # propagated, so we must store user_id explicitly in ConversationContext.
        user_id = resolve_runtime_user_id(runtime)
        # The memory update fires on a threading.Timer thread that inherits no
        # ContextVars, so the id is captured here, while the request context is
        # still alive, and carried as data. The runtime context is authoritative
        # (worker._bind_trace_id always fills it); the ambient fallback covers
        # embedded callers driving the agent outside a Gateway run.
        runtime_context = runtime.context if isinstance(runtime.context, dict) else {}
        trace_id = resolve_trace_id(runtime_context.get(DEERFLOW_TRACE_METADATA_KEY))

        return thread_id, self._redact_queued_messages(messages), user_id, trace_id

    def _redact_queued_messages(self, messages: list) -> list:
        """Redact the conversation payload queued for extraction (#3190 vector 5)."""
        return redact_queued_messages(messages, self._pii_redaction_config)

    @override
    def after_agent(self, state: MemoryMiddlewareState, runtime: Runtime) -> dict | None:
        """Queue conversation for memory update after agent completes."""
        add_args = self._resolve_add_args(state, runtime)
        if add_args is None:
            return None
        thread_id, messages, user_id, trace_id = add_args

        # Hand raw messages to the manager; the backend filters to user + final-AI
        # turns, validates, detects correction/reinforcement, and enqueues.
        get_memory_manager().add(
            thread_id,
            messages,
            agent_name=self._agent_name,
            user_id=user_id,
            trace_id=trace_id,
        )

        return None

    @override
    async def aafter_agent(self, state: MemoryMiddlewareState, runtime: Runtime) -> dict | None:
        """Use the manager's async boundary on LangGraph's async execution path."""
        add_args = self._resolve_add_args(state, runtime)
        if add_args is None:
            return None
        thread_id, messages, user_id, trace_id = add_args
        manager = await asyncio.to_thread(get_memory_manager)
        await manager.aadd(
            thread_id,
            messages,
            agent_name=self._agent_name,
            user_id=user_id,
            trace_id=trace_id,
        )
        return None
