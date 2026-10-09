"""Native dependency receipt uses the original goal and native admission ledger."""

import json
import os
import secrets
import subprocess
import sys
import time
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages/ecs-executor"))

from ecs_executor.dependencies import notification_receipt, source_job, validate_dependency_goal
from ecs_executor.job_store import JobStore

from deerflow.runtime.goal import DEFAULT_MAX_GOAL_CONTINUATIONS, DEFAULT_MAX_NO_PROGRESS_CONTINUATIONS, build_goal_state


def test_dependency_goal_revision_and_cumulative_native_budgets():
    goal = build_goal_state("Deliver B output", now="2026-10-09T00:00:00+00:00")
    goal.update(continuation_count=2, no_progress_count=1)
    wait = {"goal": deepcopy(goal), "conversation_signature": "original"}
    assert validate_dependency_goal(wait, goal, "original") == goal
    changed = {**goal, "updated_at": "new-revision"}
    with pytest.raises(ValueError, match="superseded"):
        validate_dependency_goal(wait, changed, "original")
    with pytest.raises(ValueError, match="superseded"):
        validate_dependency_goal(wait, goal, "new-user-message")
    for counter, cap in (("continuation_count", DEFAULT_MAX_GOAL_CONTINUATIONS), ("no_progress_count", DEFAULT_MAX_NO_PROGRESS_CONTINUATIONS)):
        capped = {key: value for key, value in goal.items() if key not in {"max_continuations", "max_no_progress_continuations"}}
        capped[counter] = cap
        with pytest.raises(ValueError, match="budget exhausted"):
            validate_dependency_goal({"goal": capped, "conversation_signature": "original"}, capped, "original")


@pytest.mark.asyncio
async def test_all_dependencies_and_physical_finalize_before_one_native_continuation(tmp_path, monkeypatch):
    import ecs_executor.dependencies as dependencies

    from app.mcp_tasks.errors import PermanentNotificationError
    from deerflow.runtime.runs.manager import ConflictError

    store = JobStore(f"sqlite:///{tmp_path / 'jobs.db'}")
    store.initialize()
    goal = build_goal_state("Deliver outputs")
    wait = {"goal": goal, "conversation_signature": "original", "task_ids": ["b1", "b2"], "source_run_id": "c1"}
    job = store.create(
        namespace="native-C", request_key="c1", spec_digest="c", record={"kind": "C", "native": {"run_id": "c1", "user_id": "owner", "thread_id": "thread", "incarnation": "inc"}, "dependency_wait": wait, "physical_stopped": False}
    )
    rows = [{"id": "b1", "status": "completed"}, {"id": "b2", "status": "working"}]
    run_store = SimpleNamespace(get=AsyncMock(return_value={"status": "success"}), find_by_idempotency_key=AsyncMock(return_value=None))
    host = SimpleNamespace(pool=SimpleNamespace(store=store), app=SimpleNamespace(state=SimpleNamespace(run_store=run_store, mcp_task_repo=SimpleNamespace(list_by_run=AsyncMock(side_effect=lambda *args, **kwargs: rows)))))
    monkeypatch.setattr(dependencies, "checkpoint_receipt", AsyncMock(return_value=(goal, "original")))
    args = dict(owner_user_id="owner", thread_id="thread", task_id="b1", source_run_id="c1")
    try:
        with pytest.raises(ConflictError, match="finalizers"):
            await notification_receipt(host, **args)
        store.mutate(job["id"], lambda row: row.update(physical_stopped=True, state="completed"))
        with pytest.raises(ConflictError, match="all terminal"):
            await notification_receipt(host, **args)
        rows[1]["status"] = "completed"
        assert await notification_receipt(host, **args) == wait
        run_store.find_by_idempotency_key.return_value = {"run_id": "c2"}
        dependencies.checkpoint_receipt.return_value = (None, "new-user-message")
        assert (await notification_receipt(host, **args))["continuation_run_id"] == "c2"
        run_store.get.return_value = {"status": "interrupted", "cancel_action": "interrupt"}
        with pytest.raises(PermanentNotificationError, match="cancelled"):
            await notification_receipt(host, **args)
        assert source_job(store, "c1")["id"] == job["id"]
    finally:
        store.engine.dispose()


@pytest.mark.asyncio
async def test_shared_notification_claim_forwarding_uses_canonical_task_not_sender_placement(tmp_path, monkeypatch):
    import httpx
    from ecs_executor.agent_dispatch import NativeWorkerHost, install_native_dispatch
    from ecs_executor.dispatch import PROTOCOL
    from starlette.applications import Starlette

    import app.gateway.services as services

    store = JobStore(f"sqlite:///{tmp_path / 'shared-notifications.db'}")
    store.initialize()
    app = Starlette()
    secret = "notification-sender-secret-at-least-32-bytes"
    task = {"run_id": "central-run", "dispatch_version": 1, "dispatch_attempt": 1, "dispatch_event": {"status": "completed"}, "notification_status": "launching"}
    app.state.thread_store = SimpleNamespace(get=AsyncMock(return_value={"incarnation": "inc"}))
    app.state.mcp_task_repo = SimpleNamespace(get=AsyncMock(side_effect=lambda *args, **kwargs: task))
    host = SimpleNamespace(app=app, config={"artifact_root": str(tmp_path / "pool")}, credentials={"sender": secret}, pool=SimpleNamespace(store=store, nodes={"sender": SimpleNamespace(worker_version="1")}))
    install_native_dispatch(app, host)
    launch = AsyncMock(return_value={"run_id": "notification-run"})
    monkeypatch.setattr(services, "launch_mcp_task_notification_run", launch)
    worker = NativeWorkerHost.__new__(NativeWorkerHost)
    worker.app, worker.secret, worker.config = app, secret, {"node_id": "sender"}
    mount = (tmp_path / "pool/pool-mount-id").read_text()
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://central") as client:

            async def request(operation, **kwargs):
                response = await client.post(
                    f"/api/native-workers/sender/{operation}", headers={"Authorization": "Bearer " + secret}, json={"protocol": PROTOCOL, "worker_version": "1", "mount_id": mount, "owner": "notification-claim-owner", **kwargs}
                )
                response.raise_for_status()
                return response.json()

            worker.request = request
            notification = {"owner_user_id": "owner", "thread_id": "thread", "task_id": "task", "dispatch_version": 1, "dispatch_attempt": 1, "event": task["dispatch_event"]}
            assert (await worker.forward_notification(notification))["run_id"] == "notification-run"
            task["run_id"] = "other-c-run"
            store.create(
                namespace="native-C", request_key="other-c-run", spec_digest="other", record={"kind": "C", "node_id": "other-node", "native": {"run_id": "other-c-run", "user_id": "owner", "thread_id": "thread", "incarnation": "inc"}}
            )
            assert (await worker.forward_notification(notification))["run_id"] == "notification-run"
            task["run_id"] = None
            assert (await worker.forward_notification(notification))["run_id"] == "notification-run"
            assert launch.await_count == 3
            assert app.state.mcp_task_repo.get.await_args.kwargs == {"user_id": "owner", "thread_id": "thread", "thread_incarnation": "inc"}
    finally:
        store.engine.dispose()


@pytest.mark.live
@pytest.mark.skipif(os.environ.get("ECS_NATIVE_LIVE") != "1", reason="Explicit native live acceptance opt-in required")
def test_real_native_c_mcp_b_same_goal_c(tmp_path):
    from test_ecs_executor_c_live import _native_http_acceptance

    _native_http_acceptance(tmp_path, dependency_mode=True)


def _setup_dependency_pool(backend, tmp_path, environment, native, owner, processes, handles, central_port, worker_port):
    import httpx
    from test_ecs_executor_c_live import _port

    for process in processes:
        process.terminate()
        process.wait(timeout=30)
    processes.clear()
    port = _port()
    environment.update(
        ECS_EXECUTOR_SCOPE_SECRET=secrets.token_urlsafe(48),
        ECS_EXECUTOR_SCOPE_SERVER="ecs",
        ECS_EXECUTOR_SCOPE_SUBMIT_TOOL="submit",
        ECS_EXECUTOR_SCOPE_STATUS_TOOL="status",
        ECS_EXECUTOR_SCOPE_CANCEL_TOOL="cancel",
        ECS_EXECUTOR_SCOPE_AUDIENCE="executor",
        BC_DISCOVERY=secrets.token_urlsafe(40),
        BC_OWNER=secrets.token_urlsafe(40),
        BC_NODE=secrets.token_urlsafe(40),
    )
    environment["BC_DISCOVERY_HEADER"] = "Bearer " + environment["BC_DISCOVERY"]
    environment["BC_OWNER_HEADER"] = "Bearer " + environment["BC_OWNER"]
    (tmp_path / "extensions.json").write_text(
        json.dumps(
            {
                "mcpInterceptors": ["ecs_executor.interceptor:build_execution_scope_interceptor"],
                "mcpServers": {
                    "ecs": {
                        "type": "http",
                        "url": f"http://127.0.0.1:{port}/mcp",
                        "headers": {"Authorization": "$BC_DISCOVERY_HEADER"},
                        "user_auth": {"enabled": True, "on_missing": "deny", "users": {owner: "$BC_OWNER_HEADER"}},
                        "task_toolsets": [{"name": "execution", "submit_tool": "submit", "status_tool": "status", "cancel_tool": "cancel"}],
                    }
                },
                "skills": {},
            }
        )
    )
    executor = {
        "mode": "pool",
        "database_url": environment["C_NATIVE_EXECUTOR_DATABASE_URL"],
        "audience": "executor",
        "profiles": {"small": {"image": "alpine:3.20", "cpu_millis": 500, "memory_mib": 128}},
        "nodes": native["nodes"],
        "worker_credential_env": {"one": "BC_NODE"},
        "user_profiles": {owner: ["small"]},
        "user_credential_env": {owner: "BC_OWNER"},
        "discovery_credential_env": "BC_DISCOVERY",
        "artifact_root": native["artifact_root"],
        "workspace_root": str(tmp_path / "nas"),
        "metadata_database_url": environment["C_NATIVE_EXECUTOR_DATABASE_URL"],
        "artifact_base_url": f"http://127.0.0.1:{central_port}",
        "port": port,
    }
    (tmp_path / "b.json").write_text(json.dumps(executor))
    (tmp_path / "b-worker.json").write_text(
        json.dumps(
            {
                "node_id": "one",
                "credential_env": "BC_NODE",
                "executor_url": f"http://127.0.0.1:{port}",
                "artifact_root": native["artifact_root"],
                "workspace_root": str(tmp_path / "nas"),
                "metadata_database_url": environment["C_NATIVE_EXECUTOR_DATABASE_URL"],
            }
        )
    )
    commands = [("b", ["-m", "ecs_executor.mcp_server"], {"ECS_EXECUTOR_CONFIG": str(tmp_path / "b.json")}), ("b-worker", ["-m", "ecs_executor.dispatch"], {"ECS_WORKER_CONFIG": str(tmp_path / "b-worker.json")})]
    for role, gateway_port in (("central", central_port), ("worker", worker_port)):
        commands.append(
            (role, ["-m", "uvicorn", "app.gateway.app:app", "--host", "127.0.0.1", "--port", str(gateway_port)], {"DEER_FLOW_CONFIG_PATH": str(tmp_path / (role + ".yaml")), "ECS_NATIVE_CONFIG": str(tmp_path / (role + "-native.json"))})
        )
    for role, args, overrides in commands:
        log = (tmp_path / (role + "-bc.log")).open("w")
        handles.append(log)
        process = subprocess.Popen([str(backend / ".venv/bin/python"), *args], cwd=backend, env={**environment, **overrides}, stdout=log, stderr=subprocess.STDOUT)
        processes.append(process)
        if role in {"central", "worker"}:
            gateway_port = central_port if role == "central" else worker_port
            for _ in range(180):
                if process.poll() is not None:
                    raise AssertionError(f"{role} dependency Gateway failed startup; inspect test-owned log")
                try:
                    if httpx.get(f"http://127.0.0.1:{gateway_port}/health/ready", timeout=1).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.5)
            else:
                raise AssertionError("Dependency Gateway readiness timed out")


def _run_dependency_main(client, headers, owner, tmp_path, environment, suffix):
    from sqlalchemy import create_engine, text

    thread = "native-bc-" + suffix
    assert client.post("/api/threads", json={"thread_id": thread}, headers=headers).status_code in {200, 201}
    objective = "Submit the delegated B command once; when its actual output is available, read the B output file and deliver it with native present_files. The delivered file must contain dependency-proof-338350."
    goal_response = client.put(f"/api/threads/{thread}/goal", json={"objective": objective}, headers=headers)
    assert goal_response.status_code == 200, goal_response.text[:300]
    original_goal = goal_response.json()["goal"]
    prompt = (
        "Use the ecs submit tool (discover it via tool_search if necessary) ONCE with request_key='bc-main', profile='small', "
        "argv=['sh','-c','sleep 2; printf dependency-proof-338350 > /output/b.txt']. This job executes outside your current native run. "
        "End this turn immediately after durable submission; do not poll, sleep or simulate its output. Wait for the automatic terminal notification. "
        "On that later notification, find its published /mnt/user-data/outputs/<job-id>/files/b.txt using native tools, read it and present_files that exact file to achieve the active goal."
    )
    started = client.post(
        f"/api/threads/{thread}/runs",
        headers=headers,
        json={
            "assistant_id": "lead_agent",
            "input": {"messages": [{"role": "user", "content": prompt}]},
            "metadata": {"deerflow_origin": {"kind": "schedule"}},
            "context": {"model_name": "deepseek-chat", "non_interactive": True},
            "on_disconnect": "continue",
            "config": {"recursion_limit": 100},
        },
    )
    assert started.status_code == 200, started.text[:300]
    source_id = started.json()["run_id"]
    sql = create_engine(environment["C_NATIVE_EXECUTOR_DATABASE_URL"])
    try:
        for _ in range(480):
            with sql.connect() as connection:
                runs = list(connection.execute(text("select run_id,status,goal_verdict from runs where thread_id=:thread order by created_at"), {"thread": thread}).mappings())
                jobs = [row[0] for row in connection.execute(text("select record from ecs_execution_jobs where record->'native'->>'thread_id'=:thread or record->>'thread_id'=:thread"), {"thread": thread})]
            if len(runs) >= 2 and runs[-1]["status"] not in {"pending", "running"}:
                break
            time.sleep(0.5)
        assert len(runs) == 2 and all(row["status"] == "success" for row in runs), str([{key: row[key] for key in ("run_id", "status", "goal_verdict")} for row in runs])
        source = next(job for job in jobs if job.get("kind") == "C" and job["native"]["run_id"] == source_id)
        delegated = next(job for job in jobs if job.get("kind", "B") == "B")
        continuation = next(job for job in jobs if job.get("kind") == "C" and job["native"]["run_id"] != source_id)
        assert source["dependency_wait"]["goal"]["created_at"] == original_goal["created_at"]
        assert source["physical_stopped"] and delegated["started_at"] >= source["physical_stopped_at"]
        assert source["node_id"] == delegated["node_id"] == continuation["node_id"] == "one"
        assert delegated["attempt"] == 1
        wait_goal = source["dependency_wait"]["goal"]
        assert continuation["native"]["goal"] == wait_goal
        assert runs[-1]["goal_verdict"]["continuations"] >= wait_goal["continuation_count"] + 1
        output = tmp_path / "nas/users" / owner / "threads" / thread / "user-data/outputs" / delegated["id"] / "files/b.txt"
        assert output.read_text() == "dependency-proof-338350"
        state = client.get(f"/api/threads/{thread}/state", headers=headers).json()["values"]
        assert "present_files" in {call["name"] for message in state["messages"] for call in message.get("tool_calls", [])}
        assert not state.get("goal"), "Successful final native delivery did not clear the original goal"
        print("Native C→ordinary MCP B→C: one original goal, two native Runs, one real Docker B, same 2CPU/4GiB node with one dynamic slot, native present_files delivery.")
    finally:
        sql.dispose()


@pytest.mark.asyncio
async def test_scheduled_wait_resume_preserves_goal_and_cancel_during_capture_cleans_it(monkeypatch):
    from langchain_core.messages import AIMessage, HumanMessage
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import END, START, StateGraph

    from deerflow.agents.thread_state import ThreadState
    from deerflow.runtime import goal
    from deerflow.runtime.runs import worker
    from deerflow.runtime.runs.manager import RunManager
    from deerflow.runtime.runs.store.memory import MemoryRunStore

    saver, store = InMemorySaver(), MemoryRunStore()
    manager = RunManager(store)
    metadata = {"scheduled_task_id": "task", "scheduled_task_run_id": "occ", "scheduled_goal_objective": "Deliver B"}
    runtime = {"task_id": "task", "occurrence_id": "occ", "user_id": "owner", "goal_objective": "Deliver B"}
    observed = []

    async def node(state):
        observed.append(deepcopy(state.get("goal")))
        return {"messages": [AIMessage(content="Waiting for B" if len(observed) == 1 else "Delivered B evidence")], "title": "B"}

    graph = StateGraph(ThreadState)
    graph.add_node("answer", node)
    graph.add_edge(START, "answer")
    graph.add_edge("answer", END)
    compiled = graph.compile(checkpointer=saver)
    outcomes = iter([{"satisfied": False, "blocker": "external_wait", "reason": "B pending", "relied_on_assumption": False}, {"satisfied": True, "blocker": "none", "reason": "B delivered", "relied_on_assumption": False}])

    async def evaluate(*args, **kwargs):
        return next(outcomes)

    monkeypatch.setattr(worker, "evaluate_goal_completion", evaluate)
    monkeypatch.setattr(worker, "create_goal_evaluator_model", lambda **kwargs: object())
    bridge = SimpleNamespace(publish=AsyncMock(), publish_end=AsyncMock(), cleanup=AsyncMock())
    first = await manager.create("scheduled-bc", user_id="owner", metadata=metadata)
    await worker.run_agent(
        bridge,
        manager,
        first,
        ctx=worker.RunContext(checkpointer=saver, scheduled_task_runtime=runtime, on_dependency_wait=AsyncMock(return_value=True)),
        agent_factory=lambda config: compiled,
        graph_input={"messages": [HumanMessage(content="Start B")]},
        config={"configurable": {"thread_id": "scheduled-bc"}, "context": {"non_interactive": True}},
    )
    preserved = await goal.read_thread_goal(saver, "scheduled-bc")
    assert preserved["created_at"] == observed[0]["created_at"]
    assert first.goal_verdict["native_dependency_wait"] is True
    # Prior continuations/no-progress belong to the same native goal instance.
    preserved.update(continuation_count=3, no_progress_count=1)
    await goal.write_thread_goal(saver, "scheduled-bc", preserved)
    snapshot = await compiled.aget_state({"configurable": {"thread_id": "scheduled-bc"}})
    wait = {"goal": preserved, "conversation_signature": goal.visible_conversation_signature(snapshot.values["messages"])}
    second = await manager.create("scheduled-bc", user_id="owner", metadata=metadata)
    await worker.run_agent(
        bridge,
        manager,
        second,
        ctx=worker.RunContext(checkpointer=saver, scheduled_task_runtime=runtime, dependency_continuation=wait, on_dependency_wait=AsyncMock(return_value=False)),
        agent_factory=lambda config: compiled,
        graph_input={"messages": [HumanMessage(content="B terminal", additional_kwargs={"hide_from_ui": True})]},
        config={"configurable": {"thread_id": "scheduled-bc"}, "context": {"non_interactive": True}},
    )
    assert second.status.value == "success"
    assert observed[1]["created_at"] == preserved["created_at"]
    assert observed[1]["continuation_count"] == 4 and observed[1]["no_progress_count"] == 1
    assert observed[1]["max_continuations"] == preserved["max_continuations"]
    assert await goal.read_thread_goal(saver, "scheduled-bc") is None

    cancelled = await manager.create("cancel-bc", user_id="owner", metadata=metadata)
    monkeypatch.setattr(worker, "evaluate_goal_completion", AsyncMock(return_value={"satisfied": False, "blocker": "external_wait", "reason": "B pending", "relied_on_assumption": False}))

    async def cancel_during_capture(record):
        await manager.cancel(record.run_id)
        return True

    await worker.run_agent(
        bridge,
        manager,
        cancelled,
        ctx=worker.RunContext(checkpointer=saver, scheduled_task_runtime=runtime, on_dependency_wait=cancel_during_capture),
        agent_factory=lambda config: compiled,
        graph_input={"messages": [HumanMessage(content="Start B")]},
        config={"configurable": {"thread_id": "cancel-bc"}, "context": {"non_interactive": True}},
    )
    assert cancelled.status.value == "interrupted"
    assert not (cancelled.goal_verdict or {}).get("native_dependency_wait")
    assert await goal.read_thread_goal(saver, "cancel-bc") is None

    late = await manager.create("late-cancel-bc", user_id="owner", metadata=metadata)
    original_terminal = manager.set_status_if_not_cancelled

    async def cancel_at_terminal(run_id, status, **kwargs):
        if (kwargs.get("goal_verdict") or {}).get("native_dependency_wait"):
            # Simulate the durable terminal CAS finding an accepted peer
            # cancellation after local success was staged.
            return "interrupt"
        return await original_terminal(run_id, status, **kwargs)

    monkeypatch.setattr(manager, "set_status_if_not_cancelled", cancel_at_terminal)
    await worker.run_agent(
        bridge,
        manager,
        late,
        ctx=worker.RunContext(checkpointer=saver, scheduled_task_runtime=runtime, on_dependency_wait=AsyncMock(return_value=True)),
        agent_factory=lambda config: compiled,
        graph_input={"messages": [HumanMessage(content="Start B")]},
        config={"configurable": {"thread_id": "late-cancel-bc"}, "context": {"non_interactive": True}},
    )
    assert late.status.value == "interrupted"
    assert await goal.read_thread_goal(saver, "late-cancel-bc") is None


@pytest.mark.asyncio
async def test_scheduled_occurrence_transfer_keeps_overlap_recovery_and_accounting(tmp_path, monkeypatch):
    from datetime import UTC, datetime, timedelta

    import ecs_executor.dependencies as dependencies
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from deerflow.persistence.base import Base
    from deerflow.persistence.run.model import RunRow
    from deerflow.persistence.run.sql import RunRepository
    from deerflow.persistence.scheduled_task_runs.model import ScheduledTaskRunRow
    from deerflow.persistence.scheduled_task_runs.sql import ScheduledTaskRunRepository
    from deerflow.persistence.scheduled_tasks.model import ScheduledTaskRow
    from deerflow.persistence.scheduled_tasks.sql import ScheduledTaskRepository
    from deerflow.runtime.runs.manager import RunManager

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'schedule.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sf, now = async_sessionmaker(engine, expire_on_commit=False), datetime.now(UTC)
    metadata = {"scheduled_task_id": "task", "scheduled_task_run_id": "occ"}
    repo = ScheduledTaskRunRepository(sf)
    try:
        async with sf() as session:
            session.add(ScheduledTaskRow(id="task", user_id="owner", title="B", prompt="B", schedule_type="once", schedule_spec={}, timezone="UTC", status="running", run_count=1, last_run_id="c1", last_occurrence_seq=1))
            session.add(ScheduledTaskRunRow(id="occ", task_id="task", thread_id="thread", run_id="c1", scheduled_for=now, trigger="scheduled", status="running", occurrence_seq=1, launch_accounted=True))
            session.add(RunRow(run_id="c1", thread_id="thread", user_id="owner", status="success", metadata_json=metadata, goal_verdict={"native_dependency_wait": True}))
            await session.commit()
        ledger = JobStore(f"sqlite:///{tmp_path / 'mixed-waits.db'}")
        ledger.initialize()
        try:
            goal = build_goal_state("B")
            for index in range(100):
                ledger.create(namespace="native-C", request_key=f"ordinary-{index}", spec_digest="wait", record={"kind": "C", "native": {"run_id": f"ordinary-{index}"}, "dependency_wait": {"active": True}})
            ledger.create(
                namespace="native-C",
                request_key="c1",
                spec_digest="scheduled",
                record={"kind": "C", "native": {"run_id": "c1", "user_id": "owner", "thread_id": "thread", "incarnation": "inc"}, "dependency_wait": {"active": True, "goal": goal, "conversation_signature": "same", "source_run_id": "c1"}},
            )
            first_page = ledger.list_native_dependency_waiting()
            assert len(first_page) == 100
            assert len(ledger.list_native_dependency_waiting(after_id=first_page[-1]["id"])) == 1
            runs = RunRepository(sf)
            host = SimpleNamespace(pool=SimpleNamespace(store=ledger), app=SimpleNamespace(state=SimpleNamespace(run_manager=RunManager(runs), run_store=runs, scheduled_task_run_repo=repo)))
            monkeypatch.setattr(dependencies, "checkpoint_receipt", AsyncMock(return_value=(goal, "same")))
            checked = await repo.dependency_wait_sources()
            assert checked == frozenset({"c1"})
            valid = await dependencies.maintain_waits(host, source_run_ids=checked)
            assert valid == checked
            assert await repo.reconcile_active_runs(error="orphan", now=now, valid_dependency_wait_runs=valid, checked_dependency_wait_runs=checked) == 0
            # Admission has committed C2, but snapshot creation is paused before
            # the occurrence transfer. Its existence is not a durable handoff.
            async with sf() as session:
                session.add(RunRow(run_id="c2", thread_id="thread", user_id="owner", status="pending", metadata_json=metadata, idempotency_key="mcp-dependencies:c1", lease_expires_at=now + timedelta(seconds=120)))
                await session.commit()

            async def acknowledge(wait, run_id):
                original = dependencies.source_job(ledger, wait["source_run_id"])
                ledger.mutate(original["id"], lambda row: row["dependency_wait"].update(continuation_run_id=run_id))

            host.acknowledge_continuation = AsyncMock(side_effect=acknowledge)
            valid = await dependencies.maintain_waits(host, source_run_ids=checked)
            assert valid == checked
            assert not dependencies.source_job(ledger, "c1")["dependency_wait"].get("continuation_run_id")
            host.acknowledge_continuation.assert_not_awaited()
            assert await repo.reconcile_active_runs(error="orphan", now=now, valid_dependency_wait_runs=valid, checked_dependency_wait_runs=checked) == 0
            assert (await repo.get_active_run("task"))["run_id"] == "c1"
            await repo.transfer_dependency_run(task_id="task", occurrence_id="occ", user_id="owner", source_run_id="c1", continuation_run_id="c2")
            await dependencies.maintain_waits(host, source_run_ids=checked)
            assert dependencies.source_job(ledger, "c1")["dependency_wait"]["continuation_run_id"] == "c2"
            # Crash before transfer: native expired-lease CAS terminalizes the
            # unassociated admission, and its source no longer holds recovery.
            expired_metadata = {"scheduled_task_id": "expired-task", "scheduled_task_run_id": "expired-occ"}
            async with sf() as session:
                session.add(ScheduledTaskRow(id="expired-task", user_id="owner", title="B", prompt="B", schedule_type="once", schedule_spec={}, timezone="UTC", status="running", run_count=1, last_run_id="expired-source"))
                session.add(ScheduledTaskRunRow(id="expired-occ", task_id="expired-task", thread_id="expired-thread", run_id="expired-source", scheduled_for=now, trigger="scheduled", status="running", launch_accounted=True))
                session.add(RunRow(run_id="expired-source", thread_id="expired-thread", user_id="owner", status="success", metadata_json=expired_metadata, goal_verdict={"native_dependency_wait": True}))
                session.add(
                    RunRow(
                        run_id="expired-continuation",
                        thread_id="expired-thread",
                        user_id="owner",
                        status="pending",
                        metadata_json=expired_metadata,
                        idempotency_key="mcp-dependencies:expired-source",
                        lease_expires_at=now - timedelta(seconds=120),
                    )
                )
                await session.commit()
            ledger.create(
                namespace="native-C",
                request_key="expired-source",
                spec_digest="expired",
                record={
                    "kind": "C",
                    "native": {"run_id": "expired-source", "user_id": "owner", "thread_id": "expired-thread", "incarnation": "inc"},
                    "dependency_wait": {"active": True, "goal": goal, "conversation_signature": "same", "source_run_id": "expired-source"},
                },
            )
            expired_checked = await repo.dependency_wait_sources()
            assert expired_checked == frozenset({"expired-source"})
            assert not await dependencies.maintain_waits(host, source_run_ids=expired_checked)
            assert (await runs.get("expired-continuation", user_id="owner"))["status"] == "error"
            assert await repo.reconcile_active_runs(error="orphan", now=now, checked_dependency_wait_runs=expired_checked) == 1
            assert await repo.get_active_run("expired-task") is None
        finally:
            ledger.engine.dispose()
        async with sf() as session:
            session.add(ScheduledTaskRunRow(id="competing", task_id="task", thread_id="other", scheduled_for=now, trigger="scheduled", status="queued"))
            with pytest.raises(IntegrityError):
                await session.commit()
        args = dict(task_id="task", occurrence_id="occ", user_id="owner", source_run_id="c1", continuation_run_id="c2")
        await repo.transfer_dependency_run(**args)
        await repo.transfer_dependency_run(**args)
        assert await repo.reconcile_active_runs(error="orphan", now=now) == 0
        async with sf() as session:
            assert (await session.get(ScheduledTaskRunRow, "occ")).run_id == "c2"
            task = await session.get(ScheduledTaskRow, "task")
            assert task.run_count == 1 and task.last_run_id == "c2"
        tasks = ScheduledTaskRepository(sf)
        assert not await tasks.complete_run("task", user_id="owner", task_run_id="occ", run_id="c1", status="success", error=None, finished_at=now)
        assert await tasks.complete_run("task", user_id="owner", task_run_id="occ", run_id="c2", status="success", error=None, finished_at=now)
        # Historical marker alone cannot protect an orphan after host/receipt
        # removal: default native recovery has no valid dependency source IDs.
        async with sf() as session:
            session.add(ScheduledTaskRow(id="orphan-task", user_id="owner", title="B", prompt="B", schedule_type="once", schedule_spec={}, timezone="UTC", status="running", run_count=1, last_run_id="orphan-source"))
            session.add(ScheduledTaskRunRow(id="orphan-occ", task_id="orphan-task", thread_id="orphan-thread", run_id="orphan-source", scheduled_for=now, trigger="scheduled", status="running", launch_accounted=True))
            session.add(
                RunRow(
                    run_id="orphan-source",
                    thread_id="orphan-thread",
                    user_id="owner",
                    status="success",
                    metadata_json={"scheduled_task_id": "orphan-task", "scheduled_task_run_id": "orphan-occ"},
                    goal_verdict={"native_dependency_wait": True},
                )
            )
            await session.commit()
        # Completed after the preflight snapshot: defer unchecked receipts,
        # then validate or settle them in the next recovery pass.
        assert await repo.reconcile_active_runs(error="orphan", now=now, checked_dependency_wait_runs=frozenset()) == 0
        assert await repo.dependency_wait_sources() == frozenset({"orphan-source"})
        assert await repo.reconcile_active_runs(error="orphan", now=now, checked_dependency_wait_runs=frozenset({"orphan-source"})) == 1
        assert await repo.get_active_run("orphan-task") is None
        race_metadata = {"scheduled_task_id": "race-task", "scheduled_task_run_id": "race-occ"}
        async with sf() as session:
            session.add(ScheduledTaskRow(id="race-task", user_id="owner", title="B", prompt="B", schedule_type="once", schedule_spec={}, timezone="UTC", status="running", run_count=1, last_run_id="race-source"))
            session.add(ScheduledTaskRunRow(id="race-occ", task_id="race-task", thread_id="race-thread", run_id="race-source", scheduled_for=now, trigger="scheduled", status="running", launch_accounted=True))
            session.add(RunRow(run_id="race-source", thread_id="race-thread", user_id="owner", status="running", metadata_json=race_metadata, lease_expires_at=now - timedelta(seconds=120)))
            await session.commit()
        assert await repo.dependency_wait_sources() == frozenset()
        native_takeover = repo._run_repository.claim_for_takeover

        async def completion_wins_takeover(run_id, **kwargs):
            # A real peer terminal commit lands after recovery's candidate read
            # and before its native lease CAS. The CAS must lose to completion.
            async with sf() as session:
                source = await session.get(RunRow, run_id)
                source.status = "success"
                source.goal_verdict = {"native_dependency_wait": True}
                await session.commit()
            claimed = await native_takeover(run_id, **kwargs)
            assert claimed is False
            return claimed

        monkeypatch.setattr(repo._run_repository, "claim_for_takeover", completion_wins_takeover)
        assert await repo.reconcile_active_runs(error="orphan", now=now, checked_dependency_wait_runs=frozenset()) == 0
        assert (await repo.get_active_run("race-task"))["run_id"] == "race-source"
        assert await repo.reconcile_active_runs(error="orphan", now=now, checked_dependency_wait_runs=frozenset({"race-source"}), valid_dependency_wait_runs=frozenset({"race-source"})) == 0
        # No host preserves the normal terminal-success recovery behavior.
        assert await repo.reconcile_active_runs(error="orphan", now=now) == 1
        assert await repo.get_active_run("race-task") is None
    finally:
        await engine.dispose()
