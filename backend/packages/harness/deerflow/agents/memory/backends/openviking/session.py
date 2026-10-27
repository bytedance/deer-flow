"""Stable OpenViking session identity and transcript-cursor helpers."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from .config import GENERATED_PEER_PREFIX, is_safe_peer_id

_SESSION_NAMESPACE = "deerflow-openviking-adapter-v1"
_DEFAULT_AGENT_SCOPE = "__default__"
_CURSOR_SCHEMA_VERSION = 1


def _canonical_peer_id(
    agent_name: str | None,
    default_peer_id: str,
) -> str:
    """Map DeerFlow's case-insensitive agent names to disjoint peer IDs."""

    if agent_name is None:
        return default_peer_id

    value = str(agent_name).strip().lower()
    if not value or value == _DEFAULT_AGENT_SCOPE:
        raise ValueError(f"Invalid OpenViking peer scope: {agent_name!r}")
    if is_safe_peer_id(value) and value != default_peer_id and not value.startswith(GENERATED_PEER_PREFIX):
        return value

    # The generated namespace is reserved, so compatible names, the default
    # peer, and hashed fallbacks cannot alias one another. The 128-bit digest
    # also avoids collisions caused by sanitizing or truncating agent names.
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]
    return f"{GENERATED_PEER_PREFIX}{digest}"


def _session_id(
    owner_user_id: str,
    peer_id: str,
    thread_id: str,
) -> str:
    """Derive one stable OpenViking session for one DeerFlow thread."""

    digest = hashlib.sha256(f"{_SESSION_NAMESPACE}\0{owner_user_id}\0{peer_id}\0{thread_id}".encode()).hexdigest()
    return f"df_{digest[:48]}"


def _memory_target_uris(peer_id: str) -> list[str]:
    """Return the self and current-peer memory roots for a request."""

    return [
        "viking://user/memories",
        f"viking://user/peers/{peer_id}/memories",
    ]


def _captureable_messages(
    messages: list[Any],
    should_keep_hidden_message: Any,
) -> list[Any]:
    """Drop DeerFlow-only injected context before handing messages to OpenViking."""

    selected: list[Any] = []
    for message in messages:
        additional_kwargs = _message_value(
            message,
            "additional_kwargs",
            {},
        )
        if not isinstance(additional_kwargs, dict):
            additional_kwargs = {}
        if additional_kwargs.get("hide_from_ui") and not (should_keep_hidden_message and should_keep_hidden_message(additional_kwargs)):
            continue
        selected.append(message)
    return selected


def _message_signature(message: Any) -> str:
    """Hash stable message semantics without retaining transcript content."""

    additional_kwargs = _message_value(message, "additional_kwargs", {})
    if not isinstance(additional_kwargs, Mapping):
        additional_kwargs = {}
    tool_calls = _message_value(message, "tool_calls", None)
    if not tool_calls:
        tool_calls = additional_kwargs.get("tool_calls") or []

    value = {
        "id": _message_value(message, "id", None),
        "role": _message_value(message, "type", None) or _message_value(message, "role", None),
        "content": _message_value(message, "content", ""),
        "tool_calls": tool_calls,
        "tool_call_id": _message_value(message, "tool_call_id", None) or _message_value(message, "tool_id", None),
        "tool_name": _message_value(message, "name", None) or _message_value(message, "tool_name", None),
        "tool_status": _message_value(message, "status", None) or _message_value(message, "tool_status", None),
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
    """Return the already submitted prefix, including after compaction."""

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
    newly_submitted: list[str],
    *,
    max_seen: int,
    commit_pending: bool,
) -> dict[str, Any]:
    """Advance confirmed capture progress without persisting message content."""

    recent = [
        *_string_list(previous.get("submitted_signatures")),
        *newly_submitted,
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


def _message_value(message: Any, key: str, default: Any) -> Any:
    if isinstance(message, Mapping):
        return message.get(key, default)
    return getattr(message, key, default)
