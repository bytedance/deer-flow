<<<<<<< HEAD
"""Middleware for logging and persisting LLM token usage with rate limiting and async batch writes."""
=======
"""Middleware for logging token usage and annotating step attribution."""

from __future__ import annotations
>>>>>>> 4ead2c6b197bcfa863b8381b3e30484060e41e0c

from __future__ import annotations

import asyncio
import logging
<<<<<<< HEAD
from collections import deque
from datetime import datetime, timezone
from typing import override
=======
from collections import defaultdict
from typing import Any, override
>>>>>>> 4ead2c6b197bcfa863b8381b3e30484060e41e0c

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.todo import Todo
from langchain_core.messages import AIMessage
from langgraph.runtime import Runtime

from deerflow.config.tenant import get_current_tenant_id

logger = logging.getLogger(__name__)

<<<<<<< HEAD
# Per-tenant in-memory rate limit counters
_rate_limit_counters: dict[str, dict] = {}


def _get_tenant_counter(tenant_id: str) -> dict:
    now = datetime.now(timezone.utc)
    minute_key = now.strftime("%Y-%m-%dT%H:%M")
    if tenant_id not in _rate_limit_counters:
        _rate_limit_counters[tenant_id] = {"minute_key": minute_key, "calls": 0, "tokens": 0}
    counter = _rate_limit_counters[tenant_id]
    if counter["minute_key"] != minute_key:
        counter["minute_key"] = minute_key
        counter["calls"] = 0
        counter["tokens"] = 0
    return counter


class TokenUsageMiddleware(AgentMiddleware):
    """Logs and optionally persists token usage from model response usage_metadata.

    When cost management is enabled, records are buffered in memory and
    flushed asynchronously in batches to reduce filesystem I/O.
    """

    _BUFFER_FLUSH_SIZE = 50
    _BUFFER_FLUSH_INTERVAL = 5.0

    def __init__(self, storage: object | None = None, calculator: object | None = None) -> None:
        self.storage = storage
        self.calculator = calculator
        self._buffer: deque = deque()
        self._flush_task: asyncio.Task | None = None
        self._started = False

    def _ensure_flush_task(self) -> None:
        if self._started:
            return
        self._started = True
        try:
            loop = asyncio.get_running_loop()
            self._flush_task = loop.create_task(self._periodic_flush())
        except RuntimeError:
            pass

    async def _periodic_flush(self) -> None:
        while True:
            await asyncio.sleep(self._BUFFER_FLUSH_INTERVAL)
            await self._flush_buffer()

    async def _flush_buffer(self) -> None:
        if not self._buffer:
            return
        records = list(self._buffer)
        self._buffer.clear()
        try:
            for record in records:
                self.storage.add_record(record)
            logger.debug("Flushed %d token usage records", len(records))
        except Exception:
            logger.exception("Failed to flush token usage batch (%d records)", len(records))
            self._buffer.extendleft(reversed(records))

    async def shutdown(self) -> None:
        if self._flush_task is not None:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
        await self._flush_buffer()

    @override
    def after_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        return self._process_usage(state, runtime)

    @override
    async def aafter_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        return self._process_usage(state, runtime)

    def _check_llm_rate_limit(self, tenant_id: str, total_tokens: int) -> bool:
        """Check LLM-level rate limits. Returns True if allowed, False if exceeded."""
        from deerflow.config.rate_limit_config import get_rate_limit_config

        rl_config = get_rate_limit_config()
        if not rl_config.enabled:
            return True

        counter = _get_tenant_counter(tenant_id)
        counter["calls"] += 1
        counter["tokens"] += total_tokens

        if counter["calls"] > rl_config.llm_calls_per_minute:
            logger.warning("LLM call rate limit exceeded for tenant %s: %d calls", tenant_id, counter["calls"])
            return False

        if counter["tokens"] > rl_config.tokens_per_minute:
            logger.warning("LLM token rate limit exceeded for tenant %s: %d tokens", tenant_id, counter["tokens"])
            return False

        return True

    def _process_usage(self, state: AgentState, runtime: Runtime) -> None:
=======
TOKEN_USAGE_ATTRIBUTION_KEY = "token_usage_attribution"


def _string_arg(value: Any) -> str | None:
    if isinstance(value, str):
        normalized = value.strip()
        return normalized or None
    return None


def _normalize_todos(value: Any) -> list[Todo]:
    if not isinstance(value, list):
        return []

    normalized: list[Todo] = []
    for item in value:
        if not isinstance(item, dict):
            continue

        todo: Todo = {}
        content = _string_arg(item.get("content"))
        status = item.get("status")

        if content is not None:
            todo["content"] = content
        if status in {"pending", "in_progress", "completed"}:
            todo["status"] = status

        normalized.append(todo)

    return normalized


def _todo_action_kind(previous: Todo | None, current: Todo) -> str:
    status = current.get("status")
    previous_content = previous.get("content") if previous else None
    current_content = current.get("content")

    if previous is None:
        if status == "completed":
            return "todo_complete"
        if status == "in_progress":
            return "todo_start"
        return "todo_update"

    if previous_content != current_content:
        return "todo_update"

    if status == "completed":
        return "todo_complete"
    if status == "in_progress":
        return "todo_start"
    return "todo_update"


def _build_todo_actions(previous_todos: list[Todo], next_todos: list[Todo]) -> list[dict[str, Any]]:
    # This is the single source of truth for precise write_todos token
    # attribution. The frontend intentionally falls back to a generic
    # "Update to-do list" label when this metadata is missing or malformed.
    previous_by_content: dict[str, list[tuple[int, Todo]]] = defaultdict(list)
    matched_previous_indices: set[int] = set()

    for index, todo in enumerate(previous_todos):
        content = todo.get("content")
        if isinstance(content, str) and content:
            previous_by_content[content].append((index, todo))

    actions: list[dict[str, Any]] = []

    for index, todo in enumerate(next_todos):
        content = todo.get("content")
        if not isinstance(content, str) or not content:
            continue

        previous_match: Todo | None = None
        content_matches = previous_by_content.get(content)
        if content_matches:
            while content_matches and content_matches[0][0] in matched_previous_indices:
                content_matches.pop(0)
            if content_matches:
                previous_index, previous_match = content_matches.pop(0)
                matched_previous_indices.add(previous_index)

        if previous_match is None and index < len(previous_todos) and index not in matched_previous_indices:
            previous_match = previous_todos[index]
            matched_previous_indices.add(index)

        if previous_match is not None:
            previous_content = previous_match.get("content")
            previous_status = previous_match.get("status")
            if previous_content == content and previous_status == todo.get("status"):
                continue

        actions.append(
            {
                "kind": _todo_action_kind(previous_match, todo),
                "content": content,
            }
        )

    for index, todo in enumerate(previous_todos):
        if index in matched_previous_indices:
            continue

        content = todo.get("content")
        if not isinstance(content, str) or not content:
            continue

        actions.append(
            {
                "kind": "todo_remove",
                "content": content,
            }
        )

    return actions


def _describe_tool_call(tool_call: dict[str, Any], todos: list[Todo]) -> list[dict[str, Any]]:
    name = _string_arg(tool_call.get("name")) or "unknown"
    args = tool_call.get("args") if isinstance(tool_call.get("args"), dict) else {}
    tool_call_id = _string_arg(tool_call.get("id"))

    if name == "write_todos":
        next_todos = _normalize_todos(args.get("todos"))
        actions = _build_todo_actions(todos, next_todos)
        if not actions:
            return [
                {
                    "kind": "tool",
                    "tool_name": name,
                    "tool_call_id": tool_call_id,
                }
            ]
        return [
            {
                **action,
                "tool_call_id": tool_call_id,
            }
            for action in actions
        ]

    if name == "task":
        return [
            {
                "kind": "subagent",
                "description": _string_arg(args.get("description")),
                "subagent_type": _string_arg(args.get("subagent_type")),
                "tool_call_id": tool_call_id,
            }
        ]

    if name in {"web_search", "image_search"}:
        query = _string_arg(args.get("query"))
        return [
            {
                "kind": "search",
                "tool_name": name,
                "query": query,
                "tool_call_id": tool_call_id,
            }
        ]

    if name == "present_files":
        return [
            {
                "kind": "present_files",
                "tool_call_id": tool_call_id,
            }
        ]

    if name == "ask_clarification":
        return [
            {
                "kind": "clarification",
                "tool_call_id": tool_call_id,
            }
        ]

    return [
        {
            "kind": "tool",
            "tool_name": name,
            "description": _string_arg(args.get("description")),
            "tool_call_id": tool_call_id,
        }
    ]


def _infer_step_kind(message: AIMessage, actions: list[dict[str, Any]]) -> str:
    if actions:
        first_kind = actions[0].get("kind")
        if len(actions) == 1 and first_kind in {"todo_start", "todo_complete", "todo_update", "todo_remove"}:
            return "todo_update"
        if len(actions) == 1 and first_kind == "subagent":
            return "subagent_dispatch"
        return "tool_batch"

    if message.content:
        return "final_answer"
    return "thinking"


def _build_attribution(message: AIMessage, todos: list[Todo]) -> dict[str, Any]:
    tool_calls = getattr(message, "tool_calls", None) or []
    actions: list[dict[str, Any]] = []
    current_todos = list(todos)

    for raw_tool_call in tool_calls:
        if not isinstance(raw_tool_call, dict):
            continue

        described_actions = _describe_tool_call(raw_tool_call, current_todos)
        actions.extend(described_actions)

        if raw_tool_call.get("name") == "write_todos":
            args = raw_tool_call.get("args") if isinstance(raw_tool_call.get("args"), dict) else {}
            current_todos = _normalize_todos(args.get("todos"))

    tool_call_ids: list[str] = []
    for tool_call in tool_calls:
        if not isinstance(tool_call, dict):
            continue

        tool_call_id = _string_arg(tool_call.get("id"))
        if tool_call_id is not None:
            tool_call_ids.append(tool_call_id)

    return {
        # Schema changes should remain additive where possible so older
        # frontends can ignore unknown fields and fall back safely.
        "version": 1,
        "kind": _infer_step_kind(message, actions),
        "shared_attribution": len(actions) > 1,
        "tool_call_ids": tool_call_ids,
        "actions": actions,
    }


class TokenUsageMiddleware(AgentMiddleware):
    """Logs token usage from model responses and annotates the AI step."""

    def _apply(self, state: AgentState) -> dict | None:
>>>>>>> 4ead2c6b197bcfa863b8381b3e30484060e41e0c
        messages = state.get("messages", [])
        if not messages:
            return None

        last = messages[-1]
        if not isinstance(last, AIMessage):
            return None

        usage = getattr(last, "usage_metadata", None)
<<<<<<< HEAD
        if not usage:
            return None

        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)
        total_tokens = usage.get("total_tokens", 0)

        logger.info(
            "LLM token usage: input=%s output=%s total=%s",
            input_tokens,
            output_tokens,
            total_tokens,
        )

        tenant_id = get_current_tenant_id()

        if not self._check_llm_rate_limit(tenant_id, total_tokens):
            logger.warning("LLM rate limit triggered for tenant %s", tenant_id)
            try:
                from deerflow.events.bus import get_event_bus
                from deerflow.events.models import Event, EventType

                get_event_bus().publish(Event(
                    type=EventType.TOKEN_THRESHOLD_EXCEEDED,
                    tenant_id=tenant_id,
                    thread_id=thread_id,
                    data={"total_tokens": total_tokens, "input_tokens": input_tokens, "output_tokens": output_tokens},
                ))
            except Exception:
                logger.debug("Event bus not available for token threshold event")

        if self.storage is not None and self.calculator is not None:
            try:
                model_name = getattr(last, "response_metadata", {}).get("model_name", "unknown")
                cost = self.calculator.calculate(model_name, input_tokens, output_tokens)

                thread_id = None
                if runtime is not None:
                    ctx = getattr(runtime, "context", None) or {}
                    if isinstance(ctx, dict):
                        thread_id = ctx.get("thread_id")
                        # Prefer tenant_id from runtime context (set by frontend
                        # via LangGraph Server), falling back to ContextVar which
                        # is only set for Gateway REST API requests.
                        tenant_id = ctx.get("tenant_id", tenant_id)

                from deerflow.cost.storage import UsageRecord

                record = UsageRecord(
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    tenant_id=tenant_id,
                    thread_id=thread_id,
                    model_name=model_name,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=total_tokens,
                    cost_usd=cost,
                )

                self._ensure_flush_task()
                self._buffer.append(record)
                if len(self._buffer) >= self._BUFFER_FLUSH_SIZE:
                    if self._flush_task is not None:
                        self._flush_task.cancel()
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(self._flush_buffer())
                    except RuntimeError:
                        pass
            except Exception:
                logger.exception("Failed to buffer token usage record")

        return None
=======
        if usage:
            logger.info(
                "LLM token usage: input=%s output=%s total=%s",
                usage.get("input_tokens", "?"),
                usage.get("output_tokens", "?"),
                usage.get("total_tokens", "?"),
            )

        todos = state.get("todos") or []
        attribution = _build_attribution(last, todos if isinstance(todos, list) else [])
        additional_kwargs = dict(getattr(last, "additional_kwargs", {}) or {})

        if additional_kwargs.get(TOKEN_USAGE_ATTRIBUTION_KEY) == attribution:
            return None

        additional_kwargs[TOKEN_USAGE_ATTRIBUTION_KEY] = attribution
        updated_msg = last.model_copy(update={"additional_kwargs": additional_kwargs})
        return {"messages": [updated_msg]}

    @override
    def after_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        return self._apply(state)

    @override
    async def aafter_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        return self._apply(state)
>>>>>>> 4ead2c6b197bcfa863b8381b3e30484060e41e0c
