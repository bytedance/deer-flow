"""Run inputs are durable, owner-scoped and cannot race terminal admission."""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
import pytest_asyncio
import sqlalchemy as sa
from alembic import command
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from deerflow.persistence.base import Base
from deerflow.persistence.run.sql import RunRepository
from deerflow.runtime.runs.inputs import InputCancelled, InputConflict, RunInputs
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
@pytest.mark.parametrize("cancel_at", ["before_snapshot", "while_waiting", "before_claim"])
async def test_queue_dispatch_skips_cancelled_input_and_runs_its_successor(input_store, cancel_at):
    from app.gateway.run_inputs import dispatch_queued_inputs

    inputs = RunInputs(input_store, "run", USER_ID, "worker")
    for input_id in ("B", "C", "D"):
        await inputs.submit(input_id, f"Reply {input_id}_DONE", "queue")
    await input_store.update_status("run", "success")
    if cancel_at == "before_snapshot":
        await inputs.cancel("C")
    dispatched = []

    async def dispatch_input(*, thread_id, run_id, input_id):
        if input_id == "C" and cancel_at == "before_claim":
            # Even a fresh read before dispatch cannot rule out cancellation
            # while admission yields, before the store's atomic claim.
            await inputs.cancel("C")
        await inputs.claim(input_id)
        dispatched.append(input_id)
        await inputs.dispatched(input_id, f"child-{input_id}")
        return SimpleNamespace(run_id=f"child-{input_id}", status="running")

    async def wait(*, thread_id, run_id, timeout):
        if run_id == "child-B" and cancel_at == "while_waiting":
            await inputs.cancel("C")
        return SimpleNamespace(run_id=run_id, status="success", stop_reason=None)

    await dispatch_queued_inputs(inputs, agent_runs=SimpleNamespace(dispatch_input=dispatch_input, wait=wait), thread_id="thread")

    assert dispatched == ["B", "D"]
    state = await inputs.read()
    assert [(x["id"], x["status"], x.get("run_id")) for x in state["items"]] == [
        ("B", "applied", "child-B"),
        ("C", "cancelled", None),
        ("D", "applied", "child-D"),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["conflict", "permission", "uncertain_admission", "wait", "cancelled_wait"])
async def test_queue_dispatch_stops_on_errors_other_than_confirmed_input_cancellation(input_store, failure):
    from deerflow_extension_api.agent_runs import AgentRunError

    from app.gateway.run_inputs import dispatch_queued_inputs

    inputs = RunInputs(input_store, "run", USER_ID, "worker")
    for input_id in ("B", "C", "D"):
        await inputs.submit(input_id, f"Reply {input_id}_DONE", "queue")
    await input_store.update_status("run", "success")
    attempted = []

    async def dispatch_input(*, thread_id, run_id, input_id):
        attempted.append(input_id)
        if failure == "conflict":
            raise InputConflict("Input not found or removed")
        if failure == "permission":
            raise AgentRunError(403, "Permission denied: runs:create")
        await inputs.claim(input_id)
        if failure == "uncertain_admission":
            raise RuntimeError("Admission outcome unknown")
        await inputs.dispatched(input_id, f"child-{input_id}")
        return SimpleNamespace(run_id=f"child-{input_id}", status="running")

    async def wait(**kwargs):
        # Cancellation of another queued input must not mask a wait failure.
        await inputs.cancel("C")
        if failure == "cancelled_wait":
            raise InputCancelled("Cancellation was reported while waiting, not claiming")
        raise RuntimeError("Cannot read child Run status")

    await dispatch_queued_inputs(inputs, agent_runs=SimpleNamespace(dispatch_input=dispatch_input, wait=wait), thread_id="thread")

    assert attempted == ["B"]
    state = await inputs.read()
    assert state["items"][2]["status"] == "pending"
    assert "run_id" not in state["items"][2]
    if failure == "uncertain_admission":
        assert state["items"][0]["status"] == "dispatching"
        assert (await inputs.claim("B", retry=True))["id"] == "B"


@pytest.mark.asyncio
@pytest.mark.parametrize("input_id,error", [("cancelled", InputCancelled), ("missing", InputConflict)])
async def test_dispatch_one_input_preserves_claim_error_without_admitting_run(input_store, monkeypatch, input_id, error):
    from unittest.mock import AsyncMock

    from app.gateway import run_inputs
    from app.gateway.routers import thread_runs

    inputs = RunInputs(input_store, "run", USER_ID, "worker")
    await inputs.submit("cancelled", "Do not execute", "queue")
    await inputs.cancel("cancelled")
    await input_store.update_status("run", "success")
    monkeypatch.setattr(run_inputs, "get_current_user", AsyncMock(return_value=USER_ID))
    monkeypatch.setattr(run_inputs, "_store", lambda _: input_store)
    create_run = AsyncMock()
    monkeypatch.setattr(thread_runs, "create_run", create_run)

    with pytest.raises(error, match="Input not found or removed") as caught:
        await run_inputs.dispatch_one_input("thread", "run", input_id, SimpleNamespace())

    assert type(caught.value) is error
    create_run.assert_not_awaited()
    assert (await inputs.read())["items"][0]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_http_input_admission_and_status_are_owner_scoped(input_store, monkeypatch):
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
        await input_store.update_status("run", "success")
        retry = await client.post(url + "/one/retry")
        assert retry.status_code == 409, retry.text
        assert retry.json()["detail"] == "Input not found or removed"
        user = User(id=uuid4(), email="other@example.com", password_hash="unused")
        assert (await client.post(url, json=body)).status_code == 404
        assert (await client.get("/api/threads/thread/inputs")).json() == {"items": [], "active_run_id": None}
