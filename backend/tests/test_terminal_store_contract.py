"""Execute the terminal/lease contract against memory and real SQL backends."""

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from support.postgres import asyncpg_test_url

from deerflow.persistence.run import RunRepository
from deerflow.persistence.run.model import RunChangeClockRow, RunRow
from deerflow.runtime.runs.store.memory import MemoryRunStore


@pytest.fixture(params=["memory", "sqlite", "postgresql"])
async def store(request, tmp_path):
    if request.param == "memory":
        yield MemoryRunStore()
        return
    schema = None
    if request.param == "postgresql":
        uri = os.getenv("TEST_POSTGRES_URI")
        if not uri:
            pytest.skip("set TEST_POSTGRES_URI for real PostgreSQL terminal/lease contracts")
        schema = f"r2_{uuid.uuid4().hex}"
        engine = create_async_engine(asyncpg_test_url(uri), connect_args={"server_settings": {"search_path": schema}})
    else:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'r2.db'}")
    try:
        async with engine.begin() as conn:
            if schema:
                await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            await conn.run_sync(lambda c: RunRow.metadata.create_all(c, tables=[RunRow.__table__, RunChangeClockRow.__table__]))
        yield RunRepository(async_sessionmaker(engine, expire_on_commit=False))
    finally:
        if schema:
            async with engine.begin() as conn:
                await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await engine.dispose()


async def put(store, *, expired=False):
    expiry = (datetime.now(UTC) + timedelta(seconds=-1 if expired else 30)).isoformat()
    await store.put("run", thread_id="thread", status="running", owner_worker_id="owner", lease_expires_at=expiry)
    return expiry


@pytest.mark.anyio
async def test_expired_lease_cannot_be_resurrected(store):
    expired = await put(store, expired=True)
    renewal = await store.renew_lease("run", owner_worker_id="owner", lease_expires_at=(datetime.now(UTC) + timedelta(seconds=60)).isoformat())
    assert not renewal.renewed
    assert datetime.fromisoformat((await store.get("run"))["lease_expires_at"]) == datetime.fromisoformat(expired)


@pytest.mark.anyio
@pytest.mark.parametrize("expired,owner", [(True, "owner"), (False, "peer")])
async def test_terminal_cas_requires_live_owner(store, expired, owner):
    await put(store, expired=expired)
    result = await store.finalize_if_not_cancelled("run", status="success", owner_worker_id=owner)
    assert not result.finalized
    assert (await store.get("run"))["status"] == "running"


@pytest.mark.anyio
async def test_cancel_wins_and_metadata_cannot_bypass_cas(store):
    await put(store)
    assert await store.request_cancel("run", action="rollback") == "rollback"
    result = await store.finalize_if_not_cancelled("run", status="success", owner_worker_id="owner")
    assert not result.finalized
    assert result.cancel_action == "rollback"
    assert await store.update_run_completion("run", status="success", require_terminal=True, owner_worker_id="owner", total_tokens=5) is False
    assert (await store.get("run"))["status"] == "running"


@pytest.mark.anyio
async def test_confirmed_terminal_allows_only_matching_metadata(store):
    await put(store)
    assert (await store.finalize_if_not_cancelled("run", status="success", owner_worker_id="owner")).finalized
    assert await store.update_run_completion("run", status="error", require_terminal=True, owner_worker_id="owner") is False
    assert await store.update_run_completion("run", status="success", require_terminal=True, owner_worker_id="peer") is False
    assert await store.update_run_completion("run", status="success", require_terminal=True, owner_worker_id="owner", total_tokens=5) is True
    assert (await store.get("run"))["total_tokens"] == 5


@pytest.mark.anyio
async def test_terminal_metadata_needs_matching_owner_and_outcome_but_not_live_lease(store):
    expired = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    await store.put("run", thread_id="thread", status="success", owner_worker_id="owner", lease_expires_at=expired)
    assert await store.update_run_completion("run", status="success", require_terminal=True, owner_worker_id="owner", total_tokens=5)
    assert await store.update_run_completion("run", status="success", require_terminal=True, owner_worker_id="peer", total_tokens=10) is False
    assert await store.update_run_completion("run", status="error", require_terminal=True, owner_worker_id="owner", total_tokens=10) is False
    row = await store.get("run")
    assert row["status"] == "success"
    assert row["total_tokens"] == 5
    assert datetime.fromisoformat(row["lease_expires_at"]) == datetime.fromisoformat(expired)


@pytest.mark.anyio
@pytest.mark.parametrize("method", ["renew_lease", "update_lease", "finalize_if_not_cancelled", "update_status"])
async def test_postgres_checks_database_time_after_row_lock(store, monkeypatch, method):
    """A transaction begun before expiry cannot write after waiting past it."""
    if not isinstance(store, RunRepository) or store._sf.kw["bind"].dialect.name != "postgresql":
        pytest.skip("requires PostgreSQL row locks and clock_timestamp")
    import asyncio

    from sqlalchemy import func, select

    expiry = datetime.now(UTC) + timedelta(milliseconds=300)
    await store.put("locked", thread_id="locked-thread", status="running", owner_worker_id="owner", lease_expires_at=expiry.isoformat())
    entered = asyncio.Event()
    lock = store._lock_owned_row

    async def observe_transaction_start(session, run_id):
        assert await session.scalar(select(func.clock_timestamp())) < expiry
        entered.set()
        await lock(session, run_id)

    monkeypatch.setattr(store, "_lock_owned_row", observe_transaction_start)
    operation = None
    async with store._sf() as blocker:
        await blocker.execute(select(RunRow).where(RunRow.run_id == "locked").with_for_update())
        try:
            if method in ("renew_lease", "update_lease"):
                operation = asyncio.create_task(getattr(store, method)("locked", owner_worker_id="owner", lease_expires_at=(expiry + timedelta(seconds=30)).isoformat()))
            elif method == "update_status":
                operation = asyncio.create_task(store.update_status("locked", "error", owner_worker_id="owner"))
            else:
                operation = asyncio.create_task(store.finalize_if_not_cancelled("locked", status="success", owner_worker_id="owner"))
            await asyncio.wait_for(entered.wait(), 1)
            async with asyncio.timeout(2):
                while await blocker.scalar(select(func.clock_timestamp())) <= expiry:
                    await asyncio.sleep(0.01)
            assert not operation.done()
        finally:
            await blocker.rollback()
    assert operation is not None
    result = await asyncio.wait_for(operation, 1)
    if method == "renew_lease":
        assert not result.renewed
    elif method == "finalize_if_not_cancelled":
        assert not result.finalized
    else:
        assert result is False
    row = await store.get("locked")
    assert row["status"] == "running"
    assert datetime.fromisoformat(row["lease_expires_at"]) == expiry


@pytest.mark.anyio
async def test_durable_cancel_does_not_authorize_expired_terminal_writer(store):
    await put(store, expired=True)
    assert await store.request_cancel("run", action="rollback") == "rollback"
    result = await store.finalize_if_not_cancelled("run", status="success", owner_worker_id="owner")
    assert not result.finalized
    assert result.cancel_action is None


@pytest.mark.anyio
async def test_renewal_cannot_write_an_already_expired_target(store):
    original = await put(store)
    renewal = await store.renew_lease("run", owner_worker_id="owner", lease_expires_at=(datetime.now(UTC) - timedelta(seconds=1)).isoformat())
    assert not renewal.renewed
    assert datetime.fromisoformat((await store.get("run"))["lease_expires_at"]) == datetime.fromisoformat(original)


@pytest.mark.anyio
async def test_strict_completion_cannot_rewrite_terminal_outcome_fields(store):
    await put(store)
    verdict = {"satisfied": True}
    assert (await store.finalize_if_not_cancelled("run", status="success", owner_worker_id="owner", goal_verdict=verdict)).finalized
    assert await store.update_run_completion("run", status="success", require_terminal=True, owner_worker_id="owner", error="changed", goal_verdict={"satisfied": False}, total_tokens=5)
    row = await store.get("run")
    assert row.get("error") is None
    assert row["goal_verdict"] == verdict
    assert row["total_tokens"] == 5


@pytest.mark.anyio
async def test_terminal_cancel_row_does_not_report_active_cancellation_win(store):
    await put(store)
    assert await store.request_cancel("run", action="interrupt") == "interrupt"
    assert await store.update_status("run", "interrupted", owner_worker_id="owner")
    result = await store.finalize_if_not_cancelled("run", status="success", owner_worker_id="owner")
    assert not result.finalized
    assert result.cancel_action is None


@pytest.mark.anyio
async def test_owned_status_success_cannot_bypass_durable_cancel(store):
    await put(store)
    assert await store.request_cancel("run", action="interrupt") == "interrupt"
    assert await store.update_status("run", "success", owner_worker_id="owner") is False
    assert (await store.get("run"))["status"] == "running"
