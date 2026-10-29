"""``GET /api/thread-activity``: the per-user activity feed over the run-change clock.

Drives the real router against real SQLite repositories (``RunRepository``
for the clock, ``ThreadReadRepository`` for the read clock), with runs written
through ``RunRepository.put`` so ``origin_kind`` is derived as in production.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from uuid import UUID

import httpx
import pytest
from _router_auth_helpers import make_authed_test_app
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.gateway.auth.models import User
from app.gateway.deps import get_config
from app.gateway.routers import features, thread_activity, threads
from deerflow.persistence.base import Base
from deerflow.persistence.run import RunRepository
from deerflow.persistence.run.model import RunChangeClockRow, RunRow
from deerflow.persistence.thread_reads import ThreadReadMarkerRow, ThreadReadRepository, ThreadReadVersionRow
from deerflow.runtime.run_origin import DEERFLOW_ORIGIN_KEY, make_origin
from deerflow.runtime.runs.store.memory import MemoryRunStore

_ALICE = User(id=UUID("2a8c4f53-6a0b-4a51-9f5e-0c1d2e3f4a51"), email="alice@example.com", password_hash="unused", system_role="user")
_BOB = User(id=UUID("7d1e2f30-4b5c-4d6e-8f70-81a2b3c4d5e6"), email="bob@example.com", password_hash="unused", system_role="user")
ALICE = str(_ALICE.id)
BOB = str(_BOB.id)


@asynccontextmanager
async def repositories(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'activity.db'}")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(lambda sync: Base.metadata.create_all(sync, tables=[m.__table__ for m in (RunRow, RunChangeClockRow, ThreadReadMarkerRow, ThreadReadVersionRow)]))
        sf = async_sessionmaker(engine, expire_on_commit=False)
        yield RunRepository(sf), ThreadReadRepository(sf)
    finally:
        await engine.dispose()


@asynccontextmanager
async def client_for(run_store, read_repo, *, user=_ALICE):
    app = make_authed_test_app(user_factory=lambda: user, bind_current_user=True)
    app.state.run_store = run_store
    app.state.thread_read_repo = read_repo
    app.include_router(thread_activity.router)
    app.include_router(threads.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://activity.test") as client:
        yield client


async def put_run(runs, run_id, thread_id, *, user_id=ALICE, origin=None, status="success"):
    metadata = {DEERFLOW_ORIGIN_KEY: make_origin(origin)} if origin else {}
    await runs.put(run_id, thread_id=thread_id, user_id=user_id, status=status, metadata=metadata)


async def poll(client, cursor=None, **params):
    if cursor is not None:
        params["cursor"] = cursor
    response = await client.get("/api/thread-activity", params=params)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio
async def test_first_poll_only_seeds_at_the_callers_head(tmp_path):
    async with repositories(tmp_path) as (runs, reads), client_for(runs, reads) as client:
        await put_run(runs, "run-1", "sched", origin="schedule")
        seeded = await poll(client)
        assert seeded["threads"] == []
        assert seeded["truncated"] is False
        assert seeded["read_version"] == 0
        latest = await runs.latest_change(user_id=ALICE)
        assert seeded["cursor"] == f"{latest[0]}:{latest[1]}"
        # Nothing changed since the seed.
        again = await poll(client, seeded["cursor"])
        assert again["threads"] == [] and again["cursor"] == seeded["cursor"]


@pytest.mark.asyncio
async def test_user_without_runs_seeds_at_zero_and_sees_the_first_scheduled_run(tmp_path):
    async with repositories(tmp_path) as (runs, reads), client_for(runs, reads) as client:
        seeded = await poll(client)
        assert seeded["cursor"] == "0:"
        await put_run(runs, "run-1", "sched", origin="schedule", status="running")
        page = await poll(client, seeded["cursor"])
        assert page["threads"] == [{"thread_id": "sched", "origin_kind": "schedule", "status": "running"}]


@pytest.mark.asyncio
async def test_cursor_advances_to_the_last_returned_row_without_skips_or_repeats(tmp_path):
    async with repositories(tmp_path) as (runs, reads), client_for(runs, reads) as client:
        cursor = (await poll(client))["cursor"]
        for index in range(5):
            await put_run(runs, f"run-{index}", f"thread-{index}", origin="schedule")
        seen: list[str] = []
        truncated_flags = []
        for _ in range(3):
            page = await poll(client, cursor, limit=2)
            seen.extend(item["thread_id"] for item in page["threads"])
            truncated_flags.append(page["truncated"])
            if page["threads"]:
                last = await runs.get(f"run-{page['threads'][-1]['thread_id'].split('-')[1]}", user_id=None)
                assert page["cursor"] == f"{last['change_seq']}:{last['run_id']}"
            cursor = page["cursor"]
        assert seen == [f"thread-{index}" for index in range(5)]
        assert truncated_flags == [True, True, False]
        assert (await poll(client, cursor))["threads"] == []


@pytest.mark.asyncio
async def test_interactive_changes_advance_the_cursor_but_are_not_returned(tmp_path):
    async with repositories(tmp_path) as (runs, reads), client_for(runs, reads) as client:
        cursor = (await poll(client))["cursor"]
        await put_run(runs, "chat-1", "chat", status="pending")
        await put_run(runs, "chat-1", "chat", status="running")
        await put_run(runs, "chat-1", "chat", status="success")
        page = await poll(client, cursor)
        assert page["threads"] == []
        assert page["cursor"] != cursor
        latest = await runs.latest_change(user_id=ALICE)
        assert page["cursor"] == f"{latest[0]}:{latest[1]}"


@pytest.mark.asyncio
async def test_new_server_runs_are_listed_once_per_thread_with_latest_status(tmp_path):
    async with repositories(tmp_path) as (runs, reads), client_for(runs, reads) as client:
        cursor = (await poll(client))["cursor"]
        await put_run(runs, "run-s", "sched", origin="schedule", status="running")
        await put_run(runs, "run-im", "im", origin="im_channel", status="running")
        await put_run(runs, "run-s", "sched", origin="schedule", status="success")
        page = await poll(client, cursor)
        assert page["threads"] == [
            {"thread_id": "im", "origin_kind": "im_channel", "status": "running"},
            {"thread_id": "sched", "origin_kind": "schedule", "status": "success"},
        ]


@pytest.mark.asyncio
async def test_other_users_runs_never_appear_even_with_their_cursor(tmp_path):
    async with repositories(tmp_path) as (runs, reads):
        async with client_for(runs, reads, user=_BOB) as bob:
            bob_cursor = (await poll(bob))["cursor"]
        await put_run(runs, "run-bob", "bob-thread", user_id=BOB, origin="schedule")
        # Bob's run in a thread shared with Alice.
        await put_run(runs, "run-bob-shared", "shared", user_id=BOB, origin="im_channel")
        async with client_for(runs, reads) as alice:
            assert (await poll(alice, bob_cursor))["threads"] == []
            assert (await poll(alice, "0:"))["threads"] == []
            assert (await poll(alice))["cursor"] == "0:"


@pytest.mark.asyncio
@pytest.mark.parametrize("cursor", ["", "abc", "12", "-1:run", "1:run:x", "01:run", "1: run", "9" * 20 + ":r", f"{2**63}:r", "1:" + "r" * 65, "1:" + "r" * 200])
async def test_malformed_cursor_is_rejected(tmp_path, cursor):
    async with repositories(tmp_path) as (runs, reads), client_for(runs, reads) as client:
        response = await client.get("/api/thread-activity", params={"cursor": cursor})
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "invalid_cursor"


@pytest.mark.asyncio
async def test_largest_change_seq_is_a_valid_cursor(tmp_path):
    async with repositories(tmp_path) as (runs, reads), client_for(runs, reads) as client:
        cursor = f"{2**63 - 1}:r"
        page = await poll(client, cursor)
        assert page["threads"] == [] and page["cursor"] == cursor


@pytest.mark.asyncio
async def test_read_version_moves_only_when_a_read_clears_something(tmp_path):
    async with repositories(tmp_path) as (runs, reads), client_for(runs, reads) as client:
        await put_run(runs, "run-1", "sched", origin="schedule")
        cursor = (await poll(client))["cursor"]

        cleared = await client.post("/api/threads/sched/read")
        assert cleared.status_code == 200, cleared.text
        assert cleared.json() == {"unread": False, "read_version": 1}
        page = await poll(client, cursor)
        assert page["read_version"] == 1
        assert page["threads"] == []

        again = await client.post("/api/threads/sched/read")
        assert again.json() == {"unread": False, "read_version": 1}
        assert (await poll(client, page["cursor"]))["read_version"] == 1


@pytest.mark.asyncio
async def test_memory_backend_reports_unavailable(tmp_path):
    app = make_authed_test_app(bind_current_user=True)
    app.state.run_store = MemoryRunStore()
    app.state.thread_read_repo = None
    app.include_router(thread_activity.router)
    app.include_router(threads.router)
    app.include_router(features.router)
    app.dependency_overrides[get_config] = lambda: _feature_config()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://activity.test") as client:
        assert (await client.get("/api/thread-activity")).status_code == 503
        assert (await client.post("/api/threads/some-thread/read")).status_code == 503
        response = await client.get("/api/features")
        assert response.status_code == 200
        assert response.json()["thread_activity"] == {"available": False}


def _feature_config():
    from types import SimpleNamespace

    config = SimpleNamespace(
        agents_api=SimpleNamespace(enabled=False),
        tools=[],
        subagent_runtime=SimpleNamespace(max_running=3),
        knowledge_base=SimpleNamespace(enabled=False, scope_selection_enabled=False),
        scheduler=SimpleNamespace(enabled=False, tool_enabled=False, min_once_delay_seconds=60),
    )
    config.get_tool_config = lambda _name: None
    return config
