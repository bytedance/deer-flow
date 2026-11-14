"""ACP admission reuses graph policy instances and never calls the legacy tool."""

from types import SimpleNamespace

import pytest

from deerflow.config.subagents_config import SubagentsAppConfig
from deerflow.guardrails.middleware import GuardrailMiddleware
from deerflow.guardrails.provider import GuardrailDecision
from deerflow.subagents.admission import DelegationAdmissionError, bind_delegation_admission
from deerflow.subagents.worker_backends import WorkerOperation, WorkerPlan, freeze_config


class Policy:
    name = "test-policy"

    def __init__(self, allow):
        self.allow = allow
        self.requests = []

    async def aevaluate(self, request):
        self.requests.append(request)
        return GuardrailDecision(allow=self.allow)


def plan():
    return WorkerPlan("worker", "acp", "External", 30, freeze_config({"agent": "coder", "launch": {"command": "test-acp"}}))


@pytest.mark.anyio
async def test_different_graph_policies_do_not_overwrite_shared_runtime():
    app = SimpleNamespace(guardrails=SimpleNamespace(enabled=True), authorization=SimpleNamespace(enabled=False))
    yes, no = Policy(True), Policy(False)
    first = bind_delegation_admission([GuardrailMiddleware(yes)], app)
    second = bind_delegation_admission([GuardrailMiddleware(no)], app)
    runtime = SimpleNamespace(context={"thread_id": "thread", "user_id": "owner"}, state={"messages": []}, config={})
    assert await first.approve(plan(), "do work", runtime, "call", WorkerOperation("invoke_acp_agent", {"agent": "coder", "prompt": "do work"})) == "do work"
    with pytest.raises(DelegationAdmissionError):
        await second.approve(plan(), "do work", runtime, "call", WorkerOperation("invoke_acp_agent", {"agent": "coder", "prompt": "do work"}))
    assert await first.approve(plan(), "other work", runtime, "call", WorkerOperation("invoke_acp_agent", {"agent": "coder", "prompt": "other work"})) == "other work"
    assert len(yes.requests) == 2 and len(no.requests) == 1
    assert yes.requests[0].tool_name == "invoke_acp_agent"
    assert yes.requests[0].tool_input == {"agent": "coder", "prompt": "do work"}


@pytest.mark.anyio
@pytest.mark.parametrize("layer", ["authorization", "guardrails", "hitl_approval"])
async def test_explicitly_required_missing_policy_is_fail_closed(layer):
    app = SimpleNamespace(**{layer: SimpleNamespace(enabled=True)}, subagents=SubagentsAppConfig())
    admission = bind_delegation_admission([], app)
    with pytest.raises(DelegationAdmissionError) as error:
        await admission.approve(plan(), "do work", SimpleNamespace(), "call")
    assert error.value.code == "delegation_policy_unavailable"
