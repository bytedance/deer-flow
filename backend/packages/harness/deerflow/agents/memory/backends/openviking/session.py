"""Stable OpenViking session identity and transcript-cursor helpers."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from math import isfinite
from typing import Any

from deerflow.config.agents_config import AGENT_NAME_PATTERN
from deerflow.utils.messages import message_to_text

from .settings import GENERATED_PEER_PREFIX, is_safe_peer_id

# This string is part of the stable session-ID mapping. Keep it even though the
# implementation module no longer uses "official" in its public naming.
_SESSION_NAMESPACE = "deerflow-openviking-official-v1"
_DEFAULT_AGENT_SCOPE = "__default__"
_CURSOR_SCHEMA_VERSION = 2


def _canonical_peer_id(agent_name: str | None, default_peer_id: str) -> str:
    if agent_name is None:
        return default_peer_id

    raw_name = str(agent_name).strip()
    if not AGENT_NAME_PATTERN.fullmatch(raw_name):
        raise ValueError(f"Invalid DeerFlow agent name: {raw_name!r}")

    value = raw_name.lower()
    if value == _DEFAULT_AGENT_SCOPE:
        raise ValueError(f"Invalid OpenViking peer scope: {value!r}")
    if is_safe_peer_id(value) and value != default_peer_id and not value.startswith(GENERATED_PEER_PREFIX):
        # Preserve every already-compatible name. The configured default and
        # generated namespace are reserved to keep all mapping branches disjoint.
        return value

    # DeerFlow permits leading hyphens and names longer than OpenViking's
    # 64-character peer limit. A digest prevents truncation/sanitization aliases.
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]
    return f"{GENERATED_PEER_PREFIX}{digest}"


def _session_id(owner_user_id: str, peer_id: str, thread_id: str) -> str:
    digest = hashlib.sha256(f"{_SESSION_NAMESPACE}\0{owner_user_id}\0{peer_id}\0{thread_id}".encode()).hexdigest()
    return f"df_{digest[:48]}"


def _memory_target_uris(peer_id: str) -> list[str]:
    """Return the self + current-peer memory roots for one agent request."""

    return [
        "viking://user/memories",
        f"viking://user/peers/{peer_id}/memories",
    ]


def _captureable_messages(
    messages: list[Any],
    should_keep_hidden_message: Any,
) -> list[Any]:
    selected: list[Any] = []
    for message in messages:
        additional_kwargs = message.get("additional_kwargs", {}) if isinstance(message, dict) else getattr(message, "additional_kwargs", {})
        if not isinstance(additional_kwargs, dict):
            additional_kwargs = {}
        if additional_kwargs.get("hide_from_ui") and not (should_keep_hidden_message and should_keep_hidden_message(additional_kwargs)):
            continue
        selected.append(message)
    return selected


def _message_signature(message: Any) -> str:
    """Hash only stable transcript semantics, excluding volatile metadata."""

    if isinstance(message, Mapping):
        message_id = message.get("id")
        role = message.get("role") or message.get("type")
        tool_calls = message.get("tool_calls") or []
        tool_result = {
            "tool_call_id": message.get("tool_call_id") or message.get("tool_id"),
            "name": message.get("name") or message.get("tool_name"),
            "output": message.get("tool_output") or message.get("output"),
            "status": message.get("status") or message.get("tool_status"),
        }
    else:
        message_id = getattr(message, "id", None)
        role = getattr(message, "type", None)
        tool_calls = getattr(message, "tool_calls", None) or []
        if not tool_calls:
            additional_kwargs = getattr(message, "additional_kwargs", {}) or {}
            if isinstance(additional_kwargs, Mapping):
                tool_calls = additional_kwargs.get("tool_calls") or []
        tool_result = {
            "tool_call_id": getattr(message, "tool_call_id", None),
            "name": getattr(message, "name", None),
            "status": getattr(message, "status", None),
        }
    value = {
        "id": str(message_id) if message_id else None,
        "role": role,
        "content": message_to_text(message),
        "tool_calls": tool_calls,
        "tool_result": tool_result,
    }
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _matching_prefix_count(
    state: dict[str, Any],
    signatures: list[str],
) -> int | None:
    count = state.get("submitted_prefix_count")
    digest = state.get("submitted_prefix_digest")
    if isinstance(count, int) and 0 <= count <= len(signatures) and isinstance(digest, str):
        if _sequence_digest(signatures[:count]) == digest:
            return count
        return None
    submitted = _string_list(state.get("submitted_signatures"))
    if submitted and len(submitted) <= len(signatures):
        width = len(submitted)
        for start in range(len(signatures) - width, -1, -1):
            if signatures[start : start + width] == submitted:
                return start + width
    return 0 if not state else None


def _advanced_cursor(
    previous: dict[str, Any],
    prefix_signatures: list[str] | None,
    newly_submitted: Any,
    *,
    max_seen: int,
    commit_pending: bool,
) -> dict[str, Any]:
    recent = [
        *_string_list(previous.get("submitted_signatures")),
        *list(newly_submitted),
    ][-max_seen:]
    state: dict[str, Any] = {
        "schema_version": _CURSOR_SCHEMA_VERSION,
        "submitted_signatures": recent,
        "commit_pending": commit_pending,
    }
    if prefix_signatures is not None:
        state["submitted_prefix_count"] = len(prefix_signatures)
        state["submitted_prefix_digest"] = _sequence_digest(prefix_signatures)
    else:
        state["submitted_prefix_count"] = previous.get("submitted_prefix_count")
        state["submitted_prefix_digest"] = previous.get("submitted_prefix_digest")
    return state


def _cursor_lifecycle(
    state: dict[str, Any],
    *,
    peer_id: str,
    idle_due_at: float | None,
    commit_pending: bool,
) -> dict[str, Any]:
    return {
        **state,
        "schema_version": _CURSOR_SCHEMA_VERSION,
        "peer_id": peer_id,
        "idle_due_at": idle_due_at,
        "commit_pending": commit_pending,
    }


def _timestamp(value: Any) -> float | None:
    if isinstance(value, (int, float)) and isfinite(value) and value > 0:
        return float(value)
    return None


def _sequence_digest(signatures: list[str]) -> str:
    digest = hashlib.sha256()
    for signature in signatures:
        encoded = signature.encode()
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]
