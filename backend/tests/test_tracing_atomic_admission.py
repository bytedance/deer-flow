"""A profile edit and run insertion serialize on the shared tracing authority."""

import asyncio
from datetime import UTC, datetime

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ["run", "scheduled_queue"])
async def test_profile_changed_after_capture_rejects_atomic_admission_without_a_run(tmp_path, monkeypatch, target):
    from deerflow.config.credentials_key import CredentialsCipher
    from deerflow.config.tracing_config import reset_tracing_config
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
    from deerflow.persistence.run import RunRepository
    from deerflow.persistence.scheduled_task_runs import ScheduledTaskRunRepository
    from deerflow.persistence.tracing_profiles.sql import SqlTracingProfileRepository
    from deerflow.runtime.tracing_snapshot import snapshot_references
    from deerflow.tracing.profiles import TracingConflictError, TracingProfileService

    for name in ("MONOCLE_TRACING", "LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2", "LANGFUSE_TRACING"):
        monkeypatch.delenv(name, raising=False)
    reset_tracing_config()
    await init_engine("sqlite", url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}", sqlite_dir=str(tmp_path))
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False})
    service = TracingProfileService(SqlTracingProfileRepository(sessionmaker(engine, expire_on_commit=False)), CredentialsCipher.from_keys([Fernet.generate_key()]), identity_resolver=lambda name, owner: f"test:{owner}:{name}")
    run_repo = RunRepository(get_session_factory())
    captured = asyncio.Event()
    admit = asyncio.Event()

    async def capture_then_admit():
        snapshot = await asyncio.to_thread(service.resolve_snapshot, "researcher", "alice")
        captured.set()
        await admit.wait()
        if target == "scheduled_queue":
            return await ScheduledTaskRunRepository(get_session_factory()).create(
                run_record_id="occurrence-raced",
                task_id="task-raced",
                thread_id="thread-raced",
                scheduled_for=datetime.now(UTC),
                trigger="manual",
                status="queued",
                expected_task_user_id="alice",
                tracing_snapshot_refs=snapshot_references(snapshot),
            )
        return await run_repo.create_thread_operation_atomic("run-raced", thread_id="thread-raced", owner_worker_id="worker-a", lease_expires_at=None, user_id="alice", metadata=snapshot_references(snapshot))

    task = None
    try:
        await asyncio.to_thread(service.set_binding, "researcher", "alice", mode="disabled", profile_id=None, expected_revision=0)
        task = asyncio.create_task(capture_then_admit())
        await asyncio.wait_for(captured.wait(), timeout=10)
        await asyncio.to_thread(service.set_binding, "researcher", "alice", mode="inherit", profile_id=None, expected_revision=1)
        admit.set()
        with pytest.raises(TracingConflictError):
            await task
        assert await run_repo.get("run-raced", user_id="alice") is None
        assert await ScheduledTaskRunRepository(get_session_factory()).list_queued_runs(limit=10) == []
    finally:
        admit.set()
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)
        engine.dispose()
        await close_engine()
        reset_tracing_config()
