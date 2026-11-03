"""Successful-operation observations for Goal's no-progress counter.

These records measure newly observed operations, not correctness or usefulness.
Only hashes are retained, in the current Goal's existing evaluation record.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from langchain_core.messages import HumanMessage, ToolMessage

from deerflow.agents.middlewares.message_utils import is_genuine_user_message
from deerflow.agents.middlewares.tool_receipt import TOOL_RECEIPT_KEY, is_valid_receipt, make_tool_receipt
from deerflow.agents.middlewares.tool_result_meta import TOOL_META_KEY, normalize_tool_message
from deerflow.agents.middlewares.tool_transform_meta import TOOL_TRANSFORMS_KEY

# Native sandbox tools use this argument only to explain the call in the UI.
# Other tools may persist or send a description as their actual payload.
_UI_NARRATION_TOOLS = frozenset({"bash", "read_file", "write_file", "str_replace", "ls", "glob", "grep"})


def _field(message: Any, name: str, default: Any = None) -> Any:
    return message.get(name, default) if isinstance(message, dict) else getattr(message, name, default)


def _kind(message: Any) -> str | None:
    kind = _field(message, "type") or _field(message, "role")
    return {"user": "human", "assistant": "ai"}.get(kind, kind)


def _starts_goal_turn(message: Any) -> bool:
    if _kind(message) != "human":
        return False
    kwargs = _field(message, "additional_kwargs", {}) or {}
    kwargs = dict(kwargs) if isinstance(kwargs, Mapping) else {}
    if kwargs.get("deerflow_goal_continuation") is True:
        return True
    # Share the established card-answer/summary/framework distinction. Only
    # boundary metadata is needed to adapt serialized checkpoint messages.
    candidate = message if isinstance(message, HumanMessage) else HumanMessage(content="", name=_field(message, "name"), additional_kwargs=kwargs)
    return is_genuine_user_message(candidate)


def previous_goal_operations(goal: Mapping[str, Any]) -> dict[str, Any] | None:
    previous = goal.get("last_evaluation")
    record = previous.get("operation_progress") if isinstance(previous, Mapping) else None
    if not isinstance(record, dict) or record.get("version") != 1:
        return None
    keys = record.get("seen_keys")
    if not isinstance(keys, list) or any(not isinstance(key, str) or len(key) != 64 or any(char not in "0123456789abcdef" for char in key) for key in keys):
        return None
    return record


def _successful_operation_key(call: dict[str, Any], message: Any) -> str | None:
    name = call.get("name")
    args = call.get("args")
    if not isinstance(name, str) or not name or not isinstance(args, dict):
        return None
    if _field(message, "status") == "error":
        return None
    kwargs = _field(message, "additional_kwargs", {}) or {}
    if not isinstance(kwargs, dict):
        return None
    receipt = kwargs.get(TOOL_RECEIPT_KEY)
    if is_valid_receipt(receipt) and receipt["tool_call_id"] == call["id"] and receipt["tool_name"] == name and receipt["status"] != "success":
        return None
    # Reuse the established classification for old messages without structured
    # status. Work on a copy: observing a checkpoint must never rewrite it.
    status_message = normalize_tool_message(ToolMessage(content=_field(message, "content", ""), tool_call_id=str(call["id"]), name=name, additional_kwargs=dict(kwargs)))
    meta = status_message.additional_kwargs.get(TOOL_META_KEY)
    if not isinstance(meta, Mapping) or meta.get("status") != "success":
        return None
    # Use the native canonical format on the fallback path too, so enabling
    # receipts does not turn an old operation into a new one. The generated
    # timestamp is discarded; only the existing fingerprint fields are retained.
    canonical = make_tool_receipt(call, status_message)
    matching = (
        is_valid_receipt(receipt)
        and receipt["tool_call_id"] == call["id"]
        and receipt["tool_name"] == name
        and receipt["args_sha256"] == canonical["args_sha256"]
        and receipt["output_bytes"] >= 0
        and len(receipt["output_sha256"]) == len(canonical["output_sha256"])
        and all(char in "0123456789abcdef" for char in receipt["output_sha256"])
    )
    if matching:
        fingerprint = receipt
    elif kwargs.get(TOOL_TRANSFORMS_KEY):
        # Externalized previews contain per-call paths. Without a matching raw
        # receipt their changing wrappers cannot establish a new result; do not
        # read saved files or grant progress from a partial transformed view.
        return None
    else:
        fingerprint = canonical
    args_key = fingerprint["args_sha256"]
    if name in _UI_NARRATION_TOOLS and "description" in args:
        # Validate the receipt against raw arguments above. Only repetition
        # identity excludes narration; native receipts remain unchanged.
        operation_args = {key: value for key, value in args.items() if key != "description"}
        args_key = hashlib.sha256(json.dumps(operation_args, sort_keys=True, default=str).encode("utf-8")).hexdigest()[: len(canonical["args_sha256"])]
    body = json.dumps([name, args_key, fingerprint["output_sha256"], fingerprint["output_bytes"]])
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def observe_goal_operations(goal: Mapping[str, Any], messages: list[Any]) -> dict[str, Any]:
    """Observe paired successful results since this turn's initiating input.

    Genuine user/card replies and explicit hidden Goal continuations start turns;
    framework reminders do not. Already evaluated operations survive compaction
    and restart in ``last_evaluation``. There is no global cache or arbitrary
    operation cutoff; retained storage follows actual work.
    """
    previous = previous_goal_operations(goal)
    seen = set(previous["seen_keys"]) if previous is not None else set()
    start = 0
    for index in range(len(messages) - 1, -1, -1):
        if _starts_goal_turn(messages[index]):
            start = index + 1
            break
    calls: dict[str, dict[str, Any]] = {}
    observed: set[str] = set()
    has_tool_activity = False
    for message in messages[start:]:
        kind = _kind(message)
        if kind == "ai":
            for call in _field(message, "tool_calls", []) or []:
                if isinstance(call, dict) and isinstance(call.get("id"), str) and call["id"]:
                    calls[call["id"]] = call
                    has_tool_activity = True
        elif kind == "tool":
            has_tool_activity = True
            call = calls.pop(_field(message, "tool_call_id"), None)
            if call is not None:
                key = _successful_operation_key(call, message)
                if key is not None:
                    observed.add(key)
    return {
        "version": 1,
        "seen_keys": sorted(seen | observed),
        "has_tool_activity": has_tool_activity,
        "new_keys": len(observed - seen),
    }
