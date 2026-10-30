"""Gateway admission owns new captures without relabeling recovered snapshots."""

import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy import select


@pytest.mark.asyncio
async def test_gateway_capture_is_published_with_its_run_and_recovery_keeps_its_identity(tmp_path, monkeypatch):
    from app.gateway import tracing_admission
    from deerflow.config.app_config import AppConfig
    from deerflow.config.tracing_config import reset_tracing_config
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
    from deerflow.persistence.run import RunRepository
    from deerflow.persistence.tracing_profiles.model import RunTracingSnapshotRow

    for name in ("MONOCLE_TRACING", "LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2", "LANGFUSE_TRACING"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path / "home"))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    reset_tracing_config()
    config = AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}, "database": {"backend": "sqlite", "sqlite_dir": str(tmp_path)}})
    await init_engine("sqlite", url=config.database.app_sqlalchemy_url, sqlite_dir=str(tmp_path))
    sf = get_session_factory()
    metadata = {}
    state = SimpleNamespace(checkpointer=object())
    state.tracing_gc_authority = (state.checkpointer, tracing_admission.tracing_database_identity(config))
    request = SimpleNamespace(app=SimpleNamespace(state=state))
    try:
        await tracing_admission.admit_run_tracing(request, {}, metadata, thread_id="thread-a", agent_name=None, user_id="alice", app_config=config)
        snapshot_id = metadata["deerflow_tracing_snapshot_id"]
        async with sf() as session:
            captured = await session.get(RunTracingSnapshotRow, snapshot_id)
            assert getattr(captured, "retention_state", "unmanaged") == "pending"

        await RunRepository(sf).create_thread_operation_atomic("run-a", thread_id="thread-a", owner_worker_id="worker-a", lease_expires_at=None, user_id="alice", metadata=metadata)
        async with sf() as session:
            assert (await session.get(RunTracingSnapshotRow, snapshot_id)).retention_state == "published"

        class Checkpointer:
            async def aget_tuple(self, _config):
                return SimpleNamespace(metadata=metadata)

        state.checkpointer = Checkpointer()
        state.tracing_gc_authority = (state.checkpointer, tracing_admission.tracing_database_identity(config))
        resumed = {}
        await tracing_admission.admit_run_tracing(request, {}, resumed, thread_id="thread-a", agent_name=None, user_id="alice", app_config=config, resume=True)
        assert resumed["deerflow_tracing_snapshot_id"] == snapshot_id
        assert resumed["deerflow_tracing_pinned"] is True
        async with sf() as session:
            assert list(await session.scalars(select(RunTracingSnapshotRow.snapshot_id))) == [snapshot_id]

        state.tracing_gc_authority = (state.checkpointer, None)
        external_resume = {}
        await tracing_admission.admit_run_tracing(request, {}, external_resume, thread_id="thread-a", agent_name=None, user_id="alice", app_config=config, resume=True)
        assert external_resume["deerflow_tracing_snapshot_id"] == snapshot_id
        async with sf() as session:
            assert (await session.get(RunTracingSnapshotRow, snapshot_id)).retention_state == "unmanaged"
        state.tracing_gc_authority = (state.checkpointer, tracing_admission.tracing_database_identity(config))
        await tracing_admission.admit_run_tracing(request, {}, {}, thread_id="thread-a", agent_name=None, user_id="alice", app_config=config, resume=True)
        async with sf() as session:
            assert (await session.get(RunTracingSnapshotRow, snapshot_id)).retention_state == "unmanaged"
    finally:
        await close_engine()
        reset_tracing_config()


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["reuse", "busy"])
async def test_gateway_releases_only_its_unused_capture_after_a_known_admission_result(tmp_path, monkeypatch, outcome):
    from fastapi import HTTPException
    from test_gateway_services import _make_start_run_request, _run_create_request

    from app.gateway import services
    from deerflow.config.app_config import AppConfig, reset_app_config, set_app_config
    from deerflow.config.tracing_config import reset_tracing_config
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
    from deerflow.persistence.run import RunRepository
    from deerflow.persistence.tracing_profiles.model import RunTracingSnapshotRow
    from deerflow.runtime import RunManager, RunStatus

    for name in ("MONOCLE_TRACING", "LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2", "LANGFUSE_TRACING"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path / "home"))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    reset_tracing_config()
    config = AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}, "database": {"backend": "sqlite", "sqlite_dir": str(tmp_path)}})
    set_app_config(config)
    await init_engine("sqlite", url=config.database.app_sqlalchemy_url, sqlite_dir=str(tmp_path))
    sf = get_session_factory()
    manager = RunManager(store=RunRepository(sf))
    request = _make_start_run_request(manager)
    from app.gateway.tracing_admission import tracing_database_identity

    request.app.state.tracing_gc_authority = (request.app.state.checkpointer, tracing_database_identity(config))
    started, finish = asyncio.Event(), asyncio.Event()

    async def execute(_bridge, owner, record, **_kwargs):
        assert await owner.try_start(record.run_id)
        started.set()
        await finish.wait()
        await owner.set_status(record.run_id, RunStatus.success)

    monkeypatch.setattr(services, "resolve_agent_factory", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(services, "run_agent", execute)
    first = None
    try:
        body = _run_create_request()
        first = await services.start_run(body, "thread-owned", request, idempotency_key="request-a" if outcome == "reuse" else None)
        await asyncio.wait_for(started.wait(), 10)
        if outcome == "reuse":
            reused = await services.start_run(body, "thread-owned", request, idempotency_key="request-a")
            assert reused.run_id == first.run_id
        else:
            with pytest.raises(HTTPException) as rejected:
                await services.start_run(body, "thread-owned", request)
            assert rejected.value.status_code == 409
        async with sf() as session:
            states = list(await session.scalars(select(RunTracingSnapshotRow.retention_state)))
        assert sorted(states) == ["published", "released"]
    finally:
        finish.set()
        if first is not None:
            await asyncio.wait_for(first.task, 10)
        await close_engine()
        reset_app_config()
        reset_tracing_config()


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["task_changed", "trace_conflict", "active_race", "unknown_commit"])
async def test_scheduler_releases_rejected_captures_but_preserves_an_unknown_committed_queue(tmp_path, monkeypatch, outcome):
    from datetime import UTC, datetime

    from test_scheduled_task_queue import _seed_reuse_task

    from app.scheduler.service import ScheduledTaskService
    from deerflow.config.app_config import AppConfig
    from deerflow.config.tracing_config import reset_tracing_config
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
    from deerflow.persistence.scheduled_task_runs import ScheduledTaskRunRepository
    from deerflow.persistence.scheduled_tasks import ScheduledTaskRepository
    from deerflow.persistence.tracing_profiles.model import RunTracingSnapshotRow
    from deerflow.tracing.profiles import get_profile_service, release_run_snapshot, resolve_run_snapshot

    for name in ("MONOCLE_TRACING", "LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2", "LANGFUSE_TRACING"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path / "home"))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    reset_tracing_config()
    config = AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}, "database": {"backend": "sqlite", "sqlite_dir": str(tmp_path)}})
    await init_engine("sqlite", url=config.database.app_sqlalchemy_url, sqlite_dir=str(tmp_path))
    sf = get_session_factory()
    task_repo, queue_repo = ScheduledTaskRepository(sf), ScheduledTaskRunRepository(sf)
    now = datetime.now(UTC)
    try:
        task = await _seed_reuse_task(task_repo, task_id="task-a", now=now)
        original_create = queue_repo.create

        async def interleave(**kwargs):
            if outcome == "task_changed":
                await task_repo.update("task-a", user_id="user-1", updates={"status": "paused"})
            elif outcome == "trace_conflict":
                await asyncio.to_thread(get_profile_service(app_config=config).set_binding, "lead_agent", "user-1", mode="disabled", profile_id=None, expected_revision=0)
            elif outcome == "active_race":
                await original_create(run_record_id="peer-queue", task_id="task-a", thread_id="thread-1", scheduled_for=now, trigger="manual", status="queued", expected_task_user_id="user-1")
            result = await original_create(**kwargs)
            if outcome == "unknown_commit":
                raise RuntimeError("queue commit acknowledgement unavailable")
            return result

        monkeypatch.setattr(queue_repo, "create", interleave)

        async def launch(**_kwargs):
            pytest.fail("a rejected or uncertain queue must not execute")

        service = ScheduledTaskService(
            task_repo=task_repo,
            task_run_repo=queue_repo,
            launch_run=launch,
            poll_interval_seconds=5,
            lease_seconds=120,
            max_concurrent_runs=3,
            resolve_tracing_snapshot=lambda name, owner: resolve_run_snapshot(name, owner, app_config=config, managed_admission=True),
            release_tracing_snapshot=lambda snapshot_id, owner: release_run_snapshot(snapshot_id, owner, app_config=config),
        )
        if outcome == "unknown_commit":
            with pytest.raises(RuntimeError, match="acknowledgement"):
                await service.dispatch_task(task, now=now, trigger="manual")
        else:
            await service.dispatch_task(task, now=now, trigger="manual")
        async with sf() as session:
            assert list(await session.scalars(select(RunTracingSnapshotRow.retention_state))) == ["published" if outcome == "unknown_commit" else "released"]
        queues = await queue_repo.list_queued_runs(limit=10)
        assert len(queues) == (1 if outcome in {"unknown_commit", "active_race"} else 0)
    finally:
        await close_engine()
        reset_tracing_config()


@pytest.mark.asyncio
@pytest.mark.parametrize("startup_authority", ["missing", "legacy", "other_database", "saver_replaced"])
async def test_unknown_or_changed_startup_checkpoint_authority_keeps_capture_unmanaged(tmp_path, monkeypatch, startup_authority):
    from app.gateway import tracing_admission
    from deerflow.config.app_config import AppConfig
    from deerflow.config.tracing_config import reset_tracing_config
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
    from deerflow.persistence.tracing_profiles.model import RunTracingSnapshotRow

    for name in ("MONOCLE_TRACING", "LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2", "LANGFUSE_TRACING"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path / "home"))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    reset_tracing_config()
    config = AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}, "database": {"backend": "sqlite", "sqlite_dir": str(tmp_path)}})
    await init_engine("sqlite", url=config.database.app_sqlalchemy_url, sqlite_dir=str(tmp_path))
    saver = object()
    state = SimpleNamespace(checkpointer=saver)
    if startup_authority != "missing":
        source = config.model_copy(deep=True)
        source.database.sqlite_dir = str(tmp_path / "old-database")
        state.tracing_gc_authority = (saver, None if startup_authority == "legacy" else tracing_admission.tracing_database_identity(source))
    if startup_authority == "saver_replaced":
        state.tracing_gc_authority = (object(), tracing_admission.tracing_database_identity(config))
    request = SimpleNamespace(app=SimpleNamespace(state=state))
    try:
        metadata = {}
        await tracing_admission.admit_run_tracing(request, {}, metadata, thread_id="thread-a", agent_name=None, user_id="alice", app_config=config)
        async with get_session_factory()() as session:
            row = await session.get(RunTracingSnapshotRow, metadata["deerflow_tracing_snapshot_id"])
            assert row.retention_state == "unmanaged"
    finally:
        await close_engine()
        reset_tracing_config()
