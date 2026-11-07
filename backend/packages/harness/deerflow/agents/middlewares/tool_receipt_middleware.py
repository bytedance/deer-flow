"""Stamp deterministic tool receipts and render the receipt ledger to the model.

Ordering contract (enforced by the build-time constraints in
``deerflow.extensions.ordering.core_ordering_constraints``): this is the
outermost ``wrap_tool_call`` layer — Guardrail, SandboxAudit, ReadBeforeWrite,
and ToolProgress can short-circuit or rebuild results, and an inner receipt
layer would silently gap the ledger on those. Normal results still carry a
normalized ``deerflow_tool_meta`` status when stamped (ToolErrorHandling runs
on the inner return path); short-circuit messages either self-stamp the meta
or fall back to ``message.status`` in ``make_tool_receipt``.

Receipts are rendered on every model call from the in-flight messages and
never written back to state: each receipt line is appended to its own tool
result in the request, so the rendered history stays append-only and the
provider prefix cache survives across calls.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from deerflow.agents.middlewares.message_utils import is_genuine_user_message
from deerflow.agents.middlewares.tool_receipt import (
    TOOL_RECEIPT_KEY,
    TOOL_RECEIPT_LEDGER_KEY,
    ToolReceipt,
    extract_tool_receipts,
    is_valid_receipt,
    ledger_header_lines,
    make_tool_receipt,
    render_receipt_line,
)

logger = logging.getLogger(__name__)

#: Receipts citable at once. The snapshot stamped on each model response holds
#: at most this many entries; crossing a multiple drops the older inline lines.
_RECEIPT_EPOCH = 50


def _with_suffix(message: ToolMessage, suffix: str) -> ToolMessage:
    content = message.content
    if isinstance(content, list):
        content = [*content, {"type": "text", "text": "\n\n" + suffix}]
    else:
        content = f"{content}\n\n{suffix}"
    return message.model_copy(update={"content": content})


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

    def _eligible(self, messages: list) -> list[tuple[int, ToolReceipt]]:
        """Receipts to render, paired with the index of their tool result.

        delegation_only renders only while a subagent result is being processed
        (a task ToolMessage carries subagent_status in its additional_kwargs —
        see subagents/status_contract.py), and only the current turn's receipts:
        a completed delegation must not keep receipts rendering on later
        ordinary turns. A turn starts after the latest genuine user message;
        without one (scheduled/internal invocations) the whole stream is in scope.
        """
        receipts = iter(extract_tool_receipts(messages))
        indexed: list[tuple[int, ToolReceipt]] = []
        for index, message in enumerate(messages):
            if isinstance(message, ToolMessage) and is_valid_receipt((message.additional_kwargs or {}).get(TOOL_RECEIPT_KEY)):
                indexed.append((index, next(receipts)))
        if self._render_mode == "always":
            return indexed
        turn_start = max((index for index, message in enumerate(messages) if is_genuine_user_message(message)), default=-1) + 1
        if not any(isinstance(message, ToolMessage) and (message.additional_kwargs or {}).get("subagent_status") for message in messages[turn_start:]):
            return []
        return [(index, receipt) for index, receipt in indexed if index >= turn_start]

    def _prepare_model_call(self, request: ModelRequest) -> tuple[ModelRequest, list[ToolReceipt] | None]:
        messages = list(request.messages)
        eligible = self._eligible(messages)
        if not eligible:
            return request, None
        # Each receipt line is a pure function of its own tool result, so earlier
        # messages render identically on every call and the provider prefix cache
        # keeps hitting. Epochs bound the citable snapshot; crossing one re-renders
        # once.
        current = eligible[((len(eligible) - 1) // _RECEIPT_EPOCH) * _RECEIPT_EPOCH :]
        for position, (index, receipt) in enumerate(current):
            lines = [*ledger_header_lines(), render_receipt_line(receipt)] if position == 0 else [render_receipt_line(receipt)]
            messages[index] = _with_suffix(messages[index], "\n".join(lines))
        return request.override(messages=messages), [receipt for _, receipt in current]

    @staticmethod
    def _stamp_citing_ledger(result: ModelCallResult, receipts: list[ToolReceipt] | None) -> ModelCallResult:
        if receipts is None:
            return result
        if isinstance(result, AIMessage):
            messages = [result]
        else:
            response = getattr(result, "model_response", result)
            messages = getattr(response, "result", [])
        for message in messages:
            if not isinstance(message, AIMessage):
                continue
            kwargs = dict(message.additional_kwargs or {})
            # Runtime-owned and always overwritten so provider output cannot
            # forge the ledger against which its citations will be checked.
            kwargs[TOOL_RECEIPT_LEDGER_KEY] = [dict(receipt) for receipt in receipts]
            message.additional_kwargs = kwargs
        return result

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        prepared, receipts = self._prepare_model_call(request)
        return self._stamp_citing_ledger(handler(prepared), receipts)

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        prepared, receipts = self._prepare_model_call(request)
        return self._stamp_citing_ledger(await handler(prepared), receipts)
