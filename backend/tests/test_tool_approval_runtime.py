"""Drive real graph pause/resume; a card is not proof that the tool was gated."""

from unittest.mock import AsyncMock

import pytest
from _agent_e2e_helpers import build_single_tool_call_model
from langchain.agents import create_agent
from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from deerflow.approvals.middleware import ToolApprovalMiddleware
from deerflow.config.app_config import AppConfig
from deerflow.config.hitl_approval_config import HitlApprovalConfig


def graph_fixture(*, mode="ask", reviewer=None, policy_overrides=None, inner=None):
    calls = []

    @tool
    def external_write(value: str) -> str:
        """Write externally."""
        calls.append(value)
        return "written"

    policy = HitlApprovalConfig(enabled=True, tools=["external_write"], default_mode=mode, **{"allowed_modes": ["ask", "auto", "full"], **(policy_overrides or {})})
    middleware = ToolApprovalMiddleware(policy, app_config=AppConfig(sandbox={"use": "deerflow.sandbox.local:LocalSandboxProvider"}, hitl_approval=policy), reviewer=reviewer)
    model = build_single_tool_call_model(tool_name="external_write", tool_args={"value": "original"}, tool_call_id="call")
    graph = create_agent(model, tools=[external_write], middleware=[middleware, *([inner] if inner else [])], checkpointer=InMemorySaver())
    return graph, {"configurable": {"thread_id": "approval-thread"}}, calls


def response(paused, option, **extra):
    payload = paused["__interrupt__"][0].value
    action = payload["actions"][0]
    return {"responses": [{"tool_call_id": action["tool_call_id"], "request_id": action["request_id"], "option_id": option, **extra}]}


@pytest.mark.asyncio
async def test_ask_really_stops_then_executes_exact_call_once():
    graph, config, calls = graph_fixture()
    paused = await graph.ainvoke({"messages": [("user", "write original")]}, config)
    assert not calls
    await graph.ainvoke(Command(resume=response(paused, "approve")), config)
    assert calls == ["original"]


@pytest.mark.asyncio
async def test_rejection_and_stale_response_never_execute():
    for decision in ("reject", "approve"):
        graph, config, calls = graph_fixture()
        paused = await graph.ainvoke({"messages": [("user", "write original")]}, config)
        value = response(paused, decision)
        if decision == "approve":
            value["responses"][0]["request_id"] = "stale"
        result = await graph.ainvoke(Command(resume=value), config)
        assert not calls
        assert any(isinstance(m, ToolMessage) and m.status == "error" for m in result["messages"])


@pytest.mark.asyncio
async def test_auto_uses_separate_reviewer_and_never_rereviews_on_resume():
    reviewer = AsyncMock(return_value={"outcome": "ask", "risk": "high", "authorization": "explicit", "reason": "External change"})
    graph, config, calls = graph_fixture(mode="auto", reviewer=reviewer)
    paused = await graph.ainvoke({"messages": [("user", "write original")]}, config)
    assert not calls
    assert reviewer.await_count == 1
    await graph.ainvoke(Command(resume=response(paused, "approve")), config)
    assert calls == ["original"]
    assert reviewer.await_count == 1


@pytest.mark.asyncio
async def test_full_skips_reviewer_but_still_executes_inner_middleware():
    from langchain.agents.middleware import AgentMiddleware

    class MandatoryGuard(AgentMiddleware):
        async def awrap_tool_call(self, request, handler):
            return ToolMessage(content="Denied by account permission", tool_call_id=request.tool_call["id"], status="error")

    reviewer = AsyncMock(side_effect=AssertionError("Full must not invoke the reviewer"))
    graph, config, calls = graph_fixture(mode="full", reviewer=reviewer, inner=MandatoryGuard())
    await graph.ainvoke({"messages": [("user", "write original")]}, config)
    assert calls == []
    reviewer.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["ask", "auto", "full"])
async def test_operator_deny_applies_in_every_mode(mode):
    graph, config, calls = graph_fixture(mode=mode, policy_overrides={"deny_tools": ["external_write"]})
    result = await graph.ainvoke({"messages": [("user", "write original")]}, config)
    assert not calls and not result.get("__interrupt__")


@pytest.mark.asyncio
async def test_invalid_edit_and_injected_runtime_fields_never_execute():
    for args in ({"value": 99}, {"value": "edited", "runtime": {"is_admin": True}}):
        graph, config, calls = graph_fixture()
        paused = await graph.ainvoke({"messages": [("user", "write original")]}, config)
        await graph.ainvoke(Command(resume=response(paused, "edit", args=args)), config)
        assert not calls


def test_sync_graph_suspends_before_execution():
    graph, config, calls = graph_fixture()
    paused = graph.invoke({"messages": [("user", "write original")]}, config)
    assert not calls
    graph.invoke(Command(resume=response(paused, "approve")), config)
    assert calls == ["original"]


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_child_in_an_isolated_loop_waits_for_parent_decision(cancel):
    import asyncio
    import threading
    from types import SimpleNamespace

    from deerflow.approvals.runtime import ApprovalRuntime
    from deerflow.approvals.store import ApprovalStore

    store = ApprovalStore()
    scope = ("owner", "parent-thread", "incarnation")
    bridge = ApprovalRuntime(store, scope=scope, run_id="parent-run", mode="ask", timeout=5, record=SimpleNamespace(ownership_lost=False, abort_event=threading.Event()))
    bridge.set_user_messages(["write original"])
    graph, config, calls = graph_fixture()
    context = {"is_subagent": True, "__tool_approval_runtime": bridge.child(), "user_id": "owner", "thread_id": "parent-thread"}
    running = asyncio.create_task(asyncio.to_thread(lambda: asyncio.run(graph.ainvoke({"messages": [("user", "delegated work")]}, config, context=context))))
    async with asyncio.timeout(5):
        while not (rows := await store.list(scope=scope, status="pending")):
            await asyncio.sleep(0.01)
        row = rows[0]
        assert row["payload"]["transport"] == "live"
        assert calls == []
        if cancel:
            await bridge.close()
        else:
            action = row["payload"]["actions"][0]
            await store.decide(row["request_id"], {"responses": [{"request_id": action["request_id"], "tool_call_id": action["tool_call_id"], "option_id": "approve"}]}, scope=scope, fingerprint=row["fingerprint"])
        await running
    assert calls == ([] if cancel else ["original"])
    assert (await store.get(row["request_id"], scope=scope))["status"] == ("cancelled" if cancel else "consumed")
    await bridge.close()


@pytest.mark.asyncio
async def test_exact_thread_grant_is_reused_then_revoked():
    import threading
    from types import SimpleNamespace

    from deerflow.approvals.runtime import ApprovalRuntime
    from deerflow.approvals.store import ApprovalStore

    bridge = ApprovalRuntime(ApprovalStore(), scope=("owner", "thread", "incarnation"), run_id="run", mode="ask", timeout=5, record=SimpleNamespace(ownership_lost=False, abort_event=threading.Event()))
    context = {"__tool_approval_runtime": bridge, "user_id": "owner", "thread_id": "thread"}
    graph, config, calls = graph_fixture()
    paused = await graph.ainvoke({"messages": [("user", "write original")]}, config, context=context)
    assert paused["__interrupt__"][0].value["actions"][0]["grant_allowed"]
    await graph.ainvoke(Command(resume=response(paused, "approve_thread")), config, context=context)
    assert calls == ["original"]
    fresh, config, fresh_calls = graph_fixture()
    result = await fresh.ainvoke({"messages": [("user", "write original")]}, config, context=context)
    assert not result.get("__interrupt__") and fresh_calls == ["original"]
    await bridge.store.revoke(scope=bridge.scope)
    fresh, config, fresh_calls = graph_fixture()
    result = await fresh.ainvoke({"messages": [("user", "write original")]}, config, context=context)
    assert result.get("__interrupt__") and fresh_calls == []
    await bridge.close()


@pytest.mark.asyncio
async def test_edited_arguments_are_schema_checked_before_tool_execution():
    graph, config, calls = graph_fixture()
    paused = await graph.ainvoke({"messages": [("user", "write original")]}, config)
    await graph.ainvoke(Command(resume=response(paused, "edit", args={"value": "edited"})), config)
    assert calls == ["edited"]


@pytest.mark.asyncio
async def test_noninteractive_auto_uncertainty_fails_closed_without_parking():
    reviewer = AsyncMock(return_value={"outcome": "ask", "risk": "high", "authorization": "unknown", "reason": "Need authorization"})
    graph, config, calls = graph_fixture(mode="auto", reviewer=reviewer)
    result = await graph.ainvoke({"messages": [("user", "write original")]}, config, context={"non_interactive": True})
    assert not calls
    assert not result.get("__interrupt__")


@pytest.mark.asyncio
async def test_parallel_approval_uses_each_interrupt_identity_without_replaying_sibling():
    from _approval_test_helpers import StateAwareToolModel

    calls = []

    @tool
    def external_write(value: str) -> str:
        """Write externally."""
        calls.append(value)
        return "written"

    policy = HitlApprovalConfig(enabled=True)
    app = AppConfig(sandbox={"use": "deerflow.sandbox.local:LocalSandboxProvider"}, hitl_approval=policy)
    graph = create_agent(
        StateAwareToolModel(responses=[], calls=[{"name": "external_write", "args": {"value": value}, "id": value} for value in ("a", "b")]),
        tools=[external_write],
        middleware=[ToolApprovalMiddleware(policy, app_config=app)],
        checkpointer=InMemorySaver(),
    )
    config = {"configurable": {"thread_id": "parallel"}}
    paused = await graph.ainvoke({"messages": [("user", "write a and b")]}, config)
    assert len(paused["__interrupt__"]) == 2
    assert not calls
    resume = {}
    for item in paused["__interrupt__"]:
        action = item.value["actions"][0]
        resume[item.id] = {"responses": [{"request_id": action["request_id"], "tool_call_id": action["tool_call_id"], "option_id": "approve"}]}
    await graph.ainvoke(Command(resume=resume), config)
    assert sorted(calls) == ["a", "b"]


@pytest.mark.asyncio
async def test_auto_approved_parallel_sibling_is_not_reexecuted_on_human_resume():
    from _approval_test_helpers import StateAwareToolModel

    calls = []

    @tool
    def external_write(value: str) -> str:
        """Record a write."""
        calls.append(value)
        return "written"

    async def review(action, instructions):
        return {"outcome": "allow" if action["arguments"]["value"] == "a" else "ask", "risk": "medium", "authorization": "explicit", "reason": "review"}

    reviewer = AsyncMock(side_effect=review)
    policy = HitlApprovalConfig(enabled=True, default_mode="auto")
    app = AppConfig(sandbox={"use": "deerflow.sandbox.local:LocalSandboxProvider"}, hitl_approval=policy)
    model = StateAwareToolModel(responses=[], calls=[{"name": "external_write", "args": {"value": value}, "id": value} for value in ("a", "b")])
    graph = create_agent(model, tools=[external_write], middleware=[ToolApprovalMiddleware(policy, app_config=app, reviewer=reviewer)], checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "mixed"}}
    paused = await graph.ainvoke({"messages": [("user", "write both")]}, config)
    assert calls == ["a"]
    assert len(paused["__interrupt__"]) == 1
    await graph.ainvoke(Command(resume=response(paused, "approve")), config)
    assert calls == ["a", "b"]
    assert reviewer.await_count == 2
