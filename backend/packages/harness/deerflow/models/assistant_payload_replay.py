"""Helpers for replaying provider-specific assistant message fields.

Several provider adapters need to preserve fields that LangChain stores on the
original ``AIMessage`` but drops when serializing request payloads. This module
keeps the assistant-message matching logic shared while letting each provider
decide which fields to restore.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage

AssistantPayloadRestorer = Callable[[dict[str, Any], AIMessage], None]


def restore_assistant_payloads(
    payload_messages: Sequence[dict[str, Any]],
    original_messages: Sequence[BaseMessage],
    restore: AssistantPayloadRestorer,
) -> None:
    """Restore provider-specific fields onto serialized assistant payloads."""
    if len(payload_messages) == len(original_messages):
        for payload_msg, orig_msg in zip(payload_messages, original_messages):
            if payload_msg.get("role") == "assistant" and isinstance(orig_msg, AIMessage):
                restore(payload_msg, orig_msg)
        return

    ai_messages = [m for m in original_messages if isinstance(m, AIMessage)]
    assistant_payloads = [m for m in payload_messages if m.get("role") == "assistant"]
    used_ai_indexes: set[int] = set()

    for ordinal, payload_msg in enumerate(assistant_payloads):
        ai_msg = _match_ai_message(payload_msg, ai_messages, used_ai_indexes, ordinal)
        if ai_msg is not None:
            restore(payload_msg, ai_msg)


def restore_additional_kwargs_field(payload_msg: dict[str, Any], orig_msg: AIMessage, field_name: str) -> None:
    """Copy a provider-specific ``additional_kwargs`` field onto a payload message."""
    value = orig_msg.additional_kwargs.get(field_name)
    if value is not None:
        payload_msg[field_name] = value


def restore_reasoning_content(payload_msg: dict[str, Any], orig_msg: AIMessage) -> None:
    """Copy provider reasoning content onto a serialized assistant payload."""
    restore_additional_kwargs_field(payload_msg, orig_msg, "reasoning_content")


def _match_ai_message(
    payload_msg: dict[str, Any],
    ai_messages: Sequence[AIMessage],
    used_ai_indexes: set[int],
    fallback_ordinal: int,
) -> AIMessage | None:
    payload_key = _assistant_signature(payload_msg)
    if payload_key is not None:
        matches = [index for index, ai_msg in enumerate(ai_messages) if index not in used_ai_indexes and _ai_signature(ai_msg) == payload_key]
        if len(matches) == 1:
            used_ai_indexes.add(matches[0])
            return ai_messages[matches[0]]

    fallback_index = _next_unused_index_at_or_after(len(ai_messages), used_ai_indexes, fallback_ordinal)
    if fallback_index is not None:
        used_ai_indexes.add(fallback_index)
        return ai_messages[fallback_index]

    return None


def _next_unused_index_at_or_after(count: int, used_ai_indexes: set[int], start: int) -> int | None:
    """Return the next unused AI index at or after ``start``.

    Scanning forward from the payload's ordinal preserves the positional bias of
    the previous behaviour while still recovering when serialization drops or
    reorders messages so the exact ordinal index is already taken. It does not
    wrap to earlier indexes because those messages may be represented by payload
    entries that were already dropped.
    """
    if count == 0 or start >= count:
        return None
    for index in range(start, count):
        if index not in used_ai_indexes:
            return index
    return None


def _assistant_signature(payload_msg: dict[str, Any]) -> tuple[str, str] | None:
    return _signature(
        payload_msg.get("content"),
        _tool_call_ids(payload_msg.get("tool_calls") or []),
    )


def _ai_signature(message: AIMessage) -> tuple[str, str] | None:
    tool_calls = message.tool_calls or message.additional_kwargs.get("tool_calls") or []
    return _signature(message.content, _tool_call_ids(tool_calls))


def _signature(content: Any, tool_call_ids: tuple[str, ...]) -> tuple[str, str] | None:
    if content in (None, "") and not tool_call_ids:
        return None
    return (_stable_repr(content), "|".join(tool_call_ids))


def _stable_repr(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False)
    except TypeError:
        return repr(value)


def _tool_call_ids(tool_calls: Sequence[Any]) -> tuple[str, ...]:
    ids: list[str] = []
    for tool_call in tool_calls:
        if isinstance(tool_call, dict):
            call_id = tool_call.get("id")
            if isinstance(call_id, str) and call_id:
                ids.append(call_id)
    return tuple(ids)
