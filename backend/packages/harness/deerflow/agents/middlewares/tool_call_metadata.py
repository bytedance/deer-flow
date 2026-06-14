"""Helpers for keeping AIMessage tool-call metadata consistent."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from langchain_core.messages import AIMessage


def _valid_tool_call_id(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _raw_tool_call_id(raw_tool_call: Any) -> str | None:
    if not isinstance(raw_tool_call, dict):
        return None

    return _valid_tool_call_id(raw_tool_call.get("id"))


def _stable_missing_tool_call_id(message: AIMessage, tool_call: dict[str, Any], index: int) -> str:
    payload = {
        "message_id": getattr(message, "id", None) or "",
        "index": index,
        "name": tool_call.get("name"),
        "args": tool_call.get("args"),
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":"))
    digest = hashlib.sha1(encoded.encode("utf-8")).hexdigest()[:16]
    return f"call_{digest}"


def _sync_missing_raw_tool_call_ids(
    additional_kwargs: dict[str, Any],
    tool_calls: list[dict[str, Any]],
) -> tuple[dict[str, Any], bool]:
    raw_tool_calls = additional_kwargs.get("tool_calls")
    if not isinstance(raw_tool_calls, list):
        return additional_kwargs, False

    changed = False
    synced_raw_tool_calls: list[Any] = []
    for index, raw_tool_call in enumerate(raw_tool_calls):
        if not isinstance(raw_tool_call, dict):
            synced_raw_tool_calls.append(raw_tool_call)
            continue

        raw_id = _raw_tool_call_id(raw_tool_call)
        replacement_id = _valid_tool_call_id(tool_calls[index].get("id")) if index < len(tool_calls) else None
        if raw_id or not replacement_id:
            synced_raw_tool_calls.append(raw_tool_call)
            continue

        synced_raw_tool_call = dict(raw_tool_call)
        synced_raw_tool_call["id"] = replacement_id
        synced_raw_tool_calls.append(synced_raw_tool_call)
        changed = True

    if not changed:
        return additional_kwargs, False

    updated = dict(additional_kwargs)
    updated["tool_calls"] = synced_raw_tool_calls
    return updated, True


def normalize_ai_message_tool_call_ids(message: AIMessage) -> AIMessage:
    """Ensure AIMessage tool calls have string IDs and sync raw provider metadata."""
    tool_calls = list(getattr(message, "tool_calls", None) or [])
    additional_kwargs = dict(getattr(message, "additional_kwargs", {}) or {})
    if not tool_calls:
        synced_kwargs, raw_changed = _sync_missing_raw_tool_call_ids(additional_kwargs, [])
        if raw_changed:
            return message.model_copy(update={"additional_kwargs": synced_kwargs})
        return message

    raw_tool_calls = additional_kwargs.get("tool_calls")
    normalized_tool_calls: list[dict[str, Any]] = []
    changed = False
    for index, tool_call in enumerate(tool_calls):
        normalized_tool_call = dict(tool_call)
        existing_id = _valid_tool_call_id(normalized_tool_call.get("id"))

        raw_id = None
        if isinstance(raw_tool_calls, list) and index < len(raw_tool_calls):
            raw_id = _raw_tool_call_id(raw_tool_calls[index])

        tool_call_id = existing_id or raw_id or _stable_missing_tool_call_id(message, normalized_tool_call, index)
        if tool_call_id != normalized_tool_call.get("id"):
            normalized_tool_call["id"] = tool_call_id
            changed = True

        normalized_tool_calls.append(normalized_tool_call)

    synced_kwargs, raw_changed = _sync_missing_raw_tool_call_ids(additional_kwargs, normalized_tool_calls)
    if not changed and not raw_changed:
        return message

    return message.model_copy(
        update={
            "tool_calls": normalized_tool_calls,
            "additional_kwargs": synced_kwargs,
        }
    )


def clone_ai_message_with_tool_calls(
    message: AIMessage,
    tool_calls: list[dict[str, Any]],
    *,
    content: Any | None = None,
) -> AIMessage:
    """Clone an AIMessage while keeping raw provider tool-call metadata in sync."""
    kept_ids = {tc["id"] for tc in tool_calls if isinstance(tc.get("id"), str) and tc["id"]}

    update: dict[str, Any] = {"tool_calls": tool_calls}
    if content is not None:
        update["content"] = content

    additional_kwargs = dict(getattr(message, "additional_kwargs", {}) or {})
    raw_tool_calls = additional_kwargs.get("tool_calls")
    if isinstance(raw_tool_calls, list):
        synced_raw_tool_calls = [raw_tc for raw_tc in raw_tool_calls if _raw_tool_call_id(raw_tc) in kept_ids]
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

    return message.model_copy(update=update)
