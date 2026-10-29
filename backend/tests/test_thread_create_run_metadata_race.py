"""The detached run metadata writer participates in thread create admission."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx
import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from sqlalchemy.exc import IntegrityError
from test_gateway_services import _stub_app_config as _base_config
from test_thread_create_idempotency import USER, app_for
from test_thread_create_idempotency import thread_store as _thread_store

from app.gateway import services
from app.gateway.routers import threads
from deerflow.runtime import RunManager, goal
from deerflow.runtime.events.store.memory import MemoryRunEventStore
from deerflow.runtime.runs.store.memory import MemoryRunStore
from deerflow.runtime.user_context import reset_current_user, set_current_user

thread_store = _thread_store
_stub_app_config = _base_config


@pytest.mark.anyio
@pytest.mark.parametrize("first_reader", ["run", "http"])
async def test_detached_run_metadata_and_http_create_share_admission(thread_store, monkeypatch, first_reader):
    thread_id = "cross-entry-create"
    first_missing = asyncio.Event()
    competing_attempt = asyncio.Event()
    release_first = asyncio.Event()
    original_get = thread_store.get
    original_create = thread_store.create
    real_lock = goal.goal_thread_lock
    creates = []
    first_task = None

    async def observed_get(identifier, **kwargs):
        row = await original_get(identifier, **kwargs)
        if identifier == thread_id and row is None:
            if asyncio.current_task() is first_task or (first_reader == "http" and first_task is None):
                first_missing.set()
                await release_first.wait()
            else:
                # Baseline reaches the second missing read; the fixed writer
                # instead reaches the lock observer before waiting for it.
                competing_attempt.set()
        return row

    @asynccontextmanager
    async def observed_lock(identifier):
        if identifier == thread_id and first_missing.is_set():
            competing_attempt.set()
        async with real_lock(identifier):
            yield

    saver = InMemorySaver()

    async def observed_create(identifier, **kwargs):
        row = await original_create(identifier, **kwargs)
        creates.append(row)
        if len(creates) == 1:
            await thread_store.update_status(identifier, "busy")
            await thread_store.update_display_name(identifier, "Existing title")
        return row

    monkeypatch.setattr(thread_store, "get", observed_get)
    monkeypatch.setattr(thread_store, "create", observed_create)
    monkeypatch.setattr(threads, "goal_thread_lock", observed_lock)
    monkeypatch.setattr(services, "goal_thread_lock", observed_lock)
    app = app_for(thread_store, saver)
    record = await RunManager().create(thread_id, metadata={"source": "run"}, kwargs={"input": {"title": "Run title"}})
    tasks = []

    async def ensure_from_run():
        token = set_current_user(USER)
        try:
            # Production run_after_metadata owns this writer as a detached
            # task too. No graph/model execution is simulated by this test.
            return await services._ensure_thread_metadata(SimpleNamespace(thread_store=thread_store), record, owner_user_id=None)
        finally:
            reset_current_user(token)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:

        async def post():
            return await client.post("/api/threads", json={"thread_id": thread_id, "metadata": {"source": "http"}})

        try:
            if first_reader == "run":
                first_task = asyncio.create_task(ensure_from_run())
                tasks.append(first_task)
                await asyncio.wait_for(first_missing.wait(), 5)
                tasks.append(asyncio.create_task(post()))
            else:
                # HTTP executes in the middleware's child task, so leave the
                # first-task marker absent until its first missing read parks.
                tasks.append(asyncio.create_task(post()))
                await asyncio.wait_for(first_missing.wait(), 5)
                first_task = tasks[0]
                tasks.append(asyncio.create_task(ensure_from_run()))
            await asyncio.wait_for(competing_attempt.wait(), 5)
            release_first.set()
            results = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 5)
            # The SQL loser may raise IntegrityError; run_after_metadata logs
            # that existing non-fatal failure. The winning row stays intact.
            assert all(isinstance(value, (dict, httpx.Response, IntegrityError)) for value in results)
            response = next(value for value in results if isinstance(value, httpx.Response))
            assert response.status_code == 200
            row = await original_get(thread_id, user_id=str(USER.id))
            assert len(creates) == 1
            assert response.json()["metadata"] == row["metadata"] == creates[0]["metadata"]
            assert row["status"] == "busy"
            assert row["display_name"] == "Existing title"
        finally:
            release_first.set()
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
    assert not goal._goal_locks._entries_by_loop


@pytest.mark.anyio
async def test_start_run_detached_writer_cannot_replace_http_thread(thread_store, monkeypatch, _stub_app_config):
    """Use native admission/task attachment; only agent execution is stubbed."""
    from app.gateway.routers.thread_runs import RunCreateRequest

    missing = asyncio.Event()
    release = asyncio.Event()
    http_attempted = asyncio.Event()
    writer_locked = False
    writer_task = None
    original_get = thread_store.get
    original_create = thread_store.create
    original_ensure = services._ensure_thread_metadata
    real_lock = goal.goal_thread_lock
    creations = []

    async def tracked_ensure(*args, **kwargs):
        nonlocal writer_task
        writer_task = asyncio.current_task()
        return await original_ensure(*args, **kwargs)

    async def held_get(identifier, **kwargs):
        row = await original_get(identifier, **kwargs)
        if identifier == "native-admission" and row is None and asyncio.current_task() is writer_task:
            missing.set()
            await release.wait()
        return row

    async def counted_create(*args, **kwargs):
        row = await original_create(*args, **kwargs)
        creations.append(row)
        return row

    @asynccontextmanager
    async def service_lock(identifier):
        nonlocal writer_locked
        if asyncio.current_task() is writer_task:
            writer_locked = True
        async with real_lock(identifier):
            yield

    @asynccontextmanager
    async def http_lock(identifier):
        http_attempted.set()
        async with real_lock(identifier):
            yield

    async def no_agent(*args, **kwargs):
        pass

    monkeypatch.setattr(services, "_ensure_thread_metadata", tracked_ensure)
    monkeypatch.setattr(services, "goal_thread_lock", service_lock)
    monkeypatch.setattr(threads, "goal_thread_lock", http_lock)
    monkeypatch.setattr(thread_store, "get", held_get)
    monkeypatch.setattr(thread_store, "create", counted_create)
    monkeypatch.setattr(services, "resolve_agent_factory", lambda _name: object())
    monkeypatch.setattr(services, "run_agent", no_agent)
    app = app_for(thread_store, InMemorySaver())
    app.state.run_manager = RunManager(store=MemoryRunStore())
    app.state.stream_bridge = SimpleNamespace()
    app.state.store = InMemoryStore()
    app.state.run_event_store = MemoryRunEventStore()
    request = SimpleNamespace(headers={}, state=SimpleNamespace(user=USER), app=app)
    record = None
    http_task = None
    token = set_current_user(USER)
    try:
        record = await services.start_run(RunCreateRequest(input={"messages": [{"role": "user", "content": "hello"}]}, metadata={"source": "run"}), "native-admission", request)
        await asyncio.wait_for(missing.wait(), 5)
        assert writer_task is not record.task
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            http_task = asyncio.create_task(client.post("/api/threads", json={"thread_id": "native-admission", "metadata": {"source": "http"}}))
            await asyncio.wait_for(http_attempted.wait(), 5)
            if not writer_locked:
                # Baseline permits this HTTP create to finish while the
                # detached writer still retains its earlier missing read.
                await asyncio.wait_for(asyncio.shield(http_task), 5)
            release.set()
            await asyncio.wait_for(asyncio.shield(record.task), 5)
            response = await asyncio.wait_for(http_task, 5)
            assert response.status_code == 200
            row = await original_get("native-admission", user_id=str(USER.id))
            assert len(creations) == 1
            assert response.json()["metadata"] == row["metadata"]
    finally:
        release.set()
        tasks = [task for task in [http_task, writer_task, record.task if record is not None else None] if task is not None]
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        reset_current_user(token)
    assert not goal._goal_locks._entries_by_loop


@pytest.mark.anyio
async def test_cancelled_metadata_waiter_releases_its_lock_entry(thread_store, monkeypatch):
    attempted = asyncio.Event()
    real_lock = goal.goal_thread_lock

    @asynccontextmanager
    async def observed_lock(identifier):
        attempted.set()
        async with real_lock(identifier):
            yield

    monkeypatch.setattr(services, "goal_thread_lock", observed_lock)
    record = await RunManager().create("cancelled-metadata")
    ctx = SimpleNamespace(thread_store=thread_store)
    task = None
    token = set_current_user(USER)
    try:
        async with real_lock(record.thread_id):
            task = asyncio.create_task(services._ensure_thread_metadata(ctx, record, owner_user_id=None))
            await asyncio.wait_for(attempted.wait(), 5)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert await thread_store.get(record.thread_id) is None
        row = await asyncio.wait_for(services._ensure_thread_metadata(ctx, record, owner_user_id=None), 5)
        assert row["thread_id"] == record.thread_id
    finally:
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        reset_current_user(token)
    assert not goal._goal_locks._entries_by_loop
