"""Helpers for keeping AIMessage tool-call metadata consistent."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage


def _raw_tool_call_id(raw_tool_call: Any) -> str | None:
    if not isinstance(raw_tool_call, dict):
        return None

    raw_id = raw_tool_call.get("id")
    return raw_id if isinstance(raw_id, str) and raw_id else None


def _clone_raw_tool_call_with_updated_args(raw_tool_call: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    """Clone a raw provider tool-call dict while updating any serialized args payloads."""
    cloned = dict(raw_tool_call)

    if "args" in cloned:
        cloned["args"] = json.dumps(args, ensure_ascii=False) if isinstance(cloned["args"], str) else dict(args)

    function = cloned.get("function")
    if isinstance(function, dict):
        cloned_function = dict(function)
        if "arguments" in cloned_function:
            cloned_function["arguments"] = json.dumps(args, ensure_ascii=False) if isinstance(cloned_function["arguments"], str) else dict(args)
        if "args" in cloned_function:
            cloned_function["args"] = json.dumps(args, ensure_ascii=False) if isinstance(cloned_function["args"], str) else dict(args)
        cloned["function"] = cloned_function

    return cloned


def _build_message_update(
    message: AIMessage,
    tool_calls: list[dict[str, Any]],
    *,
    content: Any | None = None,
    sync_args: bool = False,
) -> dict[str, Any]:
    """Build a model_copy update dict while keeping raw provider tool metadata in sync."""
    kept_ids = {tc["id"] for tc in tool_calls if isinstance(tc.get("id"), str) and tc["id"]}
    tool_calls_by_id = {tc["id"]: tc for tc in tool_calls if isinstance(tc.get("id"), str) and tc["id"] and isinstance(tc.get("args"), dict)}

    update: dict[str, Any] = {"tool_calls": tool_calls}
    if content is not None:
        update["content"] = content

    additional_kwargs = dict(getattr(message, "additional_kwargs", {}) or {})
    raw_tool_calls = additional_kwargs.get("tool_calls")
    if isinstance(raw_tool_calls, list):
        synced_raw_tool_calls = []
        for raw_tc in raw_tool_calls:
            raw_id = _raw_tool_call_id(raw_tc)
            if raw_id not in kept_ids:
                continue
            if sync_args and isinstance(raw_tc, dict) and raw_id in tool_calls_by_id:
                synced_raw_tool_calls.append(_clone_raw_tool_call_with_updated_args(raw_tc, tool_calls_by_id[raw_id]["args"]))
            else:
                synced_raw_tool_calls.append(raw_tc)
        if synced_raw_tool_calls:
            additional_kwargs["tool_calls"] = synced_raw_tool_calls
        else:
            additional_kwargs.pop("tool_calls", None)

    if not tool_calls:
        additional_kwargs.pop("function_call", None)

    update["additional_kwargs"] = additional_kwargs

    response_metadata = dict(getattr(message, "response_metadata", {}) or {})
    if not tool_calls and response_metadata.get("finish_reason") == "tool_calls":
        response_metadata["finish_reason"] = "stop"
    update["response_metadata"] = response_metadata
    return update


def clone_ai_message_with_tool_calls(
    message: AIMessage,
    tool_calls: list[dict[str, Any]],
    *,
    content: Any | None = None,
) -> AIMessage:
    """Clone an AIMessage while keeping raw provider tool-call metadata in sync."""
    return message.model_copy(update=_build_message_update(message, tool_calls, content=content))


def clone_ai_message_with_updated_tool_calls(
    message: AIMessage,
    tool_calls: list[dict[str, Any]],
    *,
    content: Any | None = None,
) -> AIMessage:
    """Clone an AIMessage while preserving raw tool-call metadata and updating args."""
    return message.model_copy(update=_build_message_update(message, tool_calls, content=content, sync_args=True))
