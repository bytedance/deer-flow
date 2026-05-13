"""Middleware for logging token usage and annotating step attribution."""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.todo import Todo
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.runtime import Runtime

logger = logging.getLogger(__name__)

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


def _has_tool_call(message: AIMessage, tool_call_id: str) -> bool:
    """Return True if the AIMessage contains a tool_call with the given id."""
    for tc in message.tool_calls or []:
        if isinstance(tc, dict):
            if tc.get("id") == tool_call_id:
                return True
        elif hasattr(tc, "id") and tc.id == tool_call_id:
            return True
    return False


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
        messages = state.get("messages", [])
        if not messages:
            return None

        # Annotate subagent token usage onto the AIMessage that dispatched it.
        # When a task tool completes, its usage is cached by tool_call_id.  Detect
        # the ToolMessage → search backward for the corresponding AIMessage → merge.
        # Walk backward through consecutive ToolMessages before the new AIMessage
        # so that multiple concurrent task tool calls all get their subagent tokens
        # written back to the same dispatch message (merging into one update).
        state_updates: dict[int, AIMessage] = {}
        if len(messages) >= 2:
            from deerflow.tools.builtins.task_tool import pop_cached_subagent_usage

            idx = len(messages) - 2
            while idx >= 0:
                tool_msg = messages[idx]
                if not isinstance(tool_msg, ToolMessage) or not tool_msg.tool_call_id:
                    break

                subagent_usage = pop_cached_subagent_usage(tool_msg.tool_call_id)
                if subagent_usage:
                    # Search backward from the ToolMessage to find the AIMessage
                    # that dispatched it.  A single model response can dispatch
                    # multiple task tool calls, so we can't assume a fixed offset.
                    dispatch_idx = idx - 1
                    while dispatch_idx >= 0:
                        candidate = messages[dispatch_idx]
                        if isinstance(candidate, AIMessage) and _has_tool_call(candidate, tool_msg.tool_call_id):
                            # Accumulate into an existing update for the same
                            # AIMessage (multiple task calls in one response),
                            # or merge fresh from the original message.
                            existing_update = state_updates.get(dispatch_idx)
                            prev = existing_update.usage_metadata if existing_update else (getattr(candidate, "usage_metadata", None) or {})
                            merged = {
                                **prev,
                                "input_tokens": prev.get("input_tokens", 0) + subagent_usage["input_tokens"],
                                "output_tokens": prev.get("output_tokens", 0) + subagent_usage["output_tokens"],
                                "total_tokens": prev.get("total_tokens", 0) + subagent_usage["total_tokens"],
                            }
                            state_updates[dispatch_idx] = candidate.model_copy(update={"usage_metadata": merged})
                            break
                        dispatch_idx -= 1
                idx -= 1

        last = messages[-1]
        if not isinstance(last, AIMessage):
            if state_updates:
                return {"messages": [state_updates[idx] for idx in sorted(state_updates)]}
            return None

        usage = getattr(last, "usage_metadata", None)
        if usage:
            input_token_details = usage.get("input_token_details") or {}
            output_token_details = usage.get("output_token_details") or {}
            detail_parts = []
            if input_token_details:
                detail_parts.append(f"input_token_details={input_token_details}")
            if output_token_details:
                detail_parts.append(f"output_token_details={output_token_details}")
            detail_suffix = f" {' '.join(detail_parts)}" if detail_parts else ""
            logger.info(
                "LLM token usage: input=%s output=%s total=%s%s",
                usage.get("input_tokens", "?"),
                usage.get("output_tokens", "?"),
                usage.get("total_tokens", "?"),
                detail_suffix,
            )

        todos = state.get("todos") or []
        attribution = _build_attribution(last, todos if isinstance(todos, list) else [])
        additional_kwargs = dict(getattr(last, "additional_kwargs", {}) or {})

        if additional_kwargs.get(TOKEN_USAGE_ATTRIBUTION_KEY) == attribution:
            return {"messages": [state_updates[idx] for idx in sorted(state_updates)]} if state_updates else None

        additional_kwargs[TOKEN_USAGE_ATTRIBUTION_KEY] = attribution
        updated_msg = last.model_copy(update={"additional_kwargs": additional_kwargs})
        state_updates[len(messages) - 1] = updated_msg
        return {"messages": [state_updates[idx] for idx in sorted(state_updates)]}

    @override
    def after_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        return self._apply(state)

    @override
    async def aafter_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        return self._apply(state)
