from __future__ import annotations

from collections.abc import Mapping
from typing import Any

ORIGINAL_USER_CONTENT_KEY = "original_user_content"


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


def restore_original_user_content_blocks(content: Any, original_text: str) -> list[dict]:
    """Restore display content for a user message stamped with ``ORIGINAL_USER_CONTENT_KEY``.

    Mirrors the merge shape produced by ``InputSanitizationMiddleware._rebuild_content``:
    the first text block is replaced with the pre-wrap text, any subsequent text
    blocks (already merged into the first by the middleware) are dropped, and
    non-text blocks (images, files) stay in place. For string content (or any
    non-list shape) a single text-block list is returned.

    Without this, display surfaces that wholesale-replace ``content`` with a
    single text block lose the image/file blocks of multimodal user messages.
    """
    if not isinstance(content, list):
        return [{"type": "text", "text": original_text}]

    result: list[dict] = []
    text_replaced = False
    for block in content:
        if isinstance(block, Mapping) and block.get("type") == "text":
            if not text_replaced:
                result.append({"type": "text", "text": original_text})
                text_replaced = True
            # Subsequent text blocks were merged into the first by the
            # middleware; drop them so the displayed text is not duplicated.
            continue
        result.append(block)

    if not text_replaced:
        # No text block in the persisted list — prepend the original text
        # so the user's typed input still renders.
        result.insert(0, {"type": "text", "text": original_text})

    return result
