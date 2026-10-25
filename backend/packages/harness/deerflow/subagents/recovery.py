"""Subagent session recovery and message transcript sanitization.

When a subagent execution crashes, times out, or is cancelled mid-turn, its
streamed message transcript may be left in an invalid state for LLM resumption:
1. Dangling tool calls: an AIMessage emitted tool_calls, but the process was
   interrupted before corresponding ToolMessages were recorded. Sending unclosed
   tool calls to Anthropic/OpenAI APIs causes immediate 400 Bad Request errors.
2. Empty/whitespace assistant messages: aborted streaming chunks with empty
   content blocks violate API contracts upon resumption.
3. Orphaned or malformed message sequences.

This module provides pure, deterministic message transcript sanitization and
recovery extraction to allow failed/interrupted subagents to resume cleanly
from their last known good state.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

if TYPE_CHECKING:
    from deerflow.subagents.executor import SubagentResult

logger = logging.getLogger(__name__)

INTERRUPTED_TOOL_RESULT_CONTENT = "[Execution interrupted: subagent was stopped or timed out before recording this tool result; completion status unknown — verify side effects before repeating non-idempotent actions]"


def dict_to_message(item: dict[str, Any] | BaseMessage) -> BaseMessage | None:
    """Convert a message dict or BaseMessage into a typed BaseMessage instance.

    Handles LangChain model_dump format as well as standard message dicts.
    Returns None if the message is invalid and unrecoverable (e.g. ToolMessage
    missing tool_call_id).
    """
    if isinstance(item, BaseMessage):
        if isinstance(item, ToolMessage) and not str(getattr(item, "tool_call_id", "") or "").strip():
            logger.debug("Dropping BaseMessage ToolMessage with empty tool_call_id")
            return None
        return item
    if not isinstance(item, dict):
        raise TypeError(f"Expected BaseMessage or dict, got {type(item).__name__}")

    raw_type = str(item.get("type", "")).lower()
    content = item.get("content", "")
    msg_id = item.get("id")
    additional_kwargs = dict(item.get("additional_kwargs") or {})

    if raw_type in {"ai", "assistant"}:
        raw_calls = list(item.get("tool_calls") or [])
        normalized_calls: list[dict[str, Any]] = []
        for call in raw_calls:
            if isinstance(call, dict):
                call_id = call.get("id")
                if not call_id or not str(call_id).strip():
                    call_id = f"synth_call_{uuid.uuid4().hex[:8]}"
                normalized_calls.append(
                    {
                        "name": str(call.get("name") or "unknown"),
                        "args": call.get("args") if isinstance(call.get("args"), dict) else {},
                        "id": str(call_id),
                    }
                )
            elif hasattr(call, "id"):
                normalized_calls.append(call)
        return AIMessage(
            content=content,
            tool_calls=normalized_calls,
            id=msg_id,
            additional_kwargs=additional_kwargs,
        )
    elif raw_type == "tool":
        tool_call_id = str(item.get("tool_call_id", "") or "").strip()
        if not tool_call_id:
            logger.debug("Dropping dict ToolMessage with missing or empty tool_call_id: %s", item)
            return None
        status = str(item.get("status", "success"))
        name = str(item.get("name", "")) if item.get("name") else None
        kwargs: dict[str, Any] = {
            "content": content,
            "tool_call_id": tool_call_id,
            "status": status,
            "id": msg_id,
            "additional_kwargs": additional_kwargs,
        }
        if name:
            kwargs["name"] = name
        return ToolMessage(**kwargs)
    elif raw_type in {"human", "user"}:
        return HumanMessage(
            content=content,
            id=msg_id,
            additional_kwargs=additional_kwargs,
        )
    elif raw_type == "system":
        return SystemMessage(
            content=content,
            id=msg_id,
            additional_kwargs=additional_kwargs,
        )
    else:
        # Fallback to HumanMessage if type is unknown or generic
        return HumanMessage(content=str(content), id=msg_id, additional_kwargs=additional_kwargs)


def filter_empty_assistant_messages(messages: Sequence[BaseMessage]) -> list[BaseMessage]:
    """Filter out assistant messages that have no content and no tool calls.

    Such messages occur when a subagent stream is aborted before any text or tool
    calls are generated, causing provider API rejections on replay.
    """
    result: list[BaseMessage] = []
    for msg in messages:
        if isinstance(msg, AIMessage):
            has_tool_calls = bool(getattr(msg, "tool_calls", None))
            content = getattr(msg, "content", "")
            is_empty_text = False
            if isinstance(content, str):
                is_empty_text = not content.strip()
            elif isinstance(content, list):
                is_empty_text = len(content) == 0

            if not has_tool_calls and is_empty_text:
                logger.debug("Filtered out empty assistant message %s", getattr(msg, "id", None))
                continue
        result.append(msg)
    return result


def filter_unresolved_tool_calls(
    messages: Sequence[BaseMessage],
    *,
    interrupted_content: str = INTERRUPTED_TOOL_RESULT_CONTENT,
) -> list[BaseMessage]:
    """Heal message histories containing unfulfilled tool calls.

    Scopes tool-call resolution per-turn to correctly handle repeated call IDs
    across long trajectories. Drops any id-less tool results. For any tool_call
    emitted in an AIMessage that lacks a corresponding ToolMessage before the next
    non-tool turn (or transcript end), synthesizes an interrupted ToolMessage
    with status="error" and honest completion-uncertainty guidance.
    """
    result: list[BaseMessage] = []
    pending_turn_calls: dict[str, str] = {}  # call_id -> tool_name for current turn

    def flush_pending() -> None:
        if not pending_turn_calls:
            return
        for call_id, name in list(pending_turn_calls.items()):
            synthetic = ToolMessage(
                content=interrupted_content,
                tool_call_id=call_id,
                status="error",
                name=name,
            )
            result.append(synthetic)
            logger.info("Synthesized turn-scoped interrupted ToolMessage for unresolved tool_call_id=%s (tool=%s)", call_id, name)
        pending_turn_calls.clear()

    for msg in messages:
        if isinstance(msg, ToolMessage):
            tool_call_id = str(getattr(msg, "tool_call_id", "") or "").strip()
            if not tool_call_id:
                logger.debug("Dropping unassociated ToolMessage without tool_call_id")
                continue
            # Answered in current turn
            pending_turn_calls.pop(tool_call_id, None)
            result.append(msg)
        else:
            # Entering a non-tool turn (AIMessage, HumanMessage, SystemMessage)
            flush_pending()
            result.append(msg)
            if isinstance(msg, AIMessage):
                tool_calls = getattr(msg, "tool_calls", None) or []
                for call in tool_calls:
                    call_id = str(call.get("id", "")) if isinstance(call, dict) else str(getattr(call, "id", ""))
                    if call_id:
                        call_name = str(call.get("name", "unknown") if isinstance(call, dict) else getattr(call, "name", "unknown"))
                        pending_turn_calls[call_id] = call_name

    flush_pending()
    return result


def sanitize_subagent_history(
    messages: Sequence[BaseMessage | dict[str, Any]],
    *,
    interrupted_content: str = INTERRUPTED_TOOL_RESULT_CONTENT,
) -> list[BaseMessage]:
    """Normalize and sanitize subagent message transcripts for safe resumption.

    Performs:
    1. Type normalization from dicts/model_dumps to BaseMessage instances (dropping invalid messages).
    2. Removal of empty/whitespace assistant messages.
    3. Healing of dangling/unresolved tool calls with turn-scoped tracking.
    """
    if not messages:
        return []

    # 1. Normalize
    normalized: list[BaseMessage] = []
    for m in messages:
        converted = dict_to_message(m)
        if converted is not None:
            normalized.append(converted)

    # 2. Filter empty assistant messages
    filtered_empty = filter_empty_assistant_messages(normalized)

    # 3. Heal unresolved tool calls with turn-scoped tracking
    healed = filter_unresolved_tool_calls(filtered_empty, interrupted_content=interrupted_content)

    return healed


def extract_resumable_messages(result: SubagentResult) -> list[BaseMessage]:
    """Extract and sanitize messages from a SubagentResult.

    Uses public accessor get_resumable_history() when available, preserving the
    original assignment prompt as the leading HumanMessage and avoiding private field leaks.
    """
    if hasattr(result, "get_resumable_history") and callable(result.get_resumable_history):
        raw_messages = result.get_resumable_history()
    else:
        raw_messages = []
        if getattr(result, "initial_task", None):
            raw_messages.append({"type": "human", "content": result.initial_task})
        if getattr(result, "ai_messages", None):
            raw_messages.extend(result.ai_messages)

    return sanitize_subagent_history(raw_messages)


def get_resumable_subagent_task(execution_id_or_task_id: str) -> SubagentResult | None:
    """Find a background subagent task by execution ID or external task ID from active or holding registries."""
    from deerflow.subagents.executor import (
        get_background_task_result,
        get_resumable_holding_task,
        list_background_tasks,
    )

    # 1. Try active background registry by execution ID
    res = get_background_task_result(execution_id_or_task_id)
    if res is not None:
        return res

    # 2. Try resumable holding registry
    held = get_resumable_holding_task(execution_id_or_task_id)
    if held is not None:
        return held

    # 3. Search active tasks by external task ID
    for task in list_background_tasks():
        if task.external_task_id == execution_id_or_task_id or task.task_id == execution_id_or_task_id:
            return task

    return None


def supersede_and_claim_resumable_task(execution_id_or_task_id: str) -> SubagentResult | None:
    """Locate, validate, and supersede an interrupted/failed task for resumption.

    Guards against concurrent duplicate resumes and cancels any lingering background execution.
    """
    from deerflow.subagents.executor import (
        get_background_task_result,
        get_resumable_holding_task,
        list_background_tasks,
        request_cancel_background_task,
    )

    target_task = None
    res = get_background_task_result(execution_id_or_task_id)
    if res is not None:
        target_task = res
    else:
        held = get_resumable_holding_task(execution_id_or_task_id)
        if held is not None:
            target_task = held
        else:
            for task in list_background_tasks():
                if task.external_task_id == execution_id_or_task_id or task.task_id == execution_id_or_task_id:
                    target_task = task
                    break

    if target_task is None:
        return None

    # Check if already superseded
    if getattr(target_task, "is_superseded", False):
        logger.warning("Attempted to resume task %s which is already superseded", execution_id_or_task_id)
        return None

    # Cancel any still-running zombie twin to prevent concurrent tool execution
    if not target_task.status.is_terminal:
        request_cancel_background_task(target_task.task_id)

    target_task.is_superseded = True
    return target_task
