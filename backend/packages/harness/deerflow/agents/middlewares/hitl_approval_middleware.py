"""Human-in-the-loop approval for high-risk tool calls (Phase 1).

Uses the after_model pattern (same shape as LangChain's HumanInTheLoopMiddleware):
dangerous calls pause via interrupt(); rejections become artificial ToolMessages.
Never rejects inside wrap_tool_call — that path is bypassed by the DeerFlow
execution chain (validated by the design spike).
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Mapping
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.config import get_config
from langgraph.types import interrupt

from deerflow.agents.interaction_policy import resolve_run_interaction_policy
from deerflow.agents.middlewares.pii_redaction_middleware import redact_text
from deerflow.agents.middlewares.tool_call_metadata import clone_ai_message_with_tool_calls
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


def _addressable(calls: list[dict[str, Any]]) -> bool:
    """Whether every call can carry a stable approval decision.

    ``ToolMessage`` requires a non-empty string ``tool_call_id``. A pause whose
    payload carries a null or duplicated call id can never be validated: the
    Gateway resume validator answers 422 (all-reject included) while a pending
    pause blocks new runs with 409, so pausing would wedge the thread forever.
    An empty id is technically resumable end to end, but strict providers reject
    it when the conversation is replayed, so it is denied by the same rule.
    These calls are denied by removing them from the model response instead of
    by result.
    """
    ids = [call.get("id") for call in calls]
    return all(isinstance(call_id, str) and call_id for call_id in ids) and len(set(ids)) == len(ids)


def _unambiguous_ids(last: AIMessage, calls: list[dict[str, Any]]) -> bool:
    """Whether every targeted call has an id no other call in the response shares.

    ``_addressable`` only asks whether a ``ToolMessage`` can answer the targeted
    calls. An id shared with an ordinary call makes the approval ambiguous in
    both directions: approving, rejecting or denying one call would also answer
    the other by id. Such a group is denied before pausing or answering by result.
    """
    if not _addressable(calls):
        return False
    response_ids = Counter(tool_call.get("id") for tool_call in last.tool_calls)
    return all(response_ids[call.get("id")] == 1 for call in calls)


def _deny_message(tool_call: Mapping[str, Any], reason: str) -> ToolMessage:
    return ToolMessage(
        content=reason,
        tool_call_id=tool_call["id"],
        name=tool_call["name"],
        status="error",
    )


def _append_visible_note(content: Any, note: str) -> Any:
    if isinstance(content, list):
        return [*content, {"type": "text", "text": note}]
    text = content if isinstance(content, str) else ""
    return f"{text}\n\n{note}" if text else note


def _strip_calls(last: AIMessage, calls: list[dict[str, Any]], reason: str) -> dict[str, Any]:
    """Deny calls that cannot carry a result by removing them from the response.

    A non-target call can share an id with a removed one. ``clone_ai_message_with_tool_calls``
    filters the raw provider payload and content tool-call blocks by id, so such
    a survivor would keep the removed call's raw entry, and the next request
    would advertise a call that has no result. Drop the whole colliding id group
    instead: an id shared with a denied approval call cannot be answered
    unambiguously either.
    """
    dropped_ids = {call["id"] for call in calls if isinstance(call.get("id"), str) and call["id"]}
    dropped = {id(call) for call in calls}
    kept = [tool_call for tool_call in last.tool_calls if id(tool_call) not in dropped and not (isinstance(tool_call.get("id"), str) and tool_call["id"] in dropped_ids)]
    return {"messages": [clone_ai_message_with_tool_calls(last, kept, content=_append_visible_note(last.content, reason))]}


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

    def _deny_all(self, last: AIMessage, calls: list[dict[str, Any]], reason: str) -> dict[str, Any]:
        # A denial ``ToolMessage`` answers a call by id, so it needs an id no
        # other call in the response shares: otherwise the ordinary call is
        # answered too while staying serialized, and the next request carries
        # the id twice with two results. Strip the whole colliding group instead.
        if not _unambiguous_ids(last, calls):
            return _strip_calls(last, calls, reason)
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
            return self._deny_all(last, targets, _too_many_reason(len(targets), self.max_actions))

        if not self._can_resume(runtime):
            if self.non_interactive == "allow":
                # allow is meaningful for genuine non-interactive entries (e.g. IM).
                # Missing resume support or subagent is always a hard fail-closed.
                if not self.supports_resume or self._is_subagent(runtime):
                    return self._deny_all(last, targets, _no_resume_reason())
                return None
            return self._deny_all(last, targets, _no_resume_reason())

        ai_message_id = last.id or ""
        # A pause is only resolvable when every targeted call has a unique,
        # non-empty string id: the Gateway resume validator rejects a payload
        # with a null or duplicate id with 422, and a pending pause blocks new
        # runs with 409, so pausing here would wedge the thread permanently.
        # Fail closed instead of interrupting.
        if not _unambiguous_ids(last, targets):
            return _strip_calls(last, targets, _unaddressable_reason())
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
            return self._deny_all(last, targets, _too_large_reason())
        responses = interrupt(payload)
        if any(tc["name"] in resume_tool_names and tc["name"] not in live_tool_names for tc in targets):
            return self._deny_all(last, targets, _invalid_response_reason())
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
        if not _unambiguous_ids(last, targets):
            return _strip_calls(last, targets, _invalid_response_reason())
        ai_message_id = last.id or ""
        expected_request_ids = {call_id: f"hitl_approval:{ai_message_id}:{call_id}" for call_id in target_ids}
        responses = resume_value.get("responses") if isinstance(resume_value, Mapping) else None
        if not isinstance(responses, list) or len(responses) != len(target_ids):
            return self._deny_all(last, targets, _invalid_response_reason())
        by_id = {tc["id"]: tc for tc in targets}
        seen_ids: set[str] = set()
        artificial: list[ToolMessage] = []
        for response in responses:
            if not isinstance(response, Mapping):
                return self._deny_all(last, targets, _invalid_response_reason())
            response_id = response.get("tool_call_id")
            if not isinstance(response_id, str) or response_id in seen_ids or response_id not in by_id:
                return self._deny_all(last, targets, _invalid_response_reason())
            if response.get("request_id") != expected_request_ids[response_id]:
                return self._deny_all(last, targets, _invalid_response_reason())
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


def _unaddressable_reason() -> str:
    return "Approval could not be requested because this tool call has no usable id (missing, empty, or duplicated). The tool was not executed. Do not retry unless the user explicitly asks."


def _invalid_response_reason() -> str:
    return "The approval response was invalid, mismatched, or the approval configuration changed while paused. The tool calls were rejected for safety. The tool was not executed. Do not retry unless the user explicitly asks."


def _unknown_decision_reason(decision: Any) -> str:
    return f"Unsupported approval decision {_bounded_text(decision)}; treated as rejection."[:MAX_REASON_CHARS]


def _too_many_reason(count: int, max_actions: int) -> str:
    return f"Too many tool calls require approval ({count} > {max_actions}); rejected for safety."


def _too_large_reason() -> str:
    return "Approval payload exceeded the size budget; rejected for safety."
