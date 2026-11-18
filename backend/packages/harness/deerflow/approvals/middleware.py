"""Intercept the bound tool call, after argument resolution and before execution."""

from __future__ import annotations

import asyncio
import copy
from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from jsonschema import Draft202012Validator
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.config import get_config
from langgraph.errors import GraphBubbleUp
from langgraph.func import task
from langgraph.types import interrupt

from deerflow.agents.interaction_policy import resolve_run_interaction_policy
from deerflow.agents.middlewares.tool_call_metadata import clone_ai_message_with_tool_calls
from deerflow.approvals.policy import action_fingerprint, canonical_json, digest, effective_outcome, is_routine_tool, permits_thread_grant, resolve_mode, tool_descriptor
from deerflow.approvals.reviewer import REVIEW_POLICY_VERSION, review_operation
from deerflow.runtime.run_origin import origin_kind_of
from deerflow.utils.messages import get_original_user_content_text

APPROVAL_RUNTIME_KEY = "__tool_approval_runtime"


def _context(request) -> dict:
    context = getattr(request.runtime, "context", None)
    return context if isinstance(context, dict) else {}


def user_instructions(messages) -> list[str]:
    return [
        get_original_user_content_text(message.content, message.additional_kwargs)
        for message in messages
        if isinstance(message, HumanMessage) and not message.additional_kwargs.get("deerflow_producer_kind") and not message.additional_kwargs.get("untrusted_input")
    ]


def denial(request, reason: str) -> ToolMessage:
    additional_kwargs: dict[str, Any] = {}
    if request.tool_call["name"] == "task":
        # A denied delegation never ran. Stamp the subagent status contract so
        # the delegation ledger settles it as cancelled instead of leaving it
        # in_progress; the ledger never infers status from result text.
        from deerflow.subagents.status_contract import make_subagent_additional_kwargs

        additional_kwargs = make_subagent_additional_kwargs("cancelled", error=reason)
    return ToolMessage(
        content=f"The tool was not executed. {reason} Do not retry without new user authorization.",
        name=request.tool_call["name"],
        tool_call_id=request.tool_call["id"],
        status="error",
        additional_kwargs=additional_kwargs,
    )


class ToolApprovalMiddleware(AgentMiddleware):
    """Ask, Auto and Full share exact operation binding and mandatory inner guards.

    Root calls use durable LangGraph interrupts. Children keep their original
    invocation suspended through a host-owned approval bridge; they never replay
    an entire delegated task to obtain a decision.
    """

    def __init__(self, policy, *, app_config, reviewer=None, supports_resume=True, model_name=None):
        self.policy = policy.model_copy(deep=True)
        self.app_config = app_config
        self.reviewer = reviewer
        self.supports_resume = supports_resume
        self.model_name = model_name
        self.policy_digest = digest({"policy": policy.model_dump(), "reviewer_policy": REVIEW_POLICY_VERSION})

    def release_policy_parameters(self):
        return {"policy_digest": self.policy_digest}

    def before_model(self, state, runtime):
        context = getattr(runtime, "context", None) or {}
        bridge = context.get(APPROVAL_RUNTIME_KEY)
        if bridge is not None and not context.get("is_subagent"):
            bridge.set_user_messages(user_instructions(state.get("messages", [])))

    async def abefore_model(self, state, runtime):
        self.before_model(state, runtime)

    def after_model(self, state, runtime):
        last = next((message for message in reversed(state.get("messages", [])) if isinstance(message, AIMessage)), None)
        if last is None or not last.tool_calls:
            return None
        ids = [call.get("id") for call in last.tool_calls]
        if all(isinstance(call_id, str) and call_id for call_id in ids) and len(set(ids)) == len(ids):
            return None
        # Neither an interrupt nor a ToolMessage can safely address these calls.
        # Drop the whole group, including ordinary calls sharing an approval id,
        # and synchronize every provider surface before any tool can execute.
        note = "Approval could not be requested because this tool call has no usable id (missing, empty, or duplicated). The tool was not executed. Do not retry unless the user explicitly asks."
        content = [*last.content, {"type": "text", "text": note}] if isinstance(last.content, list) else f"{last.content}\n\n{note}" if last.content else note
        return {"messages": [clone_ai_message_with_tool_calls(last, [], content=content)]}

    async def aafter_model(self, state, runtime):
        return self.after_model(state, runtime)

    async def _prepare(self, request) -> dict:
        context = _context(request)
        bridge = context.get(APPROVAL_RUNTIME_KEY)
        mode = bridge.mode if bridge is not None else resolve_mode(self.policy, context)
        descriptor = tool_descriptor(request.tool)
        args = copy.deepcopy(request.tool_call["args"])
        fingerprint = action_fingerprint(descriptor, args, self.policy_digest)
        plan = {
            "request_id": f"tool_approval:{uuid4().hex}",
            "tool_call_id": request.tool_call["id"],
            "tool_name": request.tool_call["name"],
            "descriptor": descriptor,
            "args": args,
            "fingerprint": fingerprint,
            "policy_digest": self.policy_digest,
            "mode": mode,
            "owner": context.get("user_id"),
            "thread_id": context.get("thread_id"),
            "grant_allowed": permits_thread_grant(descriptor) and bridge is not None,
            "outcome": "ask",
            "reason": "Human approval is required for this operation.",
        }
        name = request.tool_call["name"]
        last_ai = next((message for message in reversed(request.state.get("messages", [])) if isinstance(message, AIMessage)), None)
        calls = last_ai.tool_calls if last_ai is not None else [request.tool_call]
        ids = [call.get("id") for call in calls]
        if (self.policy.max_actions and len(calls) > self.policy.max_actions) or len(ids) != len(set(ids)):
            return {**plan, "outcome": "deny", "reason": "Too many tool calls or duplicate tool-call identities in this turn."}
        if name in self.policy.deny_tools:
            return {**plan, "outcome": "deny", "reason": "The deployment policy denies this tool."}
        if name in self.policy.always_ask_tools:
            return {**plan, "grant_allowed": False}
        if mode == "ask" and self.policy.non_interactive == "allow" and self.supports_resume and not context.get("is_subagent"):
            interactive = resolve_run_interaction_policy({"context": context}).allows_clarification
            if not interactive or origin_kind_of(get_config().get("metadata") or {}) is not None:
                return {**plan, "outcome": "allow", "reason": "The operator explicitly allows unattended operations."}
        if mode == "full" or name in self.policy.allow_tools:
            return {**plan, "outcome": "allow", "reason": "Allowed by the selected permission mode or operator rule."}
        if name not in self.policy.tools and is_routine_tool(descriptor, request.tool):
            return {**plan, "outcome": "allow", "reason": "Trusted host read or navigation tool."}
        if not self.policy.review_unknown_tools and name not in self.policy.tools:
            return {**plan, "outcome": "allow", "reason": "The operator limits review to explicitly selected tools."}
        if bridge is not None and await bridge.has_grant(fingerprint):
            return {**plan, "outcome": "allow", "basis": "thread_grant", "reason": "Exact operation approved for this thread."}
        if mode == "auto":
            instructions = bridge.user_messages if bridge is not None else ([] if context.get("is_subagent") else user_instructions(request.state.get("messages", [])))
            action = {"tool": descriptor, "arguments": args}
            if self.reviewer is not None:
                try:
                    async with asyncio.timeout(self.policy.reviewer_timeout_seconds):
                        verdict = await self.reviewer(action, instructions)
                except Exception:
                    verdict = {"outcome": "ask", "reason": "Automatic review failed; human approval is required."}
            else:
                verdict = await review_operation(action, instructions, app_config=self.app_config, model_name=self.model_name or context.get("model_name"), usage_recorder=bridge.record_usage if bridge else None, context=context)
            if not isinstance(verdict, dict):
                verdict = {}
            plan.update(outcome=effective_outcome(verdict), reason=str(verdict.get("reason", "Human approval is required."))[:1000], review=verdict)
        return plan

    def _payload(self, plan: dict, context: dict) -> dict:
        action = {key: plan[key] for key in ("request_id", "tool_call_id", "tool_name", "args", "fingerprint", "reason")}
        action.update(args_summary=plan["args"], args_schema=plan["descriptor"]["schema"], source=plan["descriptor"]["source"], grant_allowed=plan["grant_allowed"])
        decisions = ["approve", "reject", "edit"]
        if plan["grant_allowed"]:
            decisions.append("approve_thread")
        return {
            "version": 2,
            "kind": "hitl_approval",
            "max_payload_bytes": self.policy.max_payload_bytes,
            "request_id": plan["request_id"],
            "actions": [action],
            "allowed_decisions": decisions,
            "pending_tool_call_ids": [plan["tool_call_id"]],
            "agent_id": context.get("agent_id"),
        }

    def _validate_response(self, plan, response):
        responses = response.get("responses") if isinstance(response, Mapping) else None
        if not isinstance(responses, list):
            raise ValueError("Invalid approval response.")
        matching = [item for item in responses if isinstance(item, dict) and item.get("request_id") == plan["request_id"]]
        if len(matching) != 1 or matching[0].get("tool_call_id") != plan["tool_call_id"]:
            raise ValueError("Stale or mismatched approval response.")
        response = matching[0]
        decision = response.get("option_id")
        if decision not in ("approve", "approve_thread", "edit", "reject"):
            raise ValueError("Unsupported approval decision.")
        if decision == "approve_thread" and not plan["grant_allowed"]:
            raise ValueError("This tool does not support a persistent thread grant.")
        args = response.get("args") if decision == "edit" else plan["args"]
        if not isinstance(args, dict):
            raise ValueError("Edited arguments must be a JSON object.")
        if len(canonical_json(args).encode()) > self.policy.max_payload_bytes:
            raise ValueError("Edited arguments exceed the approval size limit.")
        schema = plan["descriptor"]["schema"]
        Draft202012Validator(schema).validate(args)
        # Injected runtime fields are never editable, even when the provider's
        # public JSON schema permits additional properties.
        properties = schema.get("properties")
        if isinstance(properties, dict) and set(args) - set(properties):
            raise ValueError("Edited arguments contain unknown or injected fields.")
        return decision, args

    async def _decide(self, request, plan):
        context = _context(request)
        if plan["policy_digest"] != self.policy_digest or plan["owner"] != context.get("user_id") or plan["thread_id"] != context.get("thread_id"):
            return denial(request, "The policy or request owner changed while approval was pending.")
        if plan["fingerprint"] != action_fingerprint(tool_descriptor(request.tool), request.tool_call["args"], self.policy_digest):
            return denial(request, "The tool or its arguments changed after review.")
        bridge = context.get(APPROVAL_RUNTIME_KEY)
        if plan.get("basis") == "thread_grant" and (bridge is None or not await bridge.has_grant(plan["fingerprint"])):
            return denial(request, "The thread grant was revoked. Request fresh approval.")
        if plan["outcome"] == "deny":
            if bridge is not None:
                await bridge.record_decision(plan, "deny")
            return denial(request, plan["reason"])
        if plan["outcome"] == "allow":
            if bridge is not None:
                await bridge.record_decision(plan, "allow")
            return request
        payload = self._payload(plan, context)
        if len(canonical_json(payload).encode()) > self.policy.max_payload_bytes:
            return denial(request, "The complete approval card exceeds the size limit.")
        interactive = resolve_run_interaction_policy({"context": context}).allows_clarification
        if not interactive or origin_kind_of(get_config().get("metadata") or {}) is not None:
            return denial(request, "This run cannot collect human approval.")
        if context.get("is_subagent"):
            if bridge is None or not bridge.interactive:
                return denial(request, "No parent approval channel is available.")
            response = await bridge.wait_for_decision(plan, payload)
        elif self.supports_resume:
            response = interrupt(payload)
        else:
            return denial(request, "This runtime does not support approval resume.")
        try:
            decision, args = self._validate_response(plan, response)
        except Exception:
            return denial(request, "Invalid, stale, or schema-incompatible approval response.")
        if bridge is not None:
            await bridge.record_decision(plan, decision, arguments=args)
        if decision == "reject":
            reason = next((item.get("value", "") for item in response["responses"] if item.get("request_id") == plan["request_id"]), "")
            return denial(request, f"The user rejected the operation. {str(reason)[:2000]}")
        # The handler includes mandatory authorization and guardrail middleware;
        # it evaluates the edited arguments as well as the original ones.
        return request.override(tool_call={**request.tool_call, "args": args})

    async def awrap_tool_call(self, request, handler):
        @task(name="prepare_tool_approval")
        async def prepare():
            return await self._prepare(request)

        try:
            plan = await prepare()
            decision = await self._decide(request, plan)
        except GraphBubbleUp:
            raise
        except Exception:
            return denial(request, "The approval service is unavailable. The operation requires a fresh review.")
        return decision if isinstance(decision, ToolMessage) else await handler(decision)

    def wrap_tool_call(self, request, handler):
        @task(name="prepare_tool_approval")
        def prepare():
            return asyncio.run(self._prepare(request))

        try:
            plan = prepare().result()
            decision = asyncio.run(self._decide(request, plan))
        except GraphBubbleUp:
            raise
        except Exception:
            return denial(request, "The approval service is unavailable. The operation requires a fresh review.")
        return decision if isinstance(decision, ToolMessage) else handler(decision)
