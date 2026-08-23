"""Stamp deterministic tool receipts and render the receipt ledger to the model.

Ordering contract (enforced by the build-time constraints in
``deerflow.extensions.ordering.core_ordering_constraints``): this is the
outermost ``wrap_tool_call`` layer — Guardrail, SandboxAudit, ReadBeforeWrite,
and ToolProgress can short-circuit or rebuild results, and an inner receipt
layer would silently gap the ledger on those. Normal results still carry a
normalized ``deerflow_tool_meta`` status when stamped (ToolErrorHandling runs
on the inner return path); short-circuit messages either self-stamp the meta
or fall back to ``message.status`` in ``make_tool_receipt``.

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

from deerflow.agents.middlewares.message_utils import insert_after_leading_system_messages, is_genuine_user_message
from deerflow.agents.middlewares.tool_receipt import TOOL_RECEIPT_KEY, extract_tool_receipts, make_tool_receipt, render_tool_receipts

logger = logging.getLogger(__name__)

_RECEIPT_CONTEXT_KEY = "deerflow_tool_receipt_context"


class ToolReceiptMiddleware(AgentMiddleware[AgentState]):
    """Receipt layer: zero-LLM provenance for every tool call.

    render_mode: 'always' renders the ledger on every model call (subagent
    chains — citations are produced there; without the ledger the subagent
    cannot cite and Layer 1 goes inert). 'delegation_only' renders only when
    the message stream contains a completed subagent result (lead chain —
    the one place the lead needs citation context), avoiding the always-on
    token tax in ordinary conversation turns.
    """

    state_schema = AgentState

    def __init__(self, *, render_mode: str = "always") -> None:
        super().__init__()
        if render_mode not in {"always", "delegation_only"}:
            raise ValueError(f"Unknown render_mode: {render_mode}")
        self._render_mode = render_mode

    def _stamp_message(self, message: ToolMessage, request: ToolCallRequest) -> None:
        try:
            kwargs = dict(message.additional_kwargs or {})
            # The receipt key is runtime-owned: always overwrite, never preserve
            # a pre-existing value — a tool could otherwise forge its own
            # "evidence" and have it rendered as runtime-stamped provenance.
            kwargs[TOOL_RECEIPT_KEY] = make_tool_receipt(request.tool_call, message)
            message.additional_kwargs = kwargs
        except Exception:
            # Never block tool execution — but a systematic stamping failure must
            # be visible, or the ledger silently goes incomplete and citations lie.
            logger.warning("Failed to stamp tool receipt", exc_info=True)

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

    def _should_render(self, request: ModelRequest) -> bool:
        if self._render_mode == "always":
            return True
        # delegation_only: render only while a subagent result is being
        # processed (a task ToolMessage carries subagent_status in its
        # additional_kwargs — see subagents/status_contract.py). Scoped to the
        # current turn: only messages after the latest genuine user message
        # count, otherwise one completed delegation would keep the ledger
        # rendering on every later ordinary turn and defeat the token saving.
        # Without any genuine user message there is no turn boundary (e.g.
        # scheduled/internal invocations), so the whole stream is in scope.
        messages = list(request.messages)
        latest_user_index = -1
        for index, message in enumerate(messages):
            if is_genuine_user_message(message):
                latest_user_index = index
        turn_messages = messages[latest_user_index + 1 :] if latest_user_index >= 0 else messages
        for message in turn_messages:
            if isinstance(message, ToolMessage) and (message.additional_kwargs or {}).get("subagent_status"):
                return True
        return False

    def _inject(self, request: ModelRequest) -> ModelRequest:
        if not self._should_render(request):
            return request
        receipts = extract_tool_receipts(list(request.messages))
        ledger = render_tool_receipts(receipts)
        if not ledger:
            return request
        ledger_message = HumanMessage(
            content=ledger,
            additional_kwargs={"hide_from_ui": True, _RECEIPT_CONTEXT_KEY: True},
        )
        messages = insert_after_leading_system_messages(list(request.messages), [ledger_message])
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
