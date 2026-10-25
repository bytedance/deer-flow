"""Real PostgreSQL coordination; opt in with DEERFLOW_TEST_WORKFLOW_POSTGRES."""

import asyncio
import os
import uuid
from dataclasses import replace

import pytest
import pytest_asyncio
import test_workflow_plugin as fixtures
from test_workflow_plugin import context

plugin = fixtures.plugin
pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not os.getenv("DEERFLOW_TEST_WORKFLOW_POSTGRES"), reason="Requires dedicated PostgreSQL")]


@pytest_asyncio.fixture
async def cluster(plugin):
    import psycopg
    from deerflow_extension_workflows.service import Workflows
    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    dsn = os.environ["DEERFLOW_TEST_WORKFLOW_POSTGRES"]
    schema = "workflow_test_" + uuid.uuid4().hex
    with psycopg.connect(dsn, autocommit=True) as db:
        db.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    scoped = make_conninfo(dsn, options=f"-csearch_path={schema}")
    with psycopg.connect(scoped) as db:
        db.execute(
            "CREATE TABLE extension_execution_leases(namespace varchar(96),resource_id varchar(128),user_id varchar(64) NOT NULL,holder_id varchar(128) NOT NULL,epoch bigint NOT NULL,expires_at double precision NOT NULL,"
            "PRIMARY KEY(namespace,resource_id))"
        )
    original_start = plugin[3].start
    plugin[3].fences = []

    async def fenced_start(*, execution_fence, **kwargs):
        assert execution_fence.namespace == "community.workflows"
        plugin[3].fences.append(execution_fence)
        return await original_start(**kwargs)

    original_cancel = plugin[3].cancel

    async def fenced_cancel(*, execution_fence, **kwargs):
        assert execution_fence.namespace == "community.workflows"
        return await original_cancel(**kwargs)

    plugin[3].cancel = fenced_cancel
    plugin[3].start = fenced_start
    config = {**plugin[2].config, "storage_url": scoped, "lease_seconds": 10}
    a, b = Workflows(config), Workflows(config)
    await a.start(None)
    await b.start(None)
    try:
        yield a, b, plugin[3]
    finally:
        await asyncio.gather(a.stop(), b.stop())
        with psycopg.connect(dsn, autocommit=True) as db:
            db.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


async def test_launch_on_a_resume_on_b(cluster):
    a, b, runs = cluster
    payload = {"request_id": "same", "script": "await pause({stepId:'p'}); return 42;", "args": {}}
    first, retry = await asyncio.gather(a.launch(payload, context(runs)), b.launch(payload, context(runs)))
    assert first["run_id"] == retry["run_id"]
    run_id = first["run_id"]
    for _ in range(200):
        record = await b.get({"run_id": run_id}, context(runs))
        if record["status"] == "paused":
            break
        await asyncio.sleep(0.02)
    assert record["status"] == "paused"
    await b.resume(dict(run_id=run_id, fingerprint=record["fingerprint"], step_id="p", attempt=1), context(runs))
    await asyncio.wait_for(asyncio.gather(a.wait_idle(run_id), b.wait_idle(run_id)), 10)
    assert (await b.get({"run_id": run_id}, context(runs)))["result"] == 42


async def test_expired_owner_cannot_write_after_takeover(cluster):
    a, b, runs = cluster
    payload = {"request_id": "takeover", "script": "await pause({stepId:'p'}); return 42;", "args": {}}
    run_id = (await a.launch(payload, context(runs)))["run_id"]
    for _ in range(200):
        old = await asyncio.to_thread(a.store.get, "alice", run_id)
        if old["status"] == "paused":
            break
        await asyncio.sleep(0.02)
    a.heartbeats[run_id].cancel()
    await asyncio.gather(a.heartbeats[run_id], return_exceptions=True)

    def expire():
        from contextlib import closing

        with closing(a.store.connect()) as db, db:
            db.execute("UPDATE extension_execution_leases SET expires_at=0 WHERE resource_id=?", (run_id,))

    await asyncio.to_thread(expire)
    session = replace(context(runs), interaction="session")
    await b.recover({"run_id": run_id}, session)
    with pytest.raises(ValueError, match="lease lost"):
        await asyncio.to_thread(a.store.put, "alice", old)
    # Restore the stale owner after takeover; its next renewal must kill only
    # its own worker and leave the successor and shared record untouched.
    await a.follow_lease(a.entries[run_id])
    for _ in range(200):
        record = await b.get({"run_id": run_id}, session)
        if record["status"] == "paused":
            break
        await asyncio.sleep(0.02)
    await b.resume(dict(run_id=run_id, fingerprint=record["fingerprint"], step_id="p", attempt=1), session)
    await asyncio.wait_for(b.wait_idle(run_id), 10)
    assert (await b.get({"run_id": run_id}, session))["result"] == 42


async def test_shared_workflow_limit(cluster):
    a, b, runs = cluster
    a.config["max_workflows"] = b.config["max_workflows"] = 1
    await a.launch({"request_id": "first", "script": "await pause({stepId:'p'});", "args": {}}, context(runs))
    with pytest.raises(ValueError, match="workflow limit"):
        await b.launch({"request_id": "second", "script": "return 1;", "args": {}}, context(runs, owner="bob"))


async def poll(service, runs, run_id, status):
    for _ in range(300):
        record = await service.get({"run_id": run_id}, context(runs))
        if record["status"] == status:
            return record
        await asyncio.sleep(0.02)
    raise AssertionError(record)


async def test_cross_gateway_approval_is_exact_and_idempotent(cluster):
    a, b, runs = cluster
    run_id = (
        await a.launch(
            {
                "request_id": "approval",
                "script": "const a=await agent({stepId:'a',agentRef:'lead_agent',task:1}); await humanCheckpoint({stepId:'c',sourceStepId:'a',artifactVersion:a.artifactVersion}); "
                "return await agent({stepId:'b',agentRef:'reviewer',task:2});",
                "args": {},
            },
            context(runs),
        )
    )["run_id"]
    record = await poll(b, runs, run_id, "waiting_approval")
    session = replace(context(runs), interaction="session")
    payload = dict(run_id=run_id, step_id="c", attempt=1, artifact_version=record["checkpoints"][0]["artifact_version"], decision="approve")
    with pytest.raises(ValueError, match="exact checkpoint"):
        await b.decide({**payload, "artifact_version": "wrong"}, session)
    await asyncio.gather(a.decide(payload, session), b.decide(payload, session))
    await asyncio.wait_for(a.wait_idle(run_id), 10)
    assert (await b.get({"run_id": run_id}, session))["status"] == "completed"
    assert len(runs.starts) == 2
    assert len(runs.fences) == 2


async def test_cross_gateway_cancel_and_revocation(cluster):
    a, b, runs = cluster
    run_id = (await a.launch({"request_id": "cancel", "script": "await pause({stepId:'p'}); return 1;", "args": {}}, context(runs)))["run_id"]
    record = await poll(b, runs, run_id, "paused")
    runs.denied = True
    with pytest.raises(Exception, match="revoked"):
        await b.resume(dict(run_id=run_id, fingerprint=record["fingerprint"], step_id="p", attempt=1), context(runs))
    runs.denied = False
    await b.cancel({"run_id": run_id}, context(runs))
    await asyncio.wait_for(a.wait_idle(run_id), 10)
    assert (await b.get({"run_id": run_id}, context(runs)))["status"] == "cancelled"


async def test_real_owner_kill_during_review_and_rolling_upgrade(cluster):
    import json
    import sys
    from pathlib import Path

    a, b, runs = cluster
    root = Path(__file__).resolve().parents[2]
    program = r"""
import asyncio,json,sys
from deerflow_extension_workflows.service import Workflows
from test_workflow_plugin import Runs,context
async def main():
    service=Workflows(json.loads(sys.argv[1]));await service.start(None)
    runs=Runs()
    result=await service.launch({'request_id':'killed-owner','script':"await pause({stepId:'p'}); return 7;",'args':{}},context(runs))
    while (await service.get({'run_id':result['run_id']},context(runs)))['status']!='paused':
        await asyncio.sleep(.01)
    print(result['run_id'],flush=True)
    await asyncio.Event().wait()
asyncio.run(main())
"""
    child = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        program,
        json.dumps(a.config),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, "PYTHONPATH": os.pathsep.join([str(root / "examples/deerflow-extension-workflows"), str(root / "backend/tests"), str(root / "backend")])},
    )
    try:
        run_id = (await asyncio.wait_for(child.stdout.readline(), 10)).decode().strip()
        assert len(run_id) == 32
    finally:
        child.kill()
        await child.wait()

    def expire():
        from contextlib import closing

        with closing(b.store.connect()) as db, db:
            db.execute("UPDATE extension_execution_leases SET expires_at=0 WHERE resource_id=?", (run_id,))

    await asyncio.to_thread(expire)
    session = replace(context(runs), interaction="session")
    version = b.runtime_version
    b.runtime_version = "incompatible-upgrade"
    with pytest.raises(ValueError, match="runtime version"):
        await b.recover({"run_id": run_id}, session)
    b.runtime_version = version
    runs.denied = True
    with pytest.raises(Exception, match="revoked"):
        await b.recover({"run_id": run_id}, session)
    runs.denied = False
    await b.recover({"run_id": run_id}, session)
    record = await poll(b, runs, run_id, "paused")
    await b.resume(dict(run_id=run_id, fingerprint=record["fingerprint"], step_id="p", attempt=1), session)
    await asyncio.wait_for(b.wait_idle(run_id), 10)
    assert (await b.get({"run_id": run_id}, session))["result"] == 7


async def test_cancel_keeps_lease_until_child_cleanup_finishes(cluster, monkeypatch):
    a, b, runs = cluster
    cleaning = asyncio.Event()
    finish_cleanup = asyncio.Event()
    original_cancel = a.cancel_child

    async def held_cancel(*args, **kwargs):
        cleaning.set()
        await finish_cleanup.wait()
        return await original_cancel(*args, **kwargs)

    monkeypatch.setattr(a, "cancel_child", held_cancel)
    script = "return await agent({stepId:'a',agentRef:'lead_agent',task:'blocked'});"
    run_id = (await a.launch({"request_id": "cleanup-lease", "script": script, "args": {}}, context(runs)))["run_id"]
    await asyncio.wait_for(runs.entered.wait(), 5)
    try:
        # Agent admission signals before the supervisor persists its run ID.
        # Wait for that commit so remote cancel does not race its revision CAS.
        async with asyncio.timeout(5):
            while True:
                record = await b.get({"run_id": run_id}, context(runs))
                if record["steps"][0]["status"] == "running":
                    break
                await asyncio.sleep(0.01)
        await b.cancel({"run_id": run_id}, context(runs))
        await asyncio.wait_for(cleaning.wait(), 5)
        # The supervisor has stopped its worker but is still draining the child.
        async with asyncio.timeout(5):
            while run_id in a.processes:
                await asyncio.sleep(0.01)
    finally:
        finish_cleanup.set()
    await asyncio.wait_for(a.wait_idle(run_id), 10)
    record = await b.get({"run_id": run_id}, context(runs))
    assert record["status"] == "cancelled"
    assert record["steps"][0]["status"] == "cancelled"
    assert not a.entries


async def test_shared_child_quota_and_cancel(cluster):
    a, b, runs = cluster
    a.config["global_concurrency"] = b.config["global_concurrency"] = 1
    script = "return await agent({stepId:'a',agentRef:'lead_agent',task:'blocked'});"
    first = (await a.launch({"request_id": "slot-a", "script": script, "args": {}}, context(runs)))["run_id"]
    await asyncio.wait_for(runs.entered.wait(), 5)
    second = (await b.launch({"request_id": "slot-b", "script": script, "args": {}}, context(runs)))["run_id"]
    await asyncio.sleep(0.2)
    assert len(runs.starts) == 1
    await b.cancel({"run_id": first}, context(runs))
    await asyncio.wait_for(a.wait_idle(first), 10)
    await asyncio.wait_for(b.wait_idle(second), 10)
    assert len(runs.starts) == 2
    assert runs.peak == 1


async def test_capture_is_fenced_and_immutable(cluster):
    a, b, runs = cluster
    run_id = (await a.launch({"request_id": "file", "script": "await pause({stepId:'p'});", "args": {}}, context(runs)))["run_id"]
    await poll(a, runs, run_id, "paused")
    record = await asyncio.to_thread(a.store.get, "alice", run_id)
    with pytest.raises(ValueError, match="lease lost"):
        await asyncio.to_thread(b.store.capture_artifact, "alice", run_id, "file", "report.txt", b"wrong", execution_record=record)
    info = await asyncio.to_thread(a.store.capture_artifact, "alice", run_id, "file", "report.txt", b"original", execution_record=record)
    assert (await asyncio.to_thread(b.store.artifact, "alice", run_id, info["version"]))[1] == b"original"
    with pytest.raises(ValueError, match="overwritten"):
        await asyncio.to_thread(a.store.capture_artifact, "alice", run_id, "file", "report.txt", b"changed", execution_record=record)


@pytest.mark.parametrize("boundary", ["admission", "result", "approval"])
async def test_cross_gateway_recovery_persistence_boundaries(cluster, monkeypatch, boundary):
    import copy
    import json
    from contextlib import closing

    a, b, runs = cluster
    snapshots = []
    original = runs.start if boundary == "admission" else runs.configuration_evidence

    async def capture(**kwargs):
        value = await original(**kwargs)
        entry = next(iter(a.entries.values()))
        snapshots.append(await asyncio.to_thread(a.store.get, "alice", entry["record"]["id"]))
        return value

    if boundary != "approval":
        monkeypatch.setattr(runs, "start" if boundary == "admission" else "configuration_evidence", capture)
    script = "const a=await agent({stepId:'a',agentRef:'lead_agent',task:1}); await humanCheckpoint({stepId:'c',sourceStepId:'a',artifactVersion:a.artifactVersion}); return await agent({stepId:'b',agentRef:'reviewer',task:2});"
    run_id = (await a.launch({"request_id": boundary, "script": script, "args": {}}, context(runs)))["run_id"]
    record = await poll(a, runs, run_id, "waiting_approval")
    session = replace(context(runs), interaction="session")
    if boundary == "approval":
        a.heartbeats[run_id].cancel()
        await asyncio.gather(a.heartbeats[run_id], return_exceptions=True)
        await b.decide(dict(run_id=run_id, step_id="c", attempt=1, artifact_version=record["checkpoints"][0]["artifact_version"], decision="approve"), session)
        snapshots.append(await asyncio.to_thread(a.store.get, "alice", run_id))
    snapshot = copy.deepcopy(snapshots[0])
    if boundary != "approval":
        monkeypatch.setattr(runs, "start" if boundary == "admission" else "configuration_evidence", original)
    await a.stop()

    def install_crash_image():
        with closing(b.store.connect()) as db, db:
            revision = db.execute("SELECT revision FROM workflows WHERE id=?", (run_id,)).fetchone()[0] + 1
            snapshot["revision"] = revision
            db.execute("UPDATE workflows SET data=?,status=?,revision=? WHERE id=?", (json.dumps(snapshot), snapshot["status"], revision, run_id))
            db.execute("UPDATE extension_execution_leases SET expires_at=0 WHERE resource_id=?", (run_id,))

    await asyncio.to_thread(install_crash_image)
    restored = await b.recover({"run_id": run_id}, session)
    if boundary == "admission":
        assert restored["status"] == "needs_reconciliation"
        assert len(runs.starts) == 1
    else:
        if boundary == "result":
            record = await poll(b, runs, run_id, "waiting_approval")
            await b.decide(dict(run_id=run_id, step_id="c", attempt=1, artifact_version=record["checkpoints"][0]["artifact_version"], decision="approve"), session)
        await asyncio.wait_for(b.wait_idle(run_id), 10)
        assert (await b.get({"run_id": run_id}, session))["status"] == "completed"
        assert len(runs.starts) == 2


async def test_expired_cancel_command_cannot_resume_dispatch(cluster):
    from contextlib import closing

    a, b, runs = cluster
    run_id = (await a.launch({"request_id": "cancel-before-crash", "script": "await pause({stepId:'p'}); return 1;", "args": {}}, context(runs)))["run_id"]
    await poll(a, runs, run_id, "paused")
    a.heartbeats[run_id].cancel()
    await asyncio.gather(a.heartbeats[run_id], return_exceptions=True)
    await b.cancel({"run_id": run_id}, context(runs))

    def expire():
        with closing(b.store.connect()) as db, db:
            db.execute("UPDATE extension_execution_leases SET expires_at=0 WHERE resource_id=?", (run_id,))

    await asyncio.to_thread(expire)
    session = replace(context(runs), interaction="session")
    with pytest.raises(ValueError, match="Cancellation pending"):
        await b.recover({"run_id": run_id}, session)
    await a.follow_lease(a.entries[run_id])
    await b.cancel({"run_id": run_id}, session)
    assert (await b.get({"run_id": run_id}, session))["status"] == "cancelled"


async def test_cluster_policy_rejects_mismatched_replica(cluster):
    from deerflow_extension_workflows.service import Workflows

    a, _, _ = cluster
    peer = Workflows({**a.config, "global_concurrency": 1})
    with pytest.raises(ValueError, match="cluster limits differ"):
        await peer.start(None)


async def test_peer_rejects_configuration_change_and_expired_review(cluster):
    import json
    from contextlib import closing

    a, b, runs = cluster
    run_id = (await a.launch({"request_id": "config", "script": "await pause({stepId:'p'}); return 1;", "args": {}}, context(runs)))["run_id"]
    record = await poll(a, runs, run_id, "paused")
    payload = dict(run_id=run_id, fingerprint=record["fingerprint"], step_id="p", attempt=1)
    runs.revision = "changed-config"
    with pytest.raises(ValueError, match="configuration changed"):
        await b.resume(payload, context(runs))
    runs.revision = "initial"
    a.heartbeats[run_id].cancel()
    await asyncio.gather(a.heartbeats[run_id], return_exceptions=True)

    def expire_checkpoint():
        with closing(b.store.connect()) as db, db:
            retained = json.loads(db.execute("SELECT data FROM workflows WHERE id=?", (run_id,)).fetchone()[0])
            retained["pause_expires_at"] = 0
            db.execute("UPDATE workflows SET data=? WHERE id=?", (json.dumps(retained), run_id))

    await asyncio.to_thread(expire_checkpoint)
    with pytest.raises(ValueError, match="expired"):
        await b.resume(payload, context(runs))


@pytest.mark.parametrize("saturated", [False, True])
async def test_expired_cancelling_can_finish_cleanup_and_delete(cluster, saturated):
    import copy
    from contextlib import closing

    a, b, runs = cluster
    run_id = (await a.launch({"request_id": "cancel-recovery", "script": "await pause({stepId:'p'}); return 1;", "args": {}}, context(runs)))["run_id"]
    await poll(a, runs, run_id, "paused")
    await a.stop()

    # Crash image of cancel_recovered after persisting cancelling, before cleanup.
    def crash():
        with closing(b.store.connect()) as db, db:
            import json

            record = json.loads(db.execute("SELECT data FROM workflows WHERE id=?", (run_id,)).fetchone()[0])
            record["status"] = "cancelling"
            db.execute("UPDATE workflows SET status='cancelling',data=? WHERE id=?", (json.dumps(record), run_id))
            db.execute("UPDATE extension_execution_leases SET expires_at=0 WHERE resource_id=?", (run_id,))
            if saturated:
                # Other active rows already consume both budget ceilings.
                for i in range(max(b.config["max_workflows"], b.config["max_workflows_per_owner"])):
                    other = copy.deepcopy(record)
                    other.update(id=f"occupied-{i}", status="running")
                    db.execute("INSERT INTO workflows(id,owner,request_id,fingerprint,status,data) VALUES (?,?,?,?,?,?)", (other["id"], "alice", other["id"], "occupied", "running", json.dumps(other)))

    await asyncio.to_thread(crash)
    session = replace(context(runs), interaction="session")
    with pytest.raises(ValueError, match="Cancellation pending"):
        await b.recover({"run_id": run_id}, session)
    result = await b.cancel({"run_id": run_id}, session)
    assert result["status"] == "cancelled"
    await b.delete({"run_id": run_id}, session)
    with pytest.raises(ValueError, match="unavailable"):
        await b.get({"run_id": run_id}, session)
    assert not runs.starts


async def test_reads_do_not_wait_for_cluster_budget_lock(cluster):
    import psycopg
    from deerflow_extension_workflows.postgres import LOCK

    a, b, runs = cluster
    run_id = (await a.launch({"request_id": "read-lock", "script": "return 1;", "args": {}}, context(runs)))["run_id"]
    await poll(a, runs, run_id, "completed")
    with psycopg.connect(b.store.dsn) as blocker:
        blocker.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK,))
        # A real held advisory lock makes the old read path hit lock_timeout.
        assert (await asyncio.to_thread(b.store.get, "alice", run_id))["status"] == "completed"
        assert [r["id"] for r in await asyncio.to_thread(b.store.list, "alice")] == [run_id]
        assert await asyncio.to_thread(b.store.list, "other") == []


@pytest.mark.parametrize("failure", ["permission", "configuration", "uncertain"])
async def test_rejected_admission_slot_accounting(cluster, monkeypatch, failure):
    from contextlib import closing

    from deerflow_extension_api import AgentRunError

    a, b, runs = cluster
    a.config["global_concurrency"] = b.config["global_concurrency"] = 1
    original_start = runs.start
    original_check = a.check_configuration

    async def reject_start(**kwargs):
        raise AgentRunError(403 if failure == "permission" else 503, "synthetic rejection")

    async def reject_step_configuration(entry):
        if entry["record"]["steps"]:
            raise ValueError("Configuration changed")
        await original_check(entry)

    if failure == "configuration":
        monkeypatch.setattr(a, "check_configuration", reject_step_configuration)
    else:
        monkeypatch.setattr(runs, "start", reject_start)
    script = "return await agent({stepId:'a',agentRef:'lead_agent',task:'hello'});"
    run_id = (await a.launch({"request_id": "rejected", "script": script, "args": {}}, context(runs)))["run_id"]
    await asyncio.wait_for(a.wait_idle(run_id), 10)
    assert not runs.starts

    def slots():
        with closing(a.store.connect(readonly=True)) as db:
            return db.execute("SELECT count(*) FROM workflow_slots").fetchone()[0]

    assert await asyncio.to_thread(slots) == (1 if failure == "uncertain" else 0)
    if failure == "uncertain":
        with pytest.raises(ValueError, match="Reconcile retained"):
            await b.delete({"run_id": run_id}, context(runs))
        return
    await b.delete({"run_id": run_id}, context(runs))
    monkeypatch.setattr(runs, "start", original_start)
    peer = (await b.launch({"request_id": "peer-after-rejection", "script": script, "args": {}}, context(runs)))["run_id"]
    await asyncio.wait_for(b.wait_idle(peer), 10)
    assert (await b.get({"run_id": peer}, context(runs)))["status"] == "completed"
    assert len(runs.starts) == 1
