"""Shared model response content and termination classification."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage


def last_ai_message(response: Any) -> AIMessage | None:
    """Return the last assistant message from a middleware model result."""
    if isinstance(response, AIMessage):
        return response
    result = getattr(response, "result", None)
    if isinstance(result, (list, tuple)):
        return next((message for message in reversed(result) if isinstance(message, AIMessage)), None)
    return None


def has_tool_call_intent(message: AIMessage) -> bool:
    """Return whether parsed or provider-raw tool-call intent is present."""
    if message.tool_calls or getattr(message, "invalid_tool_calls", None):
        return True
    additional_kwargs = message.additional_kwargs or {}
    return bool(additional_kwargs.get("tool_calls") or additional_kwargs.get("function_call"))


def has_visible_content(message: AIMessage) -> bool:
    """Return whether a message contains non-whitespace user-visible text."""
    content = message.content
    if isinstance(content, str):
        return bool(content.strip())
    if not isinstance(content, list):
        return False

    for block in content:
        if isinstance(block, str) and block.strip():
            return True
        if not isinstance(block, dict) or block.get("type") not in {"text", "output_text"}:
            continue
        text = block.get("text")
        if isinstance(text, str) and text.strip():
            return True
    return False


def append_visible_text(message: AIMessage, text: str) -> Any:
    """Append a visible text block without dropping existing content blocks."""
    if isinstance(message.content, list):
        return [*message.content, {"type": "text", "text": text}]
    return text


def finish_reason(message: AIMessage) -> str | None:
    """Read and normalize common provider termination-reason fields."""
    for metadata in (message.response_metadata or {}, message.additional_kwargs or {}):
        for field in ("finish_reason", "stop_reason"):
            value = metadata.get(field)
            if isinstance(value, str):
                return value.strip().lower()
    return None
