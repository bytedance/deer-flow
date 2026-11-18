"""Concurrent HTTP creates preserve the first admitted thread and checkpoint."""

import asyncio
from contextlib import asynccontextmanager
from uuid import UUID

import httpx
import pytest
from _router_auth_helpers import make_authed_test_app
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore

from app.gateway.auth.models import User
from app.gateway.routers import threads
from deerflow.persistence.thread_meta import ThreadMetaRepository
from deerflow.persistence.thread_meta.memory import MemoryThreadMetaStore
from deerflow.runtime import goal

USER = User(id=UUID("00000000-0000-0000-0000-000000000001"), email="create@example.com", password_hash="x", system_role="admin")


@pytest.fixture(params=["memory", "sqlite"])
async def thread_store(request, tmp_path):
    if request.param == "memory":
        yield MemoryThreadMetaStore(InMemoryStore())
        return
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine

    try:
        await init_engine("sqlite", url=f"sqlite+aiosqlite:///{tmp_path / 'threads.db'}", sqlite_dir=str(tmp_path))
        yield ThreadMetaRepository(get_session_factory())
    finally:
        await close_engine()


def app_for(store, checkpointer):
    # Identity is a test double; authorization, owner filtering, the router,
    # metadata store and checkpoint storage retain their production paths.
    app = make_authed_test_app(user_factory=lambda: USER, bind_current_user=True)
    app.state.thread_store = store
    app.state.checkpointer = checkpointer
    app.include_router(threads.router)
    return app


@pytest.mark.anyio
@pytest.mark.parametrize("assertion", ["metadata", "status", "checkpoint"])
async def test_racing_creates_preserve_first_thread(thread_store, monkeypatch, assertion):
    first_read = asyncio.Event()
    second_attempt = asyncio.Event()
    release = asyncio.Event()
    original_get = thread_store.get
    original_create = thread_store.create
    real_lock = threads.goal_thread_lock
    missing_reads = 0
    lock_attempts = 0
    creates = 0

    async def observed_get(thread_id, **kwargs):
        nonlocal missing_reads
        row = await original_get(thread_id, **kwargs)
        if thread_id == "same-thread" and row is None:
            missing_reads += 1
            if missing_reads == 1:
                first_read.set()
                await release.wait()
            else:
                # Baseline: both requests have observed no existing row.
                second_attempt.set()
        return row

    @asynccontextmanager
    async def observed_lock(thread_id):
        nonlocal lock_attempts
        if thread_id == "same-thread":
            lock_attempts += 1
            if lock_attempts == 2:
                # Fixed path: observe the second lock attempt before it waits.
                second_attempt.set()
        async with real_lock(thread_id):
            yield

    async def observed_create(thread_id, **kwargs):
        nonlocal creates
        row = await original_create(thread_id, **kwargs)
        creates += 1
        if creates == 1:
            await thread_store.update_status(thread_id, "busy")
            await thread_store.update_display_name(thread_id, "Existing conversation")
        return row

    class ProgressSaver(InMemorySaver):
        seed_writes = 0

        async def aput(self, config, checkpoint, metadata, versions):
            self.seed_writes += 1
            result = await super().aput(config, checkpoint, metadata, versions)
            if self.seed_writes == 1:
                # Interleave a real persisted checkpoint between the initial
                # seed and the late create. Model/worker execution is not claimed.
                progress = empty_checkpoint()
                progress["channel_values"] = {"messages": [HumanMessage(content="Keep this history")]}
                progress["channel_versions"] = {"messages": 1}
                await super().aput(result, progress, {"source": "update", "step": 0, "writes": {}}, {"messages": 1})
            return result

    saver = ProgressSaver()
    monkeypatch.setattr(thread_store, "get", observed_get)
    monkeypatch.setattr(thread_store, "create", observed_create)
    monkeypatch.setattr(threads, "goal_thread_lock", observed_lock)
    app = app_for(thread_store, saver)
    tasks = []
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        try:
            tasks.append(asyncio.create_task(client.post("/api/threads", json={"thread_id": "same-thread", "metadata": {"request": "first"}})))
            await asyncio.wait_for(first_read.wait(), 5)
            tasks.append(asyncio.create_task(client.post("/api/threads", json={"thread_id": "same-thread", "metadata": {"request": "second"}})))
            await asyncio.wait_for(second_attempt.wait(), 5)
            release.set()
            responses = await asyncio.wait_for(asyncio.gather(*tasks), 5)
            assert [response.status_code for response in responses] == [200, 200]
            row = await original_get("same-thread", user_id=str(USER.id))
            checkpoint = await saver.aget_tuple({"configurable": {"thread_id": "same-thread", "checkpoint_ns": ""}})
            if assertion == "metadata":
                assert responses[0].json()["metadata"] == responses[1].json()["metadata"] == row["metadata"]
            elif assertion == "status":
                assert row["status"] == "busy"
                assert row["display_name"] == "Existing conversation"
            else:
                assert checkpoint.checkpoint["channel_values"]["messages"][0].content == "Keep this history"
                assert saver.seed_writes == 1
        finally:
            release.set()
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
    assert not goal._goal_locks._entries_by_loop


@pytest.mark.anyio
async def test_cancelled_waiter_keeps_other_threads_available(thread_store, monkeypatch):
    attempted = asyncio.Event()
    real_lock = threads.goal_thread_lock

    @asynccontextmanager
    async def observed_lock(thread_id):
        if thread_id == "held-thread":
            attempted.set()
        async with real_lock(thread_id):
            yield

    monkeypatch.setattr(threads, "goal_thread_lock", observed_lock)
    saver = InMemorySaver()
    app = app_for(thread_store, saver)
    task = None
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        try:
            async with real_lock("held-thread"):
                task = asyncio.create_task(client.post("/api/threads", json={"thread_id": "held-thread"}))
                await asyncio.wait_for(attempted.wait(), 5)
                # A wait on this id must not stop another conversation.
                other = await asyncio.wait_for(client.post("/api/threads", json={"thread_id": "other-thread"}), 5)
                assert other.status_code == 200
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
                assert await thread_store.get("held-thread", user_id=str(USER.id)) is None
            retry = await asyncio.wait_for(client.post("/api/threads", json={"thread_id": "held-thread"}), 5)
            assert retry.status_code == 200
        finally:
            if task is not None:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    assert not goal._goal_locks._entries_by_loop


@pytest.mark.anyio
async def test_cancelled_holder_allows_create_retry(thread_store, monkeypatch):
    entered = asyncio.Event()
    release = asyncio.Event()
    original_get = thread_store.get
    first = True

    async def held_get(thread_id, **kwargs):
        nonlocal first
        row = await original_get(thread_id, **kwargs)
        if thread_id == "cancelled-create" and row is None and first:
            first = False
            entered.set()
            await release.wait()
        return row

    monkeypatch.setattr(thread_store, "get", held_get)
    saver = InMemorySaver()
    app = app_for(thread_store, saver)
    task = None
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        try:
            task = asyncio.create_task(client.post("/api/threads", json={"thread_id": "cancelled-create"}))
            await asyncio.wait_for(entered.wait(), 5)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert await original_get("cancelled-create", user_id=str(USER.id)) is None
            release.set()
            retry = await asyncio.wait_for(client.post("/api/threads", json={"thread_id": "cancelled-create", "metadata": {"retry": True}}), 5)
            assert retry.status_code == 200
            assert retry.json()["metadata"] == {"retry": True}
            assert await saver.aget_tuple({"configurable": {"thread_id": "cancelled-create", "checkpoint_ns": ""}}) is not None
        finally:
            release.set()
            if task is not None:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    assert not goal._goal_locks._entries_by_loop


@pytest.mark.anyio
async def test_checkpoint_failure_releases_creation_lock(thread_store, monkeypatch):
    saver = InMemorySaver()
    original_put = saver.aput

    async def failed_put(*args, **kwargs):
        raise RuntimeError("injected checkpoint failure")

    monkeypatch.setattr(saver, "aput", failed_put)
    app = app_for(thread_store, saver)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        failed = await client.post("/api/threads", json={"thread_id": "failed-seed", "metadata": {"keep": True}})
        assert failed.status_code == 500
        assert not goal._goal_locks._entries_by_loop
        monkeypatch.setattr(saver, "aput", original_put)
        # Preserve existing retry semantics for a metadata row whose initial
        # seed failed; this fix does not add transactional seed recovery.
        retry = await asyncio.wait_for(client.post("/api/threads", json={"thread_id": "failed-seed"}), 5)
        assert retry.status_code == 200
        assert retry.json()["metadata"] == {"keep": True}
    assert not goal._goal_locks._entries_by_loop
