"""Explicit retry arbitration through HTTP, real SQL, and the batch worker."""

import asyncio
import json
import os
import uuid
from collections import Counter
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from enum import Enum
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from _router_auth_helpers import make_authed_test_app
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from support.postgres import asyncpg_test_url

from app.gateway.auth_disabled import AUTH_SOURCE_SESSION
from app.gateway.routers import subagent_batches
from deerflow.config.database_config import DatabaseConfig
from deerflow.config.subagent_batches_config import SubagentBatchesConfig
from deerflow.config.subagent_runtime_config import SubagentRuntimeConfig
from deerflow.persistence.engine import close_engine, get_session_factory, init_engine_from_config
from deerflow.persistence.extension_leases.model import ExtensionExecutionLeaseRow
from deerflow.persistence.subagent_batches import SubagentBatchRepository
from deerflow.persistence.subagent_batches.model import SubagentBatchItemRow, SubagentBatchRow
from deerflow.persistence.thread_meta import ThreadMetaRepository
from deerflow.subagents import batch_service
from deerflow.subagents.batch_runtime import BATCH_CONTINUATION_NAMESPACE

_URL = "/api/threads/thread-1/subagent-batches/batch-1"
_REQUEST = ContextVar("retry_request", default="")


class _Status(Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self):
        return self is not _Status.RUNNING


class _RetryBarrier:
    """Park the selected HTTP request at its actual item read or write."""

    def __init__(self, *, after_write=False):
        self.read = asyncio.Event()
        self.release = asyncio.Event()
        self.snapshot = None
        self.after_write = after_write

    def session(self, session):
        barrier = self

        class Session:
            def __getattr__(self, name):
                return getattr(session, name)

            async def __aenter__(self):
                await session.__aenter__()
                return self

            async def __aexit__(self, *args):
                return await session.__aexit__(*args)

            async def get(self, entity, ident, **kwargs):
                row = await session.get(entity, ident, **kwargs)
                if _REQUEST.get() == "stale" and entity is SubagentBatchItemRow and kwargs.get("with_for_update") and not barrier.after_write and not barrier.read.is_set():
                    assert row.status == "failed"
                    barrier.snapshot = (row.id, row.status, row.attempt)
                    barrier.read.set()
                    await asyncio.wait_for(barrier.release.wait(), 10)
                return row

            async def execute(self, statement, *args, **kwargs):
                result = await session.execute(statement, *args, **kwargs)
                if _REQUEST.get() == "stale" and barrier.after_write and not barrier.read.is_set() and getattr(statement, "is_update", False) and statement.table.name == "subagent_batch_items":
                    assert result.rowcount == 1
                    barrier.read.set()
                    await asyncio.wait_for(barrier.release.wait(), 10)
                return result

        return Session()


@pytest_asyncio.fixture(params=["sqlite", "postgres"])
async def env(tmp_path, monkeypatch, request):
    schema = None
    if request.param == "postgres":
        uri = os.environ.get("TEST_POSTGRES_URI")
        if not uri:
            pytest.skip("requires TEST_POSTGRES_URI (isolated retry admission schema)")
        schema = f"batch_retry_{uuid.uuid4().hex}"
        db = DatabaseConfig(backend="postgres", postgres_url=asyncpg_test_url(uri), postgres_schema=schema)
    else:
        db = DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path / "db"))
    user = SimpleNamespace(id="user-1", system_role="user")
    app = make_authed_test_app(user_factory=lambda: user, bind_current_user=True)
    app.include_router(subagent_batches.router)

    @app.middleware("http")
    async def request_context(request, call_next):
        request.state.auth_source = AUTH_SOURCE_SESSION
        token = _REQUEST.set(request.headers.get("x-retry-request", ""))
        try:
            return await call_next(request)
        finally:
            _REQUEST.reset(token)

    state = SimpleNamespace(db=db, app=app, service=None, starts=Counter(), results={}, paths={}, tasks=[])

    class Executor:
        def __init__(self, **kwargs):
            pass

        def execute_async(self, prompt, task_id=None):
            state.starts[task_id] += 1
            # An append per admission makes a duplicate side effect observable.
            path = tmp_path / f"{task_id}.txt"
            with path.open("a", encoding="utf-8") as stream:
                stream.write("fixed-work\n")
            state.paths[task_id] = path
            result = SimpleNamespace(status=_Status.RUNNING, result="fixed report", error=None, stop_reason=None, token_usage_records=[], bash_executions=[])
            execution_id = f"{task_id}:{state.starts[task_id]}"
            state.results[execution_id] = result
            return execution_id

    def cancel(execution_id):
        state.results[execution_id].status = _Status.CANCELLED

    monkeypatch.setattr(batch_service, "SubagentExecutor", Executor)
    monkeypatch.setattr(batch_service, "SubagentStatus", _Status)
    monkeypatch.setattr(batch_service, "get_background_task_result", state.results.get)
    monkeypatch.setattr(batch_service, "cleanup_background_task", lambda _: None)
    monkeypatch.setattr(batch_service, "request_cancel_background_task", cancel)
    monkeypatch.setattr(batch_service, "resolve_subagent_model_name", lambda *args, **kwargs: "fixed-model")
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **kwargs: [])

    async def open_database():
        await init_engine_from_config(db)
        state.sessions = get_session_factory()
        state.repo = SubagentBatchRepository(state.sessions)
        app.state.subagent_batch_repo = state.repo
        app.state.thread_store = ThreadMetaRepository(state.sessions)
        state.service = batch_service.SubagentBatchService(
            repository=state.repo,
            config=SubagentBatchesConfig(lease_seconds=30, poll_interval_seconds=0.1),
            runtime_config=SubagentRuntimeConfig(max_running=3),
            app_config=SimpleNamespace(),
        )
        app.state.subagent_batch_service = state.service
        app.state.subagent_batches_available = True
        if schema:
            async with state.sessions() as session:
                assert await session.scalar(text("SELECT current_schema()")) == schema

    state.open_database = open_database
    try:
        await open_database()
        await app.state.thread_store.create("thread-1", user_id="user-1")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            state.client = client
            yield state
    finally:
        for task in state.tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*state.tasks, return_exceptions=True)
        try:
            if state.service is not None:
                await state.service.stop()
        finally:
            await close_engine()
            if schema:
                engine = create_async_engine(db.app_sqlalchemy_url)
                try:
                    async with engine.begin() as connection:
                        await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
                finally:
                    await engine.dispose()


async def _seed(env, *, count=1, live_sibling=False, continuation=False):
    await env.repo.create_batch(
        batch_id="batch-1",
        user_id="user-1",
        thread_id="thread-1",
        run_id="run-1",
        tool_call_id="call-1",
        submission_key="run-1:call-1",
        title="Retry arbitration",
        subagent_type="general-purpose",
        items=[{"key": f"item-{index}", "prompt": "Fixed work"} for index in range(count)],
        max_live_items=count,
        max_running_items=count,
        max_attempts=1,
        execution_spec={"subagent_config": {"name": "general-purpose", "description": "Fixed worker"}},
        continuation={"prompt": "Summarize"} if continuation else None,
    )
    items = await env.repo.claim_items(now=datetime.now(UTC), lease_owner="initial", lease_seconds=300, limit=count)
    assert len(items) == count
    for item in items[:1] if live_sibling else items:
        assert await _finish(env.repo, item["id"], owner="initial", succeeded=False)
    return items


async def _finish(repo, item_id, *, owner, succeeded=True):
    return await repo.finalize_item(
        item_id,
        lease_owner=owner,
        succeeded=succeeded,
        result="old report" if succeeded else None,
        result_preview="old report" if succeeded else None,
        result_truncated=False,
        error=None if succeeded else "initial failure",
        stop_reason=None,
        token_usage=None,
        model_name="fixed-model",
        completed_at=datetime.now(UTC),
    )


async def _stored(env, item_id):
    async with env.sessions() as session:
        return dict((await session.execute(select(SubagentBatchItemRow.__table__).where(SubagentBatchItemRow.id == item_id))).mappings().one())


async def _retry(env, item_id, **kwargs):
    return await env.client.post(f"{_URL}/items/{item_id}/retry", **kwargs)


async def _running(env, item_id):
    # Only the observation is polled; the race window is controlled by DB events.
    async with asyncio.timeout(10):
        while True:
            row = await _stored(env, item_id)
            if row["status"] == "running":
                return row
            await asyncio.sleep(0)


async def _complete(env, *, succeeded=True):
    for execution_id in env.service._execution_ids.values():
        result = env.results[execution_id]
        result.status = _Status.COMPLETED if succeeded else _Status.FAILED
        result.error = None if succeeded else "new execution failure"
    await asyncio.wait_for(asyncio.gather(*list(env.service._executions.values())), 10)


async def _assert_reopened(env, ids):
    before = [await _stored(env, item_id) for item_id in ids]
    await env.service.stop()
    await close_engine()
    await env.open_database()
    assert [await _stored(env, item_id) for item_id in ids] == before
    exported = await env.client.get(f"{_URL}/results.jsonl")
    assert exported.status_code == 200
    rows = {row["id"]: row for row in map(json.loads, exported.text.splitlines())}
    for row in before:
        assert rows[row["id"]]["status"] == row["status"]
        assert rows[row["id"]]["attempt"] == row["attempt"]
        assert rows[row["id"]]["result"] == row["result"]
    await env.service.run_once(now=datetime.now(UTC))
    assert env.service._executions == {}


def _park_retry(env, monkeypatch, item_id, *, after_write=False):
    gate = _RetryBarrier(after_write=after_write)
    monkeypatch.setattr(env.repo, "_sf", lambda: gate.session(env.sessions()))
    task = asyncio.create_task(_retry(env, item_id, headers={"x-retry-request": "stale"}))
    env.tasks.append(task)
    return gate, task


@pytest.mark.asyncio
@pytest.mark.parametrize("env", ["sqlite"], indirect=True)
@pytest.mark.parametrize("winner_status", ["running", "succeeded", "failed"])
async def test_stale_retry_preserves_new_attempt_and_executes_once(env, monkeypatch, winner_status):
    item = (await _seed(env, continuation=True))[0]
    assert len(await env.repo.claim_continuations(now=datetime.now(UTC), lease_owner="old-followup", lease_seconds=30)) == 1
    gate, stale = _park_retry(env, monkeypatch, item["id"])
    try:
        await asyncio.wait_for(gate.read.wait(), 10)
        assert gate.snapshot == (item["id"], "failed", 1)
        assert (await _retry(env, item["id"])).status_code == 200
        assert not await env.repo.finish_continuation("batch-1", lease_owner="old-followup", status="dispatched", run_id="stale-followup")
        await env.service.run_once(now=datetime.now(UTC))
        await _running(env, item["id"])
        if winner_status in ("succeeded", "failed"):
            await _complete(env, succeeded=winner_status == "succeeded")
            assert len(await env.repo.claim_continuations(now=datetime.now(UTC), lease_owner="new-followup", lease_seconds=30)) == 1
        before = await _stored(env, item["id"])
        batch_before = await env.repo.get_batch("batch-1", user_id="user-1")
        async with env.sessions() as session:
            fence_before = dict((await session.execute(select(ExtensionExecutionLeaseRow.__table__))).mappings().one())
        gate.release.set()
        response = await asyncio.wait_for(stale, 10)
        assert response.status_code == 409, {"before": before, "after": await _stored(env, item["id"]), "starts": dict(env.starts)}
        assert response.json()["detail"] == "Only failed items of a batch that is not cancelled can be retried"
        assert await _stored(env, item["id"]) == before
        assert await env.repo.get_batch("batch-1", user_id="user-1") == batch_before
        async with env.sessions() as session:
            assert dict((await session.execute(select(ExtensionExecutionLeaseRow.__table__))).mappings().one()) == fence_before
        if winner_status == "running":
            renewed = await env.repo.renew_item_lease(item["id"], lease_owner=before["lease_owner"], lease_seconds=30, now=datetime.now(UTC))
            assert renewed == {"valid": True, "cancel_requested": False}
            assert not await _finish(env.repo, item["id"], owner="initial")
            await _complete(env)
        assert (await _stored(env, item["id"]))["status"] == ("failed" if winner_status == "failed" else "succeeded")
        assert not await _finish(env.repo, item["id"], owner="initial")
        await _assert_reopened(env, [item["id"]])
        assert env.starts == {item["id"]: 1}
        assert env.paths[item["id"]].read_text(encoding="utf-8") == "fixed-work\n"
    finally:
        gate.release.set()


@pytest.mark.asyncio
@pytest.mark.parametrize("duplicate_status", ["pending", "leased", "running", "succeeded"])
async def test_sequential_duplicate_keeps_current_attempt(env, duplicate_status):
    item = (await _seed(env))[0]
    assert (await _retry(env, item["id"])).status_code == 200
    if duplicate_status == "leased":
        assert len(await env.repo.claim_items(now=datetime.now(UTC), lease_owner="new-owner", lease_seconds=30, limit=1)) == 1
    elif duplicate_status in ("running", "succeeded"):
        await env.service.run_once(now=datetime.now(UTC))
        await _running(env, item["id"])
        if duplicate_status == "succeeded":
            await _complete(env)
    before = await _stored(env, item["id"])
    assert before["status"] == duplicate_status
    assert (await _retry(env, item["id"])).status_code == 409
    assert await _stored(env, item["id"]) == before
    if duplicate_status == "leased":
        assert await _finish(env.repo, item["id"], owner="new-owner")
    else:
        if duplicate_status == "pending":
            await env.service.run_once(now=datetime.now(UTC))
            await _running(env, item["id"])
        await _complete(env)
        assert env.starts == {item["id"]: 1}
    await _assert_reopened(env, [item["id"]])


@pytest.mark.asyncio
async def test_fresh_retry_after_new_failure_admits_next_execution(env):
    item = (await _seed(env))[0]
    assert (await _retry(env, item["id"])).status_code == 200
    await env.service.run_once(now=datetime.now(UTC))
    await _running(env, item["id"])
    await _complete(env, succeeded=False)
    failed = await _stored(env, item["id"])
    assert failed["status"] == "failed" and failed["attempt"] == 1
    assert failed["error"] == "new execution failure"
    assert (await _retry(env, item["id"])).status_code == 200
    await env.service.run_once(now=datetime.now(UTC))
    await _running(env, item["id"])
    await _complete(env)
    await _assert_reopened(env, [item["id"]])
    assert (await _stored(env, item["id"]))["status"] == "succeeded"
    assert env.starts == {item["id"]: 2}
    assert env.paths[item["id"]].read_text(encoding="utf-8") == "fixed-work\n" * 2


@pytest.mark.asyncio
async def test_concurrent_retries_of_different_items_both_execute_once(env):
    items = await _seed(env, count=2)
    responses = await asyncio.gather(*(_retry(env, item["id"]) for item in items))
    assert [response.status_code for response in responses] == [200, 200]
    await env.service.run_once(now=datetime.now(UTC))
    for item in items:
        await _running(env, item["id"])
    await _complete(env)
    await _assert_reopened(env, [item["id"] for item in items])
    assert env.starts == {item["id"]: 1 for item in items}
    assert all(path.read_text(encoding="utf-8") == "fixed-work\n" for path in env.paths.values())


@pytest.mark.asyncio
@pytest.mark.parametrize("env", ["sqlite"], indirect=True)
async def test_delayed_retry_of_different_item_preserves_running_sibling(env, monkeypatch):
    first, second = await _seed(env, count=2)
    gate, delayed = _park_retry(env, monkeypatch, second["id"])
    try:
        await asyncio.wait_for(gate.read.wait(), 10)
        assert (await _retry(env, first["id"])).status_code == 200
        await env.service.run_once(now=datetime.now(UTC))
        before = await _running(env, first["id"])
        gate.release.set()
        assert (await asyncio.wait_for(delayed, 10)).status_code == 200
        assert await _stored(env, first["id"]) == before
        await env.service.run_once(now=datetime.now(UTC))
        await _running(env, second["id"])
        await _complete(env)
        await _assert_reopened(env, [first["id"], second["id"]])
        assert env.starts == {first["id"]: 1, second["id"]: 1}
        assert all(path.read_text(encoding="utf-8") == "fixed-work\n" for path in env.paths.values())
    finally:
        gate.release.set()


@pytest.mark.asyncio
@pytest.mark.parametrize("env", ["postgres"], indirect=True)
async def test_postgres_retries_serialize_at_parent_before_item(env, monkeypatch):
    item = (await _seed(env))[0]
    gate, first = _park_retry(env, monkeypatch, item["id"])
    parent_read = asyncio.Event()
    original_get = AsyncSession.get
    peer_pid = None
    lock_order = []

    async def get(session, entity, ident, **kwargs):
        nonlocal peer_pid
        if _REQUEST.get() == "peer" and kwargs.get("with_for_update"):
            lock_order.append(entity)
            if entity is SubagentBatchRow:
                peer_pid = await session.scalar(text("SELECT pg_backend_pid()"))
                parent_read.set()
        return await original_get(session, entity, ident, **kwargs)

    monkeypatch.setattr(AsyncSession, "get", get)
    try:
        await asyncio.wait_for(gate.read.wait(), 10)
        peer = asyncio.create_task(_retry(env, item["id"], headers={"x-retry-request": "peer"}))
        env.tasks.append(peer)
        await asyncio.wait_for(parent_read.wait(), 10)
        async with asyncio.timeout(10):
            while True:
                async with env.sessions() as session:
                    waiting = await session.scalar(text("SELECT count(*) FROM pg_stat_activity WHERE pid=:pid AND wait_event_type='Lock'"), {"pid": peer_pid})
                if waiting:
                    break
                await asyncio.sleep(0.01)
        assert lock_order == [SubagentBatchRow]
        gate.release.set()
        responses = await asyncio.wait_for(asyncio.gather(first, peer), 10)
        assert [response.status_code for response in responses] == [200, 409]
        assert lock_order == [SubagentBatchRow, SubagentBatchItemRow]
        await env.service.run_once(now=datetime.now(UTC))
        await _running(env, item["id"])
        await _complete(env)
        await _assert_reopened(env, [item["id"]])
        assert env.starts == {item["id"]: 1}
        assert env.paths[item["id"]].read_text(encoding="utf-8") == "fixed-work\n"
    finally:
        gate.release.set()


@pytest.mark.asyncio
async def test_paused_retry_waits_for_resume(env):
    items = await _seed(env, count=2, live_sibling=True)
    assert (await env.client.post(f"{_URL}/pause")).json()["status"] == "paused"
    assert (await _retry(env, items[0]["id"])).status_code == 200
    await env.service.run_once(now=datetime.now(UTC))
    assert env.starts == {}
    assert (await env.client.get(_URL)).json()["status"] == "paused"
    assert (await env.client.post(f"{_URL}/resume")).status_code == 200
    await env.service.run_once(now=datetime.now(UTC))
    await _running(env, items[0]["id"])
    await _complete(env)
    assert await _finish(env.repo, items[1]["id"], owner="initial")
    await _assert_reopened(env, [item["id"] for item in items])
    assert env.starts == {items[0]["id"]: 1}


@pytest.mark.asyncio
async def test_cancelled_parent_rejects_retry(env):
    items = await _seed(env, count=2, live_sibling=True)
    assert (await env.client.post(f"{_URL}/cancel")).json()["status"] == "cancelled"
    before = await _stored(env, items[0]["id"])
    assert (await _retry(env, items[0]["id"])).status_code == 409
    assert await _stored(env, items[0]["id"]) == before
    await _assert_reopened(env, [item["id"] for item in items])
    assert env.starts == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("env", ["sqlite"], indirect=True)
async def test_cancel_committed_during_retry_rolls_back_item_reset(env, monkeypatch):
    items = await _seed(env, count=2, live_sibling=True)
    before = await _stored(env, items[0]["id"])
    gate, stale = _park_retry(env, monkeypatch, items[0]["id"])
    try:
        await asyncio.wait_for(gate.read.wait(), 10)
        assert (await env.client.post(f"{_URL}/cancel")).json()["status"] == "cancelled"
        gate.release.set()
        assert (await asyncio.wait_for(stale, 10)).status_code == 409
        assert await _stored(env, items[0]["id"]) == before
        assert (await env.client.get(_URL)).json()["status"] == "cancelled"
        await _assert_reopened(env, [item["id"] for item in items])
        assert env.starts == {}
    finally:
        gate.release.set()


@pytest.mark.asyncio
@pytest.mark.parametrize("env", ["sqlite"], indirect=True)
@pytest.mark.parametrize("after_write", [False, True], ids=["after-read", "after-write"])
async def test_cancelled_retry_request_releases_transaction(env, monkeypatch, after_write):
    item = (await _seed(env))[0]
    before = await _stored(env, item["id"])
    gate, stale = _park_retry(env, monkeypatch, item["id"], after_write=after_write)
    try:
        await asyncio.wait_for(gate.read.wait(), 10)
        stale.cancel()
        with pytest.raises(asyncio.CancelledError):
            await stale
        assert await _stored(env, item["id"]) == before
        assert (await _retry(env, item["id"])).status_code == 200
        await env.service.run_once(now=datetime.now(UTC))
        await _running(env, item["id"])
        await _complete(env)
        await _assert_reopened(env, [item["id"]])
        assert env.starts == {item["id"]: 1}
    finally:
        gate.release.set()


@pytest.mark.asyncio
async def test_retry_resets_only_unadmitted_continuation(env):
    item = (await _seed(env, continuation=True))[0]
    assert len(await env.repo.claim_continuations(now=datetime.now(UTC), lease_owner="old", lease_seconds=30)) == 1
    assert (await _retry(env, item["id"])).status_code == 200
    assert not await env.repo.finish_continuation("batch-1", lease_owner="old", status="dispatched", run_id="old-run")
    async with env.sessions() as session:
        fence = await session.get(ExtensionExecutionLeaseRow, (BATCH_CONTINUATION_NAMESPACE, "batch-1"))
        assert fence.expires_at == 0 and fence.epoch == 2
    assert await env.repo.claim_continuations(now=datetime.now(UTC) + timedelta(seconds=31), lease_owner="new", lease_seconds=30) == []
    await env.service.run_once(now=datetime.now(UTC))
    await _running(env, item["id"])
    await _complete(env)
    assert len(await env.repo.claim_continuations(now=datetime.now(UTC), lease_owner="new", lease_seconds=30)) == 1
    assert await env.repo.finish_continuation("batch-1", lease_owner="new", status="dispatched", run_id="new-run")
    await _assert_reopened(env, [item["id"]])
    assert (await env.client.get(_URL)).json()["continuation_run_id"] == "new-run"
