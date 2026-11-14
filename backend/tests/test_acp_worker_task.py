"""Real task/runtime and installed ACP SDK driven by a local protocol process."""

import asyncio
import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage

from deerflow.config.acp_config import ACPAgentConfig
from deerflow.config.app_config import AppConfig
from deerflow.config.subagents_config import SubagentsAppConfig
from deerflow.extensions.registry import ExtensionRegistry
from deerflow.subagents.runtime import SubagentRuntime

ACP_PROCESS = r"""
import json, sys
def send(value):
    print(json.dumps(value), flush=True)
for line in sys.stdin:
    request = json.loads(line)
    method = request.get("method")
    if method == "initialize":
        result = {"protocolVersion": 1, "agentCapabilities": {}}
    elif method == "session/new":
        assert request["params"]["mcpServers"] == []
        result = {"sessionId": "local"}
    elif method == "session/prompt":
        if sys.argv[2]:
            send({"jsonrpc": "2.0", "method": "session/update", "params": {"sessionId": "local", "update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": sys.argv[2]}}}})
        result = {"stopReason": sys.argv[1]}
    else:
        continue
    send({"jsonrpc": "2.0", "id": request["id"], "result": result})
"""


@pytest.fixture
def worker_setup(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "examples/deerflow-extension-acp-workers"))
    from deerflow_extension_acp_workers import install

    registry = ExtensionRegistry()
    with registry.attributed_to("acp-workers"):
        install(registry, {})
    from deerflow.subagents import registry as catalog

    monkeypatch.setattr(catalog, "_managed_definitions", lambda **kwargs: ())
    script = tmp_path / "acp_process.py"
    script.write_text(ACP_PROCESS, encoding="utf-8")
    task_module = importlib.import_module("deerflow.tools.builtins.task_tool")
    events = []
    monkeypatch.setattr(task_module, "get_stream_writer", lambda: lambda event: None)

    async def emit(event, **kwargs):
        events.append(event)

    monkeypatch.setattr(task_module, "aemit_custom_event", emit)
    return SimpleNamespace(script=script, task_module=task_module, events=events, extensions=registry.build(), root=tmp_path)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "reason,text,status,cap",
    [
        ("end_turn", "Error: legitimate report", "completed", None),
        ("end_turn", "", "completed", None),
        ("refusal", "refused", "failed", None),
        ("max_tokens", "partial", "completed", "backend_capped"),
        ("max_turn_requests", "", "failed", "backend_capped"),
        ("cancelled", "", "cancelled", None),
    ],
)
async def test_task_drives_real_acp_process(worker_setup, monkeypatch, reason, text, status, cap):
    probe = worker_setup
    app = AppConfig(
        models=[],
        sandbox={"use": "deerflow.sandbox.local:LocalSandboxProvider"},
        acp_agents={"coder": ACPAgentConfig(command=sys.executable, args=[str(probe.script), reason, text], description="Local", timeout_seconds=20)},
        subagents=SubagentsAppConfig(workers={"external": {"backend": "acp", "description": "Local coder", "config": {"agent": "coder"}}}),
    )
    runtime = SubagentRuntime.from_app_config(app, extensions=probe.extensions, workspace_resolver=lambda thread, user, execution: probe.root / execution)
    task = probe.task_module.bind_task_tool(runtime.execution_capacity, app_config=app, extensions=probe.extensions, workspace_resolver=runtime.workspace_resolver)
    parent = SimpleNamespace(context={"thread_id": "thread", "run_id": "run"}, config={"metadata": {}}, state={"messages": [AIMessage(id="dispatch", content="", tool_calls=[{"name": "task", "id": "call", "args": {}}])]})
    monkeypatch.setattr(probe.task_module, "check_acceptance_criteria", lambda *args, **kwargs: pytest.fail("ACP cannot read parent files"))
    command = await task.coroutine(runtime=parent, prompt="Do work", subagent_type="external", tool_call_id="call", acceptance_criteria=["file:../outputs/result.md exists"])
    message = command.update["messages"][0]
    meta = message.additional_kwargs
    assert meta["subagent_status"] == status
    assert meta.get("subagent_stop_reason") == cap
    assert meta["subagent_executor"] == "acp"
    assert meta["subagent_dispatch_id"] == "dispatch"
    assert meta["subagent_execution_id"]
    assert "subagent_model_name" not in meta and "subagent_token_usage" not in meta
    assert "subagent_tool_receipts" not in meta
    if status == "completed":
        assert all(not leaf["checked"] for leaf in meta["subagent_acceptance_verdict"]["leaves"])
    else:
        assert "subagent_acceptance_verdict" not in meta
    assert all(event["execution_id"] == meta["subagent_execution_id"] for event in probe.events)
    from deerflow.subagents.execution import get_background_task_result

    holder = get_background_task_result(meta["subagent_execution_id"])
    if holder is not None:
        assert await asyncio.to_thread(holder.execution_done_event.wait, 10)
    assert runtime.execution_capacity.snapshot().running == 0


@pytest.mark.anyio
async def test_sdk_graphs_share_runtime_but_keep_distinct_admission(worker_setup, monkeypatch):
    from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
    from langchain_core.messages import HumanMessage, ToolMessage

    from deerflow.agents.factory import create_deerflow_agent
    from deerflow.agents.features import RuntimeFeatures
    from deerflow.guardrails.middleware import GuardrailMiddleware
    from deerflow.guardrails.provider import GuardrailDecision

    class Model(FakeMessagesListChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

    class Policy:
        name = "graph-local"

        def __init__(self, allow):
            self.allow = allow

        async def aevaluate(self, request):
            return GuardrailDecision(allow=request.tool_name == "task" or self.allow)

    probe = worker_setup
    app = AppConfig(
        sandbox={"use": "deerflow.sandbox.local:LocalSandboxProvider"},
        guardrails={"enabled": True},
        acp_agents={"coder": ACPAgentConfig(command=sys.executable, args=[str(probe.script), "end_turn", "from external"], description="Test", timeout_seconds=20)},
        subagents={"workers": {"external": {"backend": "acp", "description": "External", "config": {"agent": "coder"}}}},
    )
    runtime = SubagentRuntime.from_app_config(app, extensions=probe.extensions, workspace_resolver=lambda *args: probe.root / args[-1])

    def graph(allow):
        model = Model(responses=[AIMessage(id="dispatch", content="", tool_calls=[{"name": "task", "id": "same", "args": {"prompt": "work", "subagent_type": "external"}}]), AIMessage(content="Done")])
        return create_deerflow_agent(model, features=RuntimeFeatures(sandbox=False, subagent=True, guardrail=GuardrailMiddleware(Policy(allow))), subagent_runtime=runtime)

    yes, no = graph(True), graph(False)
    # Pure SDK assembly and execution must stay on this caller's config.
    monkeypatch.setattr(probe.task_module, "get_app_config", lambda: pytest.fail("SDK read global config"))
    for agent, expected in ((yes, "completed"), (no, "failed"), (yes, "completed")):
        state = await agent.ainvoke({"messages": [HumanMessage(content="Delegate work")]}, context={"thread_id": "thread", "run_id": "run"})
        result = next(message for message in state["messages"] if isinstance(message, ToolMessage) and message.name == "task")
        assert result.additional_kwargs["subagent_status"] == expected
    assert len({event["execution_id"] for event in probe.events}) == 2


@pytest.mark.anyio
@pytest.mark.parametrize("action", ["edit", "edit_denied", "change_target", "steer"])
async def test_live_approval_keeps_plan_and_rechecks_edits(worker_setup, monkeypatch, action):
    import threading

    from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
    from langchain_core.messages import HumanMessage, ToolMessage

    from deerflow.agents.factory import create_deerflow_agent
    from deerflow.agents.features import RuntimeFeatures
    from deerflow.approvals.middleware import ToolApprovalMiddleware
    from deerflow.approvals.runtime import ApprovalRuntime
    from deerflow.approvals.store import ApprovalStore
    from deerflow.guardrails.middleware import GuardrailMiddleware
    from deerflow.guardrails.provider import GuardrailDecision
    from deerflow.runtime.runs.input_control import ChildInputGate

    class Model(FakeMessagesListChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

    created = asyncio.Event()

    class Store(ApprovalStore):
        async def create(self, row):
            await super().create(row)
            if row["kind"] == "live":
                created.set()

    seen = []

    class Policy:
        name = "edit-policy"

        async def aevaluate(self, request):
            seen.append(request.tool_input)
            return GuardrailDecision(allow=request.tool_input.get("prompt") != "denied edit")

    probe = worker_setup
    app = AppConfig(
        sandbox={"use": "deerflow.sandbox.local:LocalSandboxProvider"},
        hitl_approval={"enabled": True, "default_mode": "ask"},
        acp_agents={"coder": ACPAgentConfig(command=sys.executable, args=[str(probe.script), "end_turn", "approved output"], description="Test", timeout_seconds=20)},
        subagents={"workers": {"external": {"backend": "acp", "description": "External", "config": {"agent": "coder"}}}},
    )
    runtime = SubagentRuntime.from_app_config(app, extensions=probe.extensions, workspace_resolver=lambda *args: probe.root / args[-1])
    store = Store()
    bridge = ApprovalRuntime(store, scope=("owner", "thread", "incarnation"), run_id="run", mode="ask", timeout=15, record=SimpleNamespace(ownership_lost=False, abort_event=threading.Event()))
    model = Model(responses=[AIMessage(id="dispatch", content="", tool_calls=[{"name": "task", "id": "call", "args": {"prompt": "original", "subagent_type": "external"}}]), AIMessage(content="Done")])
    graph = create_deerflow_agent(
        model, features=RuntimeFeatures(subagent=True, sandbox=False, guardrail=GuardrailMiddleware(Policy())), subagent_runtime=runtime, extra_middleware=[ToolApprovalMiddleware(app.hitl_approval, app_config=app)]
    )
    gate = ChildInputGate()
    control = SimpleNamespace(child=lambda call: gate, bind_execution=lambda *args: None)
    # Keep the real task/admission path, substituting only the run input source.
    monkeypatch.setattr("deerflow.runtime.runs.input_control.run_input_control", lambda context: control)
    running = asyncio.create_task(graph.ainvoke({"messages": [HumanMessage(content="Delegate this work")]}, context={"thread_id": "thread", "run_id": "run", "user_id": "owner", "__tool_approval_runtime": bridge}))
    try:
        await asyncio.wait_for(created.wait(), timeout=10)
        row = next(row for row in store.rows.values() if row["kind"] == "live")
        assert row["payload"]["actions"][0]["tool_name"] == "invoke_acp_agent"
        assert not running.done()
        # A pending decision cannot re-read a changed launch configuration.
        app.acp_agents["coder"].command = "must-not-be-spawned"
        if action == "steer":
            gate.mark_steered()
            gate.release("continue")
        else:
            args = {"agent": "other" if action == "change_target" else "coder", "prompt": "denied edit" if action == "edit_denied" else "approved edit"}
            response = {"responses": [{"request_id": row["request_id"], "tool_call_id": "call", "option_id": "edit", "args": args}]}
            await store.decide(row["request_id"], response, scope=bridge.scope, fingerprint=row["fingerprint"])
        state = await asyncio.wait_for(running, timeout=15)
        message = next(m for m in state["messages"] if isinstance(m, ToolMessage) and m.name == "task")
        assert message.additional_kwargs["subagent_status"] == ("completed" if action == "edit" else "cancelled" if action == "steer" else "failed")
        if action == "edit":
            assert any(item.get("prompt") == "approved edit" for item in seen)
            assert probe.events
        else:
            assert not probe.events
    finally:
        if not running.done():
            running.cancel()
        await asyncio.gather(running, return_exceptions=True)
        await bridge.close()


@pytest.mark.anyio
async def test_one_parent_graph_dispatches_native_and_acp(worker_setup, monkeypatch):
    from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
    from langchain_core.messages import HumanMessage, ToolMessage

    from deerflow.agents.factory import create_deerflow_agent
    from deerflow.agents.features import RuntimeFeatures
    from deerflow.config import paths as paths_module
    from deerflow.subagents.execution import get_background_task_result

    class Model(FakeMessagesListChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

    probe = worker_setup
    monkeypatch.setenv("DEER_FLOW_HOME", str(probe.root))
    monkeypatch.setattr(paths_module, "_paths", None)
    extensions_file = probe.root / "extensions.json"
    extensions_file.write_text('{"mcpServers": {}, "skills": {}}', encoding="utf-8")
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions_file))
    # Remove conftest's import-cycle stub; every task uses the production native
    # executor. The only execution double is the external model boundary.
    import deerflow.subagents as subagents_package

    monkeypatch.setattr(subagents_package, "executor", getattr(subagents_package, "executor", None), raising=False)
    monkeypatch.delitem(sys.modules, "deerflow.subagents.executor", raising=False)
    native_module = importlib.import_module("deerflow.subagents.executor")
    monkeypatch.setattr(probe.task_module, "SubagentExecutor", native_module.SubagentExecutor)
    native_calls = []

    def model_factory(**kwargs):
        native_calls.append(kwargs["name"])
        return Model(responses=[AIMessage(content="Native completed its own work")])

    monkeypatch.setattr(native_module, "create_chat_model", model_factory)
    app = AppConfig(
        models=[{"name": "native-test", "use": "langchain_openai:ChatOpenAI", "model": "offline"}],
        sandbox={"use": "deerflow.sandbox.local:LocalSandboxProvider"},
        acp_agents={"coder": ACPAgentConfig(command=sys.executable, args=[str(probe.script), "end_turn", "External completed independent work"], description="Test", timeout_seconds=20)},
        subagents={"workers": {"external": {"backend": "acp", "description": "External", "config": {"agent": "coder"}}}},
    )
    runtime = SubagentRuntime.from_app_config(app, extensions=probe.extensions, workspace_resolver=lambda *args: probe.root / args[-1])
    parent = Model(
        responses=[
            AIMessage(
                id="mixed-dispatch",
                content="",
                tool_calls=[
                    {"name": "task", "id": "native-call", "args": {"prompt": "Native work", "subagent_type": "general-purpose"}},
                    {"name": "task", "id": "acp-call", "args": {"prompt": "External work", "subagent_type": "external"}},
                ],
            ),
            AIMessage(content="Combined"),
        ]
    )
    graph = create_deerflow_agent(parent, features=RuntimeFeatures(sandbox=False, subagent=True), subagent_runtime=runtime)
    result = await graph.ainvoke({"messages": [HumanMessage(content="Delegate two independent tasks")]}, config={"metadata": {"model_name": "native-test", "available_skills": []}}, context={"thread_id": "thread", "run_id": "run"})
    messages = [message for message in result["messages"] if isinstance(message, ToolMessage) and message.name == "task"]
    assert len(messages) == 2
    assert all(message.additional_kwargs["subagent_status"] == "completed" for message in messages)
    assert {message.additional_kwargs["subagent_executor"] for message in messages} == {"native", "acp"}
    identities = {message.additional_kwargs["subagent_execution_id"] for message in messages}
    assert len(identities) == 2 and native_calls == ["native-test"]
    for identifier in identities:
        holder = get_background_task_result(identifier)
        if holder is not None:
            assert await asyncio.to_thread(holder.execution_done_event.wait, 10)
    assert runtime.execution_capacity.snapshot().running == 0
