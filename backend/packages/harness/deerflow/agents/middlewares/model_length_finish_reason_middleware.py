"""Surface provider length-capped model responses as run stop reasons.

Background — see issue bytedance/deer-flow#4271.

Some providers stop generation because the output budget is exhausted and
surface that through ``finish_reason='length'`` while still returning assistant
content. DeerFlow should preserve that content for audit, but it should not
silently treat the run as an uncapped clean completion when the provider has
explicitly signaled truncation.

This middleware keeps that boundary narrow:
- it only marks a run-level stop reason when the final AIMessage is capped
  by a provider length signal and still has visible content;
- it never rewrites the assistant content or reparses XML-like text into a
  tool call;
- it ignores any response that still carries tool-call intent, malformed
  tool-call metadata, or no visible content, so only terminal assistant
  responses with visible content can be marked capped.

"""

from __future__ import annotations

import logging
from typing import Any, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage
from langgraph.runtime import Runtime

from deerflow.agents.middlewares.model_length_termination_detectors import (
    ModelLengthTermination,
    ModelLengthTerminationDetector,
    default_detectors,
)

MODEL_LENGTH_CAPPED_STOP_REASON = "model_length_capped"
logger = logging.getLogger(__name__)


def _has_tool_call_intent_or_error(message: AIMessage) -> bool:
    if message.tool_calls or getattr(message, "invalid_tool_calls", None):
        return True
    additional_kwargs = message.additional_kwargs or {}
    return bool(additional_kwargs.get("tool_calls") or additional_kwargs.get("function_call"))


def _has_visible_content(message: AIMessage) -> bool:
    content = message.content
    if isinstance(content, str):
        return bool(content.strip())
    if isinstance(content, list):
        for block in content:
            if isinstance(block, str) and block.strip():
                return True
            if isinstance(block, dict) and block.get("type") in {"text", "output_text"}:
                text = block.get("text")
                if isinstance(text, str) and text.strip():
                    return True
    return False


class ModelLengthFinishReasonMiddleware(AgentMiddleware[AgentState]):
    """Record provider length caps for terminal assistant responses with content.

    If the last AIMessage still carries tool-call intent, this middleware
    leaves it alone and lets the normal tool-handling path decide what to do.
    """

    def __init__(self, detectors: list[ModelLengthTerminationDetector] | None = None) -> None:
        super().__init__()
        self._detectors: list[ModelLengthTerminationDetector] = list(detectors) if detectors else default_detectors()

    def _detect(self, message: AIMessage) -> ModelLengthTermination | None:
        for detector in self._detectors:
            try:
                hit = detector.detect(message)
            except Exception:  # noqa: BLE001 - provider detectors must not break a run
                logger.exception("ModelLengthTerminationDetector %r raised; treating as no-match", getattr(detector, "name", type(detector).__name__))
                continue
            if hit is not None:
                return hit
        return None

    def _apply(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        messages = list(state.get("messages") or [])
        if not messages or not isinstance(messages[-1], AIMessage):
            return None

        last = messages[-1]
        if _has_tool_call_intent_or_error(last):
            return None
        if not _has_visible_content(last):
            return None

        termination = self._detect(last)
        if termination is None:
            return None

        ctx = getattr(runtime, "context", None)
        thread_id = ctx.get("thread_id") if isinstance(ctx, dict) else None
        run_id = ctx.get("run_id") if isinstance(ctx, dict) else None
        stamped_stop_reason = False
        if isinstance(ctx, dict):
            # Preserve any earlier cap reason carried across hidden continuation turns.
            if "stop_reason" not in ctx:
                ctx["stop_reason"] = MODEL_LENGTH_CAPPED_STOP_REASON
                stamped_stop_reason = True
        logger.info(
            "Provider model length cap detected",
            extra={
                "thread_id": thread_id,
                "run_id": run_id,
                "message_id": getattr(last, "id", None),
                "detector": termination.detector,
                "reason_field": termination.reason_field,
                "reason_value": termination.reason_value,
                "stamped_stop_reason": stamped_stop_reason,
            },
        )
        return None

    @override
    def after_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        return self._apply(state, runtime)

    @override
    async def aafter_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        return self._apply(state, runtime)
