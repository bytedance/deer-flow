import logging
import re
from collections.abc import Awaitable, Callable
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, AnyMessage, ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from deerflow.config.redaction_config import get_redaction_config

logger = logging.getLogger(__name__)


class RedactionMiddleware(AgentMiddleware[AgentState]):
    """Middleware to redact sensitive information from messages."""

    def __init__(self) -> None:
        super().__init__()
        self.config = get_redaction_config()
        self.compiled_patterns = [re.compile(p) for p in self.config.patterns]

    def _redact_text(self, text: str) -> str:
        """"""

        if not self.config.enabled or not text:
            return text

        redacted = text
        for pattern in self.compiled_patterns:
            redacted = pattern.sub(self.config.redact_string, redacted)

        return redacted

    def _redact_message(self, message: AnyMessage) -> AnyMessage:

        if not self.config.enabled:
            return message

        if isinstance(message, (AIMessage, ToolMessage)):
            if isinstance(message.content, str):
                message.content = self._redact_text(message.content)
            elif isinstance(message.content, list):
                for block in message.content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        block["text"] = self._redact_text(block.get("text", ""))

        return message

    @override
    def wrap_model_call(self, request: ModelRequest, handler: Callable[[ModelRequest], ModelResponse]) -> ModelCallResult:

        if self.config.enabled:
            for msg in request.messages:
                self._redact_message(msg)

        response = handler(request)

        if self.config.enabled and response:
            self._redact_message(response)

        return response

    @override
    async def awrap_model_call(self, request: ModelRequest, handler: Callable[[ModelRequest], Awaitable[ModelResponse]]) -> ModelResponse:
        if self.config.enabled:
            for msg in request.messages:
                self._redact_message(msg)

        response = await handler(request)

        if self.config.enabled and response:
            self._redact_message(response)

        return response

    @override
    def wrap_tool_call(self, request: ToolCallRequest, handler: Callable[[ToolCallRequest], ToolMessage | Command]) -> ToolMessage | Command:
        response = handler(request)
        if self.config.enabled and isinstance(response, ToolMessage):
            self._redact_message(response)

        return response

    @override
    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        response = await handler(request)
        if self.config.enabled and isinstance(response, ToolMessage):
            self._redact_message(response)

        return response
