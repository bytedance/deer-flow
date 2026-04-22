"""Run execution event recording callback."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import HumanMessage

from deerflow.runtime.converters import langchain_messages_to_openai, langchain_to_openai_completion

from ..store import RunEventStore

logger = logging.getLogger(__name__)


class RunEventCallback(BaseCallbackHandler):
    """Capture LangChain execution events into the run event store."""

    def __init__(
        self,
        *,
        run_id: str,
        thread_id: str,
        event_store: RunEventStore,
        flush_threshold: int = 5,
        max_trace_content: int = 10240,
    ) -> None:
        super().__init__()
        self.run_id = run_id
        self.thread_id = thread_id
        self._store = event_store
        self._flush_threshold = flush_threshold
        self._max_trace_content = max_trace_content
        self._buffer: list[dict[str, Any]] = []
        self._llm_start_times: dict[str, float] = {}
        self._llm_call_index = 0
        self._cached_prompts: dict[str, list[dict[str, Any]]] = {}
        self._tool_call_ids: dict[str, str] = {}
        self._human_message_recorded = False

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

    def on_chat_model_start(self, serialized: dict, messages: list[list], *, run_id: UUID, **kwargs: Any) -> None:
        rid = str(run_id)
        self._llm_start_times[rid] = time.monotonic()
        self._llm_call_index += 1

        prompt_msgs = messages[0] if messages else []
        openai_msgs = langchain_messages_to_openai(prompt_msgs)
        self._cached_prompts[rid] = openai_msgs
        caller = self._identify_caller(kwargs)

        self._record_first_human_message(prompt_msgs, caller=caller)

        self._put(
            event_type="llm_request",
            category="trace",
            content={"model": serialized.get("name", ""), "messages": openai_msgs},
            metadata={
                "caller": caller,
                "llm_call_index": self._llm_call_index,
            },
        )

    def on_llm_start(self, serialized: dict, prompts: list[str], *, run_id: UUID, **kwargs: Any) -> None:
        self._llm_start_times[str(run_id)] = time.monotonic()

    def on_llm_end(self, response: Any, *, run_id: UUID, **kwargs: Any) -> None:
        try:
            message = response.generations[0][0].message
        except (IndexError, AttributeError):
            logger.debug("on_llm_end: could not extract message from response")
            return

        rid = str(run_id)
        start = self._llm_start_times.pop(rid, None)
        latency_ms = int((time.monotonic() - start) * 1000) if start else None
        usage = dict(getattr(message, "usage_metadata", None) or {})
        caller = self._identify_caller(kwargs)

        call_index = self._llm_call_index
        if rid not in self._cached_prompts:
            self._llm_call_index += 1
            call_index = self._llm_call_index
        self._cached_prompts.pop(rid, None)

        self._put(
            event_type="llm_response",
            category="trace",
            content=langchain_to_openai_completion(message),
            metadata={
                "caller": caller,
                "usage": usage,
                "latency_ms": latency_ms,
                "llm_call_index": call_index,
            },
        )

        content = getattr(message, "content", "")
        tool_calls = getattr(message, "tool_calls", None) or []
        if caller != "lead_agent":
            return
        if tool_calls:
            self._put(
                event_type="ai_tool_call",
                category="message",
                content=message.model_dump(),
                metadata={"finish_reason": "tool_calls"},
            )
        elif isinstance(content, str) and content:
            self._put(
                event_type="ai_message",
                category="message",
                content=message.model_dump(),
                metadata={"finish_reason": "stop"},
            )

    def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        self._llm_start_times.pop(str(run_id), None)
        self._put(event_type="llm_error", category="trace", content=str(error))

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

        if isinstance(output, ToolMessage):
            tool_call_id = output.tool_call_id or kwargs.get("tool_call_id") or self._tool_call_ids.pop(str(run_id), None)
            tool_name = output.name or kwargs.get("name", "")
            status = getattr(output, "status", "success") or "success"
            content_str = output.content if isinstance(output.content, str) else str(output.content)
            msg_content = output.model_dump()
            if msg_content.get("tool_call_id") != tool_call_id:
                msg_content["tool_call_id"] = tool_call_id
        else:
            tool_call_id = kwargs.get("tool_call_id") or self._tool_call_ids.pop(str(run_id), None)
            tool_name = kwargs.get("name", "")
            status = "success"
            content_str = str(output)
            msg_content = ToolMessage(
                content=content_str,
                tool_call_id=tool_call_id or "",
                name=tool_name,
                status=status,
            ).model_dump()

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
        self._put(
            event_type="tool_error",
            category="trace",
            content=str(error),
            metadata={"tool_name": tool_name, "tool_call_id": tool_call_id},
        )
        self._put(
            event_type="tool_result",
            category="message",
            content=ToolMessage(
                content=str(error),
                tool_call_id=tool_call_id or "",
                name=tool_name,
                status="error",
            ).model_dump(),
            metadata={"tool_name": tool_name, "status": "error"},
        )

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
            return

        event_data = serialize_lc_object(data) if not isinstance(data, dict) else data
        self._put(
            event_type=name,
            category="trace",
            metadata=event_data if isinstance(event_data, dict) else {"data": event_data},
        )

    async def flush(self) -> None:
        if self._buffer:
            batch = self._buffer.copy()
            self._buffer.clear()
            await self._store.put_batch(batch)

    def _put(
        self,
        *,
        event_type: str,
        category: str,
        content: Any = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        normalized_metadata = dict(metadata or {})
        if category != "message" and isinstance(content, str) and len(content) > self._max_trace_content:
            normalized_metadata["content_truncated"] = True
            normalized_metadata["original_content_length"] = len(content)
            content = content[: self._max_trace_content]

        self._buffer.append(
            {
                "thread_id": self.thread_id,
                "run_id": self.run_id,
                "event_type": event_type,
                "category": category,
                "content": content,
                "metadata": normalized_metadata,
                "created_at": datetime.now(UTC).isoformat(),
            }
        )
        if len(self._buffer) >= self._flush_threshold:
            self._flush_sync()

    def _flush_sync(self) -> None:
        if not self._buffer:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        batch = self._buffer.copy()
        self._buffer.clear()
        task = loop.create_task(self._flush_async(batch))
        task.add_done_callback(self._on_flush_done)

    async def _flush_async(self, batch: list[dict[str, Any]]) -> None:
        try:
            await self._store.put_batch(batch)
        except Exception:
            logger.warning(
                "Failed to flush %d events for run %s; returning to buffer",
                len(batch),
                self.run_id,
                exc_info=True,
            )
            self._buffer = batch + self._buffer

    @staticmethod
    def _on_flush_done(task: asyncio.Task) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logger.warning("Run event flush task failed: %s", exc)

    def _identify_caller(self, kwargs: dict[str, Any]) -> str:
        for tag in kwargs.get("tags") or []:
            if isinstance(tag, str) and (
                tag.startswith("subagent:")
                or tag.startswith("middleware:")
                or tag == "lead_agent"
            ):
                return tag
        return "lead_agent"

    def _record_first_human_message(self, messages: list[Any], *, caller: str) -> None:
        if self._human_message_recorded:
            return

        for message in messages:
            if not isinstance(message, HumanMessage):
                continue
            if message.name == "summary":
                continue
            self._put(
                event_type="human_message",
                category="message",
                content=message.model_dump(),
                metadata={
                    "caller": caller,
                    "source": "chat_model_start",
                },
            )
            self._human_message_recorded = True
            return
