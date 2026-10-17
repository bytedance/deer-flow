"""Script workflows through the public extension loader and an isolated JS worker."""

import asyncio
import json
import os
from pathlib import Path

import pytest
import pytest_asyncio
from deerflow_extension_api import AgentRun, AgentRunError, ExtensionPrincipal
from deerflow_extension_api.plugins import ActionContext
from test_extension_agent_runs import host as _host_fixture
from test_extension_agent_runs import runtime as _runtime_fixture

from deerflow.extensions.loader import ExtensionSpec, load_extensions

pytestmark = pytest.mark.skipif(os.name != "posix", reason="Workflow worker execution requires POSIX")

ROOT = Path(__file__).resolve().parents[2]


class Runs:
    def __init__(self):
        self.threads = {}
        self.runs = {}
        self.starts = []
        self.active = 0
        self.peak = 0
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.admission = asyncio.Event()
        self.return_admission = asyncio.Event()
        self.hold_admission = False
        self.jobs = []
        self.denied = False

    revision = "initial"

    async def configuration_evidence(self, *, thread_id, run_id):
        return {"run_id": run_id, "thread_id": thread_id, "source": "host_assembly", "version": "synthetic-assembly", "model": "test-model"}

    async def read_artifact(self, *, thread_id, path):
        return self.file_content

    file_content = b"original file"

    async def configuration_revision(self, *, assistant_ids):
        if self.denied:
            raise AgentRunError(403, "revoked")
        return self.revision

    async def create_thread(self, *, assistant_id, thread_id, metadata):
        if self.denied:
            raise AgentRunError(403, "revoked")
        self.threads.setdefault(
            thread_id,
            {
                "values": {"messages": []},
                "next": [],
                "interrupts": [],
                "assistant": assistant_id,
            },
        )
        return thread_id

    async def start(self, *, thread_id, input, idempotency_key):
        if self.denied:
            raise AgentRunError(403, "revoked")
        if idempotency_key in self.runs:
            return self.runs[idempotency_key]
        run = AgentRun(thread_id, idempotency_key, "running", self.threads[thread_id]["assistant"])
        self.runs[run.run_id] = run
        self.starts.append((thread_id, input, idempotency_key))
        self.threads[thread_id]["values"]["messages"].extend(input["messages"])
        self.jobs.append(asyncio.create_task(self.answer(run, input)))
        self.admission.set()
        if self.hold_admission:
            await self.return_admission.wait()
        return run

    async def answer(self, run, input):
        task = json.loads(input["messages"][0]["content"])
        self.active += 1
        self.peak = max(self.peak, self.active)
        self.entered.set()
        try:
            if task == "blocked":
                await self.release.wait()
            else:
                await asyncio.sleep(0.02)
            if self.runs[run.run_id].status != "running":
                return
            state = self.threads[run.thread_id]
            if task == "interrupt":
                state["next"] = ["tools"]
                state["interrupts"] = [{"value": "Approve?"}]
            elif task == "clarification":
                state["values"]["messages"].append(
                    {
                        "type": "tool",
                        "artifact": {
                            "human_input": {
                                "kind": "human_input_request",
                                "version": 2,
                                "request_id": "req",
                                "source": "ask_clarification",
                                "question": "Confirm?",
                            }
                        },
                    }
                )
            else:
                state["values"]["messages"].append({"type": "ai", "content": json.dumps({"echo": task})})
            self.runs[run.run_id] = AgentRun(run.thread_id, run.run_id, "error" if task == "fail" else "success")
        finally:
            self.active -= 1

    async def get(self, *, thread_id, run_id):
        if self.denied:
            raise AgentRunError(403, "revoked")
        return self.runs[run_id]

    async def wait(self, *, thread_id, run_id, timeout=60):
        async with asyncio.timeout(timeout):
            while (await self.get(thread_id=thread_id, run_id=run_id)).status == "running":
                await asyncio.sleep(0.002)
        return await self.get(thread_id=thread_id, run_id=run_id)

    async def get_state(self, *, thread_id):
        return self.threads[thread_id]

    async def cancel(self, *, thread_id, run_id):
        self.runs[run_id] = AgentRun(thread_id, run_id, "interrupted")
        self.release.set()

    async def close(self):
        self.release.set()
        self.return_admission.set()
        await asyncio.gather(*self.jobs, return_exceptions=True)


@pytest_asyncio.fixture
async def plugin(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "examples/deerflow-extension-workflows"))
    loaded, diagnostics = await asyncio.to_thread(
        load_extensions,
        [
            ExtensionSpec(
                use="deerflow_extension_workflows:install",
                config={
                    "enabled": True,
                    "storage_path": str(tmp_path / "workflows.sqlite"),
                    "agents": ["lead_agent", "reviewer"],
                    "max_calls": 8,
                    "concurrency": 2,
                    "timeout_seconds": 5,
                },
            )
        ],
    )
    assert not diagnostics
    ((_, declaration),) = loaded.plugins
    actions = {a.name: a.handler for a in declaration.backend}
    service = actions["launch"].__self__
    await service.start(None)
    runs = Runs()
    yield loaded, actions, service, runs
    await service.stop()
    await runs.close()


def context(runs, owner="alice"):
    return ActionContext(ExtensionPrincipal(owner), {"enabled": True}, agent_runs=runs)


async def launch(plugin, script, **extra):
    _, actions, _, runs = plugin
    return await actions["launch"]({"request_id": "test", "script": script, "args": {}, **extra}, context(runs))


async def done(plugin, run_id):
    _, actions, service, runs = plugin
    await asyncio.wait_for(service.wait_idle(run_id), 10)
    return await actions["get"]({"run_id": run_id}, context(runs))


@pytest.mark.asyncio
async def test_sequential_parallel_branch_loop_structured_results(plugin):
    result = await launch(
        plugin,
        """
      const a = await agent({stepId:'a',agentRef:'reviewer',task:args.product});
      const b = await parallel([0,1,2,3].map(i => () => agent({stepId:'p'+i,agentRef:'lead_agent',task:{i,a:a.output}})));
      const c=[]; if(b.length===4) for(let i=0;i<2;i++) c.push(await agent({stepId:'loop'+i,agentRef:'lead_agent',task:b[i].output}));
      log('Checks finished'); return {a:a.output,b:b.map(x=>x.output),c};
    """,
        args={"product": "synthetic"},
    )
    final = await done(plugin, result["run_id"])
    assert final["status"] == "completed", final
    assert final["result"]["a"] == {"echo": "synthetic"}
    assert [x["echo"]["i"] for x in final["result"]["b"]] == [0, 1, 2, 3]
    assert plugin[3].peak == 2
    assert len(final["steps"]) == 7
    assert all(s["attempt"] == 1 and s["thread_id"] and s["run_id"] for s in final["steps"])
    assert final["script_hash"] and final["args_hash"]
    assert final["logs"] == ["Checks finished"]


@pytest.mark.asyncio
async def test_background_return_idempotency_and_owner_scope(plugin):
    script = "return await agent({stepId:'a',agentRef:'lead_agent',task:'blocked'});"
    first = await launch(plugin, script)
    await asyncio.wait_for(plugin[3].entered.wait(), 5)
    retry = await launch(plugin, script)
    assert retry["run_id"] == first["run_id"] and len(plugin[3].starts) == 1
    with pytest.raises(ValueError):
        await launch(plugin, "return 2;")
    for action in ("get", "cancel", "delete"):
        with pytest.raises(ValueError):
            await plugin[1][action]({"run_id": first["run_id"]}, context(plugin[3], "bob"))
    assert (await plugin[1]["list"]({}, context(plugin[3], "bob")))["runs"] == []
    await plugin[1]["cancel"]({"run_id": first["run_id"]}, context(plugin[3]))
    assert (await done(plugin, first["run_id"]))["status"] == "cancelled"


@pytest.mark.asyncio
async def test_cancel_during_admission_tracks_then_cancels_child(plugin):
    plugin[3].hold_admission = True
    result = await launch(plugin, "return await agent({stepId:'a',agentRef:'lead_agent',task:'blocked'});")
    await asyncio.wait_for(plugin[3].admission.wait(), 5)
    await plugin[1]["cancel"]({"run_id": result["run_id"]}, context(plugin[3]))
    # Response is deliberately delayed until after cancellation was requested.
    plugin[3].return_admission.set()
    final = await done(plugin, result["run_id"])
    assert final["status"] == "cancelled"
    assert final["steps"][0]["run_id"]
    assert all(r.status == "interrupted" for r in plugin[3].runs.values())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "script",
    [
        "return process.env;",
        "return agent.constructor('return process')();",
        "return require('fs');",
        "return fetch('https://example.com');",
        "while(true) {}",
        "const x=[]; while(true) x.push('x'.repeat(100000));",
        "return await new Promise(()=>{});",
        "return await agent({stepId:'x',agentRef:'forbidden',task:1});",
        "for(let i=0;i<9;i++) await agent({stepId:'x'+i,agentRef:'lead_agent',task:i});",
        "await agent({stepId:'x',agentRef:'lead_agent',task:1}); return await agent({stepId:'x',agentRef:'lead_agent',task:2});",
    ],
)
async def test_limits_and_ambient_capabilities_fail_closed(plugin, script):
    result = await launch(plugin, script)
    final = await done(plugin, result["run_id"])
    assert final["status"] == "failed", final
    assert len(plugin[3].starts) <= 8
    assert not plugin[2].processes


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "task,status",
    [
        ("interrupt", "waiting_input"),
        ("clarification", "waiting_input"),
        ("fail", "failed"),
    ],
)
async def test_interrupt_and_failure_do_not_dispatch_downstream(plugin, task, status):
    result = await launch(
        plugin,
        "await agent({stepId:'a',agentRef:'lead_agent',task:args.task}); return await agent({stepId:'b',agentRef:'lead_agent',task:2});",
        args={"task": task},
    )
    final = await done(plugin, result["run_id"])
    assert final["status"] == status
    assert len(plugin[3].starts) == 1


@pytest.mark.asyncio
async def test_result_attribution_refuses_external_turn(plugin):
    original = plugin[3].get_state

    async def advanced(**kwargs):
        state = await original(**kwargs)
        state["values"]["messages"].extend([{"type": "human", "content": "later"}, {"type": "ai", "content": "wrong"}])
        return state

    plugin[3].get_state = advanced
    result = await launch(plugin, "return await agent({stepId:'a',agentRef:'lead_agent',task:1});")
    final = await done(plugin, result["run_id"])
    assert final["status"] == "failed" and final["steps"][0]["status"] == "result_conflict"


@pytest.mark.asyncio
async def test_restart_retains_records_without_replaying(plugin):
    result = await launch(plugin, "return 42;")
    final = await done(plugin, result["run_id"])
    await plugin[2].stop()
    await plugin[2].start(None)
    again = await plugin[1]["get"]({"run_id": result["run_id"]}, context(plugin[3]))
    assert again["result"] == final["result"] == 42
    assert not plugin[3].starts


@pytest.mark.asyncio
async def test_uncertain_admission_is_retained_without_automatic_retry(plugin):
    original = plugin[3].start

    async def uncertain(**kwargs):
        await original(**kwargs)
        raise TimeoutError("Response lost after admission")

    plugin[3].start = uncertain
    script = "return await agent({stepId:'a',agentRef:'lead_agent',task:'blocked'});"
    result = await launch(plugin, script)
    final = await done(plugin, result["run_id"])
    assert final["status"] == "needs_reconciliation"
    assert final["steps"][0]["thread_id"] and final["steps"][0]["run_id"] is None
    assert len(plugin[3].starts) == 1
    assert final["steps"][0]["error"] == "Admission timed out; inspect the stable child thread, do not replay"
    retry = await launch(plugin, script)
    assert retry["run_id"] == result["run_id"] and len(plugin[3].starts) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "script",
    [
        "for(let i=0;i<21;i++)log('progress');return 1;",
        "return 'x'.repeat(50000);",
        "agent({stepId:'a',agentRef:'lead_agent',task:'blocked'}); return 'early';",
    ],
)
async def test_log_output_and_detached_call_limits(plugin, script):
    result = await launch(plugin, script)
    final = await done(plugin, result["run_id"])
    assert final["status"] == "failed"
    assert not plugin[2].processes
    assert all(r.status != "running" for r in plugin[3].runs.values())


@pytest.mark.asyncio
async def test_service_shutdown_drains_children_and_worker(plugin):
    result = await launch(plugin, "return await agent({stepId:'a',agentRef:'lead_agent',task:'blocked'});")
    await asyncio.wait_for(plugin[3].entered.wait(), 5)
    await plugin[2].stop()
    assert not plugin[2].processes and not plugin[2].entries
    assert all(r.status == "interrupted" for r in plugin[3].runs.values())
    await plugin[2].start(None)
    final = await plugin[1]["get"]({"run_id": result["run_id"]}, context(plugin[3]))
    assert final["status"] == "cancelled"


@pytest.mark.asyncio
async def test_process_lock_prevents_multiple_services_recovering_live_work(plugin):
    from deerflow_extension_workflows.service import Workflows

    other = Workflows(plugin[2].config)
    with pytest.raises(BlockingIOError):
        await other.start(None)
    assert other.available is False


@pytest.mark.asyncio
async def test_disabled_plugin_has_no_service_or_visible_tools(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "examples/deerflow-extension-workflows"))
    from deerflow.extensions.plugin_tools import build_plugin_tools

    loaded, diagnostics = load_extensions([ExtensionSpec(use="deerflow_extension_workflows:install", config={"enabled": False})])
    assert not diagnostics and not loaded.services and not build_plugin_tools(loaded)


@pytest.mark.asyncio
async def test_operator_configuration_rejects_unsupported_budget_and_limits(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "examples/deerflow-extension-workflows"))
    for extra in (
        {"max_cost_usd": 1},
        {"concurrency": 100},
        {"max_calls": True},
        {"agents": ["lead_agent", "lead_agent"]},
    ):
        loaded, diagnostics = load_extensions(
            [
                ExtensionSpec(
                    use="deerflow_extension_workflows:install",
                    config={
                        "enabled": True,
                        "storage_path": str(tmp_path / "runs.sqlite"),
                        "agents": ["lead_agent"],
                        **extra,
                    },
                )
            ]
        )
        assert diagnostics and not loaded.plugins and not loaded.services


@pytest.mark.asyncio
async def test_real_gateway_lifecycle_bridge(plugin, gateway_runtime):
    runs, *_ = gateway_runtime
    result = await plugin[1]["launch"](
        {
            "request_id": "real",
            "script": "const a=await agent({stepId:'a',agentRef:'lead_agent',task:'first'});return await agent({stepId:'b',agentRef:'lead_agent',task:a.output});",
            "args": {},
        },
        context(runs),
    )
    await plugin[2].wait_idle(result["run_id"])
    final = await plugin[1]["get"]({"run_id": result["run_id"]}, context(runs))
    assert final["status"] == "completed", final
    assert len(final["steps"]) == 2
    for step in final["steps"]:
        assert (await runs.get(thread_id=step["thread_id"], run_id=step["run_id"])).status == "success"


host = _host_fixture
gateway_runtime = _runtime_fixture


@pytest.mark.asyncio
async def test_global_concurrency_and_owner_admission_caps(plugin):
    service, runs = plugin[2], plugin[3]
    service.global_slots = asyncio.Semaphore(1)
    script = "return await agent({stepId:'x',agentRef:'lead_agent',task:'blocked'});"
    first = await plugin[1]["launch"]({"request_id": "first", "script": script}, context(runs))
    await asyncio.wait_for(runs.entered.wait(), 5)
    second = await plugin[1]["launch"]({"request_id": "second", "script": script}, context(runs, "bob"))
    # Wait until the second workflow has persisted a queued step, before asserting
    # the shared slot prevented admission (no timing-only concurrency assertion).
    async with asyncio.timeout(5):
        while not (await plugin[1]["get"]({"run_id": second["run_id"]}, context(runs, "bob")))["steps"]:
            await asyncio.sleep(0.002)
    assert len(runs.starts) == 1
    await plugin[1]["cancel"]({"run_id": second["run_id"]}, context(runs, "bob"))
    await plugin[1]["cancel"]({"run_id": first["run_id"]}, context(runs))
    await service.wait_idle(first["run_id"])
    await service.wait_idle(second["run_id"])
    assert len(runs.starts) == 1 and runs.peak == 1


@pytest.mark.asyncio
async def test_startup_marks_unfinished_records_interrupted_without_replay(plugin):
    result = await launch(plugin, "return 1;")
    await done(plugin, result["run_id"])
    record = await asyncio.to_thread(plugin[2].store.get, "alice", result["run_id"])
    record["status"] = "running"
    await asyncio.to_thread(plugin[2].store.put, "alice", record)
    await plugin[2].stop()
    await plugin[2].start(None)
    final = await plugin[1]["get"]({"run_id": result["run_id"]}, context(plugin[3]))
    assert final["status"] == "interrupted"
    assert not plugin[3].starts


@pytest.mark.asyncio
async def test_model_tool_dispatch_uses_stamped_principal_and_handle(plugin):
    from types import SimpleNamespace

    from deerflow_extension_api.agent_runs import AGENT_RUNS_CONTEXT_KEY

    from deerflow.extensions.plugin_tools import build_plugin_tools

    # Exercise the production model-tool wrapper, not only the action handler.
    class ScopedRuns(Runs):
        def for_plugin(self, namespace):
            assert namespace == "community.workflows"
            return self

    runs = ScopedRuns()
    tools = build_plugin_tools(plugin[0])
    tool = next(t for t in tools if "launch_workflow" in t.name)
    runtime = SimpleNamespace(
        context={
            "thread_id": "parent",
            AGENT_RUNS_CONTEXT_KEY: runs,
            "user_id": "alice",
        },
        config={"configurable": {"user_id": "alice"}},
    )
    try:
        reply = json.loads(await tool.coroutine(runtime=runtime, request_id="tool-run", script="return 7;", args={}))
        await plugin[2].wait_idle(reply["run_id"])
        final = await plugin[1]["get"]({"run_id": reply["run_id"]}, context(runs))
        assert final["result"] == 7
    finally:
        await runs.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("with_child", [False, True])
async def test_workflow_deadline_is_failed_and_cleans_up(plugin, with_child):
    service, runs = plugin[2], plugin[3]
    service.config["timeout_seconds"] = 1
    script = "return await agent({stepId:'a',agentRef:'lead_agent',task:'blocked'});" if with_child else "return await new Promise(()=>{});"
    result = await launch(plugin, script)
    final = await done(plugin, result["run_id"])
    assert final["status"] == "failed", final
    assert final["error"] == "Execution deadline exceeded"
    assert not service.processes
    if with_child:
        assert len(runs.starts) == 1
        assert final["steps"][0]["child_status"] == "interrupted"
        assert all(run.status == "interrupted" for run in runs.runs.values())


@pytest.mark.asyncio
async def test_external_supervisor_cancellation_is_interrupted(plugin):
    service, runs = plugin[2], plugin[3]
    result = await launch(plugin, "return await agent({stepId:'a',agentRef:'lead_agent',task:'blocked'});")
    await asyncio.wait_for(runs.entered.wait(), 5)
    service.workers[result["run_id"]].cancel()
    final = await done(plugin, result["run_id"])
    assert final["status"] == "interrupted", final
    assert final["error"] == "Host interrupted; child cleanup required"
    assert final["steps"][0]["child_status"] == "interrupted"
    assert not service.processes


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["get", "get_state"])
@pytest.mark.parametrize("cleanup_fails", [False, True])
async def test_post_admission_timeout_reports_observation_and_cleans_up(plugin, operation, cleanup_fails):
    service, runs = plugin[2], plugin[3]

    async def timeout_once(**kwargs):
        setattr(runs, operation, original)
        if cleanup_fails:
            runs.denied = True
        raise TimeoutError("Slow child observation")

    original = getattr(runs, operation)
    setattr(runs, operation, timeout_once)
    result = await launch(plugin, "return await agent({stepId:'a',agentRef:'lead_agent',task:args.task});", args={"task": "blocked" if operation == "get" else 1})
    final = await done(plugin, result["run_id"])
    step = final["steps"][0]
    assert step["run_id"]
    assert step["error"] == "Child observation timed out; interrupting tracked run"
    assert not service.processes
    if cleanup_fails:
        assert final["status"] == step["status"] == "needs_reconciliation"
    else:
        assert final["status"] == step["status"] == "failed"
        assert final["error"] == step["error"]
        assert step["child_status"] in ("success", "interrupted")
        assert all(run.status != "running" for run in runs.runs.values())


@pytest.mark.asyncio
async def test_idempotent_retry_survives_allowlist_reordering_and_restart(plugin):
    service, runs = plugin[2], plugin[3]
    script = "return 42;"
    first = await launch(plugin, script)
    await done(plugin, first["run_id"])
    await service.stop()
    service.config["agents"] = list(reversed(service.config["agents"]))
    await service.start(None)
    retry = await launch(plugin, script)
    assert retry["run_id"] == first["run_id"]
    assert retry["status"] == "completed"
    assert not runs.starts
    service.config["agents"].append("new_agent")
    with pytest.raises(ValueError, match="request_id already used"):
        await launch(plugin, script)


@pytest.mark.asyncio
@pytest.mark.parametrize("injection,later_turn", [(False, False), (True, False), (True, True)])
async def test_result_anchor_uses_visible_input_after_real_context_rewrite(plugin, injection, later_turn):
    from langchain_core.messages import AIMessage, HumanMessage

    from app.gateway.services import normalize_input
    from deerflow.agents.middlewares.dynamic_context_middleware import DynamicContextMiddleware
    from deerflow.runtime.serialization import serialize_channel_values_for_api

    original = plugin[3].get_state

    async def injected(**kwargs):
        state = await original(**kwargs)
        raw = state["values"]["messages"][0]
        user = normalize_input({"messages": [raw]})["messages"][0]
        assert isinstance(user, HumanMessage)
        messages = DynamicContextMiddleware._make_reminder_and_user_messages(user, "Synthetic context", "Synthetic memory") if injection else [user]
        messages.append(AIMessage(content='{"answer":42}'))
        if later_turn:
            messages.extend([HumanMessage(content="Later user input"), AIMessage(content="Wrong answer")])
        state["values"] = serialize_channel_values_for_api({"messages": messages})
        return state

    plugin[3].get_state = injected
    result = await launch(plugin, "return await agent({stepId:'a',agentRef:'lead_agent',task:'first'});")
    final = await done(plugin, result["run_id"])
    if later_turn:
        assert final["status"] == "failed" and final["steps"][0]["status"] == "result_conflict"
    else:
        assert final["status"] == "completed", final
        assert final["result"]["output"] == {"answer": 42}


@pytest.mark.asyncio
@pytest.mark.parametrize("shutdown", [False, True])
async def test_cancelled_launch_caller_keeps_committed_sqlite_launch_owned(plugin, monkeypatch, shutdown):
    import threading

    service, runs = plugin[2], plugin[3]
    committed, release = threading.Event(), threading.Event()
    original = service.store.create

    def committed_before_response(owner, record):
        result = original(owner, record)
        committed.set()
        assert release.wait(5)
        return result

    monkeypatch.setattr(service.store, "create", committed_before_response)
    script = "return await agent({stepId:'a',agentRef:'lead_agent',task:'blocked'});"
    caller = asyncio.create_task(launch(plugin, script))
    stopping = None
    try:
        assert await asyncio.to_thread(committed.wait, 5)
        caller.cancel()
        with pytest.raises(asyncio.CancelledError):
            await caller
        if shutdown:
            stopping = asyncio.create_task(service.stop())
            await asyncio.sleep(0)
        release.set()
        if shutdown:
            await asyncio.wait_for(stopping, 10)
            await service.start(None)
        retry = await launch(plugin, script)
        if not shutdown:
            await asyncio.wait_for(runs.entered.wait(), 5)
            await plugin[1]["cancel"]({"run_id": retry["run_id"]}, context(runs))
        final = await done(plugin, retry["run_id"])
        assert final["status"] == "cancelled", final
        assert len(runs.starts) <= 1
        assert not service.entries and not service.workers and not service.processes
        await plugin[1]["delete"]({"run_id": retry["run_id"]}, context(runs))
    finally:
        release.set()
        if stopping:
            await stopping


async def waiting(plugin, run_id, status="waiting_approval"):
    async with asyncio.timeout(5):
        while True:
            result = await plugin[1]["get"]({"run_id": run_id}, context(plugin[3]))
            if result["status"] == status:
                return result
            await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_phase2_definition_versions_are_immutable_and_owner_scoped(plugin):
    _, actions, _, runs = plugin
    first = await actions["save_definition"]({"name": "inspection", "script": "return args;"}, context(runs))
    assert await actions["save_definition"]({"name": "inspection", "script": "return args;"}, context(runs)) == first
    second = await actions["save_definition"]({"name": "inspection", "script": "return args.product;"}, context(runs))
    assert first["version"] != second["version"]
    launched = await actions["launch"]({"request_id": "versioned", "definition": first, "args": {"product": "A"}}, context(runs))
    assert (await done(plugin, launched["run_id"]))["result"] == {"product": "A"}
    with pytest.raises(ValueError):
        await actions["launch"]({"request_id": "stolen", "definition": first}, context(runs, "bob"))


@pytest.mark.asyncio
async def test_phase2_checkpoint_requires_exact_authenticated_decision_and_dispatches_once(plugin):
    from dataclasses import replace

    from deerflow_extension_api.plugins import ToolContext

    _, actions, _, runs = plugin
    launched = await launch(
        plugin,
        """
const evidence = await agent({stepId:'evidence',agentRef:'lead_agent',task:'evidence'});
await humanCheckpoint({stepId:'confirm',sourceStepId:'evidence',artifactVersion:evidence.artifactVersion});
return await agent({stepId:'report',agentRef:'lead_agent',task:evidence.output});
""",
    )
    run_id = launched["run_id"]
    paused = await waiting(plugin, run_id)
    checkpoint = paused["checkpoints"][0]
    assert len(runs.starts) == 1
    decision = {"run_id": run_id, "step_id": "confirm", "attempt": 1, "artifact_version": checkpoint["artifact_version"], "decision": "approve"}
    human = replace(context(runs), interaction="session")
    for invalid in (context(runs), replace(human, principal=ExtensionPrincipal("bob")), ToolContext(human.principal, human.settings, "chat", agent_runs=runs, interaction="session")):
        with pytest.raises(ValueError):
            await actions["decide"](decision, invalid)
    with pytest.raises(ValueError):
        await actions["decide"]({**decision, "artifact_version": "stale"}, human)
    await asyncio.gather(*(actions["decide"](decision, human) for _ in range(3)))
    result = await done(plugin, run_id)
    assert result["status"] == "completed"
    assert len(runs.starts) == 2
    assert result["checkpoints"][0]["decided_by"] == "alice"
    with pytest.raises(ValueError):
        await actions["decide"]({**decision, "decision": "reject"}, human)


@pytest.mark.asyncio
async def test_phase2_pause_resume_preserves_results_and_invalidates_configuration(plugin):
    _, actions, _, runs = plugin
    launched = await launch(
        plugin,
        """
const a = await agent({stepId:'a',agentRef:'lead_agent',task:'original'});
await pause({stepId:'break'});
return a.output;
""",
    )
    run_id = launched["run_id"]
    paused = await waiting(plugin, run_id, "paused")
    runs.threads[runs.starts[0][0]]["values"]["messages"].append({"type": "ai", "content": "changed later"})
    with pytest.raises(ValueError):
        await actions["resume"]({"run_id": run_id, "step_id": "break", "attempt": 1, "fingerprint": "changed"}, context(runs))
    await actions["resume"]({"run_id": run_id, "step_id": "break", "attempt": 1, "fingerprint": paused["fingerprint"]}, context(runs))
    assert (await done(plugin, run_id))["result"] == {"echo": "original"}
    assert len(runs.starts) == 1
    launched = await launch(plugin, "await pause({stepId:'break'}); return 1;", request_id="changed-config")
    paused = await waiting(plugin, launched["run_id"], "paused")
    runs.revision = "modified"
    with pytest.raises(ValueError, match="configuration"):
        await actions["resume"]({"run_id": launched["run_id"], "step_id": "break", "attempt": 1, "fingerprint": paused["fingerprint"]}, context(runs))
    await actions["cancel"]({"run_id": launched["run_id"]}, context(runs))
    assert (await done(plugin, launched["run_id"]))["status"] == "cancelled"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["reject", "cancel", "expiry"])
async def test_phase2_checkpoint_stop_never_dispatches_downstream(plugin, kind):
    from dataclasses import replace

    _, actions, service, runs = plugin
    if kind == "expiry":
        service.config["pause_timeout_seconds"] = 1
    launched = await launch(
        plugin,
        "const a=await agent({stepId:'a',agentRef:'lead_agent',task:'data'});await humanCheckpoint({stepId:'confirm',sourceStepId:'a',artifactVersion:a.artifactVersion});return await agent({stepId:'b',agentRef:'lead_agent',task:'never'});",
    )
    run_id = launched["run_id"]
    paused = await waiting(plugin, run_id)
    if kind == "reject":
        await actions["decide"]({"run_id": run_id, "step_id": "confirm", "attempt": 1, "artifact_version": paused["checkpoints"][0]["artifact_version"], "decision": "reject"}, replace(context(runs), interaction="session"))
    elif kind == "cancel":
        await actions["cancel"]({"run_id": run_id}, context(runs))
    result = await done(plugin, run_id)
    assert result["status"] == ("cancelled" if kind == "cancel" else "failed")
    assert len(runs.starts) == 1
    assert not service.processes


@pytest.mark.asyncio
async def test_phase2_pause_does_not_consume_execution_budget_and_duplicate_resume_is_fenced(plugin):
    _, actions, service, runs = plugin
    service.config["timeout_seconds"] = 1
    launched = await launch(plugin, "await pause({stepId:'first'});await pause({stepId:'second'});return 42;")
    run_id = launched["run_id"]
    first = await waiting(plugin, run_id, "paused")
    await asyncio.sleep(1.1)
    payload = {"run_id": run_id, "step_id": "first", "attempt": 1, "fingerprint": first["fingerprint"]}
    await actions["resume"](payload, context(runs))
    async with asyncio.timeout(5):
        while True:
            second = await actions["get"]({"run_id": run_id}, context(runs))
            if len(second["checkpoints"]) == 2:
                break
            await asyncio.sleep(0.01)
    await actions["resume"](payload, context(runs))
    assert (await actions["get"]({"run_id": run_id}, context(runs)))["checkpoints"][1]["status"] == "pending"
    await actions["resume"]({**payload, "step_id": "second"}, context(runs))
    assert (await done(plugin, run_id))["result"] == 42


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "script",
    [
        "await humanCheckpoint({stepId:'c',sourceStepId:'fake',artifactVersion:'approved'});",
        "pause({stepId:'p'}); await agent({stepId:'a',agentRef:'lead_agent',task:'forbidden'});",
        "await pause({stepId:'p'});",
    ],
)
async def test_phase2_fail_closed_checkpoint_and_restart(plugin, script):
    _, actions, service, runs = plugin
    launched = await launch(plugin, script)
    run_id = launched["run_id"]
    if script == "await pause({stepId:'p'});":
        paused = await waiting(plugin, run_id, "paused")
        with pytest.raises(ValueError):
            await actions["delete"]({"run_id": run_id}, context(runs))
        await service.stop()
        # Simulate a crash-retained record and a new Gateway instance.
        record = await asyncio.to_thread(service.store.get, "alice", run_id)
        record["status"] = "paused"
        await asyncio.to_thread(service.store.put, "alice", record)
        from deerflow_extension_workflows.service import Workflows

        replacement = Workflows(service.config)
        await replacement.start(None)
        try:
            assert (await replacement.get({"run_id": run_id}, context(runs)))["status"] == "interrupted"
            with pytest.raises(ValueError):
                await replacement.resume({"run_id": run_id, "step_id": "p", "attempt": 1, "fingerprint": paused["fingerprint"]}, context(runs))
        finally:
            await replacement.stop()
    else:
        assert (await done(plugin, run_id))["status"] == "failed"
    assert not runs.starts


@pytest.mark.asyncio
async def test_phase2_real_gateway_output_checkpoint(plugin, gateway_runtime):
    from dataclasses import replace

    runs, *_ = gateway_runtime
    _, actions, service, _ = plugin
    launched = await actions["launch"](
        {"request_id": "real-approval", "script": "const a=await agent({stepId:'a',agentRef:'lead_agent',task:'first'});await humanCheckpoint({stepId:'confirm',sourceStepId:'a',artifactVersion:a.artifactVersion});return a.output;"},
        context(runs),
    )
    run_id = launched["run_id"]
    paused = await waiting(plugin, run_id)
    retained = await actions["get_step"]({"run_id": run_id, "step_id": "a"}, context(runs))
    assert retained["artifact_version"] == paused["checkpoints"][0]["artifact_version"]
    await actions["decide"]({"run_id": run_id, "step_id": "confirm", "attempt": 1, "artifact_version": retained["artifact_version"], "decision": "approve"}, replace(context(runs), interaction="session"))
    await service.wait_idle(run_id)
    assert (await actions["get"]({"run_id": run_id}, context(runs)))["result"] == retained["output"]


@pytest.mark.asyncio
async def test_phase2_disconnected_decision_still_publishes_exactly_once(plugin, monkeypatch):
    from dataclasses import replace

    _, actions, service, runs = plugin
    launched = await launch(plugin, "const a=await agent({stepId:'a',agentRef:'lead_agent',task:'x'});await humanCheckpoint({stepId:'confirm',sourceStepId:'a',artifactVersion:a.artifactVersion});return 42;")
    run_id = launched["run_id"]
    paused = await waiting(plugin, run_id)
    decision = {"run_id": run_id, "step_id": "confirm", "attempt": 1, "artifact_version": paused["checkpoints"][0]["artifact_version"], "decision": "approve"}
    persisted, release = asyncio.Event(), asyncio.Event()
    original = service.save

    async def hold(owner, record):
        await original(owner, record)
        if record["status"] == "waiting_approval" and record["checkpoints"][0]["status"] == "approved":
            persisted.set()
            await release.wait()

    monkeypatch.setattr(service, "save", hold)
    caller = asyncio.create_task(actions["decide"](decision, replace(context(runs), interaction="session")))
    await asyncio.wait_for(persisted.wait(), 5)
    caller.cancel()
    with pytest.raises(asyncio.CancelledError):
        await caller
    release.set()
    assert (await done(plugin, run_id))["result"] == 42
    assert len(runs.starts) == 1


@pytest.mark.asyncio
async def test_phase2_inspection_example_reviews_each_stage_and_final_output(plugin, monkeypatch):
    from dataclasses import replace

    _, actions, _, runs = plugin
    original = runs.answer

    async def answer(run, input):
        await original(run, input)
        task = json.loads(input["messages"][0]["content"])
        if isinstance(task, dict) and task.get("instruction", "").startswith("Return JSON with verdict"):
            runs.threads[run.thread_id]["values"]["messages"][-1]["content"] = json.dumps({"verdict": "ready"})

    monkeypatch.setattr(runs, "answer", answer)
    script = (ROOT / "examples/deerflow-extension-workflows/examples/inspection.workflow.js").read_text(encoding="utf-8")
    launched = await launch(
        plugin, script, args={"complianceAgent": "lead_agent", "ingredientAgent": "lead_agent", "reportAgent": "lead_agent", "reviewerAgent": "lead_agent", "product": "synthetic", "referenceDate": "2026-10-15", "formula": []}
    )
    run_id = launched["run_id"]
    for step_id, calls in [("confirm-evidence", 1), ("confirm-findings", 2), ("confirm-final-report", 4)]:
        async with asyncio.timeout(5):
            while True:
                result = await actions["get"]({"run_id": run_id}, context(runs))
                checkpoint = next((c for c in result["checkpoints"] if c["step_id"] == step_id), None)
                if checkpoint and result["status"] == "waiting_approval":
                    break
                await asyncio.sleep(0.01)
        assert len(runs.starts) == calls
        await actions["decide"]({"run_id": run_id, "step_id": step_id, "attempt": 1, "artifact_version": checkpoint["artifact_version"], "decision": "approve"}, replace(context(runs), interaction="session"))
    result = await done(plugin, run_id)
    assert result["status"] == "completed", result
    assert result["result"]["status"] == "human_confirmed_report"
    assert result["result"]["artifactVersion"] == result["checkpoints"][-1]["artifact_version"]


@pytest.mark.asyncio
async def test_immutable_file_review_and_downstream_consume_same_version(plugin):
    import base64
    from dataclasses import replace

    _, actions, _, runs = plugin
    launched = await launch(
        plugin,
        """
await agent({stepId:'report',agentRef:'lead_agent',task:'create file'});
const file=await captureArtifact({stepId:'file',sourceStepId:'report',path:'/mnt/user-data/outputs/report.pdf'});
await humanCheckpoint({stepId:'confirm-file',sourceStepId:'file',artifactVersion:file.artifactVersion});
return await readArtifact({artifactVersion:file.artifactVersion});
""",
    )
    run_id = launched["run_id"]
    paused = await waiting(plugin, run_id)
    file = paused["artifacts"][0]
    assert file["sha256"] and file["source_run_id"]
    with pytest.raises(ValueError, match="approved"):
        await actions["read_artifact"]({"run_id": run_id, "version": file["version"]}, context(runs))
    preview = await actions["get_artifact"]({"run_id": run_id, "version": file["version"]}, context(runs))
    runs.file_content = b"overwritten source after preview"
    decision = {"run_id": run_id, "step_id": "confirm-file", "attempt": 1, "artifact_version": file["version"], "decision": "approve"}
    with pytest.raises(ValueError):
        await actions["decide"]({**decision, "artifact_version": "different-version"}, replace(context(runs), interaction="session"))
    await actions["decide"](decision, replace(context(runs), interaction="session"))
    result = await done(plugin, run_id)
    assert result["status"] == "completed", result
    assert result["result"] == preview
    assert base64.b64decode(result["result"]["content_base64"]) == b"original file"
    source = await actions["get_step"]({"run_id": run_id, "step_id": "report"}, context(runs))
    assert source["configuration_evidence"]["run_id"] == source["run_id"]


@pytest.mark.asyncio
async def test_file_reference_requires_approval_before_child_admission(plugin):
    launched = await launch(
        plugin,
        "await agent({stepId:'a',agentRef:'lead_agent',task:'file'});"
        "const f=await captureArtifact({stepId:'f',sourceStepId:'a',path:'/mnt/user-data/outputs/report.pdf'});"
        "return await agent({stepId:'b',agentRef:'lead_agent',task:'read',artifacts:[f.artifactVersion]});",
    )
    result = await done(plugin, launched["run_id"])
    assert result["status"] == "failed"
    assert len(plugin[3].starts) == 1


@pytest.mark.asyncio
async def test_approved_file_reference_is_bound_to_child_input(plugin):
    from dataclasses import replace

    _, actions, _, runs = plugin
    launched = await launch(
        plugin,
        "await agent({stepId:'a',agentRef:'lead_agent',task:'file'});"
        "const f=await captureArtifact({stepId:'f',sourceStepId:'a',path:'/mnt/user-data/outputs/report.pdf'});"
        "await humanCheckpoint({stepId:'ok',sourceStepId:'f',artifactVersion:f.artifactVersion});return await agent({stepId:'b',agentRef:'lead_agent',task:'read',artifacts:[f.artifactVersion]});",
    )
    run_id = launched["run_id"]
    paused = await waiting(plugin, run_id)
    version = paused["artifacts"][0]["version"]
    await actions["decide"]({"run_id": run_id, "step_id": "ok", "attempt": 1, "artifact_version": version, "decision": "approve"}, replace(context(runs), interaction="session"))
    result = await done(plugin, run_id)
    assert result["status"] == "completed", result
    step = await actions["get_step"]({"run_id": run_id, "step_id": "b"}, context(runs))
    task = json.loads(runs.starts[-1][1]["messages"][0]["content"])
    assert step["input_artifacts"] == task["approved_artifacts"]
    assert task["approved_artifacts"][0]["version"] == version
    assert task["approved_artifacts"][0]["sha256"] == paused["artifacts"][0]["sha256"]


@pytest.mark.asyncio
@pytest.mark.parametrize("duplicate", [False, True])
async def test_parallel_approved_file_consumers_reserve_atomically(plugin, monkeypatch, duplicate):
    import threading
    from dataclasses import replace

    _, actions, service, runs = plugin
    service.config["max_calls"] = 8 if duplicate else 2
    script = """
await agent({stepId:'source',agentRef:'lead_agent',task:'file'});
const f=await captureArtifact({stepId:'file',sourceStepId:'source',path:'/mnt/user-data/outputs/report.pdf'});
await humanCheckpoint({stepId:'confirm',sourceStepId:'file',artifactVersion:f.artifactVersion});
return await Promise.all([
agent({stepId:'consumer',agentRef:'lead_agent',task:'read',artifacts:[f.artifactVersion]}),
agent({stepId:args.second,agentRef:'lead_agent',task:'read',artifacts:[f.artifactVersion]})]);
"""
    launched = await launch(plugin, script, args={"second": "consumer" if duplicate else "other"})
    run_id = launched["run_id"]
    paused = await waiting(plugin, run_id)
    original = service.store.artifact
    barrier = threading.Barrier(2, timeout=5)
    reads = []
    lock = threading.Lock()

    def synchronized(*args):
        value = original(*args)
        with lock:
            reads.append(args)
            decision_read = len(reads) == 1
        if not decision_read:
            barrier.wait()
        return value

    monkeypatch.setattr(service.store, "artifact", synchronized)
    await actions["decide"]({"run_id": run_id, "step_id": "confirm", "attempt": 1, "artifact_version": paused["artifacts"][0]["version"], "decision": "approve"}, replace(context(runs), interaction="session"))
    result = await done(plugin, run_id)
    assert len(reads) == 3 and not barrier.broken
    assert result["status"] == "failed", result
    assert len(result["steps"]) <= 2
    assert len(runs.starts) <= 2
    assert len({s["step_id"] for s in result["steps"]}) == len(result["steps"])
