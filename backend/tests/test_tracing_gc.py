"""Conservative tracing retention never removes a recovery reference."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, text


@pytest.fixture
def authority(tmp_path):
    import deerflow.persistence.models  # noqa: F401
    from deerflow.config.app_config import AppConfig
    from deerflow.persistence.base import Base

    config = AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}, "database": {"backend": "sqlite", "sqlite_dir": str(tmp_path)}})
    engine = create_engine(config.database.app_sync_sqlalchemy_url)
    Base.metadata.create_all(engine)
    from langgraph.checkpoint.sqlite import SqliteSaver

    with SqliteSaver.from_conn_string(config.database.sqlite_path) as saver:
        saver.setup()
    try:
        yield config, engine
    finally:
        engine.dispose()


def seed_snapshot(engine, snapshot_id="a" * 32, *, state="published", days=30):
    from deerflow.persistence.tracing_profiles.model import RunTracingSnapshotRow

    with engine.begin() as connection:
        connection.execute(
            RunTracingSnapshotRow.__table__.insert().values(
                snapshot_id=snapshot_id,
                owner_user_id="alice",
                agent_name="lead_agent",
                agent_incarnation="builtin:lead_agent",
                mode="inherit",
                binding_revision=0,
                payload_ciphertext="opaque-not-decrypted",
                retention_state=state,
                created_at=datetime.now(UTC) - timedelta(days=days),
            )
        )
    return snapshot_id


def remaining(engine):
    with engine.connect() as connection:
        return set(connection.execute(text("SELECT snapshot_id FROM run_tracing_snapshots")).scalars())


def test_snapshot_model_marks_legacy_and_embedded_unmanaged():
    from deerflow.persistence.tracing_profiles.model import RunTracingSnapshotRow

    assert {"created_at", "retention_state"} <= set(RunTracingSnapshotRow.__table__.columns.keys())
    assert RunTracingSnapshotRow.__table__.c.retention_state.default.arg == "unmanaged"


def test_gc_is_dry_run_by_default_and_apply_is_idempotent(authority):
    from deerflow.persistence.tracing_profiles.gc import cleanup_tracing_records

    config, engine = authority
    old = seed_snapshot(engine)
    seed_snapshot(engine, "b" * 32, state="unmanaged")
    seed_snapshot(engine, "c" * 32, state="pending")
    seed_snapshot(engine, "d" * 32, days=1)
    result = cleanup_tracing_records(config)
    assert result["snapshot_candidates"] == 1 and result["snapshots_deleted"] == 0
    assert old in remaining(engine)
    assert cleanup_tracing_records(config, apply=True)["snapshots_deleted"] == 1
    assert remaining(engine) == {"b" * 32, "c" * 32, "d" * 32}
    assert cleanup_tracing_records(config, apply=True)["snapshots_deleted"] == 0


@pytest.mark.parametrize("carrier", ["run", "kwargs", "queue", "batch", "checkpoint"])
@pytest.mark.parametrize("escaped", [False, True], ids=["plain", "escaped"])
def test_every_durable_reference_protects_a_snapshot(authority, carrier, escaped):
    from deerflow.persistence.tracing_profiles.gc import cleanup_tracing_records

    config, engine = authority
    snapshot = seed_snapshot(engine)
    payload = {"deerflow_tracing_snapshot_id": snapshot}
    with engine.begin() as connection:
        if carrier in {"run", "kwargs"}:
            from deerflow.persistence.run.model import RunRow

            connection.execute(RunRow.__table__.insert().values(run_id="history", thread_id="thread", status="interrupted", **{"metadata_json" if carrier == "run" else "kwargs_json": payload}))
        elif carrier == "queue":
            from deerflow.persistence.scheduled_task_runs.model import ScheduledTaskRunRow

            connection.execute(
                ScheduledTaskRunRow.__table__.insert().values(id="occurrence", task_id="deleted-parent", thread_id="thread", scheduled_for=datetime.now(UTC), trigger="manual", status="interrupted", tracing_snapshot_refs=payload)
            )
        elif carrier == "batch":
            from deerflow.persistence.subagent_batches.model import SubagentBatchRow

            connection.execute(
                SubagentBatchRow.__table__.insert().values(
                    id="batch",
                    user_id="alice",
                    thread_id="thread",
                    run_id="deleted-run",
                    tool_call_id="call",
                    submission_key="key",
                    title="Paused",
                    subagent_type="test",
                    status="paused",
                    total_items=1,
                    max_live_items=1,
                    max_running_items=1,
                    max_attempts=1,
                    execution_spec=payload,
                )
            )
        else:
            import json

            connection.execute(text("INSERT INTO checkpoints (thread_id, checkpoint_ns, checkpoint_id, metadata) VALUES ('branch-without-run', 'tools:child', 'historical', :metadata)"), {"metadata": json.dumps(payload)})
        if escaped:
            table, column = {
                "run": ("runs", "metadata_json"),
                "kwargs": ("runs", "kwargs_json"),
                "queue": ("scheduled_task_runs", "tracing_snapshot_refs"),
                "batch": ("subagent_batches", "execution_spec"),
                "checkpoint": ("checkpoints", "metadata"),
            }[carrier]
            raw = '{"deerflow_tracing_snapshot_id":"' + "\\u0061" * 32 + '"}'
            connection.execute(text(f"UPDATE {table} SET {column}=:metadata"), {"metadata": raw})
    assert cleanup_tracing_records(config, apply=True)["snapshots_deleted"] == 0
    assert remaining(engine) == {snapshot}


@pytest.mark.parametrize("kind", ["run", "branch", "checkpoint_write", "delete"])
def test_active_thread_mutations_skip_snapshot_gc(authority, kind):
    from deerflow.persistence.run.model import RunRow
    from deerflow.persistence.tracing_profiles.gc import cleanup_tracing_records

    config, engine = authority
    seed_snapshot(engine)
    with engine.begin() as connection:
        connection.execute(RunRow.__table__.insert().values(run_id="active", thread_id="source", operation_kind=kind, status="pending"))
    result = cleanup_tracing_records(config, apply=True)
    assert result["snapshot_skip_reason"] == "active_thread_operations"
    assert len(remaining(engine)) == 1


@pytest.mark.parametrize("status", ["interrupted", "success", "error"])
def test_live_owner_lease_protects_unfinished_terminal_cleanup(authority, status):
    from deerflow.persistence.run.model import RunRow
    from deerflow.persistence.tracing_profiles.gc import cleanup_tracing_records

    config, engine = authority
    seed_snapshot(engine)
    with engine.begin() as connection:
        connection.execute(RunRow.__table__.insert().values(run_id="finalizing", thread_id="thread", status=status, owner_worker_id="worker", lease_expires_at=datetime.now(UTC) + timedelta(minutes=5)))
    assert cleanup_tracing_records(config, apply=True)["snapshot_skip_reason"] == "active_thread_operations"
    assert len(remaining(engine)) == 1


@pytest.mark.parametrize("damage", ["missing_table", "invalid_metadata", "legacy_config", "unsupported_metadata_type"])
def test_incomplete_checkpoint_authority_fails_closed(authority, damage):
    from deerflow.config.checkpointer_config import CheckpointerConfig
    from deerflow.persistence.tracing_profiles.gc import cleanup_tracing_records

    config, engine = authority
    seed_snapshot(engine)
    if damage == "legacy_config":
        config.checkpointer = CheckpointerConfig(type="memory")
    else:
        with engine.begin() as connection:
            if damage == "missing_table":
                connection.execute(text("DROP TABLE checkpoints"))
            elif damage == "unsupported_metadata_type":
                connection.execute(text("DROP TABLE checkpoints"))
                connection.execute(
                    text("CREATE TABLE checkpoints (thread_id TEXT, checkpoint_ns TEXT, checkpoint_id TEXT, parent_checkpoint_id TEXT, type TEXT, checkpoint BLOB, metadata INTEGER, PRIMARY KEY(thread_id,checkpoint_ns,checkpoint_id))")
                )
            else:
                connection.execute(text("INSERT INTO checkpoints (thread_id, checkpoint_ns, checkpoint_id, metadata) VALUES ('thread', '', 'bad', 'not-json')"))
    result = cleanup_tracing_records(config, apply=True)
    assert result["snapshot_skip_reason"]
    assert len(remaining(engine)) == 1


def test_gc_limit_is_a_total_record_bound(authority):
    from deerflow.persistence.tracing_profiles.gc import cleanup_tracing_records

    config, engine = authority
    for number in range(5):
        seed_snapshot(engine, f"{number:032x}")
    result = cleanup_tracing_records(config, limit=2, apply=True)
    assert result["snapshots_deleted"] + result["profile_versions_deleted"] <= 2
    assert len(remaining(engine)) == 3


def test_cleanup_does_not_advance_the_run_change_clock(authority):
    from deerflow.persistence.tracing_profiles.gc import cleanup_tracing_records

    config, engine = authority
    seed_snapshot(engine)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO run_change_clock (id,value) VALUES (1,987)"))
    assert cleanup_tracing_records(config, apply=True)["snapshots_deleted"] == 1
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT value FROM run_change_clock WHERE id=1")) == 987


@pytest.mark.parametrize("limit", [-1, 0, 1001, True])
def test_invalid_limit_is_rejected_before_authority_access(limit):
    from deerflow.persistence.tracing_profiles.gc import cleanup_tracing_records

    with pytest.raises(ValueError, match="limit"):
        cleanup_tracing_records(object(), limit=limit, apply=True)


def test_released_attempt_can_be_collected_but_ambiguous_pending_stays(authority):
    from deerflow.persistence.tracing_profiles.gc import cleanup_tracing_records

    config, engine = authority
    released = seed_snapshot(engine, state="released")
    pending = seed_snapshot(engine, "b" * 32, state="pending")
    assert cleanup_tracing_records(config, apply=True)["snapshots_deleted"] == 1
    assert remaining(engine) == {pending} and released not in remaining(engine)


def test_profile_version_gc_keeps_head_and_every_retained_snapshot(authority):
    from deerflow.persistence.tracing_profiles.gc import cleanup_tracing_records
    from deerflow.persistence.tracing_profiles.model import TracingProfileRow, TracingProfileVersionRow

    config, engine = authority
    snapshot = seed_snapshot(engine, state="unmanaged")
    with engine.begin() as connection:
        connection.execute(TracingProfileRow.__table__.insert().values(id="profile", name="Head", revision=3, providers_ciphertext="opaque", allowed_user_ids=[]))
        for version in (1, 2, 3):
            connection.execute(TracingProfileVersionRow.__table__.insert().values(profile_id="profile", name="History", revision=version, providers_ciphertext="opaque", allowed_user_ids=[]))
        connection.execute(text("UPDATE run_tracing_snapshots SET profile_id='profile', profile_revision=1 WHERE snapshot_id=:id"), {"id": snapshot})
    assert cleanup_tracing_records(config)["profile_version_candidates"] == 1
    assert cleanup_tracing_records(config, apply=True)["profile_versions_deleted"] == 1
    with engine.connect() as connection:
        assert connection.execute(text("SELECT revision FROM tracing_profile_versions ORDER BY revision")).scalars().all() == [1, 3]


def test_actual_sdk_metadata_is_json_and_protects_checkpoint_only_history(authority):
    from langgraph.checkpoint.base import empty_checkpoint
    from langgraph.checkpoint.sqlite import SqliteSaver

    from deerflow.persistence.tracing_profiles.gc import cleanup_tracing_records

    config, engine = authority
    snapshot = seed_snapshot(engine)
    with SqliteSaver.from_conn_string(config.database.sqlite_path) as saver:
        saver.put({"configurable": {"thread_id": "checkpoint-only", "checkpoint_ns": "tools:child"}}, empty_checkpoint(), {"deerflow_tracing_snapshot_id": snapshot}, {})
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT json_valid(metadata) FROM checkpoints")) == 1
        assert connection.scalar(text("SELECT json_extract(metadata, '$.deerflow_tracing_snapshot_id') FROM checkpoints")) == snapshot
    assert cleanup_tracing_records(config, apply=True)["snapshots_deleted"] == 0


def test_cleanup_cli_is_explicit_apply_and_lazy_dispatch(authority, monkeypatch, capsys):
    import json

    from deerflow.config import app_config
    from deerflow.tui.cli import main

    config, engine = authority
    seed_snapshot(engine)
    monkeypatch.setattr(app_config, "get_app_config", lambda: config)
    assert main(["tracing", "cleanup"]) == 0
    assert json.loads(capsys.readouterr().out)["dry_run"] is True
    assert len(remaining(engine)) == 1
    assert main(["tracing", "cleanup", "--apply"]) == 0
    assert json.loads(capsys.readouterr().out)["snapshots_deleted"] == 1
    assert remaining(engine) == set()


def _gc_in_process(directory, attempted, selected, release, done, output, pause_delete):
    from types import SimpleNamespace

    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    from deerflow.config.database_config import DatabaseConfig
    from deerflow.persistence.tracing_profiles.gc import cleanup_tracing_records

    @event.listens_for(Engine, "before_cursor_execute")
    def observe(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.startswith("UPDATE tracing_admission_fence"):
            attempted.set()
        if pause_delete and statement.startswith("DELETE FROM run_tracing_snapshots"):
            selected.set()
            if not release.wait(20):
                raise RuntimeError("test did not release the owned GC transaction")

    try:
        output.put(cleanup_tracing_records(SimpleNamespace(database=DatabaseConfig(backend="sqlite", sqlite_dir=directory), checkpointer=None), apply=True))
    finally:
        done.set()


def _seed_binding(engine):
    from deerflow.persistence.tracing_profiles.model import AgentTracingBindingRow

    with engine.begin() as connection:
        connection.execute(AgentTracingBindingRow.__table__.insert().values(owner_user_id="alice", agent_name="lead_agent", mode="inherit", revision=0, agent_incarnation="builtin:lead_agent"))


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["run", "branch"])
async def test_cross_process_gc_excludes_new_run_and_branch_admissions(authority, kind):
    import asyncio
    import multiprocessing

    from sqlalchemy import event
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from deerflow.persistence.run import RunRepository
    from deerflow.tracing.profiles import TracingUnavailableError

    config, engine = authority
    snapshot = seed_snapshot(engine)
    _seed_binding(engine)
    context = multiprocessing.get_context("spawn")
    attempted, selected, release, done, output = context.Event(), context.Event(), context.Event(), context.Event(), context.Queue()
    process = context.Process(target=_gc_in_process, args=(config.database.sqlite_dir, attempted, selected, release, done, output, True))
    async_engine = create_async_engine(config.database.app_sqlalchemy_url)
    admission_started = asyncio.Event()

    @event.listens_for(async_engine.sync_engine, "before_cursor_execute")
    def observe(_connection, _cursor, statement, _parameters, _context, _many):
        if (kind == "run" and (statement.startswith("UPDATE tracing_admission_fence") or statement == "BEGIN IMMEDIATE")) or (kind == "branch" and statement.startswith("INSERT INTO run_change_clock")):
            admission_started.set()

    task = None
    try:
        process.start()
        assert await asyncio.to_thread(selected.wait, 20)
        repo = RunRepository(async_sessionmaker(async_engine, expire_on_commit=False))
        metadata = {"deerflow_tracing_snapshot_id": snapshot, "deerflow_tracing_agent_name": "lead_agent", "deerflow_tracing_pinned": True}
        task = asyncio.create_task(
            repo.create_thread_operation_atomic("new-admission", thread_id="new-thread", owner_worker_id="worker", lease_expires_at=None, operation_kind=kind, user_id="alice", metadata=metadata if kind == "run" else {})
        )
        await asyncio.wait_for(admission_started.wait(), 10)
        assert not task.done()
        release.set()
        if kind == "run":
            with pytest.raises(TracingUnavailableError):
                await asyncio.wait_for(task, 10)
        else:
            await asyncio.wait_for(task, 10)
        assert await asyncio.to_thread(done.wait, 10)
        assert output.get(timeout=5)["snapshots_deleted"] == 1
        assert snapshot not in remaining(engine)
    finally:
        release.set()
        if task is not None:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await async_engine.dispose()
        if process.pid:
            await asyncio.to_thread(process.join, 10)
            if process.is_alive():
                process.kill()
                await asyncio.to_thread(process.join)
        output.close()


@pytest.mark.asyncio
async def test_cross_process_gc_waits_for_admission_commit_and_keeps_its_snapshot(authority):
    import asyncio
    import multiprocessing

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from deerflow.persistence.run import RunRepository

    config, engine = authority
    snapshot = seed_snapshot(engine)
    _seed_binding(engine)
    committing, allow_commit = asyncio.Event(), asyncio.Event()

    class PausedCommit(AsyncSession):
        async def commit(self):
            committing.set()
            await allow_commit.wait()
            await super().commit()

    context = multiprocessing.get_context("spawn")
    attempted, selected, release, done, output = context.Event(), context.Event(), context.Event(), context.Event(), context.Queue()
    release.set()
    process = context.Process(target=_gc_in_process, args=(config.database.sqlite_dir, attempted, selected, release, done, output, False))
    async_engine = create_async_engine(config.database.app_sqlalchemy_url)
    repo = RunRepository(async_sessionmaker(async_engine, class_=PausedCommit, expire_on_commit=False))
    task = asyncio.create_task(
        repo.create_thread_operation_atomic(
            "committing",
            thread_id="thread",
            owner_worker_id="worker",
            lease_expires_at=None,
            user_id="alice",
            metadata={"deerflow_tracing_snapshot_id": snapshot, "deerflow_tracing_agent_name": "lead_agent", "deerflow_tracing_pinned": True},
        )
    )
    try:
        await asyncio.wait_for(committing.wait(), 10)
        process.start()
        assert await asyncio.to_thread(attempted.wait, 20)
        assert not done.is_set()
        allow_commit.set()
        await asyncio.wait_for(task, 10)
        assert await asyncio.to_thread(done.wait, 10)
        assert output.get(timeout=5)["snapshot_skip_reason"] == "active_thread_operations"
        assert snapshot in remaining(engine)
    finally:
        allow_commit.set()
        await asyncio.gather(task, return_exceptions=True)
        await async_engine.dispose()
        if process.pid:
            await asyncio.to_thread(process.join, 10)
            if process.is_alive():
                process.kill()
                await asyncio.to_thread(process.join)
        output.close()
