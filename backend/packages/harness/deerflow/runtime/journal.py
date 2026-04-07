"""Run event capture via LangChain callbacks.

RunJournal sits between LangChain's callback mechanism and the pluggable
RunEventStore. It standardizes callback data into RunEvent records and
handles token usage accumulation.

Key design decisions:
- on_llm_new_token is NOT implemented -- only complete messages via on_llm_end
- on_chat_model_start captures structured prompts as llm_request (OpenAI format)
- on_llm_end emits llm_response in OpenAI Chat Completions format
- Token usage accumulated in memory, written to RunRow on run completion
- Caller identification via tags injection (lead_agent / subagent:{name} / middleware:{name})
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler

if TYPE_CHECKING:
    from deerflow.runtime.events.store.base import RunEventStore

logger = logging.getLogger(__name__)


class RunJournal(BaseCallbackHandler):
    """LangChain callback handler that captures events to RunEventStore."""

    def __init__(
        self,
        run_id: str,
        thread_id: str,
        event_store: RunEventStore,
        *,
        track_token_usage: bool = True,
        flush_threshold: int = 20,
    ):
        super().__init__()
        self.run_id = run_id
        self.thread_id = thread_id
        self._store = event_store
        self._track_tokens = track_token_usage
        self._flush_threshold = flush_threshold

        # Write buffer
        self._buffer: list[dict] = []

        # Token accumulators
        self._total_input_tokens = 0
        self._total_output_tokens = 0
        self._total_tokens = 0
        self._llm_call_count = 0
        self._lead_agent_tokens = 0
        self._subagent_tokens = 0
        self._middleware_tokens = 0

        # Convenience fields
        self._last_ai_msg: str | None = None
        self._first_human_msg: str | None = None
        self._msg_count = 0

        # Latency tracking
        self._llm_start_times: dict[str, float] = {}  # langchain run_id -> start time

        # LLM request/response tracking
        self._llm_call_index = 0
        self._cached_prompts: dict[str, list[dict]] = {}  # langchain run_id -> OpenAI messages
        self._cached_models: dict[str, str] = {}  # langchain run_id -> model name

        # Tool call ID cache
        self._tool_call_ids: dict[str, str] = {}  # langchain run_id -> tool_call_id

    # -- Lifecycle callbacks --

    def on_chain_start(self, serialized: dict, inputs: Any, *, run_id: UUID, **kwargs: Any) -> None:
        if kwargs.get("parent_run_id") is not None:
            return
        self._put(
            event_type="run_start",
            category="lifecycle",
            metadata={"input_preview": str(inputs)[:500]},
        )

    def on_chain_end(self, outputs: Any, *, run_id: UUID, **kwargs: Any) -> None:
        if kwargs.get("parent_run_id") is not None:
            return
        self._put(event_type="run_end", category="lifecycle", metadata={"status": "success"})
        self._flush_sync()

    def on_chain_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        if kwargs.get("parent_run_id") is not None:
            return
        self._put(
            event_type="run_error",
            category="lifecycle",
            content=str(error),
            metadata={"error_type": type(error).__name__},
        )
        self._flush_sync()

    # -- LLM callbacks --

    def on_chat_model_start(self, serialized: dict, messages: list[list], *, run_id: UUID, **kwargs: Any) -> None:
        """Capture structured prompt messages for llm_request event."""
        from deerflow.runtime.converters import langchain_messages_to_openai

        rid = str(run_id)
        self._llm_start_times[rid] = time.monotonic()
        self._llm_call_index += 1

        model_name = serialized.get("name", "")
        self._cached_models[rid] = model_name

        # Convert the first message list (LangChain passes list-of-lists)
        prompt_msgs = messages[0] if messages else []
        openai_msgs = langchain_messages_to_openai(prompt_msgs)
        self._cached_prompts[rid] = openai_msgs

        caller = self._identify_caller(kwargs)
        self._put(
            event_type="llm_request",
            category="trace",
            content={"model": model_name, "messages": openai_msgs},
            metadata={"caller": caller, "llm_call_index": self._llm_call_index},
        )

    def on_llm_start(self, serialized: dict, prompts: list[str], *, run_id: UUID, **kwargs: Any) -> None:
        # Fallback: on_chat_model_start is preferred. This just tracks latency.
        self._llm_start_times[str(run_id)] = time.monotonic()

    def on_llm_end(self, response: Any, *, run_id: UUID, **kwargs: Any) -> None:
        from deerflow.runtime.converters import langchain_to_openai_completion

        try:
            message = response.generations[0][0].message
        except (IndexError, AttributeError):
            logger.debug("on_llm_end: could not extract message from response")
            return

        caller = self._identify_caller(kwargs)

        # Latency
        rid = str(run_id)
        start = self._llm_start_times.pop(rid, None)
        latency_ms = int((time.monotonic() - start) * 1000) if start else None

        # Token usage from message
        usage = getattr(message, "usage_metadata", None)
        usage_dict = dict(usage) if usage else {}

        # Resolve call index
        call_index = self._llm_call_index
        if rid not in self._cached_prompts:
            # Fallback: on_chat_model_start was not called
            self._llm_call_index += 1
            call_index = self._llm_call_index

        # Clean up caches
        self._cached_prompts.pop(rid, None)
        self._cached_models.pop(rid, None)

        # Trace event: llm_response (OpenAI completion format)
        content = getattr(message, "content", "")
        self._put(
            event_type="llm_response",
            category="trace",
            content=langchain_to_openai_completion(message),
            metadata={
                "caller": caller,
                "usage": usage_dict,
                "latency_ms": latency_ms,
                "llm_call_index": call_index,
            },
        )

        # Message events: only lead_agent gets message-category events.
        # Content uses message.model_dump() to align with checkpoint format.
        tool_calls = getattr(message, "tool_calls", None) or []
        if caller == "lead_agent":
            resp_meta = getattr(message, "response_metadata", None) or {}
            model_name = resp_meta.get("model_name") if isinstance(resp_meta, dict) else None
            if tool_calls:
                # ai_tool_call: agent decided to use tools
                self._put(
                    event_type="ai_tool_call",
                    category="message",
                    content=message.model_dump(),
                    metadata={"model_name": model_name, "finish_reason": "tool_calls"},
                )
            elif isinstance(content, str) and content:
                # ai_message: final text reply
                self._put(
                    event_type="ai_message",
                    category="message",
                    content=message.model_dump(),
                    metadata={"model_name": model_name, "finish_reason": "stop"},
                )
                self._last_ai_msg = content
                self._msg_count += 1

        # Token accumulation
        if self._track_tokens:
            input_tk = usage_dict.get("input_tokens", 0) or 0
            output_tk = usage_dict.get("output_tokens", 0) or 0
            total_tk = usage_dict.get("total_tokens", 0) or 0
            if total_tk == 0:
                total_tk = input_tk + output_tk
            if total_tk > 0:
                self._total_input_tokens += input_tk
                self._total_output_tokens += output_tk
                self._total_tokens += total_tk
                self._llm_call_count += 1
                if caller.startswith("subagent:"):
                    self._subagent_tokens += total_tk
                elif caller.startswith("middleware:"):
                    self._middleware_tokens += total_tk
                else:
                    self._lead_agent_tokens += total_tk

    def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        self._llm_start_times.pop(str(run_id), None)
        self._put(event_type="llm_error", category="trace", content=str(error))

    # -- Tool callbacks --

    def on_tool_start(self, serialized: dict, input_str: str, *, run_id: UUID, **kwargs: Any) -> None:
        tool_call_id = kwargs.get("tool_call_id")
        if tool_call_id:
            self._tool_call_ids[str(run_id)] = tool_call_id
        self._put(
            event_type="tool_start",
            category="trace",
            metadata={
                "tool_name": serialized.get("name", ""),
                "tool_call_id": tool_call_id,
                "args": str(input_str)[:2000],
            },
        )

    def on_tool_end(self, output: Any, *, run_id: UUID, **kwargs: Any) -> None:
        from langchain_core.messages import ToolMessage

        # Extract fields from ToolMessage object when LangChain provides one.
        # LangChain's _format_output wraps tool results into a ToolMessage
        # with tool_call_id, name, status, and artifact — more complete than
        # what kwargs alone provides.
        if isinstance(output, ToolMessage):
            tool_call_id = output.tool_call_id or kwargs.get("tool_call_id") or self._tool_call_ids.pop(str(run_id), None)
            tool_name = output.name or kwargs.get("name", "")
            status = getattr(output, "status", "success") or "success"
            content_str = output.content if isinstance(output.content, str) else str(output.content)
            # Use model_dump() for checkpoint-aligned message content.
            # Override tool_call_id if it was resolved from cache.
            msg_content = output.model_dump()
            if msg_content.get("tool_call_id") != tool_call_id:
                msg_content["tool_call_id"] = tool_call_id
        else:
            tool_call_id = kwargs.get("tool_call_id") or self._tool_call_ids.pop(str(run_id), None)
            tool_name = kwargs.get("name", "")
            status = "success"
            content_str = str(output)
            # Construct checkpoint-aligned dict when output is a plain string.
            msg_content = ToolMessage(
                content=content_str,
                tool_call_id=tool_call_id or "",
                name=tool_name,
                status=status,
            ).model_dump()

        # Trace event (always)
        self._put(
            event_type="tool_end",
            category="trace",
            content=content_str,
            metadata={
                "tool_name": tool_name,
                "tool_call_id": tool_call_id,
                "status": status,
            },
        )

        # Message event: tool_result (checkpoint-aligned model_dump format)
        self._put(
            event_type="tool_result",
            category="message",
            content=msg_content,
            metadata={"tool_name": tool_name, "status": status},
        )

    def on_tool_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        from langchain_core.messages import ToolMessage

        tool_call_id = kwargs.get("tool_call_id") or self._tool_call_ids.pop(str(run_id), None)
        tool_name = kwargs.get("name", "")

        # Trace event
        self._put(
            event_type="tool_error",
            category="trace",
            content=str(error),
            metadata={
                "tool_name": tool_name,
                "tool_call_id": tool_call_id,
            },
        )

        # Message event: tool_result with error status (checkpoint-aligned)
        msg_content = ToolMessage(
            content=str(error),
            tool_call_id=tool_call_id or "",
            name=tool_name,
            status="error",
        ).model_dump()
        self._put(
            event_type="tool_result",
            category="message",
            content=msg_content,
            metadata={"tool_name": tool_name, "status": "error"},
        )

    # -- Custom event callback --

    def on_custom_event(self, name: str, data: Any, *, run_id: UUID, **kwargs: Any) -> None:
        from deerflow.runtime.serialization import serialize_lc_object

        if name == "summarization":
            data_dict = data if isinstance(data, dict) else {}
            self._put(
                event_type="summarization",
                category="trace",
                content=data_dict.get("summary", ""),
                metadata={
                    "replaced_message_ids": data_dict.get("replaced_message_ids", []),
                    "replaced_count": data_dict.get("replaced_count", 0),
                },
            )
            self._put(
                event_type="middleware:summarize",
                category="middleware",
                content={"role": "system", "content": data_dict.get("summary", "")},
                metadata={"replaced_count": data_dict.get("replaced_count", 0)},
            )
        else:
            event_data = serialize_lc_object(data) if not isinstance(data, dict) else data
            self._put(
                event_type=name,
                category="trace",
                metadata=event_data if isinstance(event_data, dict) else {"data": event_data},
            )

    # -- Internal methods --

    def _put(self, *, event_type: str, category: str, content: str | dict = "", metadata: dict | None = None) -> None:
        self._buffer.append(
            {
                "thread_id": self.thread_id,
                "run_id": self.run_id,
                "event_type": event_type,
                "category": category,
                "content": content,
                "metadata": metadata or {},
                "created_at": datetime.now(UTC).isoformat(),
            }
        )
        if len(self._buffer) >= self._flush_threshold:
            self._flush_sync()

    def _flush_sync(self) -> None:
        """Best-effort flush of buffer to RunEventStore.

        BaseCallbackHandler methods are synchronous.  If an event loop is
        running we schedule an async ``put_batch``; otherwise the events
        stay in the buffer and are flushed later by the async ``flush()``
        call in the worker's ``finally`` block.
        """
        if not self._buffer:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No event loop — keep events in buffer for later async flush.
            return
        batch = self._buffer.copy()
        self._buffer.clear()
        task = loop.create_task(self._flush_async(batch))
        task.add_done_callback(self._on_flush_done)

    async def _flush_async(self, batch: list[dict]) -> None:
        try:
            await self._store.put_batch(batch)
        except Exception:
            logger.warning(
                "Failed to flush %d events for run %s — returning to buffer",
                len(batch),
                self.run_id,
                exc_info=True,
            )
            # Return failed events to buffer for retry on next flush
            self._buffer = batch + self._buffer

    @staticmethod
    def _on_flush_done(task: asyncio.Task) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logger.warning("Journal flush task failed: %s", exc)

    def _identify_caller(self, kwargs: dict) -> str:
        for tag in kwargs.get("tags") or []:
            if isinstance(tag, str) and (tag.startswith("subagent:") or tag.startswith("middleware:") or tag == "lead_agent"):
                return tag
        # Default to lead_agent: the main agent graph does not inject
        # callback tags, while subagents and middleware explicitly tag
        # themselves.
        return "lead_agent"

    # -- Public methods (called by worker) --

    def set_first_human_message(self, content: str) -> None:
        """Record the first human message for convenience fields."""
        self._first_human_msg = content[:2000] if content else None

    def record_middleware(self, tag: str, *, name: str, hook: str, action: str, changes: dict) -> None:
        """Record a middleware state-change event.

        Called by middleware implementations when they perform a meaningful
        state change (e.g., title generation, summarization, HITL approval).
        Pure-observation middleware should not call this.

        Args:
            tag: Short identifier for the middleware (e.g., "title", "summarize",
                 "guardrail"). Used to form event_type="middleware:{tag}".
            name: Full middleware class name.
            hook: Lifecycle hook that triggered the action (e.g., "after_model").
            action: Specific action performed (e.g., "generate_title").
            changes: Dict describing the state changes made.
        """
        self._put(
            event_type=f"middleware:{tag}",
            category="middleware",
            content={"name": name, "hook": hook, "action": action, "changes": changes},
        )

    async def flush(self) -> None:
        """Force flush remaining buffer. Called in worker's finally block."""
        if self._buffer:
            batch = self._buffer.copy()
            self._buffer.clear()
            await self._store.put_batch(batch)

    def get_completion_data(self) -> dict:
        """Return accumulated token and message data for run completion."""
        return {
            "total_input_tokens": self._total_input_tokens,
            "total_output_tokens": self._total_output_tokens,
            "total_tokens": self._total_tokens,
            "llm_call_count": self._llm_call_count,
            "lead_agent_tokens": self._lead_agent_tokens,
            "subagent_tokens": self._subagent_tokens,
            "middleware_tokens": self._middleware_tokens,
            "message_count": self._msg_count,
            "last_ai_message": self._last_ai_msg,
            "first_human_message": self._first_human_msg,
        }
