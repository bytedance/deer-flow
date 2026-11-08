"""Execution identity and both sides of artifact handoffs, including real admission."""

import asyncio
import dataclasses
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from deerflow_extension_api import AgentRunError
from test_agent_teams_plugin import Runs, artifact_tools, context, create, producing_task
from test_agent_teams_plugin import plugin as plugin
from test_extension_agent_runs import host as host
from test_extension_agent_runs import runtime as runtime
from test_remote_artifact_snapshots import remote as remote

pytestmark = pytest.mark.skipif(os.name != "posix", reason="Artifact snapshots require POSIX")


@pytest.mark.asyncio
async def test_plain_admission_cannot_impersonate_plugin_with_the_same_key(runtime):
    from app.gateway.routers.thread_runs import create_run
    from app.gateway.run_models import RunCreateRequest

    runs, state, request, entered, _ = runtime
    thread = await runs.create_thread(thread_id="plain-artifact-source")
    response = await create_run(thread, RunCreateRequest(input={"messages": [{"role": "user", "content": "wait"}]}), request, idempotency_key="extension:artifact-fixture:task")
    await asyncio.wait_for(entered.wait(), 5)
    with pytest.raises(AgentRunError, match="executing"):
        await runs.for_plugin("artifact-fixture").validate_artifact_source(thread_id=thread, run_id=response.run_id, idempotency_key="task")


@pytest.mark.asyncio
async def test_registration_uses_host_key_before_admission_ack_is_persisted(plugin, monkeypatch):
    loaded, actions, service = plugin
    runs = Runs()
    team = await create(actions, runs)
    member = team["members"][0]
    job = await actions["send"]({"team_id": team["id"], "member_id": member["id"], "text": "Produce", "request_id": "task"}, context(runs))
    start = runs.start

    async def lose_ack(**kwargs):
        await start(**kwargs)
        raise OSError("Lost admission acknowledgement")

    monkeypatch.setattr(runs, "start", lose_ack)
    await service.tick()
    saved = await service.db("get", "alice", team["id"])
    assert saved["jobs"][0]["run_id"] is None
    args = {"team_id": team["id"], "request_id": "file", "name": "Report", "path": "/mnt/user-data/outputs/report.txt"}
    registered = await artifact_tools(loaded)["register_team_artifact"](args, context(runs, thread=member["thread_id"]))
    assert registered["artifact"]["source"]["run_id"] == job["id"]
    assert await artifact_tools(loaded)["register_team_artifact"](args, context(runs, thread=member["thread_id"])) == registered


@pytest.mark.asyncio
async def test_admission_rejects_remote_edits_without_overwriting_them(runtime, remote, monkeypatch):
    from pathlib import Path

    runs, state, request, _, handles = runtime
    runs = runs.for_plugin("artifact-fixture")
    thread = await runs.create_thread(thread_id="remote-recipient")
    lease = SimpleNamespace(denied=False, sandbox=remote, release=AsyncMock())
    monkeypatch.setattr("app.gateway.extension_artifacts.get_sandbox_provider", lambda: SimpleNamespace(uses_thread_data_mounts=False))
    monkeypatch.setattr("app.gateway.extension_artifacts.try_acquire_sandbox_for_request", AsyncMock(return_value=lease))
    receipt = await runs.import_artifact(thread_id=thread, filename="report.txt", content=b"original")
    target = Path(remote.artifact_root) / "uploads" / receipt["filename"]
    target.write_bytes(b"remote recipient edit")
    admitted = await runs.start(thread_id=thread, input={"messages": [{"role": "user", "content": "first"}]}, artifact_imports=[receipt])
    final = await runs.wait(thread_id=thread, run_id=admitted.run_id, timeout=5)
    assert final.status == "error" and final.stop_reason == "artifact_conflict"
    assert not handles
    assert target.read_bytes() == b"remote recipient edit"


@pytest.mark.asyncio
async def test_remote_snapshot_lease_survives_into_agent_execution(runtime, remote, monkeypatch):
    runs, state, request, entered, _ = runtime
    runs = runs.for_plugin("artifact-fixture")
    thread = await runs.create_thread(thread_id="remote-recipient-lifetime")
    lease = SimpleNamespace(denied=False, sandbox=remote, release=AsyncMock())
    monkeypatch.setattr("app.gateway.extension_artifacts.get_sandbox_provider", lambda: SimpleNamespace(uses_thread_data_mounts=False))
    monkeypatch.setattr("app.gateway.extension_artifacts.try_acquire_sandbox_for_request", AsyncMock(return_value=lease))
    receipt = await runs.import_artifact(thread_id=thread, filename="report.txt", content=b"original")
    lease.release.reset_mock()
    admitted = await runs.start(thread_id=thread, input={"messages": [{"role": "user", "content": "wait"}]}, artifact_imports=[receipt])
    try:
        await asyncio.wait_for(entered.wait(), 5)
        assert lease.release.await_count == 0
    finally:
        await runs.cancel(thread_id=thread, run_id=admitted.run_id)
        record = await state.run_manager.get(admitted.run_id, user_id=str(request.state.user.id))
        await record.task
    assert lease.release.await_count == 1


@pytest.mark.asyncio
async def test_admission_checks_files_before_agent_and_reconciles_completed_key_first(runtime):
    from deerflow.config.paths import get_paths

    runs, state, request, _, handles = runtime
    runs = runs.for_plugin("artifact-fixture")
    thread = await runs.create_thread(thread_id="artifact-admission")
    receipt = await runs.import_artifact(thread_id=thread, filename="report.txt", content=b"original")
    target = get_paths().sandbox_uploads_dir(thread, user_id=str(request.state.user.id)) / receipt["filename"]
    inputs = {"messages": [{"role": "user", "content": "first"}]}
    admitted = await runs.start(thread_id=thread, input=inputs, idempotency_key="first", artifact_imports=[receipt])
    assert (await runs.wait(thread_id=thread, run_id=admitted.run_id, timeout=5)).status == "success"
    # A retry after the run edited its own copy must reconcile admission first.
    target.write_bytes(b"edited during execution")
    retried = await runs.start(thread_id=thread, input=inputs, idempotency_key="first", artifact_imports=[receipt])
    assert retried.run_id == admitted.run_id
    called = len(handles)
    rejected = await runs.start(thread_id=thread, input=inputs, idempotency_key="second", artifact_imports=[receipt])
    final = await runs.wait(thread_id=thread, run_id=rejected.run_id, timeout=5)
    assert final.status == "error" and final.stop_reason == "artifact_conflict"
    assert len(handles) == called  # Rejection occurs before graph construction/execution.
    assert target.read_bytes() == b"edited during execution"


@pytest.mark.asyncio
async def test_import_verification_holds_durable_run_admission(runtime, monkeypatch):
    from app.gateway.extension_artifacts import verify_imports

    runs, state, request, _, _ = runtime
    runs = runs.for_plugin("artifact-fixture")
    thread = await runs.create_thread(thread_id="artifact-admission-lock")
    receipt = await runs.import_artifact(thread_id=thread, filename="report.txt", content=b"original")
    entered, release = asyncio.Event(), asyncio.Event()

    async def gated(*args, **kwargs):
        entered.set()
        await release.wait()
        return await verify_imports(*args, **kwargs)

    monkeypatch.setattr("app.gateway.extension_artifacts.verify_imports", gated)
    admitted = await runs.start(thread_id=thread, input={"messages": [{"role": "user", "content": "first"}]}, idempotency_key="first", artifact_imports=[receipt])
    try:
        await asyncio.wait_for(entered.wait(), 5)
        with pytest.raises(AgentRunError) as conflict:
            await runs.start(thread_id=thread, input={"messages": [{"role": "user", "content": "ordinary"}]})
        assert conflict.value.status_code == 409
    finally:
        release.set()
    assert (await runs.wait(thread_id=thread, run_id=admitted.run_id, timeout=5)).status == "success"


@pytest.mark.asyncio
async def test_nonmounted_capture_reads_remote_bytes_and_registration_checks_support(runtime, remote, tmp_path, monkeypatch):
    from pathlib import Path

    runs, state, request, entered, _ = runtime
    runs = runs.for_plugin("artifact-fixture")
    thread = await runs.create_thread(thread_id="remote-source")
    run = await runs.start(thread_id=thread, input={"messages": [{"role": "user", "content": "wait"}]}, idempotency_key="source")
    await asyncio.wait_for(entered.wait(), 5)
    lease = SimpleNamespace(denied=False, sandbox=remote, release=AsyncMock())
    monkeypatch.setattr("app.gateway.extension_artifacts.get_sandbox_provider", lambda: SimpleNamespace(uses_thread_data_mounts=False))
    monkeypatch.setattr("app.gateway.extension_artifacts.try_acquire_sandbox_for_request", AsyncMock(return_value=lease))
    await runs.validate_artifact_source(thread_id=thread, run_id=run.run_id, idempotency_key="source")
    remote.artifact_root = None
    with pytest.raises(AgentRunError) as unsupported:
        await runs.validate_artifact_source(thread_id=thread, run_id=run.run_id, idempotency_key="source")
    assert unsupported.value.status_code == 422
    remote.artifact_root = str(tmp_path / "remote")
    output = Path(remote.artifact_root) / "outputs/report.bin"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"remote\x00\xff")
    await runs.cancel(thread_id=thread, run_id=run.run_id)
    await runs.wait(thread_id=thread, run_id=run.run_id, timeout=5)
    record = await state.run_manager.get(run.run_id, user_id=str(request.state.user.id))
    await record.task
    assert await runs.read_artifact(thread_id=thread, path="/mnt/user-data/outputs/report.bin") == b"remote\x00\xff"
    assert lease.release.await_count == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["admission_conflict", "host_finished"])
async def test_registration_rejects_nonexecuting_job(plugin, stage):
    loaded, actions, service = plugin
    runs = Runs()
    team = await create(actions, runs)
    member = team["members"][0]
    args = {"team_id": team["id"], "request_id": "invalid-execution", "name": "Report", "path": "/mnt/user-data/outputs/report.txt"}
    if stage == "admission_conflict":
        await runs.start(thread_id=member["thread_id"], input={"messages": [{"role": "user", "content": "ordinary"}]}, idempotency_key="ordinary")
    job = await actions["send"]({"team_id": team["id"], "member_id": member["id"], "text": "Task", "request_id": "task"}, context(runs))
    with pytest.raises(ValueError, match="executing"):
        await artifact_tools(loaded)["register_team_artifact"](args, context(runs, thread=member["thread_id"]))
    await service.tick()
    if stage == "host_finished":
        runs.finish(job["id"])
    saved = await service.db("get", "alice", team["id"])
    queued = next(j for j in saved["jobs"] if j["id"] == job["id"])
    assert queued["input"] is not None
    assert (queued["run_id"] is None) if stage == "admission_conflict" else runs.runs[queued["run_id"]].status == "success"
    with pytest.raises((ValueError, AgentRunError), match="executing"):
        await artifact_tools(loaded)["register_team_artifact"](args, context(runs, thread=member["thread_id"]))
    assert not (await service.db("get", "alice", team["id"])).get("artifacts")


async def ready_attachment(plugin):
    loaded, actions, service, runs, team, author, recipient, job = await producing_task(plugin)
    path = "/mnt/user-data/outputs/report.txt"
    runs.files[author["thread_id"], path] = b"original"
    artifact = (await artifact_tools(loaded)["register_team_artifact"]({"team_id": team["id"], "request_id": "file", "name": "Report", "path": path}, context(runs, thread=author["thread_id"])))["artifact"]
    runs.finish(job["id"])
    await service.tick()
    target = await actions["send"]({"team_id": team["id"], "member_id": recipient["id"], "text": "Read file", "request_id": "read", "artifacts": [{"artifact_id": artifact["artifact_id"], "version": 1}]}, context(runs))
    return loaded, actions, service, runs, team, recipient, target


@pytest.mark.asyncio
@pytest.mark.parametrize("clarification", [False, True])
@pytest.mark.parametrize("lost_ack", [False, True])
async def test_resumed_task_registers_files_with_its_active_execution_key(plugin, monkeypatch, clarification, lost_ack):
    from deerflow.agents.middlewares.clarification_middleware import ClarificationMiddleware

    loaded, actions, service, runs, team, author, _, job = await producing_task(plugin)
    runs.finish(job["id"], interrupted=not clarification)
    if clarification:
        request = SimpleNamespace(tool_call={"name": "ask_clarification", "id": "question", "args": {"question": "Which environment?", "clarification_type": "missing_info"}}, runtime=None)
        command = ClarificationMiddleware().wrap_tool_call(request, lambda _: pytest.fail("intercept clarification"))
        runs.threads[author["thread_id"]]["values"]["messages"].extend(m.model_dump() for m in command.update["messages"])
    await service.tick()
    method = "start" if clarification else "resume"
    admit = getattr(runs, method)

    async def lose_ack(**kwargs):
        result = await admit(**kwargs)
        if lost_ack:
            raise OSError("Admission acknowledgement lost")
        return result

    monkeypatch.setattr(runs, method, lose_ack)
    await actions["resume"]({"team_id": team["id"], "job_id": job["id"], "response": "staging" if clarification else {"approved": True}, "request_id": "answer"}, context(runs))
    await service.tick()
    args = {"team_id": team["id"], "request_id": "resumed-file", "name": "Report", "path": "/mnt/user-data/outputs/resumed.txt"}
    # Registration must work both before and after the acknowledgement is saved.
    before = await artifact_tools(loaded)["register_team_artifact"](args, context(runs, thread=author["thread_id"]))
    monkeypatch.setattr(runs, method, admit)
    await service.tick()
    after = await artifact_tools(loaded)["register_team_artifact"]({**args, "request_id": "after-ack"}, context(runs, thread=author["thread_id"]))
    assert before["artifact"]["source"]["run_id"] == after["artifact"]["source"]["run_id"] != job["id"]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["import", "capture"])
async def test_artifact_transfer_can_exceed_the_poll_deadline(plugin, monkeypatch, operation):
    if operation == "import":
        _, _, service, runs, team, _, target = await ready_attachment(plugin)
        method = "import_artifact"
    else:
        loaded, _, service, runs, team, author, _, target = await producing_task(plugin)
        path = "/mnt/user-data/outputs/slow.txt"
        runs.files[author["thread_id"], path] = b"retained bytes"
        await artifact_tools(loaded)["register_team_artifact"]({"team_id": team["id"], "request_id": "file", "name": "Report", "path": path}, context(runs, thread=author["thread_id"]))
        runs.finish(target["id"])
        method = "read_artifact"
    transfer = getattr(runs, method)
    calls = 0

    async def slow_transfer(**kwargs):
        nonlocal calls
        calls += 1
        await asyncio.sleep(10.1)
        return await transfer(**kwargs)

    monkeypatch.setattr(runs, method, slow_transfer)
    await service.tick()
    saved = await service.db("get", "alice", team["id"])
    job = next(j for j in saved["jobs"] if j["id"] == target["id"])
    if operation == "import":
        assert job["run_id"] == target["id"] and job["artifact_imports"] and job["input"]
    else:
        assert job["status"] == "completed" and saved["artifacts"][0]["status"] == "ready"
    await service.tick()
    assert calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_worker", [False, True])
async def test_artifact_deadline_and_shutdown_drain_the_transfer(plugin, monkeypatch, cancel_worker):
    from deerflow_extension_agent_teams import artifacts

    _, _, service, runs, team, _, target = await ready_attachment(plugin)
    entered, draining, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    if not cancel_worker:
        monkeypatch.setattr(artifacts, "ARTIFACT_TRANSFER_SECONDS", 0.01)

    async def stalled(**kwargs):
        entered.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            draining.set()
            await release.wait()
            raise

    monkeypatch.setattr(runs, "import_artifact", stalled)
    tick = asyncio.create_task(service.tick())
    try:
        await asyncio.wait_for(entered.wait(), 5)
        if cancel_worker:
            tick.cancel()
        await asyncio.wait_for(draining.wait(), 5)
        assert not tick.done() and service.in_flight
    finally:
        release.set()
        if cancel_worker:
            with pytest.raises(asyncio.CancelledError):
                await tick
        else:
            await tick
    assert not service.in_flight and not service.workers
    saved = await service.db("get", "alice", team["id"])
    job = next(j for j in saved["jobs"] if j["id"] == target["id"])
    assert job["input"] is None and job["run_id"] is None


@pytest.mark.asyncio
async def test_completed_transfer_restores_the_ordinary_poll_budget(plugin, monkeypatch):
    from deerflow_extension_agent_teams import artifacts

    monkeypatch.setattr(artifacts, "ARTIFACT_TRANSFER_SECONDS", 2)
    transferred = False
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.1) as deadline:
            token = artifacts.worker_deadline.set(deadline)
            try:
                await artifacts.transfer(asyncio.sleep, delay=0.15)
                transferred = True
                # Ordinary work must again time out, even after a slow file.
                await asyncio.sleep(0.15)
            finally:
                artifacts.worker_deadline.reset(token)
    assert transferred


@pytest.mark.asyncio
async def test_frozen_input_still_requires_unchanged_imports_after_conflict(plugin, monkeypatch):
    loaded, actions, service, runs, team, recipient, target = await ready_attachment(plugin)
    original_start = runs.start
    first = True

    async def interleave(**kwargs):
        nonlocal first
        if first and kwargs["idempotency_key"] == target["id"]:
            first = False
            await original_start(thread_id=recipient["thread_id"], input={"messages": [{"role": "user", "content": "ordinary"}]}, idempotency_key="ordinary")
            thread, path, _ = runs.imports[-1]
            runs.files[thread, path] = b"ordinary edit"
        return await original_start(**kwargs)

    monkeypatch.setattr(runs, "start", interleave)
    await service.tick()
    saved = await service.db("get", "alice", team["id"])
    job = next(j for j in saved["jobs"] if j["id"] == target["id"])
    assert job["run_id"] is None and job["input"] is not None
    runs.finish("ordinary")
    await service.tick()
    assert target["id"] not in runs.runs
    assert len(runs.imports) == 1
    saved = await service.db("get", "alice", team["id"])
    rejected = next(j for j in saved["jobs"] if j["id"] == target["id"])
    assert rejected["status"] == "failed" and "artifact copy" in rejected["error"]


@pytest.mark.asyncio
async def test_import_conflict_reports_artifact_error_without_admission(plugin, monkeypatch):
    loaded, actions, service, runs, team, recipient, target = await ready_attachment(plugin)

    async def changed(**kwargs):
        raise AgentRunError(422, "Imported artifact was changed; existing file retained")

    monkeypatch.setattr(runs, "import_artifact", changed)
    await service.tick()
    saved = await service.db("get", "alice", team["id"])
    job = next(j for j in saved["jobs"] if j["id"] == target["id"])
    assert job["status"] == "failed"
    assert "artifact copy" in job["error"] and "changed" in job["error"]
    assert target["id"] not in runs.runs


@pytest.mark.asyncio
@pytest.mark.parametrize("later_turn", [False, True])
async def test_source_capture_is_fenced_to_checked_checkpoint(plugin, runtime, monkeypatch, later_turn):
    from langchain_core.messages import AIMessage
    from langgraph.graph import MessagesState, StateGraph
    from langgraph.runtime import Runtime

    from app.gateway import services
    from deerflow.config.paths import get_paths

    loaded, actions, service = plugin
    runs, _, request, _, _ = runtime
    runs = runs.for_plugin("community.agent-teams")
    owner = str(request.state.user.id)
    team = await actions["create"]({"request_id": "real-team", "name": "Review", "goal": "Reproduce capture race", "members": [{"name": "Author", "agent": "lead_agent"}, {"name": "Recipient", "agent": "lead_agent"}]}, context(runs, owner))
    author = team["members"][0]
    output = get_paths().sandbox_outputs_dir(author["thread_id"], user_id=owner) / "report.txt"
    output.parent.mkdir(parents=True, exist_ok=True)
    entered, finish_producer = asyncio.Event(), asyncio.Event()
    original_factory = services.resolve_agent_factory("lead_agent")

    async def answer(state: MessagesState, runtime: Runtime):
        text = state["messages"][-1].content
        if text.startswith("Team collaboration request."):
            output.write_bytes(b"producer output")
            entered.set()
            await finish_producer.wait()
        else:
            output.write_bytes(b"later ordinary output")
        from uuid import uuid4

        from langchain_core.messages import ToolMessage
        from langgraph.types import Command

        journal = runtime.context["__run_journal"]
        journal._remember_current_run_tool_calls(AIMessage(content="", tool_calls=[{"id": "present-output", "name": "present_files", "args": {}}]), caller="lead_agent")
        journal.on_tool_end(Command(update={"artifacts": ["/mnt/user-data/outputs/report.txt"], "messages": [ToolMessage("Presented", tool_call_id="present-output")]}), run_id=uuid4())
        return {"messages": [AIMessage(content="done")]}

    def factory(*, config):
        original = original_factory(config=config)
        graph = StateGraph(MessagesState)
        graph.add_node("answer", answer)
        graph.set_entry_point("answer")
        graph.set_finish_point("answer")
        return dataclasses.replace(original, graph=graph.compile())

    monkeypatch.setattr(services, "resolve_agent_factory", lambda _: factory)
    job = await actions["send"]({"team_id": team["id"], "member_id": author["id"], "text": "Produce", "request_id": "produce"}, context(runs, owner))
    await service.tick()
    await asyncio.wait_for(entered.wait(), 5)
    saved = await service.db("get", owner, team["id"])
    executing = next(j for j in saved["jobs"] if j["id"] == job["id"])
    tool_context = dataclasses.replace(context(runs, owner, author["thread_id"]), run_id=executing["run_id"])
    registered = (await artifact_tools(loaded)["register_team_artifact"]({"team_id": team["id"], "request_id": "file", "name": "Report", "path": "/mnt/user-data/outputs/report.txt"}, tool_context))["artifact"]
    producer_id = registered["source"]["run_id"]
    assert (await runs.get(thread_id=author["thread_id"], run_id=producer_id)).status == "running"
    finish_producer.set()
    producer = await runs.wait(thread_id=author["thread_id"], run_id=producer_id, timeout=5)
    assert producer.status == "success"
    original_read = runs.read_artifact
    later_ids = []

    async def interleave(**kwargs):
        later = await runs.start(thread_id=author["thread_id"], input={"messages": [{"role": "user", "content": "ordinary next turn"}]}, idempotency_key="later")
        later_ids.append(later.run_id)
        assert (await runs.wait(thread_id=author["thread_id"], run_id=later.run_id, timeout=5)).status == "success"
        return await original_read(**kwargs)

    if later_turn:
        monkeypatch.setattr(runs, "read_artifact", interleave)
    await service.tick()
    saved = await service.db("get", owner, team["id"])
    assert next(j for j in saved["jobs"] if j["id"] == job["id"])["status"] == "completed"
    retained = saved["artifacts"][0]
    assert retained["source"]["run_id"] == producer_id
    if later_turn:
        assert later_ids and retained["status"] == "failed"
        with pytest.raises(ValueError):
            await service.db("artifact", owner, team["id"], registered["artifact_id"], 1)
    else:
        assert retained["status"] == "ready"
        _, content = await service.db("artifact", owner, team["id"], registered["artifact_id"], 1)
        assert content == b"producer output"
