"""Human-in-the-loop approval for high-risk tool calls (Phase 1).

Uses the after_model pattern (same shape as LangChain's HumanInTheLoopMiddleware):
dangerous calls pause via interrupt(); rejections become artificial ToolMessages.
Never rejects inside wrap_tool_call — that path is bypassed by the DeerFlow
execution chain (validated by the design spike).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.config import get_config
from langgraph.types import interrupt

from deerflow.agents.interaction_policy import resolve_run_interaction_policy
from deerflow.agents.middlewares.pii_redaction_middleware import redact_text
from deerflow.runtime.run_origin import origin_kind_of

logger = logging.getLogger(__name__)

KIND = "hitl_approval"
MAX_REASON_CHARS = 2000
MAX_SUMMARY_FIELD_CHARS = 2000
MAX_PAYLOAD_BYTES = 32_000
HEAD_TAIL_CHARS = 400

# Fields whose meaning must never be hidden from the approver.
_UNTRUNCATED_FIELDS = frozenset({"path", "command", "url", "old_str", "new_str"})


def _shorten_middle(text: str) -> str:
    if len(text) <= MAX_SUMMARY_FIELD_CHARS:
        return text
    omitted = len(text) - 2 * HEAD_TAIL_CHARS
    return f"{text[:HEAD_TAIL_CHARS]}…[{omitted} chars omitted]…{text[-HEAD_TAIL_CHARS:]}"


def summarize_args(args: Any, *, pii_config: Any = None) -> Any:
    """Display-only argument summary. High-semantic fields are never truncated."""
    if not isinstance(args, Mapping):
        return _shorten_middle(str(args))
    summary: dict[str, Any] = {}
    for key, value in args.items():
        text = value if isinstance(value, str) else str(value)
        if key in _UNTRUNCATED_FIELDS:
            summary[key] = text
        else:
            summary[key] = _shorten_middle(text)
    return redact_text(str(summary), pii_config) if pii_config is not None else summary


def _bounded_text(value: Any) -> str:
    """Render untrusted values without allowing malformed objects to escape or grow output."""
    if isinstance(value, str):
        return value[:MAX_REASON_CHARS]
    try:
        return repr(value)[:MAX_REASON_CHARS]
    except Exception:
        return f"<unprintable {type(value).__name__}>"[:MAX_REASON_CHARS]


def _deny_message(tool_call: Mapping[str, Any], reason: str) -> ToolMessage:
    return ToolMessage(
        content=reason,
        tool_call_id=tool_call["id"],
        name=tool_call["name"],
        status="error",
    )


class HitlApprovalMiddleware(AgentMiddleware):
    """Pause high-risk tool calls for human approval.

    ``supports_resume`` is decided at assembly time (only the normal Gateway
    branch passes True); runtime cannot detect a checkpointer. ``is_subagent``
    is checked at runtime as a second defensive gate.
    """

    def __init__(
        self,
        *,
        tool_names: set[str],
        non_interactive: str = "deny",
        max_actions: int = 32,
        supports_resume: bool = True,
        pii_config: Any = None,
    ) -> None:
        self.tool_names = set(tool_names)
        self.non_interactive = non_interactive
        self.supports_resume = supports_resume
        self.pii_config = pii_config
        self.max_actions = max_actions
        self._warned_unknown: set[str] = set()

    # -- helpers ---------------------------------------------------------

    def _target_calls(self, last: AIMessage) -> list[dict[str, Any]]:
        return [tc for tc in last.tool_calls if tc["name"] in self.tool_names]

    def _deny_all(self, calls: list[dict[str, Any]], reason: str) -> dict[str, Any]:
        return {"messages": [_deny_message(tc, reason) for tc in calls]}

    def _is_subagent(self, runtime: Any) -> bool:
        context = getattr(runtime, "context", None) or {}
        return isinstance(context, Mapping) and bool(context.get("is_subagent"))

    def _can_resume(self, runtime: Any) -> bool:
        if not self.supports_resume or self._is_subagent(runtime):
            return False
        policy = resolve_run_interaction_policy({"context": getattr(runtime, "context", None)})
        if not policy.allows_clarification:
            return False
        metadata = get_config().get("metadata") or {}
        kind = origin_kind_of(metadata)
        # Only Web/SDK runs (no origin) can submit command.resume via the run API.
        # With non_interactive="allow", all other origin kinds auto-execute except
        # subagents and runtimes assembled without resume support.
        return kind is None

    # -- main hook -------------------------------------------------------

    def after_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        messages = state.get("messages") if isinstance(state, Mapping) else state.messages
        if not messages:
            return None
        last = messages[-1]
        if not isinstance(last, AIMessage) or not last.tool_calls:
            return None

        context = getattr(runtime, "context", None)
        resume_tool_names = context.get("_hitl_resume_tool_names", set()) if isinstance(context, Mapping) else set()
        if not isinstance(resume_tool_names, (set, frozenset)) or any(not isinstance(name, str) for name in resume_tool_names):
            resume_tool_names = set()
        live_tool_names = set(self.tool_names)
        if resume_tool_names:
            # The graph is assembled again on every resume. If approval tools were
            # changed or cleared while paused, the worker recovers their names from
            # the durable interrupt payload so replay still reaches interrupt().
            # Keep the recovered gate for subsequent model steps in this graph.
            self.tool_names.update(resume_tool_names)
        targets = self._target_calls(last)
        if not targets:
            return None
        if self.max_actions and len(targets) > self.max_actions:
            return self._deny_all(targets, _too_many_reason(len(targets), self.max_actions))

        if not self._can_resume(runtime):
            if self.non_interactive == "allow":
                # allow is meaningful for genuine non-interactive entries (e.g. IM).
                # Missing resume support or subagent is always a hard fail-closed.
                if not self.supports_resume or self._is_subagent(runtime):
                    return self._deny_all(targets, _no_resume_reason())
                return None
            return self._deny_all(targets, _no_resume_reason())

        ai_message_id = last.id or ""
        actions = [
            {
                "tool_call_id": tc["id"],
                "tool_name": tc["name"],
                "args_summary": summarize_args(tc.get("args", {}), pii_config=self.pii_config),
                "request_id": f"hitl_approval:{ai_message_id}:{tc['id']}",
            }
            for tc in targets
        ]
        payload = {
            "kind": KIND,
            "version": 1,
            "request_id": f"hitl_approval:{ai_message_id}:{targets[0]['id']}",
            "actions": actions,
            "allowed_decisions": ["approve", "reject"],
            "pending_tool_call_ids": [tc["id"] for tc in targets],
        }
        if len(str(payload)) > MAX_PAYLOAD_BYTES:
            return self._deny_all(targets, _too_large_reason())
        responses = interrupt(payload)
        if any(tc["name"] in resume_tool_names and tc["name"] not in live_tool_names for tc in targets):
            return self._deny_all(targets, _invalid_response_reason())
        return self._process_responses(last, targets, responses)

    async def aafter_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        return self.after_model(state, runtime)

    # -- resume handling -------------------------------------------------

    def _process_responses(
        self,
        last: AIMessage,
        targets: list[dict[str, Any]],
        resume_value: Any,
    ) -> dict[str, Any]:
        target_ids = [tc["id"] for tc in targets]
        if any(not isinstance(call_id, str) for call_id in target_ids) or len(set(target_ids)) != len(target_ids):
            return self._deny_all(targets, _invalid_response_reason())
        ai_message_id = last.id or ""
        expected_request_ids = {call_id: f"hitl_approval:{ai_message_id}:{call_id}" for call_id in target_ids}
        responses = resume_value.get("responses") if isinstance(resume_value, Mapping) else None
        if not isinstance(responses, list) or len(responses) != len(target_ids):
            return self._deny_all(targets, _invalid_response_reason())
        by_id = {tc["id"]: tc for tc in targets}
        seen_ids: set[str] = set()
        artificial: list[ToolMessage] = []
        for response in responses:
            if not isinstance(response, Mapping):
                return self._deny_all(targets, _invalid_response_reason())
            response_id = response.get("tool_call_id")
            if not isinstance(response_id, str) or response_id in seen_ids or response_id not in by_id:
                return self._deny_all(targets, _invalid_response_reason())
            if response.get("request_id") != expected_request_ids[response_id]:
                return self._deny_all(targets, _invalid_response_reason())
            seen_ids.add(response_id)
            call = by_id[response_id]
            decision = response.get("option_id")
            if decision == "approve":
                continue
            reason_value = response.get("value")
            reason = _bounded_text(reason_value) if reason_value is not None else ""
            if decision != "reject":
                reason = _unknown_decision_reason(decision)
            artificial.append(
                _deny_message(
                    call,
                    "The tool was not executed. Do not retry unless the user explicitly asks." + (f" User reason: {reason}" if reason else ""),
                )
            )
        return {"messages": artificial}


def _no_resume_reason() -> str:
    return "Approval is required for this tool, but this run cannot collect approval (non-interactive entry). The tool was not executed."


def _invalid_response_reason() -> str:
    return "The approval response was invalid, mismatched, or the approval configuration changed while paused. The tool calls were rejected for safety. The tool was not executed. Do not retry unless the user explicitly asks."


def _unknown_decision_reason(decision: Any) -> str:
    return f"Unsupported approval decision {_bounded_text(decision)}; treated as rejection."[:MAX_REASON_CHARS]


def _too_many_reason(count: int, max_actions: int) -> str:
    return f"Too many tool calls require approval ({count} > {max_actions}); rejected for safety."


def _too_large_reason() -> str:
    return "Approval payload exceeded the size budget; rejected for safety."
