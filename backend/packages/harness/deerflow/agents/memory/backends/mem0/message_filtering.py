"""Message filtering for the mem0 write path -- self-contained mirror of
DeerMem's ``filter_messages_for_memory`` rules (the portability rule forbids
importing across backend folders, so the logic is duplicated, not shared).

Keeps: visible user inputs, well-formed human clarification answers, and final
assistant responses. Drops: framework-internal ``hide_from_ui`` messages,
tool-call AI messages, tool outputs, empty/upload-only turns.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from copy import copy
from typing import Any

_UPLOAD_BLOCK_RE = re.compile(r"<(?P<tag>uploaded_files|current_uploads)>[\s\S]*?</(?P=tag)>\n*", re.IGNORECASE)


def extract_message_text(message: Any) -> str:
    """Extract plain text from message content (str or content-block list)."""
    content = getattr(message, "content", "")
    if content is None:
        return ""
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                text = part.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return " ".join(parts)
    return str(content)


def _non_empty_str(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _is_human_clarification_response(additional_kwargs: Any) -> bool:
    """Structural check for a user-authored clarification answer carried in a
    hidden message (mirrors DeerMem's host-agnostic fallback)."""
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


def filter_messages_for_memory(messages: list[Any]) -> list[Any]:
    """Keep only user inputs and final assistant responses."""
    filtered: list[Any] = []
    skip_next_ai = False
    for msg in messages:
        msg_type = getattr(msg, "type", None)
        if msg_type == "human":
            additional_kwargs = getattr(msg, "additional_kwargs", {}) or {}
            if additional_kwargs.get("hide_from_ui") and not _is_human_clarification_response(additional_kwargs):
                continue
            text = extract_message_text(msg)
            if "<uploaded_files>" in text.lower() or "<current_uploads>" in text.lower():
                stripped = _UPLOAD_BLOCK_RE.sub("", text).strip()
                if not stripped:
                    # Upload-only turn: the following AI ack carries no user content.
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
            if getattr(msg, "tool_calls", None):
                continue
            if skip_next_ai:
                skip_next_ai = False
                continue
            filtered.append(msg)
    return filtered
