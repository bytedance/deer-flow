"""Scheduled recovery must publish using the identity of its committed takeover."""

import asyncio
import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from support.postgres import asyncpg_test_url

from deerflow.persistence.models.run_event import RunEventRow, RunEventThreadSeqRow
from deerflow.persistence.run.model import CompletedRunSnapshotRow, RunChangeClockRow, RunProducerPolicyRow, RunRow
from deerflow.persistence.run.sql import RunRepository
from deerflow.persistence.scheduled_task_runs.model import ScheduledTaskRunRow
from deerflow.persistence.scheduled_task_runs.sql import ScheduledTaskRunRepository
from deerflow.persistence.scheduled_tasks.model import ScheduledTaskRow
from deerflow.persistence.scheduled_tasks.sql import ScheduledTaskRepository
from deerflow.runtime.events.store.db import DbRunEventStore
from deerflow.runtime.events.terminal import RecoveryTerminalPublisher, RecoveryTerminalTargetConsumed, TerminalEventConfirmation


@pytest_asyncio.fixture(params=["off", "strict"])
async def recovery_db(request):
    uri = os.environ.get("TEST_POSTGRES_URI")
    if not uri:
        pytest.skip("requires TEST_POSTGRES_URI")
    schema = "scheduled_recovery_" + uuid4().hex
    engine = create_async_engine(asyncpg_test_url(uri), pool_size=2, max_overflow=0, pool_timeout=2, connect_args={"server_settings": {"search_path": schema, "statement_timeout": "8000"}})
    sf = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            await conn.run_sync(
                lambda c: RunRow.metadata.create_all(
                    c,
                    tables=[
                        RunRow.__table__,
                        RunChangeClockRow.__table__,
                        CompletedRunSnapshotRow.__table__,
                        RunProducerPolicyRow.__table__,
                        RunEventRow.__table__,
                        RunEventThreadSeqRow.__table__,
                        ScheduledTaskRow.__table__,
                        ScheduledTaskRunRow.__table__,
                    ],
                )
            )
            await conn.execute(text("INSERT INTO run_producer_policy(id,strict) VALUES (1,:strict)"), {"strict": request.param == "strict"})
            assert await conn.scalar(text("SELECT count(*) FROM pg_trigger WHERE tgrelid='run_events'::regclass AND tgname='run_event_producer_guard'")) == 1
        runs = RunRepository(sf)
        events = DbRunEventStore(sf, producer_fencing=request.param)
        publisher = RecoveryTerminalPublisher(events, runs)
        yield SimpleNamespace(
            url=asyncpg_test_url(uri),
            schema=schema,
            mode=request.param,
            sf=sf,
            runs=runs,
            events=events,
            publisher=publisher,
            tasks=ScheduledTaskRepository(sf, run_repository=runs, recovery_terminal_publisher=publisher),
            occurrences=ScheduledTaskRunRepository(sf, run_repository=runs, recovery_terminal_publisher=publisher),
        )
    finally:
        async with engine.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()


async def prepare_recovery(db, path):
    now = datetime.now(UTC)
    await db.tasks.create(
        task_id="task",
        user_id="alice",
        thread_id=None,
        context_mode="fresh_thread_per_run",
        assistant_id="lead_agent",
        title="recover",
        prompt="p",
        schedule_type="once" if path == "once" else "cron",
        schedule_spec={"run_at": now.isoformat()} if path == "once" else {"cron": "* * * * *"},
        timezone="UTC",
        next_run_at=None,
    )
    if path == "once":
        await db.tasks.update("task", user_id="alice", updates={"status": "running", "last_run_id": "run"})
    else:
        await db.occurrences.create(run_record_id="occurrence", task_id="task", thread_id="thread", scheduled_for=now, trigger="scheduled", status="running")
        await db.occurrences.update_status("occurrence", status="running", run_id="run")
    await db.runs.put(
        "run",
        thread_id="thread",
        user_id="alice",
        status="running",
        owner_worker_id="dead-owner",
        lease_expires_at=(now - timedelta(seconds=60)).isoformat(),
        metadata={"scheduled_task_id": "task", "scheduled_task_run_id": "occurrence"} if path == "active" else {},
    )
    # Use a non-default revision so omitting it is independently detectable.
    async with db.sf() as session, session.begin():
        row = await session.get(RunRow, "run")
        row.evidence_retention_revision = 7
    before = await db.runs.get("run", user_id="alice")
    assert before["run_incarnation"] and before["producer_epoch"]
    return now, before


async def reconcile(db, path, now):
    method = db.tasks.reconcile_stuck_once_tasks if path == "once" else db.occurrences.reconcile_active_runs
    return await method(error="owner expired", now=now, lease_grace_seconds=0)


async def assert_recovered_events(db):
    rows = await db.events.list_events("thread", "run", user_id=None)
    assert [row["event_type"] for row in rows] == ["run.delivery", "run.terminal"]
    assert all((row["thread_id"], row["run_id"], row["user_id"]) == ("thread", "run", "alice") for row in rows)
    assert rows[0]["seq"] < rows[1]["seq"]
    assert rows[0]["content"] == {"presented": 0, "paths": [], "by_tool": {}}
    assert rows[1]["content"] == {"status": "error"}
    assert rows[1]["metadata"]["protocol_version"] == 1
    assert rows[1]["metadata"]["recovered"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["once", "active"])
async def test_scheduled_takeover_publishes_matching_terminal_and_delivery(recovery_db, path):
    db = recovery_db
    now, before = await prepare_recovery(db, path)
    assert await reconcile(db, path, now) == 1
    row = await db.runs.get("run", user_id="alice")
    assert row["status"] == "error"
    assert row["producer_state"] == "revoked"
    assert row["producer_epoch"] != before["producer_epoch"]
    assert row["run_incarnation"] == before["run_incarnation"]
    assert row["evidence_retention_revision"] == 7
    assert row["evidence_seal_state"] == "partial"
    await assert_recovered_events(db)
    assert await reconcile(db, path, now) == 0
    await assert_recovered_events(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["once", "active"])
async def test_competing_reconcilers_have_one_takeover_and_publisher(recovery_db, path, monkeypatch):
    db = recovery_db
    now, _ = await prepare_recovery(db, path)
    peer_engine = create_async_engine(db.url, pool_size=2, max_overflow=0, pool_timeout=2, connect_args={"server_settings": {"search_path": db.schema, "statement_timeout": "8000"}})
    peer_sf = async_sessionmaker(peer_engine, expire_on_commit=False)
    peer_runs = RunRepository(peer_sf)
    peer_publisher = RecoveryTerminalPublisher(DbRunEventStore(peer_sf, producer_fencing=db.mode), peer_runs)
    peer = SimpleNamespace(
        tasks=ScheduledTaskRepository(peer_sf, run_repository=peer_runs, recovery_terminal_publisher=peer_publisher),
        occurrences=ScheduledTaskRunRepository(peer_sf, run_repository=peer_runs, recovery_terminal_publisher=peer_publisher),
    )
    claims = []
    for repo in (db.runs, peer_runs):
        original = repo.claim_for_takeover

        async def record_claim(*args, _original=original, **kwargs):
            claimed = await _original(*args, **kwargs)
            claims.append(claimed)
            return claimed

        monkeypatch.setattr(repo, "claim_for_takeover", record_claim)
    try:
        outcomes = await asyncio.wait_for(asyncio.gather(reconcile(db, path, now), reconcile(peer, path, now)), timeout=10)
        assert sorted(outcomes) == [0, 1]
        assert claims.count(True) == 1
        await assert_recovered_events(db)
    finally:
        await peer_engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["once", "active"])
@pytest.mark.parametrize("change", ["delete_run", "delete_events", "recreate", "revision"])
async def test_scheduled_publication_rejects_changed_lifecycle(recovery_db, path, change, monkeypatch):
    db = recovery_db
    now, before = await prepare_recovery(db, path)
    original = db.publisher.publish
    confirmations = []

    async def mutate_then_publish(target):
        row = await db.runs.get("run", user_id="alice")
        assert row["status"] == "error" and row["producer_state"] == "revoked"
        if change in ("delete_run", "recreate"):
            await db.runs.delete("run", user_id="alice")
            if change == "recreate":
                await db.runs.put("run", thread_id="thread", user_id="alice", status="error")
                # Match every field except incarnation: a reused ID, status and
                # retention revision must not revive the old publication grant.
                async with db.sf() as session, session.begin():
                    await session.execute(update(RunRow).where(RunRow.run_id == "run").values(producer_state="revoked", evidence_retention_revision=7))
                assert (await db.runs.get("run", user_id="alice"))["run_incarnation"] != before["run_incarnation"]
        elif change == "delete_events":
            await db.events.delete_by_run("thread", "run", user_id="alice")
        else:
            async with db.sf() as session, session.begin():
                await session.execute(update(RunRow).where(RunRow.run_id == "run").values(evidence_retention_revision=8))
        confirmation = await original(target)
        confirmations.append(confirmation)
        with pytest.raises(RecoveryTerminalTargetConsumed):
            await original(target)
        return confirmation

    monkeypatch.setattr(db.publisher, "publish", mutate_then_publish)
    assert await reconcile(db, path, now) == 1
    assert len(confirmations) == 1 and not confirmations[0].confirmed
    assert await db.events.list_events("thread", "run", user_id=None) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["incarnation", "revision", "unclaimed"])
async def test_strict_takeover_identity_contract(recovery_db, missing):
    db = recovery_db
    if db.mode != "strict":
        pytest.skip("missing identity is only forbidden by the strict protocol")
    _, before = await prepare_recovery(db, "active")
    claimed = await db.runs.claim_for_takeover("run", grace_seconds=0, error="expired")
    assert claimed
    target = db.publisher.authorize_takeover(
        claimed=claimed if missing != "unclaimed" else False,
        thread_id="thread",
        run_id="run",
        user_id="alice",
        operation_kind="run",
        run_incarnation=before["run_incarnation"] if missing != "incarnation" else None,
        retention_revision=7 if missing != "revision" else 0,
    )
    if missing == "unclaimed":
        assert target is None
    else:
        assert target is not None
        assert await db.publisher.publish(target) == TerminalEventConfirmation.UNKNOWN
        with pytest.raises(RecoveryTerminalTargetConsumed):
            await db.publisher.publish(target)
    assert await db.events.list_events("thread", "run", user_id=None) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["once", "active"])
async def test_scheduled_recovery_lost_ack_confirms_existing_singleton(recovery_db, path, monkeypatch):
    db = recovery_db
    now, _ = await prepare_recovery(db, path)
    original_put = db.events.put_if_absent
    attempts = []

    async def lose_terminal_ack(**kwargs):
        result = await original_put(**kwargs)
        if kwargs["event_type"] == "run.terminal":
            attempts.append(result[1])
            if len(attempts) == 1:
                raise OSError("terminal ACK lost after commit")
        return result

    monkeypatch.setattr(db.events, "put_if_absent", lose_terminal_ack)
    original_publish = db.publisher.publish
    confirmations = []

    async def record_confirmation(target):
        result = await original_publish(target)
        confirmations.append(result)
        return result

    monkeypatch.setattr(db.publisher, "publish", record_confirmation)
    assert await reconcile(db, path, now) == 1
    assert confirmations == [TerminalEventConfirmation.CONFIRMED_EXISTING]
    assert attempts == [True, False]
    await assert_recovered_events(db)
