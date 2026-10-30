"""Read admission fences configuration edits without rewriting one shared row."""

import asyncio
import threading
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, event, select, text, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def admission_store(tmp_path, monkeypatch):
    import deerflow.persistence.models  # noqa: F401 -- register application tables
    from deerflow.config.credentials_key import CredentialsCipher
    from deerflow.config.tracing_config import reset_tracing_config
    from deerflow.persistence.base import Base
    from deerflow.persistence.engine import _configure_sqlite_engine
    from deerflow.persistence.tracing_profiles.sql import SqlTracingProfileRepository
    from deerflow.tracing.profiles import TracingProfileService

    for name in ("MONOCLE_TRACING", "LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2", "LANGCHAIN_TRACING", "LANGFUSE_TRACING"):
        monkeypatch.delenv(name, raising=False)
    reset_tracing_config()
    path = tmp_path / "admission.db"
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    sync_sessions = sessionmaker(engine, expire_on_commit=False)
    service = TracingProfileService(SqlTracingProfileRepository(sync_sessions), CredentialsCipher.from_keys([Fernet.generate_key()]), identity_resolver=lambda *_args: "builtin:lead_agent")
    async_engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
    _configure_sqlite_engine(async_engine)
    yield service, sync_sessions, async_engine, async_sessionmaker(async_engine, expire_on_commit=False)
    engine.dispose()
    reset_tracing_config()


@pytest.mark.asyncio
@pytest.mark.parametrize("prior_statement", [None, "SELECT 1", "BEGIN"])
async def test_sqlite_read_admission_reserves_writer_without_updating_global_fence(admission_store, prior_statement):
    from deerflow.persistence.tracing_profiles.sql import validate_tracing_admission
    from deerflow.runtime.tracing_snapshot import snapshot_references

    service, _, engine, sessions = admission_store
    snapshot = service.resolve_snapshot(None, "alice")
    statements = []
    event.listen(engine.sync_engine, "before_cursor_execute", lambda _conn, _cursor, statement, *_args: statements.append(statement))
    try:
        async with sessions() as session:
            if prior_statement is not None:
                await session.execute(text(prior_statement))
            await validate_tracing_admission(session, snapshot_references(snapshot), owner_user_id="alice")
            await session.commit()
        if prior_statement != "BEGIN":
            assert "BEGIN IMMEDIATE" in statements
            assert not any(statement.lower().startswith("update tracing_admission_fence") for statement in statements)
        else:
            assert sum(statement == "BEGIN" for statement in statements) == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_existing_sqlite_write_transaction_remains_valid_for_admission(admission_store):
    from deerflow.persistence.tracing_profiles.sql import validate_tracing_admission
    from deerflow.runtime.tracing_snapshot import snapshot_references

    service, _, engine, sessions = admission_store
    snapshot = service.resolve_snapshot(None, "alice")
    try:
        async with sessions.begin() as session:
            await session.execute(text("UPDATE tracing_admission_fence SET version = version + 1 WHERE id = 1"))
            await validate_tracing_admission(session, snapshot_references(snapshot), owner_user_id="alice")
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_admission_rechecks_binding_already_present_in_the_session_identity_map(admission_store):
    from deerflow.persistence.tracing_profiles.model import AgentTracingBindingRow
    from deerflow.persistence.tracing_profiles.sql import validate_tracing_admission
    from deerflow.runtime.tracing_snapshot import snapshot_references
    from deerflow.tracing.profiles import TracingConflictError

    service, _, engine, sessions = admission_store
    snapshot = service.resolve_snapshot(None, "alice")
    try:
        async with sessions() as session:
            previous = await session.get(AgentTracingBindingRow, ("alice", "lead_agent"))
            assert previous.revision == 0
            await asyncio.to_thread(service.set_binding, None, "alice", mode="disabled", profile_id=None, expected_revision=0)
            with pytest.raises(TracingConflictError):
                await validate_tracing_admission(session, snapshot_references(snapshot), owner_user_id="alice")
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_admission_emits_shared_row_lock_that_blocks_configuration_updates():
    from deerflow.persistence.tracing_profiles.sql import _read_admission_fence

    statements = []

    class PostgresSession:
        async def connection(self):
            return SimpleNamespace(dialect=postgresql.dialect())

        async def scalar(self, statement):
            statements.append(str(statement.compile(dialect=postgresql.dialect())))
            return 1

    await _read_admission_fence(PostgresSession())
    assert len(statements) == 1
    assert statements[0].endswith(" FOR SHARE")


@pytest.mark.asyncio
async def test_sqlite_configuration_committed_while_admission_waits_rejects_stale_capture(admission_store):
    from deerflow.persistence.tracing_profiles.model import AgentTracingBindingRow
    from deerflow.persistence.tracing_profiles.sql import _lock_admission_fence, validate_tracing_admission
    from deerflow.runtime.tracing_snapshot import snapshot_references
    from deerflow.tracing.profiles import TracingConflictError

    service, sync_sessions, engine, sessions = admission_store
    snapshot = service.resolve_snapshot(None, "alice", managed_admission=True)
    locked, release = threading.Event(), threading.Event()
    admission_waiting = asyncio.Event()

    def edit():
        with sync_sessions.begin() as session:
            _lock_admission_fence(session)
            session.execute(update(AgentTracingBindingRow).where(AgentTracingBindingRow.owner_user_id == "alice").values(mode="disabled", revision=1))
            locked.set()
            assert release.wait(10)

    def observe(_conn, _cursor, statement, *_args):
        if statement == "BEGIN IMMEDIATE":
            admission_waiting.set()

    event.listen(engine.sync_engine, "before_cursor_execute", observe)
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))

    async def admit():
        async with sessions.begin() as session:
            await validate_tracing_admission(session, snapshot_references(snapshot), owner_user_id="alice")

    writer = asyncio.create_task(asyncio.to_thread(edit))
    admission = None
    try:
        assert await asyncio.to_thread(locked.wait, 10)
        admission = asyncio.create_task(admit())
        await asyncio.wait_for(admission_waiting.wait(), 10)
        assert not admission.done()
        release.set()
        await writer
        with pytest.raises(TracingConflictError):
            await admission
    finally:
        release.set()
        await asyncio.gather(writer, *(task for task in (admission,) if task is not None), return_exceptions=True)
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ["run", "scheduled_queue"])
async def test_fresh_managed_snapshot_publishes_in_the_durable_admission_transaction(admission_store, target):
    from datetime import UTC, datetime

    from deerflow.persistence.run import RunRepository
    from deerflow.persistence.scheduled_task_runs import ScheduledTaskRunRepository
    from deerflow.persistence.tracing_profiles.model import RunTracingSnapshotRow
    from deerflow.runtime.tracing_snapshot import snapshot_references

    service, sync_sessions, engine, sessions = admission_store
    snapshot = service.resolve_snapshot(None, "alice", managed_admission=True)
    with sync_sessions() as session:
        assert session.get(RunTracingSnapshotRow, snapshot.snapshot_id).retention_state == "pending"
    try:
        if target == "run":
            await RunRepository(sessions).create_thread_operation_atomic("managed-run", thread_id="managed-thread", owner_worker_id="worker", lease_expires_at=None, user_id="alice", metadata=snapshot_references(snapshot))
        else:
            await ScheduledTaskRunRepository(sessions).create(
                run_record_id="queued-run",
                task_id="queued-task",
                thread_id="queued-thread",
                scheduled_for=datetime.now(UTC),
                trigger="manual",
                status="queued",
                expected_task_user_id="alice",
                tracing_snapshot_refs=snapshot_references(snapshot),
            )
        with sync_sessions() as session:
            assert session.get(RunTracingSnapshotRow, snapshot.snapshot_id).retention_state == "published"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_publication_rolls_back_with_admission_and_never_relabels_embedded_snapshots(admission_store):
    from deerflow.persistence.tracing_profiles.model import RunTracingSnapshotRow
    from deerflow.persistence.tracing_profiles.sql import validate_tracing_admission
    from deerflow.runtime.tracing_snapshot import snapshot_references

    service, sync_sessions, engine, sessions = admission_store
    managed = service.resolve_snapshot(None, "alice", managed_admission=True)
    embedded = service.resolve_snapshot(None, "alice")
    try:
        with pytest.raises(RuntimeError, match="admission rolled back"):
            async with sessions.begin() as session:
                await validate_tracing_admission(session, snapshot_references(managed), owner_user_id="alice")
                raise RuntimeError("admission rolled back")
        async with sessions.begin() as session:
            await validate_tracing_admission(session, snapshot_references(embedded), owner_user_id="alice")
        with sync_sessions() as session:
            assert session.get(RunTracingSnapshotRow, managed.snapshot_id).retention_state == "pending"
            assert session.get(RunTracingSnapshotRow, embedded.snapshot_id).retention_state == "unmanaged"
        assert service.resolve_snapshot(None, "alice", snapshot_id=managed.snapshot_id, managed_admission=True) == managed
        with sync_sessions() as session:
            assert session.get(RunTracingSnapshotRow, managed.snapshot_id).retention_state == "pending"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_release_is_owner_bound_and_only_releases_unpublished_managed_snapshots(admission_store):
    from deerflow.persistence.tracing_profiles.model import RunTracingSnapshotRow
    from deerflow.persistence.tracing_profiles.sql import validate_tracing_admission
    from deerflow.runtime.tracing_snapshot import snapshot_references
    from deerflow.tracing.profiles import TracingUnavailableError

    service, sync_sessions, engine, sessions = admission_store
    pending = service.resolve_snapshot(None, "alice", managed_admission=True)
    embedded = service.resolve_snapshot(None, "alice")
    published = service.resolve_snapshot(None, "alice", managed_admission=True)
    try:
        async with sessions.begin() as session:
            await validate_tracing_admission(session, snapshot_references(published), owner_user_id="alice")
        repository = service.repository
        assert repository.release_snapshot(pending.snapshot_id, "bob") is False
        assert repository.release_snapshot(embedded.snapshot_id, "alice") is False
        assert repository.release_snapshot(published.snapshot_id, "alice") is False
        assert repository.release_snapshot(pending.snapshot_id, "alice") is True
        assert repository.release_snapshot(pending.snapshot_id, "alice") is False
        with sync_sessions() as session:
            states = dict(session.execute(select(RunTracingSnapshotRow.snapshot_id, RunTracingSnapshotRow.retention_state)).all())
        assert states == {pending.snapshot_id: "released", embedded.snapshot_id: "unmanaged", published.snapshot_id: "published"}
        with pytest.raises(TracingUnavailableError):
            service.resolve_snapshot(None, "alice", snapshot_id=pending.snapshot_id)
        async with sessions.begin() as session:
            with pytest.raises(TracingUnavailableError):
                await validate_tracing_admission(session, snapshot_references(pending), owner_user_id="alice")
    finally:
        await engine.dispose()
