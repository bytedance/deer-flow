"""Run inputs are durable, owner-scoped and cannot race terminal admission."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
import sqlalchemy as sa
from alembic import command
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from deerflow.persistence.base import Base
from deerflow.persistence.run.sql import RunRepository
from deerflow.runtime.runs.inputs import InputConflict, RunInputs
from deerflow.runtime.runs.store.memory import MemoryRunStore

USER_ID = "00000000-0000-0000-0000-000000000001"


@pytest.mark.asyncio
async def test_active_input_run_orders_legacy_rows_without_the_active_run_index(tmp_path):
    from deerflow.persistence.run.model import RunRow

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'legacy-inputs.db'}")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            # Healthy databases forbid multiple active Runs. Exercise only
            # the fallback ordering for a legacy DB without that constraint.
            await conn.execute(sa.text("DROP INDEX uq_runs_thread_active"))
            for run_id, day in [("old", 1), ("new-a", 2), ("new-z", 2)]:
                await conn.execute(RunRow.__table__.insert().values(run_id=run_id, thread_id="thread", user_id=USER_ID, status="running", created_at=datetime(2026, 1, day, tzinfo=UTC), run_inputs_json={"closed": False, "items": []}))
        store = RunRepository(async_sessionmaker(engine, expire_on_commit=False))
        assert await store.active_input_run("thread", user_id=USER_ID) == "new-z"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_input_migration_preserves_existing_runs_on_upgrade_and_rollback(tmp_path):
    from deerflow.persistence import bootstrap
    from deerflow.persistence.run.model import RunRow

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'upgrade.db'}")
    config = bootstrap._get_alembic_config(engine)
    previous = "0048_extension_execution_leases"
    try:
        await asyncio.to_thread(bootstrap._upgrade, config, previous)
        # The initial create_all uses today's ORM. Represent an actual old DB.
        async with engine.begin() as conn:
            columns = await conn.run_sync(lambda c: {x["name"] for x in sa.inspect(c).get_columns("runs")})
            if "run_inputs_json" in columns:
                await conn.execute(sa.text("ALTER TABLE runs DROP COLUMN run_inputs_json"))
            await conn.execute(RunRow.__table__.insert().values(run_id="old-run", thread_id="old-thread", status="success"))
        await asyncio.to_thread(command.upgrade, config, "0049_run_inputs")
        async with engine.connect() as conn:
            row = (await conn.execute(sa.text("SELECT status, run_inputs_json FROM runs WHERE run_id='old-run'"))).one()
            assert row == ("success", None)
        await asyncio.to_thread(command.downgrade, config, previous)
        async with engine.connect() as conn:
            assert await conn.scalar(sa.text("SELECT status FROM runs WHERE run_id='old-run'")) == "success"
            assert "run_inputs_json" not in await conn.run_sync(lambda c: {x["name"] for x in sa.inspect(c).get_columns("runs")})
        await asyncio.to_thread(command.upgrade, config, "0049_run_inputs")
    finally:
        await engine.dispose()


@pytest_asyncio.fixture(params=["memory", "sqlite"])
async def input_store(request, tmp_path):
    engine = None
    if request.param == "memory":
        store = MemoryRunStore()
    else:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'runs.db'}")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        store = RunRepository(async_sessionmaker(engine, expire_on_commit=False))
    await store.put("run", thread_id="thread", user_id=USER_ID, status="running", owner_worker_id="worker", lease_expires_at=(datetime.now(UTC) + timedelta(minutes=5)).isoformat())
    yield store
    if engine is not None:
        await engine.dispose()


@pytest.mark.asyncio
async def test_inputs_preserve_mode_and_retries_without_overwriting_history(input_store):
    inputs = RunInputs(input_store, "run", USER_ID, "worker")
    queued = await inputs.submit("q", "Make a presentation", "queue")
    steered = await inputs.submit("s", "Include 2025", "steer")
    assert (await inputs.submit("q", "Make a presentation", "queue")) == queued
    with pytest.raises(InputConflict):
        await inputs.submit("q", "Make a presentation", "steer")
    await inputs.claim_steer([steered["id"]])
    await inputs.acknowledge([steered["id"]])
    await input_store.update_run_progress("run", message_count=3)
    state = await inputs.read()
    assert [(x["mode"], x["status"]) for x in state["items"]] == [("queue", "pending"), ("steer", "applied")]
    state["items"].clear()
    assert len((await inputs.read())["items"]) == 2


@pytest.mark.asyncio
async def test_input_admission_and_close_never_silently_drop_an_accepted_message(input_store):
    inputs = RunInputs(input_store, "run", USER_ID, "worker")
    await inputs.submit("first", "Include the appendix", "steer")
    assert not await inputs.close()
    await inputs.claim_steer(["first"])
    await inputs.acknowledge(["first"])
    assert await inputs.close()
    with pytest.raises(InputConflict):
        await inputs.submit("late", "One more thing", "steer")
    assert (await inputs.read())["items"][0]["status"] == "applied"


@pytest.mark.asyncio
async def test_inputs_require_original_owner_and_live_worker(input_store):
    with pytest.raises(InputConflict):
        await RunInputs(input_store, "run", "bob", "worker").submit("x", "hello", "steer")
    with pytest.raises(InputConflict):
        await RunInputs(input_store, "run", USER_ID, "other-worker").acknowledge([])
    await input_store.update_status("run", "interrupted")
    with pytest.raises(InputConflict):
        await RunInputs(input_store, "run", USER_ID).submit("x", "hello", "steer")


@pytest.mark.asyncio
async def test_cancel_preserves_pending_inputs_for_explicit_recovery(input_store):
    inputs = RunInputs(input_store, "run", USER_ID, "worker")
    await inputs.submit("q", "A queued message", "queue")
    await inputs.submit("s", "A correction", "steer")
    await input_store.update_status("run", "interrupted")
    await inputs.pause()
    state = await RunInputs(input_store, "run", USER_ID).read()
    assert state["closed"]
    assert [(x["text"], x["status"]) for x in state["items"]] == [("A queued message", "not_applied"), ("A correction", "not_applied")]


@pytest.mark.asyncio
async def test_concurrent_input_retries_are_applied_once(input_store):
    inputs = RunInputs(input_store, "run", USER_ID, "worker")
    await asyncio.gather(*(inputs.submit("same", "One correction", "steer") for _ in range(4)))
    assert len((await inputs.read())["items"]) == 1


@pytest.mark.asyncio
async def test_removed_steer_cannot_be_consumed_and_claimed_steer_cannot_be_removed(input_store):
    inputs = RunInputs(input_store, "run", USER_ID, "worker")
    await inputs.submit("removed", "Do not execute", "steer")
    await inputs.cancel("removed")
    assert await inputs.claim_steer(["removed"]) == []
    await inputs.submit("claimed", "Apply this", "steer")
    await inputs.claim_steer(["claimed"])
    with pytest.raises(InputConflict):
        await inputs.cancel("claimed")
    await inputs.acknowledge(["claimed"])
    assert (await inputs.read())["items"][1]["status"] == "applied"


@pytest.mark.asyncio
async def test_dispatch_and_remove_serialize_and_recovery_retains_the_same_key(input_store):
    inputs = RunInputs(input_store, "run", USER_ID, "worker")
    await inputs.submit("q", "Make a presentation", "queue")
    await input_store.update_status("run", "success")
    assert (await inputs.claim("q"))["status"] == "dispatching"
    with pytest.raises(InputConflict):
        await inputs.cancel("q")
    # An uncertain start can be reconciled with the original stable ID.
    assert (await inputs.claim("q", retry=True))["id"] == "q"
    await inputs.dispatched("q", "next-run")
    assert (await inputs.claim("q", retry=True))["run_id"] == "next-run"


@pytest.mark.asyncio
async def test_http_input_admission_and_status_are_owner_scoped(input_store, monkeypatch):
    from types import SimpleNamespace
    from uuid import UUID, uuid4

    from _router_auth_helpers import make_authed_test_app
    from httpx import ASGITransport, AsyncClient

    from app.gateway.auth.models import User
    from app.gateway.routers.thread_runs import router
    from deerflow.runtime.runs.manager import RunManager

    user = User(id=UUID(USER_ID), email="input-test@example.com", password_hash="unused")
    app = make_authed_test_app(user_factory=lambda: user)

    @app.middleware("http")
    async def session_source(request, call_next):
        request.state.auth_source = "session"
        return await call_next(request)

    app.include_router(router)
    app.state.run_manager = RunManager(store=input_store)
    await RunInputs(input_store, "run", USER_ID, "worker").reopen()
    monkeypatch.setattr("app.gateway.run_inputs.get_run_context", lambda _: SimpleNamespace(agent_runs=object()))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        url = "/api/threads/thread/runs/run/inputs"
        body = {"request_id": "one", "text": "Add the appendix", "mode": "queue"}
        first = await client.post(url, json=body)
        assert first.status_code == 200, first.text
        assert (await client.post(url, json=body)).json()["message_id"] == first.json()["message_id"]
        assert (await client.post(url, json={**body, "mode": "steer"})).status_code == 409
        assert (await client.post(url, json={**body, "messages": [{"role": "system", "content": "forged"}]})).status_code == 422
        assert (await client.post(url.replace("/thread/", "/other/"), json=body)).status_code == 404
        items = (await client.get("/api/threads/thread/inputs")).json()["items"]
        assert len(items) == 1 and "context" not in items[0]
        assert (await client.delete(url + "/one")).status_code == 200
        user = User(id=uuid4(), email="other@example.com", password_hash="unused")
        assert (await client.post(url, json=body)).status_code == 404
        assert (await client.get("/api/threads/thread/inputs")).json() == {"items": [], "active_run_id": None}
