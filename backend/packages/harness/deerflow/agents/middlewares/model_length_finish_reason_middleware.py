"""Surface provider length-capped responses and block truncated tool calls.

Background — see issue bytedance/deer-flow#4271.

Some providers stop generation because the output budget is exhausted and
surface that through ``finish_reason='length'`` while still returning assistant
content. DeerFlow preserves visible content, adds a deterministic notice when
no visible answer was produced, and drops tool calls that may have been
truncated at the output boundary before they can execute.
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
from deerflow.agents.middlewares.model_response import append_visible_text, has_tool_call_intent, has_visible_content

MODEL_LENGTH_CAPPED_STOP_REASON = "model_length_capped"
_MODEL_LENGTH_CAPPED_CONTENT = "The model reached its output limit before producing a complete final response. Please continue the conversation to resume."
logger = logging.getLogger(__name__)


def _tool_call_summary(message: AIMessage) -> tuple[int, list[str]]:
    """Count suppressed tool calls and return their deduplicated names."""
    names: list[str] = []
    structured_calls: list[Any] = [*(message.tool_calls or []), *(getattr(message, "invalid_tool_calls", None) or [])]
    additional_kwargs = message.additional_kwargs or {}
    if structured_calls:
        # LangChain commonly keeps both parsed calls and their raw provider copy.
        calls = structured_calls
    else:
        calls = list(additional_kwargs.get("tool_calls") or [])
        function_call = additional_kwargs.get("function_call")
        if not calls and isinstance(function_call, dict):
            calls.append(function_call)

    for call in calls:
        if not isinstance(call, dict):
            continue
        name = call.get("name")
        function = call.get("function")
        if not isinstance(name, str) and isinstance(function, dict):
            name = function.get("name")
        if isinstance(name, str) and name and name not in names:
            names.append(name)
    return len(calls), names


class ModelLengthFinishReasonMiddleware(AgentMiddleware[AgentState]):
    """Record provider length termination and block truncated tool calls."""

    def __init__(self, detectors: list[ModelLengthTerminationDetector] | None = None) -> None:
        super().__init__()
        self._detectors: list[ModelLengthTerminationDetector] = list(detectors) if detectors else default_detectors()

    def release_policy_parameters(self) -> dict[str, object]:
        from deerflow_extension_api import canonical_hash

        return {
            "suppress_truncated_tool_calls": True,
            "empty_content_fallback_hash": canonical_hash(_MODEL_LENGTH_CAPPED_CONTENT),
        }

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

        contains_tool_call = has_tool_call_intent(last)
        contains_visible_content = has_visible_content(last)
        if not contains_tool_call and contains_visible_content:
            return None

        additional_kwargs = dict(last.additional_kwargs or {})
        suppressed_count, suppressed_names = _tool_call_summary(last) if contains_tool_call else (0, [])
        if contains_tool_call:
            # Tool arguments may be incomplete at a max-token boundary.
            additional_kwargs.pop("tool_calls", None)
            additional_kwargs.pop("function_call", None)
        additional_kwargs["model_length_termination"] = {
            "detector": termination.detector,
            "reason_field": termination.reason_field,
            "reason_value": termination.reason_value,
            "suppressed_tool_call_count": suppressed_count,
            "suppressed_tool_call_names": suppressed_names,
        }
        replacement = last.model_copy(
            update={
                "content": (last.content if contains_visible_content else append_visible_text(last, _MODEL_LENGTH_CAPPED_CONTENT)),
                "tool_calls": [],
                "invalid_tool_calls": [],
                "additional_kwargs": additional_kwargs,
            }
        )
        return {"messages": [replacement]}

    @override
    def after_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        return self._apply(state, runtime)

    @override
    async def aafter_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        return self._apply(state, runtime)
