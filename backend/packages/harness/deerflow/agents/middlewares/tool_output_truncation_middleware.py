"""Truncate oversized tool results before they reach the next model call."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import Any, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from deerflow.config.app_config import AppConfig

logger = logging.getLogger(__name__)

_DEFAULT_TOOL_OUTPUT_MAX_BYTES = 50_000
_TRUNCATED_PREFIX = "[输出已截断，共{total_bytes}字节] 请使用过滤条件缩小查询范围"


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        if all(isinstance(part, str) for part in content):
            return "".join(content)
        pieces: list[str] = []
        for part in content:
            if isinstance(part, str):
                pieces.append(part)
            elif isinstance(part, dict):
                text = part.get("text")
                if isinstance(text, str):
                    pieces.append(text)
        return "\n".join(pieces)
    if content is None:
        return ""
    return str(content)


def _truncate_text(text: str, max_bytes: int) -> tuple[str, bool, int]:
    if max_bytes <= 0:
        return text, False, len(text.encode("utf-8"))

    encoded = text.encode("utf-8")
    total_bytes = len(encoded)
    if total_bytes <= max_bytes:
        return text, False, total_bytes

    kept = encoded[:max_bytes]
    while kept:
        try:
            truncated_text = kept.decode("utf-8")
            break
        except UnicodeDecodeError:
            kept = kept[:-1]
    else:
        truncated_text = ""

    return truncated_text, True, total_bytes


def _truncate_tool_message(message: ToolMessage, max_bytes: int) -> ToolMessage:
    text = _message_text(message.content)
    truncated_text, truncated, total_bytes = _truncate_text(text, max_bytes)
    if not truncated:
        return message

    prefix = _TRUNCATED_PREFIX.format(total_bytes=total_bytes)
    if truncated_text:
        content = f"{prefix}\n{truncated_text}"
    else:
        content = prefix

    logger.warning(
        "Truncated tool result before model call: name=%s id=%s size=%d bytes limit=%d",
        message.name,
        message.tool_call_id,
        total_bytes,
        max_bytes,
    )

    update: dict[str, Any] = {"content": content}
    if getattr(message, "response_metadata", None):
        update["response_metadata"] = dict(message.response_metadata)
    if getattr(message, "additional_kwargs", None):
        update["additional_kwargs"] = dict(message.additional_kwargs)
    return message.model_copy(update=update)


def _truncate_messages(messages: list[Any], max_bytes: int) -> list[Any]:
    updated: list[Any] = []
    changed = False
    for msg in messages:
        if isinstance(msg, ToolMessage):
            new_msg = _truncate_tool_message(msg, max_bytes)
            if new_msg is not msg:
                changed = True
            updated.append(new_msg)
        else:
            updated.append(msg)
    return updated if changed else messages


def _truncate_result(result: ToolMessage | Command, max_bytes: int) -> ToolMessage | Command:
    if isinstance(result, ToolMessage):
        return _truncate_tool_message(result, max_bytes)

    update = getattr(result, "update", None)
    if not isinstance(update, dict):
        return result

    messages = update.get("messages")
    if not isinstance(messages, list):
        return result

    new_messages = _truncate_messages(messages, max_bytes)
    if new_messages is messages:
        return result

    return replace(result, update={**update, "messages": new_messages})


class ToolOutputTruncationMiddleware(AgentMiddleware[AgentState]):
    """Clamp tool results so oversized outputs cannot blow the model context."""

    def __init__(self, *, max_bytes: int = _DEFAULT_TOOL_OUTPUT_MAX_BYTES) -> None:
        super().__init__()
        self.max_bytes = max(0, max_bytes)

    @classmethod
    def from_config(cls, config: AppConfig) -> ToolOutputTruncationMiddleware:
        return cls(max_bytes=getattr(config.tool_output, "max_bytes", _DEFAULT_TOOL_OUTPUT_MAX_BYTES))

    def _truncate_model_request(self, request: ModelRequest) -> ModelRequest:
        messages = getattr(request, "messages", [])
        if not isinstance(messages, list):
            return request

        new_messages = _truncate_messages(messages, self.max_bytes)
        if new_messages is messages:
            return request

        return request.override(messages=new_messages)

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        return handler(self._truncate_model_request(request))

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        return await handler(self._truncate_model_request(request))

    @override
    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        return _truncate_result(handler(request), self.max_bytes)

    @override
    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        return _truncate_result(await handler(request), self.max_bytes)
