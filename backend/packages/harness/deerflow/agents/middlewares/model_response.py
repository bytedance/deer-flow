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


def has_model_content(message: AIMessage) -> bool:
    """Return whether a message contains any provider-produced content block."""
    if has_tool_call_intent(message):
        return True
    additional_kwargs = message.additional_kwargs or {}
    for field in ("reasoning_content", "reasoning", "thinking"):
        value = additional_kwargs.get(field)
        if isinstance(value, str) and len(value) > 0:
            return True
        if value not in (None, "", [], {}):
            return True

    content = message.content
    if isinstance(content, str):
        # Only zero content is empty; whitespace is still provider output.
        return len(content) > 0
    if not isinstance(content, list):
        return content not in (None, "")

    for block in content:
        if isinstance(block, str):
            if len(block) > 0:
                return True
            continue
        if not isinstance(block, dict):
            if block is not None:
                return True
            continue
        block_type = block.get("type")
        if block_type in {"text", "output_text", "reasoning", "thinking"}:
            for field in ("text", "reasoning_content", "thinking", "reasoning", "content"):
                value = block.get(field)
                if isinstance(value, str) and len(value) > 0:
                    return True
                if value not in (None, "", [], {}):
                    return True
            continue
        if block:
            return True
    return False


def finish_reason(message: AIMessage) -> str | None:
    """Read and normalize common provider termination-reason fields."""
    for metadata in (message.response_metadata or {}, message.additional_kwargs or {}):
        for field in ("finish_reason", "stop_reason"):
            value = metadata.get(field)
            if isinstance(value, str):
                return value.strip().lower()
    return None
