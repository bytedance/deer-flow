"""Server-created identity for reject-only recovery of legacy HITL pauses."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class InvalidApprovalIdentity:
    """Bind recovery to one otherwise well-formed null/duplicate-ID pause."""

    request_id: str
    digest: str


ApprovalIdentity = dict[str, str] | InvalidApprovalIdentity


def invalid_approval_identity(payload: Any) -> InvalidApprovalIdentity | None:
    """Return an identity only for the legacy ID defects, never arbitrary damage."""
    if not isinstance(payload, Mapping) or payload.get("kind") != "hitl_approval" or payload.get("version") != 1:
        return None
    request_id = payload.get("request_id")
    ids = payload.get("pending_tool_call_ids")
    actions = payload.get("actions")
    if not isinstance(request_id, str) or not request_id or not isinstance(ids, list) or not ids:
        return None
    if any(call_id is not None and not isinstance(call_id, str) for call_id in ids):
        return None
    if all(isinstance(call_id, str) for call_id in ids) and len(set(ids)) == len(ids):
        return None
    if not isinstance(actions, list) or len(actions) != len(ids):
        return None
    for call_id, action in zip(ids, actions, strict=True):
        if not isinstance(action, Mapping) or "tool_call_id" not in action or action["tool_call_id"] != call_id:
            return None
        if not isinstance(action.get("request_id"), str) or not action["request_id"]:
            return None
        if not isinstance(action.get("tool_name"), str) or not action["tool_name"]:
            return None
    try:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, RecursionError):
        return None
    # The legacy producer named this a byte limit but measured Python chars.
    # Preserve that admission boundary, including non-ASCII argument summaries.
    if len(str(payload)) > 32_000:
        return None
    return InvalidApprovalIdentity(request_id, hashlib.sha256(encoded).hexdigest())
