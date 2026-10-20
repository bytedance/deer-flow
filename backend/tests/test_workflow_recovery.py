"""Recovery exercises the isolated script worker and durable SQLite boundaries."""

import asyncio
import copy
import os
from dataclasses import replace

import pytest
import test_workflow_plugin as fixtures
from test_workflow_plugin import context, done, launch, waiting

plugin = fixtures.plugin


pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(os.name != "posix", reason="Workflow execution requires POSIX")]


async def restart_snapshot(plugin, run_id):
    """Retain the last committed crash image, without shutdown's cleanup writes."""
    service = plugin[2]
    record = await asyncio.to_thread(service.store.get, "alice", run_id)
    await service.stop()
    current = await asyncio.to_thread(service.store.get, "alice", run_id)
    record["revision"] = current.get("revision", 0)
    await asyncio.to_thread(service.store.put, "alice", record)
    await service.start(None)
    return record


async def test_restart_approval_reuses_outputs_and_exact_version(plugin):
    _, actions, service, runs = plugin
    result = await launch(
        plugin,
        "const a=await agent({stepId:'a',agentRef:'lead_agent',task:1}); await humanCheckpoint({stepId:'review',sourceStepId:'a',artifactVersion:a.artifactVersion}); return await agent({stepId:'b',agentRef:'reviewer',task:a.output});",
    )
    run_id = result["run_id"]
    paused = await waiting(plugin, run_id, "waiting_approval")
    await restart_snapshot(plugin, run_id)
    assert (await actions["get"]({"run_id": run_id}, context(runs)))["status"] == "recoverable"
    session = replace(context(runs), interaction="session")
    await actions["recover"]({"run_id": run_id}, session)
    recovered = await waiting(plugin, run_id, "waiting_approval")
    assert recovered["checkpoints"] == paused["checkpoints"]
    checkpoint = recovered["checkpoints"][0]
    payload = dict(run_id=run_id, step_id="review", attempt=1, artifact_version=checkpoint["artifact_version"], decision="approve")
    await asyncio.gather(actions["decide"](payload, session), actions["decide"](payload, session))
    final = await done(plugin, run_id)
    assert final["status"] == "completed", final
    assert len(runs.starts) == 2


async def test_recovery_rejects_changed_config_and_revoked_permission(plugin):
    from deerflow_extension_api import AgentRunError

    _, actions, service, runs = plugin
    run_id = (await launch(plugin, "await pause({stepId:'p'}); return 1;"))["run_id"]
    await waiting(plugin, run_id, "paused")
    await restart_snapshot(plugin, run_id)
    session = replace(context(runs), interaction="session")
    runs.denied = True
    with pytest.raises(AgentRunError):
        await actions["recover"]({"run_id": run_id}, session)
    runs.denied = False
    runs.revision = "changed"
    with pytest.raises(ValueError, match="configuration"):
        await actions["recover"]({"run_id": run_id}, session)
    assert not runs.starts


async def test_store_rejects_stale_revision(plugin):
    service = plugin[2]
    run_id = (await launch(plugin, "return 1;"))["run_id"]
    await done(plugin, run_id)
    first = await asyncio.to_thread(service.store.get, "alice", run_id)
    stale = copy.deepcopy(first)
    await asyncio.to_thread(service.store.put, "alice", first)
    with pytest.raises(ValueError, match="revision"):
        await asyncio.to_thread(service.store.put, "alice", stale)


async def install_snapshot(plugin, record):
    service = plugin[2]
    await service.stop()
    latest = await asyncio.to_thread(service.store.get, "alice", record["id"])
    record = copy.deepcopy(record)
    record["revision"] = latest.get("revision", 0)
    await asyncio.to_thread(service.store.put, "alice", record)
    await service.start(None)


async def test_approval_committed_before_dispatch_recovers_once(plugin):
    _, actions, service, runs = plugin
    run_id = (
        await launch(
            plugin, "const a=await agent({stepId:'a',agentRef:'lead_agent',task:1}); await humanCheckpoint({stepId:'c',sourceStepId:'a',artifactVersion:a.artifactVersion}); return await agent({stepId:'b',agentRef:'reviewer',task:2});"
        )
    )["run_id"]
    await waiting(plugin, run_id, "waiting_approval")
    record = await asyncio.to_thread(service.store.get, "alice", run_id)
    record["checkpoints"][0].update(status="approved", decided_by="alice", decided_at=1)
    await install_snapshot(plugin, record)
    session = replace(context(runs), interaction="session")
    await asyncio.gather(actions["recover"]({"run_id": run_id}, session), actions["recover"]({"run_id": run_id}, session))
    result = await done(plugin, run_id)
    assert result["status"] == "completed", result
    assert len(runs.starts) == 2


@pytest.mark.parametrize("boundary", ["admission", "result"])
async def test_child_crash_boundaries_never_repeat_dispatch(plugin, monkeypatch, boundary):
    _, actions, service, runs = plugin
    snapshots = []
    original = runs.start if boundary == "admission" else runs.configuration_evidence

    async def capture(**kw):
        value = await original(**kw)
        entry = next(iter(service.entries.values()))
        snapshots.append(await asyncio.to_thread(service.store.get, "alice", entry["record"]["id"]))
        return value

    monkeypatch.setattr(runs, "start" if boundary == "admission" else "configuration_evidence", capture)
    run_id = (await launch(plugin, "return await agent({stepId:'a',agentRef:'lead_agent',task:1});"))["run_id"]
    await done(plugin, run_id)
    await install_snapshot(plugin, snapshots[0])
    session = replace(context(runs), interaction="session")
    result = await actions["recover"]({"run_id": run_id}, session)
    if boundary == "admission":
        assert result["status"] == "needs_reconciliation"
    else:
        final = await done(plugin, run_id)
        assert final["status"] == "completed", final
        assert final["result"]["output"] == {"echo": 1}
    assert len(runs.starts) == 1


async def test_parallel_results_and_file_approval_survive_restart(plugin):
    _, actions, service, runs = plugin
    script = (
        "const results=await parallel([()=>agent({stepId:'a',agentRef:'lead_agent',task:1}),()=>agent({stepId:'b',agentRef:'reviewer',task:2})]); "
        "const file=await captureArtifact({stepId:'f',sourceStepId:'a',path:'report.txt'}); "
        "await humanCheckpoint({stepId:'c',sourceStepId:'f',artifactVersion:file.artifactVersion}); "
        "return await readArtifact({artifactVersion:file.artifactVersion});"
    )
    run_id = (await launch(plugin, script))["run_id"]
    paused = await waiting(plugin, run_id, "waiting_approval")
    await restart_snapshot(plugin, run_id)
    runs.file_content = b"changed source must not be read"
    session = replace(context(runs), interaction="session")
    await actions["recover"]({"run_id": run_id}, session)
    await waiting(plugin, run_id, "waiting_approval")
    await actions["decide"](dict(run_id=run_id, step_id="c", attempt=1, artifact_version=paused["checkpoints"][0]["artifact_version"], decision="approve"), session)
    final = await done(plugin, run_id)
    assert final["status"] == "completed", final
    import base64

    assert base64.b64decode(final["result"]["content_base64"]) == b"original file"
    assert len(runs.starts) == 2


async def test_real_process_kill_during_review(plugin):
    import json
    import os
    import sys
    from pathlib import Path

    _, actions, service, runs = plugin
    await service.stop()
    root = Path(__file__).resolve().parents[2]
    program = r"""
import asyncio,json,sys
from deerflow_extension_workflows.service import Workflows
from test_workflow_plugin import Runs,context
async def main():
    service=Workflows(json.loads(sys.argv[1]));await service.start(None)
    runs=Runs()
    result=await service.launch({'request_id':'kill-test','script':("const a=await agent({stepId:'a',agentRef:'lead_agent',task:1}); "
        "await humanCheckpoint({stepId:'c',sourceStepId:'a',artifactVersion:a.artifactVersion}); return a.output;"),'args':{}},context(runs))
    while True:
        state=await service.get({'run_id':result['run_id']},context(runs))
        if state['status']=='waiting_approval':break
        await asyncio.sleep(.01)
    print(result['run_id'],flush=True)
    await asyncio.Event().wait()
asyncio.run(main())
"""
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(root / "backend/tests"), str(root / "backend"), str(root / "examples/deerflow-extension-workflows")])}
    child = await asyncio.create_subprocess_exec(sys.executable, "-c", program, json.dumps(service.config), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env)
    try:
        async with asyncio.timeout(30):
            run_id = (await child.stdout.readline()).decode().strip()
        assert len(run_id) == 32, (await child.stderr.read()).decode() if child.returncode is not None else run_id
        child.kill()
        await child.wait()
        await service.start(None)
        state = await actions["get"]({"run_id": run_id}, context(runs))
        assert state["status"] == "recoverable"
        session = replace(context(runs), interaction="session")
        await actions["recover"]({"run_id": run_id}, session)
        state = await waiting(plugin, run_id, "waiting_approval")
        await actions["decide"](dict(run_id=run_id, step_id="c", attempt=1, artifact_version=state["checkpoints"][0]["artifact_version"], decision="approve"), session)
        final = await done(plugin, run_id)
        assert final["status"] == "completed", final
        assert final["result"] == {"echo": 1}
        assert not runs.starts
    finally:
        if child.returncode is None:
            child.kill()
            await child.wait()


async def test_graceful_shutdown_pause_and_cancel_recovery(plugin):
    _, actions, service, runs = plugin
    run_id = (await launch(plugin, "await pause({stepId:'p'}); return 7;"))["run_id"]
    await waiting(plugin, run_id, "paused")
    await service.stop()
    await service.start(None)
    session = replace(context(runs), interaction="session")
    assert (await actions["get"]({"run_id": run_id}, session))["status"] == "recoverable"
    await actions["cancel"]({"run_id": run_id}, session)
    with pytest.raises(ValueError, match="not recoverable"):
        await actions["recover"]({"run_id": run_id}, session)
    assert not runs.starts


@pytest.mark.parametrize("change", ["runtime", "journal", "expiry", "owner", "tool"])
async def test_recovery_guards_prevent_new_dispatch(plugin, change):
    from deerflow_extension_api import ExtensionPrincipal
    from deerflow_extension_api.plugins import ToolContext

    _, actions, service, runs = plugin
    run_id = (await launch(plugin, "await pause({stepId:'p'}); return await agent({stepId:'a',agentRef:'lead_agent',task:1});"))["run_id"]
    await waiting(plugin, run_id, "paused")
    record = await asyncio.to_thread(service.store.get, "alice", run_id)
    if change == "runtime":
        record["runtime_version"] = "incompatible"
    if change == "journal":
        record["journal"][0]["frame"]["messages"][0]["payload"]["stepId"] = "changed"
    if change == "expiry":
        record["pause_expires_at"] = 1
    await install_snapshot(plugin, record)
    session = replace(context(runs), interaction="session")
    if change == "owner":
        session = replace(session, principal=ExtensionPrincipal("bob"))
    if change == "tool":
        session = ToolContext(session.principal, session.settings, "thread", agent_runs=runs)
    if change in ("runtime", "owner", "tool"):
        with pytest.raises(ValueError):
            await actions["recover"]({"run_id": run_id}, session)
    else:
        await actions["recover"]({"run_id": run_id}, session)
        final = await done(plugin, run_id)
        assert final["status"] == "failed", final
    assert not runs.starts


async def test_file_capture_commit_before_metadata_reuses_original_bytes(plugin, monkeypatch):
    _, actions, service, runs = plugin
    snapshots = []
    capture = service.store.capture_artifact

    def capture_before_metadata(owner, workflow, *args):
        result = capture(owner, workflow, *args)
        snapshots.append(service.store.get(owner, workflow))
        return result

    monkeypatch.setattr(service.store, "capture_artifact", capture_before_metadata)
    run_id = (await launch(plugin, "await agent({stepId:'a',agentRef:'lead_agent',task:1}); return await captureArtifact({stepId:'f',sourceStepId:'a',path:'report.txt'});"))["run_id"]
    final = await done(plugin, run_id)
    assert final["status"] == "completed"
    version = final["result"]["artifactVersion"]
    await install_snapshot(plugin, snapshots[0])
    runs.file_content = b"new mutable source"
    await actions["recover"]({"run_id": run_id}, replace(context(runs), interaction="session"))
    recovered = await done(plugin, run_id)
    assert recovered["status"] == "completed", recovered
    assert recovered["result"]["artifactVersion"] == version
    assert (await asyncio.to_thread(service.store.artifact, "alice", run_id, version))[1] == b"original file"
    assert len(runs.starts) == 1


async def test_recovered_interrupted_child_cannot_dispatch_even_when_script_catches(plugin, monkeypatch):
    from deerflow_extension_api import AgentRun

    _, actions, service, runs = plugin
    snapshots = []
    original = runs.configuration_evidence

    async def snapshot(**kwargs):
        entry = next(iter(service.entries.values()))
        snapshots.append(await asyncio.to_thread(service.store.get, "alice", entry["record"]["id"]))
        return await original(**kwargs)

    monkeypatch.setattr(runs, "configuration_evidence", snapshot)
    run_id = (await launch(plugin, "try {await agent({stepId:'a',agentRef:'lead_agent',task:1});} catch(e) {} await pause({stepId:'p'}); return await agent({stepId:'b',agentRef:'reviewer',task:2});"))["run_id"]
    await waiting(plugin, run_id, "paused")
    record = snapshots[0]
    row = record["steps"][0]
    runs.runs[row["run_id"]] = AgentRun(row["thread_id"], row["run_id"], "interrupted")
    await install_snapshot(plugin, record)
    await actions["recover"]({"run_id": run_id}, replace(context(runs), interaction="session"))
    final = await done(plugin, run_id)
    assert final["status"] == "needs_reconciliation", final
    assert len(runs.starts) == 1


async def test_recovered_cancel_survives_caller_cancellation(plugin, monkeypatch):
    _, actions, service, runs = plugin
    run_id = (await launch(plugin, "return await agent({stepId:'a',agentRef:'lead_agent',task:1});"))["run_id"]
    await done(plugin, run_id)
    record = await asyncio.to_thread(service.store.get, "alice", run_id)
    record["status"] = "running"
    record["steps"][0]["status"] = "running"
    await install_snapshot(plugin, record)
    child_id = record["steps"][0]["run_id"]
    runs.runs[child_id] = replace(runs.runs[child_id], status="running")
    entered, release = asyncio.Event(), asyncio.Event()
    original = service.cancel_child

    async def blocked_cancel(capability, row):
        entered.set()
        await release.wait()
        await original(capability, row)

    monkeypatch.setattr(service, "cancel_child", blocked_cancel)
    caller = asyncio.create_task(actions["cancel"]({"run_id": run_id}, context(runs)))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        caller.cancel()
        with pytest.raises(asyncio.CancelledError):
            await caller
        assert service.admissions, "Service must retain ownership of child cleanup"
    finally:
        release.set()
        await asyncio.gather(caller, *list(service.admissions), return_exceptions=True)
    final = await actions["get"]({"run_id": run_id}, context(runs))
    assert final["status"] == "cancelled", final
    assert final["steps"][0]["child_status"] == "interrupted"
    assert (await actions["cancel"]({"run_id": run_id}, context(runs)))["status"] == "cancelled"


async def test_save_drains_repeated_cancellation_before_unlocking(plugin, monkeypatch):
    import threading

    service = plugin[2]
    run_id = (await launch(plugin, "return 1;"))["run_id"]
    await done(plugin, run_id)
    record = await asyncio.to_thread(service.store.get, "alice", run_id)
    revision = record["revision"]
    entered, release = asyncio.Event(), threading.Event()
    loop = asyncio.get_running_loop()
    original = service.store.put

    def blocked_put(owner, snapshot):
        loop.call_soon_threadsafe(entered.set)
        assert release.wait(10), "Test did not release SQLite write"
        return original(owner, snapshot)

    monkeypatch.setattr(service.store, "put", blocked_put)
    caller = asyncio.create_task(service.save("alice", record))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        for _ in range(2):
            caller.cancel()
            for _ in range(3):
                await asyncio.sleep(0)
        assert service.write_lock.locked(), "Do not unlock while SQLite is still committing"
        assert not caller.done(), "Cancellation must wait for revision publication"
    finally:
        release.set()
        await asyncio.gather(caller, return_exceptions=True)
    assert caller.cancelled()
    assert record["revision"] == revision + 1
    assert (await asyncio.to_thread(service.store.get, "alice", run_id))["revision"] == record["revision"]
    await service.save("alice", record)
    assert record["revision"] == revision + 2


async def test_disconnected_cancel_logs_terminal_save_failure(plugin, monkeypatch, caplog):
    _, actions, service, runs = plugin
    run_id = (await launch(plugin, "await pause({stepId:'p'}); return 1;"))["run_id"]
    await waiting(plugin, run_id, "paused")
    await restart_snapshot(plugin, run_id)
    entered, release = asyncio.Event(), asyncio.Event()
    original = service.save

    async def fail_terminal_save(owner, record):
        if record["status"] == "cancelled":
            entered.set()
            await release.wait()
            raise OSError("synthetic storage failure")
        await original(owner, record)

    monkeypatch.setattr(service, "save", fail_terminal_save)
    caller = asyncio.create_task(actions["cancel"]({"run_id": run_id}, context(runs)))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        caller.cancel()
        with pytest.raises(asyncio.CancelledError):
            await caller
    finally:
        release.set()
        await asyncio.gather(caller, *list(service.admissions), return_exceptions=True)
    final = await actions["get"]({"run_id": run_id}, context(runs))
    assert final["status"] == "cancelling"
    assert not service.admissions
    errors = [r for r in caplog.records if r.levelname == "ERROR" and r.name == type(service).__module__]
    assert len(errors) == 1
    assert "OSError" in errors[0].message
