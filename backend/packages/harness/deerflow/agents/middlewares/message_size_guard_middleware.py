"""Middleware to cap oversized message content before model calls.

This keeps prompt size stable in long-running threads where some tool outputs
or assistant replies can become extremely large (for example, full skill docs
or malformed long responses). The original messages remain in state; only the
request payload sent to the model is trimmed.
"""

import logging
from collections.abc import Awaitable, Callable
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse

logger = logging.getLogger(__name__)


class MessageSizeGuardMiddleware(AgentMiddleware[AgentState]):
    """Truncate oversized message content before invoking the model."""

    _MAX_TOOL_CONTENT_CHARS = 24000
    _MAX_AI_CONTENT_CHARS = 12000
    _HEAD_CHARS = 8000
    _TAIL_CHARS = 2000

    @classmethod
    def _truncate_text(cls, text: str, max_chars: int) -> str:
        if len(text) <= max_chars:
            return text
        omitted = len(text) - (cls._HEAD_CHARS + cls._TAIL_CHARS)
        return (
            text[: cls._HEAD_CHARS]
            + f"\n\n[... truncated {max(omitted, 0)} chars to keep context within limits ...]\n\n"
            + text[-cls._TAIL_CHARS :]
        )

    @staticmethod
    def _clone_with_content(msg, content: str):
        if hasattr(msg, "model_copy"):
            return msg.model_copy(update={"content": content})
        if hasattr(msg, "copy"):
            return msg.copy(update={"content": content})
        return msg

    def _build_patched_messages(self, messages: list):
        patched = []
        patched_count = 0

        for msg in messages:
            msg_type = getattr(msg, "type", None)
            content = getattr(msg, "content", None)

            if not isinstance(content, str):
                patched.append(msg)
                continue

            if msg_type == "tool":
                new_content = self._truncate_text(content, self._MAX_TOOL_CONTENT_CHARS)
            elif msg_type == "ai":
                new_content = self._truncate_text(content, self._MAX_AI_CONTENT_CHARS)
            else:
                new_content = content

            if new_content != content:
                patched_count += 1
                patched.append(self._clone_with_content(msg, new_content))
            else:
                patched.append(msg)

        if patched_count > 0:
            logger.warning("MessageSizeGuardMiddleware truncated %s oversized message(s)", patched_count)
        return patched if patched_count > 0 else None

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        patched = self._build_patched_messages(request.messages)
        if patched is not None:
            request = request.override(messages=patched)
        return handler(request)

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        patched = self._build_patched_messages(request.messages)
        if patched is not None:
            request = request.override(messages=patched)
        return await handler(request)

