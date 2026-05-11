"""Run event capture via LangChain callbacks.

RunJournal sits between LangChain's callback mechanism and the pluggable
RunEventStore. It standardizes callback data into RunEvent records and
handles token usage accumulation.

Key design decisions:
- on_llm_new_token is NOT implemented -- only complete messages via on_llm_end
- on_chat_model_start captures structured prompts as llm_request (OpenAI format) and
  extracts the first human message for run.input, because it is more reliable than
  on_chain_start (fires on every node) — messages here are fully structured.
- on_chain_start with parent_run_id=None emits a run.start trace marking root invocation.
- on_llm_end emits llm_response in OpenAI Chat Completions format
- Token usage accumulated in memory, written to RunRow on run completion
- Caller identification via tags injection (lead_agent / subagent:{name} / middleware:{name})
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, AnyMessage, BaseMessage, HumanMessage, ToolMessage
from langgraph.types import Command

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
        self._pending_flush_tasks: set[asyncio.Task[None]] = set()

        # Token accumulators
        self._total_input_tokens = 0
        self._total_output_tokens = 0
        self._total_tokens = 0
        self._llm_call_count = 0

        # Caller-bucketed token accumulators
        self._lead_agent_tokens = 0
        self._subagent_tokens = 0
        self._middleware_tokens = 0

        # Dedup: LangChain may fire on_llm_end multiple times for the same run_id
        self._counted_llm_run_ids: set[str] = set()
        self._counted_external_source_ids: set[str] = set()
        self._counted_message_llm_run_ids: set[str] = set()

        # Convenience fields
        self._last_ai_msg: str | None = None
        self._first_human_msg: str | None = None
        self._msg_count = 0

        # Latency tracking
        self._llm_start_times: dict[str, float] = {}  # langchain run_id -> start time

        # LLM request/response tracking
        self._llm_call_index = 0
        self._seen_llm_starts: set[str] = set()  # langchain run_ids that fired on_chat_model_start

    # -- Lifecycle callbacks --

    @staticmethod
    def _message_text(message: BaseMessage) -> str:
        """Extract displayable text from a message's mixed content shape."""
        content = getattr(message, "content", None)
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, str):
                    parts.append(block)
                elif isinstance(block, Mapping):
                    text = block.get("text")
                    if isinstance(text, str):
                        parts.append(text)
                    else:
                        nested = block.get("content")
                        if isinstance(nested, str):
                            parts.append(nested)
            return "".join(parts)
        if isinstance(content, Mapping):
            for key in ("text", "content"):
                value = content.get(key)
                if isinstance(value, str):
                    return value

        text = getattr(message, "text", None)
        if isinstance(text, str):
            return text
        return ""

    def _record_message_summary(self, message: BaseMessage, *, caller: str | None = None) -> None:
        """Update run-level convenience fields for persisted run rows."""
        self._msg_count += 1

        # ``last_ai_message`` should represent the lead agent's user-facing
        # answer. Middleware/subagent model calls and empty tool-call-only
        # AI messages must not overwrite the last useful assistant text.
        is_ai_message = isinstance(message, AIMessage) or getattr(message, "type", None) == "ai"
        if is_ai_message and (caller is None or caller == "lead_agent"):
            text = self._message_text(message).strip()
            if text:
                self._last_ai_msg = text[:2000]

    def on_chain_start(
        self,
        serialized: dict[str, Any],
        inputs: dict[str, Any],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        caller = self._identify_caller(tags)
        if parent_run_id is None:
            # Root graph invocation — emit a single trace event for the run start.
            chain_name = (serialized or {}).get("name", "unknown")
            self._put(
                event_type="run.start",
                category="trace",
                content={"chain": chain_name},
                metadata={"caller": caller, **(metadata or {})},
            )

    def on_chain_end(self, outputs: Any, *, run_id: UUID, **kwargs: Any) -> None:
        self._put(event_type="run.end", category="outputs", content=outputs, metadata={"status": "success"})
        self._flush_sync()

    def on_chain_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        self._put(
            event_type="run.error",
            category="error",
            content=str(error),
            metadata={"error_type": type(error).__name__},
        )
        self._flush_sync()

    # -- LLM callbacks --

    def on_chat_model_start(
        self,
        serialized: dict,
        messages: list[list[BaseMessage]],
        *,
        run_id: UUID,
        tags: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        """Capture structured prompt messages for llm_request event.

        This is also the canonical place to extract the first human message:
        messages are fully structured here, it fires only on real LLM calls,
        and the content is never compressed by checkpoint trimming.
        """
        rid = str(run_id)
        self._llm_start_times[rid] = time.monotonic()
        self._llm_call_index += 1
        self._seen_llm_starts.add(rid)

        logger.debug(
            "on_chat_model_start %s: tags=%s num_batches=%d message_counts=%s",
            run_id,
            tags,
            len(messages),
            [len(batch) for batch in messages],
        )

        # Capture the first human message sent to any LLM in this run.
        if not self._first_human_msg and messages:
            for batch in reversed(messages):
                for m in reversed(batch):
                    if isinstance(m, HumanMessage) and m.name != "summary":
                        caller = self._identify_caller(tags)
                        self.set_first_human_message(m.text)
                        self._put(
                            event_type="llm.human.input",
                            category="message",
                            content=m.model_dump(),
                            metadata={"caller": caller},
                        )
                        self._record_message_summary(m, caller=caller)
                        break
                if self._first_human_msg:
                    break

    def on_llm_start(self, serialized: dict, prompts: list[str], *, run_id: UUID, parent_run_id: UUID | None = None, tags: list[str] | None = None, metadata: dict[str, Any] | None = None, **kwargs: Any) -> None:
        # Fallback: on_chat_model_start is preferred. This just tracks latency.
        self._llm_start_times[str(run_id)] = time.monotonic()

    def on_llm_end(
        self,
        response: Any,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        messages: list[AnyMessage] = []
        logger.debug("on_llm_end %s: tags=%s", run_id, tags)
        for generation in response.generations:
            for gen in generation:
                if hasattr(gen, "message"):
                    messages.append(gen.message)
                else:
                    logger.warning(f"on_llm_end {run_id}: generation has no message attribute: {gen}")

        for message in messages:
            caller = self._identify_caller(tags)

            # Latency
            rid = str(run_id)
            start = self._llm_start_times.pop(rid, None)
            latency_ms = int((time.monotonic() - start) * 1000) if start else None

            # Token usage from message
            usage = getattr(message, "usage_metadata", None)
            usage_dict = dict(usage) if usage else {}

            # Resolve call index
            call_index = self._llm_call_index
            if rid not in self._seen_llm_starts:
                # Fallback: on_chat_model_start was not called
                self._llm_call_index += 1
                call_index = self._llm_call_index
                self._seen_llm_starts.add(rid)

            # Trace event: llm_response (OpenAI completion format)
            self._put(
                event_type="llm.ai.response",
                category="message",
                content=message.model_dump(),
                metadata={
                    "caller": caller,
                    "usage": usage_dict,
                    "latency_ms": latency_ms,
                    "llm_call_index": call_index,
                },
            )
            if rid not in self._counted_message_llm_run_ids:
                self._record_message_summary(message, caller=caller)

            # Token accumulation (dedup by langchain run_id to avoid double-counting
            # when the callback fires more than once for the same response)
            if self._track_tokens:
                input_tk = usage_dict.get("input_tokens", 0) or 0
                output_tk = usage_dict.get("output_tokens", 0) or 0
                total_tk = usage_dict.get("total_tokens", 0) or 0
                if total_tk == 0:
                    total_tk = input_tk + output_tk
                if total_tk > 0 and rid not in self._counted_llm_run_ids:
                    self._counted_llm_run_ids.add(rid)
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

        if messages:
            self._counted_message_llm_run_ids.add(str(run_id))

    def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        self._llm_start_times.pop(str(run_id), None)
        self._put(event_type="llm.error", category="trace", content=str(error))

    def on_tool_start(self, serialized, input_str, *, run_id, parent_run_id=None, tags=None, metadata=None, inputs=None, **kwargs):
        """Handle tool start event, cache tool call ID for later correlation"""
        tool_call_id = str(run_id)
        logger.debug("Tool start for node %s, tool_call_id=%s, tags=%s", run_id, tool_call_id, tags)

    def on_tool_end(self, output, *, run_id, parent_run_id=None, **kwargs):
        """Handle tool end event, append message and clear node data"""
        try:
            if isinstance(output, ToolMessage):
                msg = cast(ToolMessage, output)
                self._put(event_type="llm.tool.result", category="message", content=msg.model_dump())
                self._record_message_summary(msg)
            elif isinstance(output, Command):
                cmd = cast(Command, output)
                messages = cmd.update.get("messages", [])
                for message in messages:
                    if isinstance(message, BaseMessage):
                        self._put(event_type="llm.tool.result", category="message", content=message.model_dump())
                        self._record_message_summary(message)
                    else:
                        logger.warning(f"on_tool_end {run_id}: command update message is not BaseMessage: {type(message)}")
            else:
                logger.warning(f"on_tool_end {run_id}: output is not ToolMessage: {type(output)}")
        finally:
            logger.debug("Tool end for node %s", run_id)

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
        # Skip if a flush is already in flight — avoids concurrent writes
        # to the same SQLite file from multiple fire-and-forget tasks.
        if self._pending_flush_tasks:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No event loop — keep events in buffer for later async flush.
            return
        batch = self._buffer.copy()
        self._buffer.clear()
        task = loop.create_task(self._flush_async(batch))
        self._pending_flush_tasks.add(task)
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

    def _on_flush_done(self, task: asyncio.Task) -> None:
        self._pending_flush_tasks.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logger.warning("Journal flush task failed: %s", exc)

    def _identify_caller(self, tags: list[str] | None) -> str:
        _tags = tags or []
        for tag in _tags:
            if isinstance(tag, str) and (tag.startswith("subagent:") or tag.startswith("middleware:") or tag == "lead_agent"):
                return tag
        # Default to lead_agent: the main agent graph does not inject
        # callback tags, while subagents and middleware explicitly tag
        # themselves.
        return "lead_agent"

    # -- Public methods (called by worker) --

    def record_external_llm_usage_records(
        self,
        records: list[dict[str, int | str]],
    ) -> None:
        """Record token usage from external sources (e.g., subagents).

        Each record should contain:
            source_run_id: Unique identifier to prevent double-counting
            caller: Caller tag (e.g. "subagent:general-purpose")
            input_tokens: Input token count
            output_tokens: Output token count
            total_tokens: Total token count (computed from input+output if 0/missing)
        """
        if not self._track_tokens:
            return
        for record in records:
            source_id = str(record.get("source_run_id", ""))
            if not source_id:
                continue
            if source_id in self._counted_external_source_ids:
                continue

            total_tk = record.get("total_tokens", 0) or 0
            if total_tk <= 0:
                input_tk = record.get("input_tokens", 0) or 0
                output_tk = record.get("output_tokens", 0) or 0
                total_tk = input_tk + output_tk
            if total_tk <= 0:
                continue

            self._counted_external_source_ids.add(source_id)
            self._total_input_tokens += record.get("input_tokens", 0) or 0
            self._total_output_tokens += record.get("output_tokens", 0) or 0
            self._total_tokens += total_tk

            caller = str(record.get("caller", ""))
            if caller.startswith("subagent:"):
                self._subagent_tokens += total_tk
            elif caller.startswith("middleware:"):
                self._middleware_tokens += total_tk
            else:
                self._lead_agent_tokens += total_tk

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
        if self._pending_flush_tasks:
            await asyncio.gather(*tuple(self._pending_flush_tasks), return_exceptions=True)

        while self._buffer:
            batch = self._buffer[: self._flush_threshold]
            del self._buffer[: self._flush_threshold]
            try:
                await self._store.put_batch(batch)
            except Exception:
                self._buffer = batch + self._buffer
                raise

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
