"""Shared helpers for turning conversations into memory update inputs."""

from __future__ import annotations

import re
from collections.abc import Mapping
from copy import copy
from typing import Any

_UPLOAD_BLOCK_RE = re.compile(r"<uploaded_files>[\s\S]*?</uploaded_files>\n*", re.IGNORECASE)
_CORRECTION_PATTERNS = (
    re.compile(r"\bthat(?:'s| is) (?:wrong|incorrect)\b", re.IGNORECASE),
    re.compile(r"\byou misunderstood\b", re.IGNORECASE),
    re.compile(r"\btry again\b", re.IGNORECASE),
    re.compile(r"\bredo\b", re.IGNORECASE),
    re.compile(r"不对"),
    re.compile(r"你理解错了"),
    re.compile(r"你理解有误"),
    re.compile(r"重试"),
    re.compile(r"重新来"),
    re.compile(r"换一种"),
    re.compile(r"改用"),
)
_REINFORCEMENT_PATTERNS = (
    re.compile(r"\byes[,.]?\s+(?:exactly|perfect|that(?:'s| is) (?:right|correct|it))\b", re.IGNORECASE),
    re.compile(r"\bperfect(?:[.!?]|$)", re.IGNORECASE),
    re.compile(r"\bexactly\s+(?:right|correct)\b", re.IGNORECASE),
    re.compile(r"\bthat(?:'s| is)\s+(?:exactly\s+)?(?:right|correct|what i (?:wanted|needed|meant))\b", re.IGNORECASE),
    re.compile(r"\bkeep\s+(?:doing\s+)?that\b", re.IGNORECASE),
    re.compile(r"\bjust\s+(?:like\s+)?(?:that|this)\b", re.IGNORECASE),
    re.compile(r"\bthis is (?:great|helpful)\b(?:[.!?]|$)", re.IGNORECASE),
    re.compile(r"\bthis is what i wanted\b(?:[.!?]|$)", re.IGNORECASE),
    re.compile(r"对[，,]?\s*就是这样(?:[。！？!?.]|$)"),
    re.compile(r"完全正确(?:[。！？!?.]|$)"),
    re.compile(r"(?:对[，,]?\s*)?就是这个意思(?:[。！？!?.]|$)"),
    re.compile(r"正是我想要的(?:[。！？!?.]|$)"),
    re.compile(r"继续保持(?:[。！？!?.]|$)"),
)


def extract_message_text(message: Any) -> str:
    """Extract plain text from message content for filtering and signal detection."""
    content = getattr(message, "content", "")
    if isinstance(content, list):
        text_parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                text_parts.append(part)
            elif isinstance(part, dict):
                text_val = part.get("text")
                if isinstance(text_val, str):
                    text_parts.append(text_val)
        return " ".join(text_parts)
    return str(content)


def _non_empty_str(value: object) -> str | None:
    """Return ``value`` if it is a non-empty (stripped) string, else None."""
    return value if isinstance(value, str) and value.strip() else None


def _is_human_clarification_response(additional_kwargs: Any) -> bool:
    """Return True iff ``additional_kwargs`` carries a well-formed human
    clarification response (a user-authored answer worth remembering).

    Host-agnostic structural mirror of deer-flow's ``read_human_input_response``
    (which the host injects via ``should_keep_hidden_message`` in production):
    a ``human_input_response`` mapping with version 1 + kind
    ``human_input_response``, non-empty source/request_id/value, and (for
    option responses) a non-empty option_id. Malformed/partial payloads return
    False so they are excluded like other hide_from_ui framework messages.
    Kept inline (no host import) so the bare ``filter_messages_for_memory``
    does the right thing standalone and in tests. NOTE: if the
    human_input_response format changes, keep this in sync with
    ``read_human_input_response`` (the production path) -- they must agree.
    """
    if not isinstance(additional_kwargs, Mapping):
        return False
    raw = additional_kwargs.get("human_input_response")
    if not isinstance(raw, Mapping):
        return False
    if raw.get("version") != 1 or raw.get("kind") != "human_input_response":
        return False
    if _non_empty_str(raw.get("source")) is None or _non_empty_str(raw.get("request_id")) is None or _non_empty_str(raw.get("value")) is None:
        return False
    response_kind = raw.get("response_kind")
    if response_kind == "text":
        return True
    if response_kind == "option":
        return _non_empty_str(raw.get("option_id")) is not None
    return False


def filter_messages_for_memory(messages: list[Any], *, should_keep_hidden_message: Any = None) -> list[Any]:
    """Keep only user inputs and final assistant responses for memory updates.

    ``hide_from_ui`` framework messages are skipped, but user-authored
    clarification answers (a well-formed ``human_input_response``) are kept by
    default via a host-agnostic structural check (mirrors deer-flow's
    ``read_human_input_response``). Pass a ``should_keep_hidden_message(
    additional_kwargs) -> bool`` hook to override the keep decision; the host
    injects one delegating to the authoritative ``read_human_input_response``
    in production.
    """
    filtered = []
    skip_next_ai = False
    for msg in messages:
        msg_type = getattr(msg, "type", None)

        if msg_type == "human":
            # Middleware-injected hidden messages (e.g. TodoMiddleware.todo_reminder,
            # ViewImageMiddleware, p0 DynamicContextMiddleware.__memory) carry
            # hide_from_ui and must never reach the memory-updating LLM — otherwise
            # framework-internal text pollutes long-term memory (and the p0 __memory
            # payload could trigger a self-amplification loop).
            additional_kwargs = getattr(msg, "additional_kwargs", {}) or {}
            if additional_kwargs.get("hide_from_ui"):
                # Framework-injected hidden messages (TodoMiddleware reminders,
                # ViewImage payloads, p0 __memory self-amplification guard) are
                # excluded. User-authored clarification answers (a well-formed
                # human_input_response) ARE real content worth remembering, so
                # they are kept by default via a host-agnostic structural check.
                # A host ``should_keep_hidden_message`` hook, when supplied,
                # overrides this (production DeerMem injects one delegating to
                # the authoritative read_human_input_response).
                if should_keep_hidden_message is not None:
                    keep = should_keep_hidden_message(additional_kwargs)
                else:
                    keep = _is_human_clarification_response(additional_kwargs)
                if not keep:
                    continue
            content_str = extract_message_text(msg)
            if "<uploaded_files>" in content_str:
                stripped = _UPLOAD_BLOCK_RE.sub("", content_str).strip()
                if not stripped:
                    skip_next_ai = True
                    continue
                clean_msg = copy(msg)
                clean_msg.content = stripped
                filtered.append(clean_msg)
                skip_next_ai = False
            else:
                filtered.append(msg)
                skip_next_ai = False
        elif msg_type == "ai":
            tool_calls = getattr(msg, "tool_calls", None)
            if not tool_calls:
                if skip_next_ai:
                    skip_next_ai = False
                    continue
                filtered.append(msg)

    return filtered


def detect_correction(messages: list[Any]) -> bool:
    """Detect explicit user corrections in recent conversation turns."""
    recent_user_msgs = [msg for msg in messages[-6:] if getattr(msg, "type", None) == "human"]

    for msg in recent_user_msgs:
        content = extract_message_text(msg).strip()
        if content and any(pattern.search(content) for pattern in _CORRECTION_PATTERNS):
            return True

    return False


def detect_reinforcement(messages: list[Any]) -> bool:
    """Detect explicit positive reinforcement signals in recent conversation turns."""
    recent_user_msgs = [msg for msg in messages[-6:] if getattr(msg, "type", None) == "human"]

    for msg in recent_user_msgs:
        content = extract_message_text(msg).strip()
        if content and any(pattern.search(content) for pattern in _REINFORCEMENT_PATTERNS):
            return True

    return False
