from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from langchain_core.messages import HumanMessage

ORIGINAL_USER_CONTENT_KEY = "original_user_content"
SUMMARY_MESSAGE_NAME = "summary"


def message_content_to_text(content: Any) -> str:
    """Extract text from LangChain message content shapes."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(part for part in parts if part)
    return str(content)


def message_to_text(message: Any, *, text_attribute_fallback: bool = False) -> str:
    """Extract display text from a whole message (``BaseMessage`` or dict-shaped).

    Reads ``content`` from either an attribute (``BaseMessage``) or a mapping key
    (``run_events`` rows are dicts), then walks the mixed ``content`` shapes:
    plain string; a list of string / ``{"text": ...}`` / nested ``{"content": ...}``
    blocks joined without a separator; or a mapping with a ``text``/``content`` key.
    Set ``text_attribute_fallback=True`` to fall back to ``message.text`` when
    content yields nothing (matches ``RunJournal._message_text``).

    Unlike :func:`message_content_to_text` (which takes raw ``content`` and joins
    list blocks with newlines), this keeps the no-separator join and the broader
    shape handling that several call sites had each reimplemented.
    """
    content = message.get("content") if isinstance(message, Mapping) else getattr(message, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, Mapping):
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
                else:
                    nested = block.get("content")
                    if isinstance(nested, str):
                        parts.append(nested)
        return "".join(parts)
    if isinstance(content, Mapping):
        for key in ("text", "content"):
            value = content.get(key)
            if isinstance(value, str):
                return value
    if text_attribute_fallback:
        text = getattr(message, "text", None)
        if isinstance(text, str):
            return text
    return ""


def get_original_user_content_text(content: Any, additional_kwargs: Mapping[str, Any] | None) -> str:
    """Return pre-middleware user text when available, otherwise content text."""
    original_content = (additional_kwargs or {}).get(ORIGINAL_USER_CONTENT_KEY)
    if isinstance(original_content, str):
        return original_content
    return message_content_to_text(content)


def is_real_user_message(message: object) -> bool:
    """Return whether ``message`` is a real user-authored HumanMessage.

    Middleware-injected hidden HumanMessages and summarization markers should not
    drive user-intent features such as slash-skill activation or MCP routing.
    """
    if not isinstance(message, HumanMessage):
        return False
    if message.name == SUMMARY_MESSAGE_NAME:
        return False
    if message.additional_kwargs.get("hide_from_ui"):
        return False
    return True
