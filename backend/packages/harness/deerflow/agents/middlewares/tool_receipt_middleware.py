"""Stamp deterministic tool receipts and render the receipt ledger to the model.

Ordering contract (enforced by the build-time guard in
``tool_error_handling_middleware._build_runtime_middlewares``): this middleware
sits immediately outer of ToolErrorHandlingMiddleware so every ToolMessage it
sees already carries a normalized ``deerflow_tool_meta`` status.

The ledger injection mirrors DurableContextMiddleware: derived from the
in-flight messages on every model call, appended as a hidden HumanMessage,
never written back to state.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from deerflow.agents.middlewares.durable_context_middleware import _insert_after_leading_system_messages
from deerflow.agents.middlewares.tool_receipt import TOOL_RECEIPT_KEY, extract_tool_receipts, make_tool_receipt, render_tool_receipts

logger = logging.getLogger(__name__)

_RECEIPT_CONTEXT_KEY = "deerflow_tool_receipt_context"


class ToolReceiptMiddleware(AgentMiddleware[AgentState]):
    """Receipt layer: zero-LLM provenance for every tool call."""

    state_schema = AgentState

    def _stamp_message(self, message: ToolMessage, request: ToolCallRequest) -> None:
        try:
            kwargs = dict(message.additional_kwargs or {})
            if TOOL_RECEIPT_KEY not in kwargs:
                kwargs[TOOL_RECEIPT_KEY] = make_tool_receipt(request.tool_call, message)
                message.additional_kwargs = kwargs
        except Exception:
            logger.debug("Failed to stamp tool receipt", exc_info=True)

    def _stamp(self, result: ToolMessage | Command, request: ToolCallRequest) -> ToolMessage | Command:
        if isinstance(result, ToolMessage):
            self._stamp_message(result, request)
            return result

        update = result.update
        if not isinstance(update, dict):
            return result
        messages = update.get("messages", [])
        if isinstance(messages, ToolMessage):
            messages = [messages]
        if not isinstance(messages, (list, tuple)):
            return result

        tool_call_id = str(request.tool_call.get("id") or "")
        for message in messages:
            if isinstance(message, ToolMessage) and str(message.tool_call_id) == tool_call_id:
                self._stamp_message(message, request)
        return result

    @override
    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        return self._stamp(handler(request), request)

    @override
    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        return self._stamp(await handler(request), request)

    def _inject(self, request: ModelRequest) -> ModelRequest:
        receipts = extract_tool_receipts(list(request.messages))
        ledger = render_tool_receipts(receipts)
        if not ledger:
            return request
        ledger_message = HumanMessage(
            content=ledger,
            additional_kwargs={"hide_from_ui": True, _RECEIPT_CONTEXT_KEY: True},
        )
        messages = _insert_after_leading_system_messages(list(request.messages), [ledger_message])
        return request.override(messages=messages)

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        return handler(self._inject(request))

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        return await handler(self._inject(request))
