"""Graph-bound policy checks for external delegation without invoking a tool."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, is_dataclass, replace
from types import SimpleNamespace
from typing import Any

from langchain_core.tools import StructuredTool
from langgraph.prebuilt.tool_node import ToolCallRequest

from deerflow.subagents.worker_backends import WorkerOperation, WorkerPlan


class DelegationAdmissionError(ValueError):
    def __init__(self, message: str, code: str = "delegation_denied"):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ApprovedDelegation:
    prompt: str


@dataclass(frozen=True)
class DelegationAdmission:
    guards: tuple[Any, ...]
    approval: Any | None
    unavailable: bool = False

    async def approve(self, plan: WorkerPlan, prompt: str, runtime: Any, call_id: str, operation: WorkerOperation | None = None) -> str:
        if self.unavailable:
            raise DelegationAdmissionError("The graph does not provide the configured delegation policy layers.", "delegation_policy_unavailable")
        if operation is None:
            if self.guards or self.approval is not None:
                raise DelegationAdmissionError("The worker does not declare a policy operation.", "delegation_policy_unavailable")
            return prompt
        if not isinstance(operation, WorkerOperation) or operation.arguments.get(operation.prompt_argument) != prompt:
            raise DelegationAdmissionError("Invalid worker policy operation.", "invalid_worker_config")

        async def plan_only(**kwargs):
            raise RuntimeError("Admission tools cannot execute")

        # The target is immutable and the approval fingerprint includes the
        # captured launch configuration. Only prompt is editable.
        def json_config(value):
            if hasattr(value, "items"):
                return {key: json_config(item) for key, item in value.items()}
            if isinstance(value, tuple):
                return [json_config(item) for item in value]
            return value

        binding = hashlib.sha256(json.dumps(json_config(plan.config), sort_keys=True).encode()).hexdigest()
        arguments = json_config(operation.arguments)
        properties = {key: {"const": value} for key, value in arguments.items()}
        properties[operation.prompt_argument] = {"type": "string"}
        tool = StructuredTool.from_function(
            name=operation.name,
            description=operation.description,
            coroutine=plan_only,
            args_schema={"type": "object", "properties": properties, "required": list(arguments), "additionalProperties": False},
            metadata={"deerflow_approval_binding": binding},
        )
        context = dict(getattr(runtime, "context", None) or {})
        bridge = context.get("__tool_approval_runtime")
        child = getattr(bridge, "child", None)
        if callable(child):
            context["__tool_approval_runtime"] = child()
        context["is_subagent"] = True
        policy_runtime = replace(runtime, context=context) if is_dataclass(runtime) else SimpleNamespace(context=context, state=runtime.state, config=runtime.config)
        request = ToolCallRequest(tool_call={"name": operation.name, "id": call_id, "args": arguments, "type": "tool_call"}, tool=tool, state=runtime.state, runtime=policy_runtime)

        async def continuation(checked):
            args = checked.tool_call["args"]
            prompt_key = operation.prompt_argument
            if set(args) != set(arguments) or any(args[key] != value for key, value in arguments.items() if key != prompt_key) or not isinstance(args[prompt_key], str):
                raise DelegationAdmissionError("Approval may edit only the delegated prompt.")
            return ApprovedDelegation(args[prompt_key])

        def guarded(handler):
            for guard in reversed(self.guards):
                inner = handler

                async def wrapped(req, guard=guard, inner=inner):
                    return await guard.awrap_tool_call(req, inner)

                handler = wrapped
            return handler

        # Check the original operation before approval and edited arguments
        # again afterwards. Receipt/progress wrappers are deliberately absent.
        async def approval(req):
            if self.approval is None:
                return await continuation(req)
            return await self.approval.awrap_tool_call(req, guarded(continuation))

        result = await guarded(approval)(request)
        if not isinstance(result, ApprovedDelegation):
            raise DelegationAdmissionError(str(getattr(result, "content", "External delegation was denied")))
        return result.prompt


def bind_delegation_admission(middlewares: list, app_config: Any | None) -> DelegationAdmission:
    """Capture the actual graph instances, never create a policy provider."""
    from deerflow.approvals.middleware import ToolApprovalMiddleware
    from deerflow.authz.adapter import GuardrailAuthorizationAdapter
    from deerflow.guardrails.middleware import GuardrailMiddleware

    guards = tuple(mw for mw in middlewares if isinstance(mw, GuardrailMiddleware))
    approval = next((mw for mw in middlewares if isinstance(mw, ToolApprovalMiddleware)), None)
    authz = any(isinstance(mw.provider, GuardrailAuthorizationAdapter) for mw in guards)
    guardrail = any(not isinstance(mw.provider, GuardrailAuthorizationAdapter) for mw in guards)
    missing = any(getattr(getattr(app_config, field, None), "enabled", False) and not present for field, present in (("authorization", authz), ("guardrails", guardrail), ("hitl_approval", approval is not None)))
    return DelegationAdmission(guards, approval, missing)
