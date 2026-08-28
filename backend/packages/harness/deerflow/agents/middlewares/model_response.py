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


def has_model_content(message: AIMessage) -> bool:
    """Return whether a message contains any provider-produced content block."""
    if message.tool_calls or getattr(message, "invalid_tool_calls", None):
        return True

    additional_kwargs = message.additional_kwargs or {}
    if additional_kwargs.get("tool_calls") or additional_kwargs.get("function_call"):
        return True
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
