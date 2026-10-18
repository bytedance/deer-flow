"""C capabilities bind the original native admission and assignment."""

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def source(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "packages" / "ecs-executor"))


def test_native_capability_rejects_changed_snapshot_and_assignment():
    from ecs_executor.agent_dispatch import sign_native_launch, verify_native_launch

    job = {
        "id": "job",
        "node_id": "node",
        "generation": "generation",
        "worker_owner": "worker",
        "native": {"run_id": "run", "user_id": "owner", "thread_id": "thread", "incarnation": "incarnation", "kwargs": {"input": {"messages": []}}, "goal": None},
    }
    token = sign_native_launch(job, "node-secret-operator-fixture-32-bytes")
    assert verify_native_launch(job, token, "node-secret-operator-fixture-32-bytes") == job["native"]
    for field in ("generation", "node_id", "worker_owner"):
        with pytest.raises(ValueError, match="capability"):
            verify_native_launch({**job, field: "changed"}, token, "node-secret-operator-fixture-32-bytes")
    with pytest.raises(ValueError, match="capability"):
        verify_native_launch({**job, "native": {**job["native"], "user_id": "other"}}, token, "node-secret-operator-fixture-32-bytes")


@pytest.mark.asyncio
async def test_native_adoption_rejects_changed_durable_payload_before_owner_transfer(tmp_path):
    from types import SimpleNamespace

    from ecs_executor.agent_dispatch import sign_native_launch
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.gateway.native_admission import adopt_native_run
    from deerflow.config.run_ownership_config import RunOwnershipConfig
    from deerflow.persistence.base import Base
    from deerflow.persistence.run import RunRepository
    from deerflow.runtime import RunManager

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'runs.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        store = RunRepository(async_sessionmaker(engine, expire_on_commit=False))
        central = RunManager(store, worker_id="central", run_ownership_config=RunOwnershipConfig(heartbeat_enabled=True))
        worker = RunManager(store, worker_id="worker", run_ownership_config=RunOwnershipConfig(heartbeat_enabled=True))
        record = await central.create_or_reject("thread", user_id="owner", kwargs={"input": {"messages": []}})
        await central.handoff_pending(record.run_id, owner_worker_id="dispatch:job")
        native = {
            "run_id": record.run_id,
            "user_id": "owner",
            "thread_id": "thread",
            "incarnation": "incarnation",
            "kwargs": {"input": {"messages": ["changed"]}},
            "assistant_id": record.assistant_id,
            "metadata": record.metadata,
            "goal": None,
        }
        job = {"id": "job", "node_id": "node", "generation": "gen", "worker_owner": "outbound", "native": native}
        secret = "node-secret-operator-fixture-32-bytes"
        app = SimpleNamespace(state=SimpleNamespace(run_manager=worker))
        with pytest.raises(ValueError, match="admission"):
            await adopt_native_run(app, job, sign_native_launch(job, secret), secret)
        assert (await store.get(record.run_id, user_id="owner"))["owner_worker_id"] == "dispatch:job"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_queued_native_dispatch_cancellation_is_owner_fenced(tmp_path):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from deerflow.persistence.base import Base
    from deerflow.persistence.run import RunRepository

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'cancel.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        store = RunRepository(async_sessionmaker(engine, expire_on_commit=False))
        await store.put("run", thread_id="thread", user_id="owner", owner_worker_id="dispatch:job")
        await store.request_cancel("run", action="interrupt")
        assert not await store.finish_dispatch_pending("run", owner_worker_id="dispatch:job", error="refusal lost to cancellation")
        assert not await store.finish_dispatch_pending("run", owner_worker_id="stale")
        assert await store.finish_dispatch_pending("run", owner_worker_id="dispatch:job")
        assert (await store.get("run", user_id="owner"))["status"] == "interrupted"
        assert not await store.finish_dispatch_pending("run", owner_worker_id="dispatch:job")
    finally:
        await engine.dispose()


def test_native_stop_requires_initialized_physical_provider(monkeypatch):
    from ecs_executor.agent_dispatch import stop_native_sandbox

    from deerflow.sandbox import sandbox_provider

    monkeypatch.setattr(sandbox_provider, "get_initialized_sandbox_provider", lambda: None)
    with pytest.raises(RuntimeError, match="unconfirmed"):
        stop_native_sandbox({"thread_id": "thread", "user_id": "owner"})


@pytest.mark.asyncio
async def test_native_terminal_success_does_not_request_cancellation():
    from types import SimpleNamespace

    from ecs_executor.agent_dispatch import NativeDispatchHost

    changes = []
    job = {"id": "job", "kind": "C", "state": "running", "native": {"run_id": "run", "user_id": "owner"}}

    async def get(*args, **kwargs):
        return {"status": "success", "owner_worker_id": "worker", "cancel_action": None}

    store = SimpleNamespace(list_native_settlement_pending=lambda: [], list_active=lambda **kwargs: [job], mutate=lambda job_id, update: (update(job), changes.append(dict(job)))[0])
    app = SimpleNamespace(state=SimpleNamespace(run_store=SimpleNamespace(get=get)))
    host = NativeDispatchHost(app, SimpleNamespace(store=store), {}, {})
    await host.maintain()
    assert changes == []


@pytest.mark.asyncio
async def test_native_cancel_stop_is_shared_with_task_finalizer(monkeypatch):
    import asyncio
    import time

    from ecs_executor import agent_dispatch

    host = agent_dispatch.NativeWorkerHost.__new__(agent_dispatch.NativeWorkerHost)
    host.stop_tasks = {}
    stopped = []

    def stop(native):
        time.sleep(0.02)
        stopped.append(native["run_id"])

    monkeypatch.setattr(agent_dispatch, "stop_native_sandbox", stop)
    job = {"id": "job", "native": {"run_id": "run"}}
    await asyncio.gather(host.stop_native(job), host.stop_native(job))
    assert stopped == ["run"]


@pytest.mark.asyncio
async def test_native_lost_ownership_retains_attempt_reservation(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    from ecs_executor import agent_dispatch

    from app.gateway import native_admission

    job = {"id": "job", "generation": "generation", "native": {"run_id": "run", "user_id": "owner"}, "node_id": "node", "node_budget": {"max_concurrency": 1, "resident_cpu_millis": 1500, "resident_memory_mib": 2048}}
    task = asyncio.create_task(asyncio.sleep(0))
    record = SimpleNamespace(task=task, ownership_lost=True, status=SimpleNamespace(value="error"), error="ownership lost")

    async def adopt(*args, **kwargs):
        return record

    async def get(*args, **kwargs):
        return {"owner_worker_id": "peer", "status": "error"}

    changes = []

    async def report(job, change):
        changes.append(change)
        return job

    async def request(*args, **kwargs):
        return job

    host = agent_dispatch.NativeWorkerHost.__new__(agent_dispatch.NativeWorkerHost)
    host.app = SimpleNamespace(state=SimpleNamespace(run_store=SimpleNamespace(get=get)))
    host.secret, host.config = "secret", {"node_id": "node"}
    host.active, host.stop_tasks = {}, {}
    host.adoption_lock, host.adopting = asyncio.Lock(), None
    host.executions, host.cleanup_task = {}, None
    host.report, host.request = report, request
    monkeypatch.setattr(agent_dispatch, "verify_native_launch", lambda *args: job["native"])
    monkeypatch.setattr(native_admission, "adopt_native_run", adopt)
    await host.execute(job, "token")
    assert changes[-1]["state"] == "uncertain"
    assert not any(change.get("physical_stopped") for change in changes)


@pytest.mark.asyncio
async def test_adopted_native_task_is_drained_after_running_report_failure(monkeypatch):
    import asyncio
    import subprocess
    from types import SimpleNamespace

    from ecs_executor import agent_dispatch

    from app.gateway import native_admission

    job = {"id": "job", "generation": "gen", "native": {"run_id": "run", "user_id": "owner"}, "node_id": "node", "node_budget": {"max_concurrency": 1, "resident_cpu_millis": 1500, "resident_memory_mib": 2048}}
    finished = asyncio.Event()
    native_task = asyncio.create_task(finished.wait())
    record = SimpleNamespace(task=native_task, ownership_lost=False, status=SimpleNamespace(value="interrupted"), error=None)

    async def adopt(*args, **kwargs):
        return record

    async def get(*args, **kwargs):
        return {"owner_worker_id": "worker", "status": "running"}

    changes = []
    failed = False
    terminal_failed = False

    async def report(job, change):
        nonlocal failed, terminal_failed
        if change.get("state") == "running" and not failed:
            failed = True
            raise RuntimeError("report response lost")
        if change.get("physical_stopped") and not terminal_failed:
            terminal_failed = True
            raise RuntimeError("terminal response lost")
        changes.append(change)
        return job

    async def request(*args, **kwargs):
        return job

    host = agent_dispatch.NativeWorkerHost.__new__(agent_dispatch.NativeWorkerHost)
    host.app = SimpleNamespace(state=SimpleNamespace(run_store=SimpleNamespace(get=get)))
    host.secret, host.config = "secret", {"node_id": "node"}
    host.active, host.stop_tasks = {}, {}
    host.adoption_lock, host.adopting = asyncio.Lock(), None
    host.executions, host.cleanup_task = {}, None
    host.report, host.request = report, request
    monkeypatch.setattr(agent_dispatch, "verify_native_launch", lambda *args: job["native"])
    monkeypatch.setattr(native_admission, "adopt_native_run", adopt)
    stop_attempts = []

    def stop(native):
        stop_attempts.append(native["run_id"])
        if len(stop_attempts) == 1:
            raise subprocess.TimeoutExpired(["docker", "stop", "native-owned"], timeout=120)

    monkeypatch.setattr(agent_dispatch, "stop_native_sandbox", stop)
    execution = asyncio.create_task(host.execute(job, "token"))
    host.active[job["id"]] = execution
    await asyncio.sleep(0.05)
    assert not execution.done() and host.active[job["id"]] is execution
    finished.set()
    await asyncio.wait_for(execution, 5)
    assert changes[-1]["state"] == "cancelled" and changes[-1]["physical_stopped"]
    assert stop_attempts == ["run", "run"]


def test_encrypted_native_secrets_rebind_through_native_skill_and_bash(tmp_path, monkeypatch):
    import json

    from ecs_executor.agent_dispatch import open_native_secrets, seal_native_secrets
    from test_skill_request_scoped_secrets import TestActivationBindsSecrets, TestBashToolInjectsActiveSecrets, _make_secret_skill

    from deerflow.runtime.secret_context import redact_config_secrets
    from deerflow.skills.types import SecretRequirement

    secret = "node-operator-credential-at-least-32-bytes"
    native = {"run_id": "run", "user_id": "owner", "thread_id": "thread", "incarnation": "inc"}
    context = {"secrets": {"ERP_TOKEN": "caller-private-value", "UNUSED": "unused", "BAD": 3}, "__active_skill_secrets": {"FORGED": "not-authority"}}
    carrier = seal_native_secrets(native, "node", secret, context)
    ledger = {**native, "secret_carrier": carrier, "config": redact_config_secrets({"context": context})}
    assert "caller-private-value" not in json.dumps(ledger)
    rebound = {"secrets": open_native_secrets(native, "node", secret, carrier)}
    assert rebound["secrets"] == {"ERP_TOKEN": "caller-private-value", "UNUSED": "unused"}
    skill = _make_secret_skill(tmp_path, "erp-report", [SecretRequirement("ERP_TOKEN")])
    TestActivationBindsSecrets()._activate(tmp_path, monkeypatch, skill, rebound)
    out, captured = TestBashToolInjectsActiveSecrets()._run_bash(rebound)
    assert captured["env"] == {"ERP_TOKEN": "caller-private-value"} and "caller-private-value" not in out
    assert "caller-private-value" not in json.dumps(redact_config_secrets({"context": rebound}))
    with pytest.raises(ValueError, match="carrier denied"):
        open_native_secrets({**native, "user_id": "other"}, "node", secret, carrier)


@pytest.mark.asyncio
async def test_native_worker_bootstrap_renews_dispatch_before_returning_startup(tmp_path, monkeypatch):
    import json
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace

    from ecs_executor import agent_dispatch
    from ecs_executor.job_store import JobStore
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.gateway.native_admission import prepare_native_host
    from deerflow.config.run_ownership_config import RunOwnershipConfig
    from deerflow.persistence.base import Base
    from deerflow.persistence.run import RunRepository
    from deerflow.runtime import RunManager

    path = tmp_path / "worker.json"
    path.write_text(json.dumps({"enabled": True, "role": "worker"}))
    monkeypatch.setenv("ECS_NATIVE_CONFIG", str(path))
    monkeypatch.setenv("DEER_FLOW_SANDBOX_CPUS", "1")
    monkeypatch.setenv("DEER_FLOW_SANDBOX_MEMORY", "1g")
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'bootstrap-native.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    native_store = RunRepository(async_sessionmaker(engine, expire_on_commit=False))
    jobs = JobStore(f"sqlite:///{tmp_path / 'bootstrap-jobs.db'}")
    jobs.initialize()
    job = jobs.create(namespace="native-C", request_key="queued", spec_digest="digest", record={"kind": "C", "native": {"run_id": "queued", "user_id": "owner"}})
    jobs.mutate(job["id"], lambda value: value.update(state="queued"))
    dispatch_owner = "dispatch:" + job["id"]
    await native_store.put("queued", thread_id="thread", user_id="owner", owner_worker_id=dispatch_owner, lease_expires_at=(datetime.now(UTC) - timedelta(seconds=240)).isoformat())
    central = SimpleNamespace(state=SimpleNamespace(run_store=native_store))
    dispatch_host = agent_dispatch.NativeDispatchHost(central, SimpleNamespace(store=jobs), {}, {})
    calls = []

    class Host:
        async def request(self, operation):
            calls.append(operation)
            await dispatch_host.maintain()
            return {"renewed": True}

        async def stop(self):
            calls.append("stop")

    host = Host()
    real_host_type = agent_dispatch.NativeWorkerHost
    monkeypatch.setattr(agent_dispatch, "NativeWorkerHost", lambda *args: host)
    config = SimpleNamespace(
        deployment=SimpleNamespace(multi_instance=True),
        database=SimpleNamespace(backend="postgres"),
        run_ownership=SimpleNamespace(heartbeat_enabled=True),
        run_events=SimpleNamespace(backend="db"),
        sandbox=SimpleNamespace(use="deerflow.community.aio_sandbox:AioSandboxProvider", replicas=1, hard_capacity=True),
    )
    app = SimpleNamespace(state=SimpleNamespace())
    try:
        assert await prepare_native_host(app, config) is host
        assert calls == ["bootstrap"]
        restarted = RunManager(native_store, worker_id="restarting", run_ownership_config=RunOwnershipConfig(heartbeat_enabled=True))
        assert await restarted.reconcile_orphaned_inflight_runs(error="startup orphan") == []
        row = await native_store.get("queued", user_id="owner")
        assert row["status"] == "pending" and row["owner_worker_id"] == dispatch_owner
    finally:
        jobs.engine.dispose()
        await engine.dispose()

    pool = tmp_path / "pool"
    pool.mkdir()
    (pool / "pool-mount-id").write_text("mount")
    path.write_text(json.dumps({"enabled": True, "role": "worker", "artifact_root": str(pool), "node_id": "node", "credential_env": "TEST_NODE_TOKEN", "executor_url": "http://127.0.0.1:1"}))
    monkeypatch.setenv("TEST_NODE_TOKEN", "operator-node-credential-at-least-32-bytes")
    monkeypatch.setenv("DEER_FLOW_INTERNAL_AUTH_TOKEN", "internal-auth-credential-at-least-32-bytes")
    created = []

    def create(app, config):
        instance = real_host_type(app, config)
        created.append(instance)
        return instance

    async def unavailable(*args, **kwargs):
        raise RuntimeError("central unavailable")

    monkeypatch.setattr(agent_dispatch, "NativeWorkerHost", create)
    monkeypatch.setattr(real_host_type, "request", unavailable)
    with pytest.raises(RuntimeError, match="central unavailable"):
        await prepare_native_host(SimpleNamespace(state=SimpleNamespace()), config)
    assert created[0].node_lock.closed and created[0].client.is_closed


@pytest.mark.asyncio
async def test_queued_cancel_recovers_end_after_native_commit_and_job_terminal(tmp_path):
    from types import SimpleNamespace

    from ecs_executor.agent_dispatch import NativeDispatchHost
    from ecs_executor.job_store import JobStore
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from deerflow.persistence.base import Base
    from deerflow.persistence.run import RunRepository

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'native.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    jobs = JobStore(f"sqlite:///{tmp_path / 'jobs.db'}")
    jobs.initialize()
    try:
        store = RunRepository(async_sessionmaker(engine, expire_on_commit=False))
        job = jobs.create(namespace="native-C", request_key="run", spec_digest="digest", record={"kind": "C", "start_intent": False, "native": {"run_id": "run", "user_id": "owner"}})
        owner = "dispatch:" + job["id"]
        await store.put("run", thread_id="thread", user_id="owner", owner_worker_id=owner)
        await store.request_cancel("run", action="interrupt")
        jobs.mutate(job["id"], lambda value: value.update(state="cancelled", physical_stopped=True, settlement_pending=True, settlement_cancel_action="interrupt"))
        assert await store.finish_dispatch_pending("run", owner_worker_id=owner)
        assert not await store.finish_dispatch_pending("run", owner_worker_id=owner)
        ended = []

        async def end(run):
            ended.append(run)
            if len(ended) == 1:
                raise RuntimeError("END acknowledgement lost")

        app = SimpleNamespace(state=SimpleNamespace(run_store=store, stream_bridge=SimpleNamespace(publish_end=end)))
        host = NativeDispatchHost(app, SimpleNamespace(store=jobs), {}, {})
        await host.maintain()
        assert jobs.get(job["id"])["settlement_pending"]
        await NativeDispatchHost(app, SimpleNamespace(store=jobs), {}, {}).maintain()
        assert ended == ["run", "run"] and not jobs.get(job["id"])["settlement_pending"]
        assert jobs.list_native_settlement_pending() == []
    finally:
        jobs.engine.dispose()
        await engine.dispose()


@pytest.mark.asyncio
async def test_quiesce_fences_inflight_adoption_before_manager_drain(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    from ecs_executor import agent_dispatch

    from app.gateway import native_admission

    entered, release = asyncio.Event(), asyncio.Event()
    events = []
    host = agent_dispatch.NativeWorkerHost.__new__(agent_dispatch.NativeWorkerHost)
    host.quiescing, host.closing, host.task = False, False, None
    host.adoption_lock, host.adopting = asyncio.Lock(), None
    host.executions, host.cleanup_task = {}, None
    host.app, host.secret = object(), "secret"
    host.active, host.stop_tasks = {}, {}
    abort, stopped = asyncio.Event(), asyncio.Event()

    async def long_tool():
        try:
            await stopped.wait()
        finally:
            events.append("native finally")

    native_task = asyncio.create_task(long_tool())
    record = SimpleNamespace(task=native_task, abort_event=abort, ownership_lost=False, status=SimpleNamespace(value="running"))
    host.executions["existing"] = ({"id": "existing", "native": {"user_id": "owner"}}, record)

    async def stop_owned(job):
        events.append("physical STOP")
        stopped.set()

    monkeypatch.setattr(host, "stop_owned", stop_owned)

    async def close_client():
        events.append("client closed")

    host.client = SimpleNamespace(aclose=close_client)
    host.node_lock = SimpleNamespace(close=lambda: events.append("node lock closed"))

    async def adopt(*args, admission_check=None):
        entered.set()
        await release.wait()
        admission_check()
        events.append("graph attached")

    monkeypatch.setattr(native_admission, "adopt_native_run", adopt)
    task = asyncio.create_task(host.adopt_owned({}, "token"))
    await entered.wait()
    quiesce = asyncio.create_task(host.quiesce())
    await asyncio.sleep(0)
    release.set()
    await quiesce
    events.append("manager drain")
    with pytest.raises(RuntimeError, match="quiescing"):
        await task
    with pytest.raises(RuntimeError, match="quiescing"):
        await host.adopt_owned({}, "token")
    assert events == ["manager drain"]
    abort.set()
    await asyncio.wait_for(native_task, 2)
    events.append("manager drain complete")
    await host.stop()
    events.append("checkpointer closed")
    assert events.index("physical STOP") < events.index("native finally") < events.index("client closed") < events.index("checkpointer closed")


@pytest.mark.asyncio
async def test_pre_adoption_refusal_recovers_native_commit_and_end_failure(tmp_path):
    from types import SimpleNamespace

    from ecs_executor.agent_dispatch import NativeDispatchHost
    from ecs_executor.job_store import JobStore
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from deerflow.persistence.base import Base
    from deerflow.persistence.run import RunRepository

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'native.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    jobs = JobStore(f"sqlite:///{tmp_path / 'jobs.db'}")
    jobs.initialize()
    try:
        native = RunRepository(async_sessionmaker(engine, expire_on_commit=False))
        job = jobs.create(namespace="native-C", request_key="run", spec_digest="digest", record={"kind": "C", "native": {"run_id": "run", "user_id": "owner"}})
        job = jobs.mutate(job["id"], lambda value: value.update(state="starting", start_intent=True, node_id="node", worker_owner="worker", generation="gen", physical_stopped=False))
        owner = "dispatch:" + job["id"]
        await native.put("run", thread_id="thread", user_id="owner", owner_worker_id=owner)
        ended = []

        async def end(run):
            ended.append(run)
            if len(ended) == 1:
                raise RuntimeError("END acknowledgement lost")

        app = SimpleNamespace(state=SimpleNamespace(run_store=native, stream_bridge=SimpleNamespace(publish_end=end)))
        host = NativeDispatchHost(app, SimpleNamespace(store=jobs), {}, {})
        with pytest.raises(RuntimeError, match="acknowledgement lost"):
            await host.refuse(job)
        pending = jobs.get(job["id"])
        assert pending["settlement_pending"] and not pending["physical_stopped"]
        assert (await native.get("run", user_id="owner"))["status"] == "error"
        fresh = NativeDispatchHost(app, SimpleNamespace(store=jobs), {}, {})
        await fresh.maintain()
        settled = jobs.get(job["id"])
        assert settled["state"] == "failed" and settled["physical_stopped"] and not settled["settlement_pending"]
        assert await fresh.refuse(settled) == settled
        assert ended == ["run", "run"]
    finally:
        jobs.engine.dispose()
        await engine.dispose()


@pytest.mark.asyncio
async def test_scoped_native_stop_cannot_acknowledge_a_different_missing_container(tmp_path, monkeypatch):
    """Poll cancellation runs without the admission workspace ContextVar.

    A policy sandbox belongs to the scoped skills projection. Inspecting the
    absent legacy name cannot establish that this acquired object stopped.
    Unknown capture/STOP may fail closed, retaining the reservation for retry.
    """
    import asyncio
    from contextvars import Context
    from dataclasses import asdict
    from types import SimpleNamespace

    from ecs_executor.agent_dispatch import NativeWorkerHost
    from ecs_executor.native_sandbox import NativeSandboxCapture
    from test_aio_sandbox_provider import _make_provider_with_active_sandbox

    from deerflow.authz.workspace import WorkspaceContext, reset_current_workspace, set_current_workspace
    from deerflow.community.aio_sandbox import aio_sandbox_provider as aio_module
    from deerflow.config.paths import Paths
    from deerflow.sandbox import sandbox_provider
    from deerflow.sandbox.execution_capture import current_execution_capture, sandbox_execution_capture

    paths = Paths(base_dir=tmp_path / "owned-home")
    monkeypatch.setattr(aio_module, "get_paths", lambda: paths)
    context = WorkspaceContext("11111111-1111-4111-8111-111111111111", "owner", 1, 1)
    probe = aio_module.AioSandboxProvider.__new__(aio_module.AioSandboxProvider)
    probe._config = {"skills_container_path": "/mnt/skills"}
    workspace_token = set_current_workspace(context)
    try:
        paths.thread_skills_view_dir("private-thread", user_id="owner").mkdir(parents=True)
        acquired_id = probe._sandbox_id_for_thread("private-thread", "owner")
    finally:
        reset_current_workspace(workspace_token)
    unscoped_id = probe._sandbox_id_for_thread("private-thread", "owner")
    assert acquired_id != unscoped_id
    provider, sandbox, _ = _make_provider_with_active_sandbox(tmp_path, acquired_id)
    provider._config.update(hard_capacity=True, skills_container_path="/mnt/skills")
    provider._thread_sandboxes[("owner", "private-thread")] = acquired_id
    provider._active_sandbox_identity[acquired_id] = ("owner", "private-thread")
    info = provider._sandbox_infos[acquired_id]
    info.container_name, info.container_id = "owned-aio-" + acquired_id, "captured-physical-container"
    physical = {info.container_id: True}
    stopped = []

    def destroy(target):
        stopped.append(target.container_id)
        if len(stopped) == 1:
            raise RuntimeError("owned physical STOP transport failed")
        physical[target.container_id] = False

    def running(name):
        return physical[info.container_id] if name in (info.container_name, info.container_id) else False

    provider._backend = SimpleNamespace(_container_prefix="owned-aio", destroy=destroy, _is_container_running=running, is_alive=lambda actual: True)
    monkeypatch.setattr(provider, "_ensure_skills_projection", lambda user_id: None)
    monkeypatch.setattr(sandbox_provider, "get_initialized_sandbox_provider", lambda: provider)
    host = NativeWorkerHost.__new__(NativeWorkerHost)
    host.stop_tasks = {}
    job = {
        "id": "owned-c-job",
        "workspace_id": context.workspace_id,
        "physical_stopped": False,
        "native": {"run_id": "bound-native-run", "user_id": "owner", "thread_id": "private-thread", "incarnation": "original-incarnation", "workspace_id": context.workspace_id, "workspace_context": asdict(context)},
    }
    job.update(node_id="worker", worker_owner="assignment-owner", generation="assignment-generation")
    capture = NativeSandboxCapture(job)
    record = SimpleNamespace(run_id="bound-native-run", user_id="owner", thread_id="private-thread", thread_incarnation="original-incarnation", workspace_context=context)
    capture.bind_execution(record)
    host.sandbox_captures = {job["id"]: capture}
    try:
        workspace_token = set_current_workspace(context)
        try:
            with sandbox_execution_capture(capture):
                assert provider.acquire("private-thread", user_id="owner") == acquired_id
                assert provider.get_scoped(acquired_id, user_id="owner", thread_id="private-thread") is sandbox
                provider.release(acquired_id)
            assert current_execution_capture() is None
        finally:
            reset_current_workspace(workspace_token)
        assert acquired_id in provider._warm_pool and physical[info.container_id]
        with pytest.raises(RuntimeError, match="STOP remains unconfirmed"):
            await asyncio.create_task(host.stop_owned(job), context=Context())
        assert physical[info.container_id] and acquired_id in provider._warm_pool and not job["physical_stopped"]
        assert job["id"] not in host.stop_tasks, "failed STOP must remain retryable"
        await asyncio.create_task(host.stop_owned(job), context=Context())
        assert not physical[info.container_id], "Missing legacy container was accepted as STOP while the acquired policy sandbox is still running"
        assert stopped == [info.container_id, info.container_id]
        assert acquired_id not in provider._warm_pool
        with pytest.raises(RuntimeError, match="no longer accepts acquisition"):
            with sandbox_execution_capture(capture):
                provider.acquire("private-thread", user_id="owner")
    finally:
        sandbox.close()
        provider.reset()


@pytest.mark.asyncio
async def test_scoped_native_text_run_proves_no_sandbox_start_after_drain():
    import asyncio
    from dataclasses import asdict
    from types import SimpleNamespace

    from ecs_executor.agent_dispatch import NativeWorkerHost
    from ecs_executor.native_sandbox import NativeSandboxCapture

    from deerflow.authz.workspace import WorkspaceContext

    context = WorkspaceContext("11111111-1111-4111-8111-111111111111", "owner", 1, 1)
    job = {
        "id": "text-job",
        "node_id": "worker",
        "worker_owner": "worker-owner",
        "generation": "one",
        "workspace_id": context.workspace_id,
        "native": {
            "run_id": "text-run",
            "user_id": "owner",
            "thread_id": "text-thread",
            "incarnation": "text-incarnation",
            "workspace_context": asdict(context),
        },
    }
    release = asyncio.Event()
    task = asyncio.create_task(release.wait())
    record = SimpleNamespace(run_id="text-run", user_id="owner", thread_id="text-thread", thread_incarnation="text-incarnation", workspace_context=context, task=task, workspace_execution_closed=False)
    capture = NativeSandboxCapture(job)
    capture.bind_execution(record)
    host = NativeWorkerHost.__new__(NativeWorkerHost)
    host.stop_tasks, host.sandbox_captures = {}, {job["id"]: capture}
    try:
        with pytest.raises(RuntimeError, match="STOP remains unconfirmed"):
            await host.stop_owned(job)
        release.set()
        await task
        record.workspace_execution_closed = True
        await host.stop_owned(job)
        # The successful proof seals future acquire, rather than guessing from
        # an empty provider map or from a task which could still start a tool.
        with pytest.raises(RuntimeError, match="no longer accepts acquisition"):
            capture.acquire_started("text-thread", "owner")
        capture.validate_assignment(job)
        unknown = NativeSandboxCapture(job)
        unknown.bind_execution(record)
        unknown.acquire_started("text-thread", "owner")
        unknown.acquire_failed()
        with pytest.raises(RuntimeError, match="unknown"):
            unknown.stop()
    finally:
        release.set()
        await task
