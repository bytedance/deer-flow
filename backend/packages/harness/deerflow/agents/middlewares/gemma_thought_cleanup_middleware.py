"""Middleware that removes Gemma 4 thought blocks from historical model turns.

Google's Gemma 4 prompt-formatting guide requires that ``<|channel>...<channel|>``
reasoning blocks from previous model turns be stripped before the next user
turn is submitted — except while a tool-call sequence is still in flight. Left
in place they inflate the input token budget and can destabilize the 26B/31B
variants, which may then hallucinate further reasoning channels.

Design mirrors :class:`DanglingToolCallMiddleware` — we intercept the request
via ``wrap_model_call`` so only the payload sent to the model is cleaned;
persistent thread state keeps the original AIMessages intact for tracing,
LangSmith, and UI inspection.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, ToolMessage

from deerflow.utils.text_sanitize import strip_gemma_channel_blocks

logger = logging.getLogger(__name__)


class GemmaThoughtCleanupMiddleware(AgentMiddleware[AgentState]):
    """Strips Gemma 4 channel blocks from historical AIMessages before model invocation."""

    @staticmethod
    def _has_outstanding_tool_calls(messages: list, index: int) -> bool:
        """Return True if messages[index] is part of an in-flight tool-call sequence."""
        msg = messages[index]
        tool_calls = getattr(msg, "tool_calls", None) or []
        if not tool_calls:
            return False
        outstanding = {tc.get("id") for tc in tool_calls if tc.get("id")}
        if not outstanding:
            return False
        for subsequent in messages[index + 1 :]:
            if isinstance(subsequent, ToolMessage) and subsequent.tool_call_id in outstanding:
                outstanding.discard(subsequent.tool_call_id)
            if not outstanding:
                return False
        return bool(outstanding)

    @staticmethod
    def _clean_text(text: str) -> str:
        return strip_gemma_channel_blocks(text)

    def _clean_content(self, content):
        """Clean AIMessage.content, which can be a plain string or a list of content blocks."""
        if isinstance(content, str):
            return self._clean_text(content)
        if isinstance(content, list):
            new_parts: list = []
            for part in content:
                if isinstance(part, str):
                    new_parts.append(self._clean_text(part))
                elif isinstance(part, dict) and isinstance(part.get("text"), str):
                    new_part = dict(part)
                    new_part["text"] = self._clean_text(part["text"])
                    new_parts.append(new_part)
                else:
                    new_parts.append(part)
            return new_parts
        return content

    def _build_cleaned_messages(self, messages: list) -> list | None:
        """Return a new message list with channel blocks removed, or None if no change."""
        if not messages:
            return None

        cleaned: list = []
        mutated = False
        for index, msg in enumerate(messages):
            if not isinstance(msg, AIMessage):
                cleaned.append(msg)
                continue

            if self._has_outstanding_tool_calls(messages, index):
                # In-flight tool-call sequence — Gemma 4 expects its own thoughts
                # echoed back in this window. Leave untouched.
                cleaned.append(msg)
                continue

            new_content = self._clean_content(msg.content)
            if new_content == msg.content:
                cleaned.append(msg)
                continue

            mutated = True
            cleaned.append(
                AIMessage(
                    id=msg.id,
                    content=new_content,
                    name=msg.name,
                    tool_calls=msg.tool_calls,
                    invalid_tool_calls=getattr(msg, "invalid_tool_calls", []),
                    additional_kwargs=msg.additional_kwargs,
                    response_metadata=msg.response_metadata,
                    usage_metadata=msg.usage_metadata,
                )
            )

        if not mutated:
            return None
        return cleaned

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        cleaned = self._build_cleaned_messages(request.messages)
        if cleaned is not None:
            request = request.override(messages=cleaned)
        return handler(request)

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        cleaned = self._build_cleaned_messages(request.messages)
        if cleaned is not None:
            request = request.override(messages=cleaned)
        return await handler(request)
