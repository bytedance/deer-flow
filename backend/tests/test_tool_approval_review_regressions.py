import asyncio
import sqlite3
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from _agent_e2e_helpers import build_single_tool_call_model
from langchain.agents import create_agent
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from test_hitl_approval_api import (  # noqa: F401
    _MODEL_PATCH,
    _create_thread,
    _enable_approval,
    _fake_model,
    _register_user,
    _resume,
    _run,
    _run_body,
    _wait_for_approval,
    _wait_run_status,
    _wait_run_terminal,
    isolated_app,
    isolated_deer_flow_home,
)

from deerflow.approvals.middleware import ToolApprovalMiddleware
from deerflow.approvals.policy import tool_descriptor
from deerflow.approvals.runtime import ApprovalRuntime
from deerflow.approvals.store import ApprovalStore
from deerflow.config.app_config import AppConfig
from deerflow.config.hitl_approval_config import HitlApprovalConfig
from deerflow.runtime import RunManager, RunStatus
from deerflow.runtime.runs.manager import PersistenceRetryPolicy
from deerflow.runtime.runs.store.memory import MemoryRunStore
from deerflow.tools.sync import make_sync_tool_wrapper


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["ask", "auto", "full"])
async def test_mandatory_ask_overrides_every_permission_mode(mode):
    from test_tool_approval_runtime import graph_fixture

    reviewer = AsyncMock(side_effect=AssertionError("Mandatory ask must not invoke the reviewer"))
    graph, config, calls = graph_fixture(mode=mode, reviewer=reviewer, policy_overrides={"always_ask_tools": ["external_write"]})
    result = await graph.ainvoke({"messages": [("user", "write original")]}, config)
    assert result.get("__interrupt__") and not calls
    assert not result["__interrupt__"][0].value["actions"][0]["grant_allowed"]
    reviewer.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("context,metadata", [({"non_interactive": True}, {}), ({}, {"deerflow_origin": {"kind": "schedule"}})])
async def test_unattended_ask_never_parks_or_executes(context, metadata):
    from test_tool_approval_runtime import graph_fixture

    graph, config, calls = graph_fixture()
    result = await graph.ainvoke({"messages": [("user", "write original")]}, {**config, "metadata": metadata}, context=context)
    assert not result.get("__interrupt__") and not calls


@pytest.mark.asyncio
async def test_child_approval_deadline_rejects_without_a_human_answer():
    bridge = ApprovalRuntime(ApprovalStore(), scope=("owner", "thread", "incarnation"), run_id="run", mode="ask", timeout=0.01, record=SimpleNamespace(ownership_lost=False, abort_event=threading.Event()))
    result = await bridge.wait_for_decision({"request_id": "request", "tool_call_id": "call", "fingerprint": "operation"}, {"version": 2})
    assert result["responses"][0]["option_id"] == "reject"
    await bridge.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("oversized", [False, True])
async def test_reviewer_timeout_and_input_limit_require_human_review(monkeypatch, oversized):
    import deerflow.models
    from deerflow.approvals.reviewer import review_operation

    cfg = AppConfig(sandbox={"use": "deerflow.sandbox.local:LocalSandboxProvider"})
    cfg.hitl_approval.reviewer_timeout_seconds = 0.01
    model = SimpleNamespace(ainvoke=AsyncMock(side_effect=lambda *args, **kwargs: None))

    async def slow(*args, **kwargs):
        await asyncio.sleep(1)

    model.ainvoke = AsyncMock(side_effect=slow)
    factory = Mock(return_value=model)
    monkeypatch.setattr(deerflow.models, "create_chat_model", factory)
    action = {"input": "x" * (cfg.hitl_approval.reviewer_max_input_bytes if oversized else 1)}
    result = await review_operation(action, ["work"], app_config=cfg)
    assert result["outcome"] == "ask"
    if oversized:
        model.ainvoke.assert_not_called()


def test_full_mode_requires_explicit_operator_enablement():
    assert HitlApprovalConfig().allowed_modes == ["ask", "auto"]


@pytest.mark.asyncio
async def test_current_loop_poll_skips_checkpoint_history(monkeypatch):
    from app.gateway import deps, hitl_approval

    store = SimpleNamespace(list_by_thread=AsyncMock(return_value=[]))
    monkeypatch.setattr(deps, "get_run_store", lambda request: store)
    history = AsyncMock(side_effect=AssertionError("ordinary polling must not scan history"))
    monkeypatch.setattr(hitl_approval, "_pending_interrupts_from_checkpoint_history", history)
    snapshot = SimpleNamespace(tasks=(), metadata={"source": "loop"}, config={"configurable": {"checkpoint_id": "head"}})
    assert await hitl_approval.find_pending_interrupts(SimpleNamespace(), "thread", snapshot=snapshot, accessor=SimpleNamespace(checkpointer=object()), read_config={"configurable": {"thread_id": "thread"}}) == {}
    history.assert_not_called()


@pytest.mark.asyncio
async def test_changed_async_implementation_requires_fresh_grant():
    calls = []

    def make_tool(marker):
        ns = {"__name__": "audit.synthetic", "calls": calls}
        exec(compile(f'async def external_write(value: str) -> str:\n    """Synthetic write."""\n    calls.append({marker!r})\n    return {marker!r}\n', "audit_synthetic.py", "exec"), ns)
        coro = ns["external_write"]
        result = StructuredTool.from_function(coroutine=coro)
        result.func = make_sync_tool_wrapper(coro, result.name)
        return result

    old, new = make_tool("old"), make_tool("new")
    assert old.coroutine.__code__.co_consts != new.coroutine.__code__.co_consts
    assert tool_descriptor(old) != tool_descriptor(new)
    policy = HitlApprovalConfig(enabled=True, tools=["external_write"])
    cfg = AppConfig(sandbox={"use": "deerflow.sandbox.local:LocalSandboxProvider"}, hitl_approval=policy)
    bridge = ApprovalRuntime(ApprovalStore(), scope=("audit", "thread", "incarnation"), run_id="run", mode="ask", timeout=5, record=SimpleNamespace(ownership_lost=False, abort_event=threading.Event()))
    context = {"__tool_approval_runtime": bridge, "user_id": "audit", "thread_id": "thread"}

    def graph(tool):
        model = build_single_tool_call_model(tool_name="external_write", tool_args={"value": "original"}, tool_call_id="call")
        return create_agent(model, tools=[tool], middleware=[ToolApprovalMiddleware(policy, app_config=cfg)], checkpointer=InMemorySaver())

    config = {"configurable": {"thread_id": "thread"}}
    first = graph(old)
    paused = await first.ainvoke({"messages": [("user", "write original")]}, config, context=context)
    action = paused["__interrupt__"][0].value["actions"][0]
    await first.ainvoke(Command(resume={"responses": [{"tool_call_id": "call", "request_id": action["request_id"], "option_id": "approve_thread"}]}), config, context=context)
    result = await graph(new).ainvoke({"messages": [("user", "write original")]}, config, context=context)
    assert result.get("__interrupt__") and calls == ["old"]
    await bridge.close()


@pytest.mark.anyio
async def test_answer_approval_is_one_atomic_transition_without_followup_put():
    store = MemoryRunStore()
    manager = RunManager(store=store, persistence_retry_policy=PersistenceRetryPolicy(max_attempts=2, initial_delay=0, max_delay=0))
    paused = await manager.create_or_reject("thread", metadata={"hitl_approval": {"request_id": "approval", "pending_tool_call_ids": ["call"], "actions": [{"request_id": "approval", "tool_call_id": "call"}]}})
    await manager.set_status(paused.run_id, RunStatus.waiting_for_input)
    original_put = store.put
    store.put = AsyncMock(side_effect=sqlite3.OperationalError("database is locked"))
    answer = await manager.mark_approval_answered("thread", expected_request_ids={"call": "approval"})
    assert answer is not None
    store.put.assert_not_awaited()
    durable = await store.get(paused.run_id)
    assert paused.status == RunStatus.success and durable["status"] == "success"
    assert "hitl_approval" not in durable["metadata"]
    store.put = original_put
    assert await manager.restore_approval_answer(answer)
    assert (await store.get(paused.run_id))["status"] == "waiting_for_input"


@pytest.mark.no_auto_user
def test_state_write_rechecks_approval_inside_reservation(isolated_app):  # noqa: F811
    import asyncio
    from concurrent.futures import ThreadPoolExecutor
    from unittest.mock import patch

    from starlette.testclient import TestClient

    from app.gateway import hitl_approval

    _enable_approval()
    checked, release = threading.Event(), threading.Event()
    original = hitl_approval.reject_new_run_when_approval_pending

    async def gate(request, thread_id):
        await original(request, thread_id)
        if request.url.path.endswith("/state"):
            checked.set()
            if not await asyncio.to_thread(release.wait, 20):
                raise TimeoutError("audit state request not released")

    with patch(_MODEL_PATCH, new=_fake_model), patch.object(hitl_approval, "reject_new_run_when_approval_pending", new=gate), TestClient(isolated_app) as client:
        csrf = _register_user(client)
        tid = _create_thread(client, csrf)
        with ThreadPoolExecutor(max_workers=1) as pool:
            state = pool.submit(client.post, f"/api/threads/{tid}/state", json={"values": {"messages": []}}, headers={"X-CSRF-Token": csrf})
            try:
                assert checked.wait(20)
                created = _run(client, csrf, tid, _run_body(input={"messages": [{"role": "user", "content": "write"}]}))
                assert created.status_code == 200, created.text
                rid = created.json()["run_id"]
                approval = _wait_for_approval(client, tid)
                assert _wait_run_status(client, tid, rid, "waiting_for_input")["status"] == "waiting_for_input"
                payload = next(i["value"] for group in approval["interrupts"].values() for i in group)
                release.set()
                result = state.result(timeout=20)
                assert result.status_code == 409, result.text
                assert result.json()["detail"]["code"] == "approval_pending"
                approved = _resume(client, csrf, tid, "approve", request_id=payload["actions"][0]["request_id"])
                assert approved.status_code == 200, approved.text
                terminal = _wait_run_terminal(client, tid, approved.json()["run_id"])
                current = client.get(f"/api/threads/{tid}").json()
                assert terminal["status"] == "success"
                assert any(m.get("type") == "tool" and m.get("content") == "OK" for m in current["values"].get("messages", []))
            finally:
                release.set()
