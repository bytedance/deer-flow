"""Shared helpers for middleware message inspection and filtering."""

import re
from copy import copy
from typing import Any

_UPLOAD_BLOCK_RE = re.compile(r"<uploaded_files>[\s\S]*?</uploaded_files>\n*", re.IGNORECASE)


def extract_message_text(message: Any) -> str:
    """Extract plain text from message content."""
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


def strip_upload_block(text: str) -> str:
    """Remove UploadsMiddleware bookkeeping from plain text."""
    return _UPLOAD_BLOCK_RE.sub("", text).strip()


def filter_messages_for_terminal_conversation(messages: list[Any]) -> list[Any]:
    """Keep only user turns and final assistant responses.

    This removes tool messages and intermediate AI tool-call steps while also
    stripping ephemeral upload bookkeeping from human turns.
    """
    filtered: list[Any] = []
    skip_next_ai = False

    for msg in messages:
        msg_type = getattr(msg, "type", None)

        if msg_type == "human":
            content_str = extract_message_text(msg)
            if "<uploaded_files>" in content_str:
                stripped = strip_upload_block(content_str)
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
