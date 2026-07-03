"""Suppress tool execution when the provider safety-terminated the response.

Background — see issue bytedance/deer-flow#3028.

Some providers (OpenAI ``finish_reason='content_filter'``, Anthropic
``stop_reason='refusal'``, Gemini ``finish_reason='SAFETY'`` ...) can stop
generation mid-stream while still returning partially-formed ``tool_calls``.
LangChain's tool router treats any AIMessage with a non-empty ``tool_calls``
field as "go execute these", so half-truncated arguments — e.g. a markdown
``write_file`` that stops in the middle of a sentence — get dispatched as if
they were complete. The agent then sees the truncated file, tries to fix it,
gets filtered again, and loops.

This middleware sits at ``after_model`` and gates that behaviour: when a
configured ``SafetyTerminationDetector`` fires *and* the AIMessage carries
tool calls, we strip the tool calls (both structured and raw provider
payloads), append a user-facing explanation, and stash observability fields
in ``additional_kwargs.safety_termination`` so logs, traces, and SSE
consumers can see what happened.

Hook choice: ``after_model`` (not ``wrap_model_call``) because the response
is a *normal* return — not an exception — and we want to participate in the
same after-model chain as ``LoopDetectionMiddleware``, with which we share
the same tool-call-suppression mechanic but a different trigger.

Placement: register *after* ``LoopDetectionMiddleware`` in the middleware
list. LangChain factory wires ``after_model`` edges in reverse list order
(``langchain/agents/factory.py:add_edge("model", middleware_w_after_model[-1])``,
then walks ``range(len-1, 0, -1)``), so the *last* registered middleware is
the *first* to observe the model output. Registering Safety after Loop
means Safety sees the raw response first, clears tool calls if it fires,
and Loop then accounts against the cleaned message.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage
from langgraph.runtime import Runtime

from deerflow.agents.middlewares.safety_termination_detectors import (
    SafetyTermination,
    SafetyTerminationDetector,
    default_detectors,
)
from deerflow.agents.middlewares.tool_call_metadata import clone_ai_message_with_tool_calls

if TYPE_CHECKING:
    from deerflow.config.safety_finish_reason_config import SafetyFinishReasonConfig

logger = logging.getLogger(__name__)


_USER_FACING_MESSAGE = (
    "The model provider stopped this response with a safety-related signal "
    "({reason_field}={reason_value!r}, detector={detector!r}). Any tool "
    "calls produced in this turn were suppressed because their arguments "
    "may be truncated and unsafe to execute. Please rephrase the request "
    "or ask for a narrower output."
)


class SafetyFinishReasonMiddleware(AgentMiddleware[AgentState]):
    """Strip tool_calls from AIMessages flagged by a SafetyTerminationDetector."""

    def __init__(self, detectors: list[SafetyTerminationDetector] | None = None) -> None:
        super().__init__()
        # Copy so caller mutations after construction don't leak into us.
        self._detectors: list[SafetyTerminationDetector] = list(detectors) if detectors else default_detectors()

    @classmethod
    def from_config(cls, config: SafetyFinishReasonConfig) -> SafetyFinishReasonMiddleware:
        """Construct from validated Pydantic config, honouring the
        reflection-loaded detector list when provided.

        An explicit empty list is intentionally rejected — it would silently
        disable detection while leaving the middleware in the chain, which
        is the worst of both worlds. Use ``enabled: false`` instead.
        """
        if config.detectors is None:
            return cls()

        if not config.detectors:
            raise ValueError("safety_finish_reason.detectors must be omitted (use built-ins) or contain at least one entry; use enabled=false to disable the middleware entirely.")

        from deerflow.reflection import resolve_variable

        detectors: list[SafetyTerminationDetector] = []
        for entry in config.detectors:
            detector_cls = resolve_variable(entry.use)
            kwargs = dict(entry.config) if entry.config else {}
            detector = detector_cls(**kwargs)
            if not isinstance(detector, SafetyTerminationDetector):
                raise TypeError(f"{entry.use} did not produce a SafetyTerminationDetector (got {type(detector).__name__}); ensure it has a `name` attribute and a `detect(message)` method")
            detectors.append(detector)
        return cls(detectors=detectors)

    # ----- detection -------------------------------------------------------

    def _detect(self, message: AIMessage) -> SafetyTermination | None:
        for detector in self._detectors:
            try:
                hit = detector.detect(message)
            except Exception:  # noqa: BLE001 - never let a buggy detector break the agent run
                logger.exception("SafetyTerminationDetector %r raised; treating as no-match", getattr(detector, "name", type(detector).__name__))
                continue
            if hit is not None:
                return hit
        return None

    # ----- message rewriting ----------------------------------------------

    @staticmethod
    def _append_user_message(content: object, text: str) -> str | list:
        """Append a plain-text explanation to AIMessage content.

        Mirrors ``LoopDetectionMiddleware._append_text`` so list-content
        responses (Anthropic thinking blocks, vLLM reasoning splits) keep
        their structure instead of being string-coerced into a TypeError.
        """
        if content is None or content == "":
            return text
        if isinstance(content, list):
            return [*content, {"type": "text", "text": f"\n\n{text}"}]
        if isinstance(content, str):
            return content + f"\n\n{text}"
        return str(content) + f"\n\n{text}"

    def _build_suppressed_message(
        self,
        message: AIMessage,
        termination: SafetyTermination,
    ) -> AIMessage:
        suppressed_names = [tc.get("name") or "unknown" for tc in (message.tool_calls or [])]
        explanation = _USER_FACING_MESSAGE.format(
            reason_field=termination.reason_field,
            reason_value=termination.reason_value,
            detector=termination.detector,
        )
        new_content = self._append_user_message(message.content, explanation)

        # clone_ai_message_with_tool_calls handles structured tool_calls,
        # raw additional_kwargs.tool_calls, and function_call in one shot.
        # It only rewrites finish_reason when the old value was "tool_calls",
        # which is not our case — content_filter / refusal / SAFETY stay put
        # so downstream SSE / converters keep seeing the real provider reason.
        cleared = clone_ai_message_with_tool_calls(message, [], content=new_content)

        # Re-clone additional_kwargs so we don't accidentally mutate the
        # dict returned by clone_ai_message_with_tool_calls (which already
        # made a shallow copy, but downstream model_copy still references
        # it). Then stamp the observability record.
        kwargs = dict(getattr(cleared, "additional_kwargs", None) or {})
        kwargs["safety_termination"] = {
            "detector": termination.detector,
            "reason_field": termination.reason_field,
            "reason_value": termination.reason_value,
            "suppressed_tool_call_count": len(suppressed_names),
            "suppressed_tool_call_names": suppressed_names,
            "extras": dict(termination.extras) if termination.extras else {},
        }
        return cleared.model_copy(update={"additional_kwargs": kwargs})

    # ----- observability ---------------------------------------------------

    def _emit_event(
        self,
        termination: SafetyTermination,
        suppressed_names: list[str],
        runtime: Runtime,
    ) -> None:
        """Notify SSE consumers (e.g. the web UI) that a tool turn was
        suppressed so they can reconcile any "tool starting..." placeholders
        already streamed to the user. Failures are logged at debug and
        ignored — this is a best-effort signal."""
        try:
            from langgraph.config import get_stream_writer

            writer = get_stream_writer()
        except Exception:  # noqa: BLE001
            logger.debug("get_stream_writer unavailable; skipping safety_termination event", exc_info=True)
            return

        thread_id = None
        if runtime is not None and getattr(runtime, "context", None):
            thread_id = runtime.context.get("thread_id") if isinstance(runtime.context, dict) else None

        try:
            writer(
                {
                    "type": "safety_termination",
                    "detector": termination.detector,
                    "reason_field": termination.reason_field,
                    "reason_value": termination.reason_value,
                    "suppressed_tool_call_count": len(suppressed_names),
                    "suppressed_tool_call_names": suppressed_names,
                    "thread_id": thread_id,
                }
            )
        except Exception:  # noqa: BLE001
            logger.debug("Failed to emit safety_termination stream event", exc_info=True)

    def _record_audit_event(
        self,
        termination: SafetyTermination,
        message,
        tool_calls: list[dict],
        runtime: Runtime,
    ) -> None:
        """Write a ``middleware:safety_termination`` record to RunEventStore
        for post-run auditability.

        The custom stream event in ``_emit_event`` is consumed by live SSE
        clients and disappears after the run; this event is persisted so an
        operator can answer "which runs were safety-suppressed today?" from
        a single SQL query without joining the message body. Worker exposes
        the run-scoped ``RunJournal`` via ``runtime.context["__run_journal"]``;
        absent in unit-test / subagent / no-event-store paths, in which case
        we silently skip.

        Tool **arguments** are deliberately **not** recorded — those are the
        very content the provider filtered; persisting them would defeat the
        purpose of the safety filter. Names / count / ids are sufficient for
        audit and debugging (issue #3028 review).
        """
        journal = None
        if runtime is not None and getattr(runtime, "context", None):
            context = runtime.context
            if isinstance(context, dict):
                journal = context.get("__run_journal")
        if journal is None:
            return

        suppressed_names = [tc.get("name") or "unknown" for tc in tool_calls]
        suppressed_ids = [tc.get("id") for tc in tool_calls if tc.get("id")]

        changes = {
            "detector": termination.detector,
            "reason_field": termination.reason_field,
            "reason_value": termination.reason_value,
            "suppressed_tool_call_count": len(tool_calls),
            "suppressed_tool_call_names": suppressed_names,
            "suppressed_tool_call_ids": suppressed_ids,
            "message_id": getattr(message, "id", None),
            "extras": dict(termination.extras) if termination.extras else {},
        }

        try:
            journal.record_middleware(
                tag="safety_termination",
                name=type(self).__name__,
                hook="after_model",
                action="suppress_tool_calls",
                changes=changes,
            )
        except Exception:  # noqa: BLE001
            # Audit-event persistence must never break agent execution.
            logger.debug("Failed to record middleware:safety_termination event", exc_info=True)

    # ----- main apply ------------------------------------------------------

    def _apply(self, state: AgentState, runtime: Runtime) -> dict | None:
        messages = state.get("messages", [])
        if not messages:
            return None

        last = messages[-1]
        if not isinstance(last, AIMessage):
            return None

        # Issue scope: only intervene when there's something to suppress.
        # ``content_filter`` without tool_calls is allowed through unchanged
        # so the partial text response (if any) reaches the user naturally.
        tool_calls = last.tool_calls
        if not tool_calls:
            return None

        termination = self._detect(last)
        if termination is None:
            return None

        patched = self._build_suppressed_message(last, termination)

        thread_id = None
        if runtime is not None and getattr(runtime, "context", None):
            thread_id = runtime.context.get("thread_id") if isinstance(runtime.context, dict) else None

        logger.warning(
            "Provider safety termination detected — suppressed %d tool call(s)",
            len(tool_calls),
            extra={
                "thread_id": thread_id,
                "detector": termination.detector,
                "reason_field": termination.reason_field,
                "reason_value": termination.reason_value,
                "suppressed_tool_call_names": [tc.get("name") for tc in tool_calls],
            },
        )

        self._emit_event(termination, [tc.get("name") or "unknown" for tc in tool_calls], runtime)
        self._record_audit_event(termination, last, list(tool_calls), runtime)

        return {"messages": [patched]}

    # ----- hooks -----------------------------------------------------------

    @override
    def after_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        return self._apply(state, runtime)

    @override
    async def aafter_model(self, state: AgentState, runtime: Runtime) -> dict | None:
        return self._apply(state, runtime)
