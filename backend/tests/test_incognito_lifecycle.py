"""Incognito lifetime: deadline renewal, explicit end, tombstones and the sweep.

The visibility contract lives in ``test_incognito_threads_router.py``; these
tests cover the clock: an active thread keeps moving its deadline, an ended
one does not grow back, and an expired one becomes an unreadable tombstone
whose data the sweep purges without ever deleting the row.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from langgraph.store.memory import InMemoryStore
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from deerflow.persistence.thread_meta.base import (
    THREAD_INCOGNITO_ENDED_METADATA_KEY,
    THREAD_INCOGNITO_EXPIRED_STATUS,
    is_incognito_expired,
)
from deerflow.persistence.thread_meta.memory import MemoryThreadMetaStore
from deerflow.persistence.thread_meta.model import ThreadMetaRow
from deerflow.persistence.thread_meta.sql import ThreadMetaRepository


@pytest.fixture(params=["memory", "sqlite"])
async def store(request, tmp_path):
    if request.param == "memory":
        yield MemoryThreadMetaStore(InMemoryStore())
        return
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'incognito.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(ThreadMetaRow.metadata.create_all)
    yield ThreadMetaRepository(async_sessionmaker(engine, expire_on_commit=False))
    await engine.dispose()


async def _incognito(store, *, thread_id="secret", user_id="alice", expires_in=3600.0):
    return await store.create(
        thread_id,
        user_id=user_id,
        display_name="private notes",
        metadata={"deerflow_pinned": True},
        incognito=True,
        expires_at=datetime.now(UTC) + timedelta(seconds=expires_in),
    )


@pytest.mark.anyio
async def test_renewal_moves_the_idle_deadline_but_never_past_the_creation_ceiling(store):
    await _incognito(store)

    assert await store.renew_incognito("secret", idle_ttl=timedelta(hours=2), max_lifetime=timedelta(days=30), user_id="alice")
    renewed = await store.get("secret", user_id="alice")
    deadline = datetime.fromisoformat(renewed["expires_at"])
    assert timedelta(hours=1, minutes=55) < deadline - datetime.now(UTC) <= timedelta(hours=2)

    # The absolute ceiling wins even when it shortens the window.
    assert await store.renew_incognito("secret", idle_ttl=timedelta(days=2), max_lifetime=timedelta(minutes=30), user_id="alice")
    capped = await store.get("secret", user_id="alice")
    assert datetime.fromisoformat(capped["expires_at"]) - datetime.now(UTC) <= timedelta(minutes=31)


@pytest.mark.anyio
async def test_renewal_skips_ordinary_ended_and_tombstoned_threads(store):
    await store.create("plain", user_id="alice")
    assert not await store.renew_incognito("plain", idle_ttl=timedelta(hours=1), max_lifetime=timedelta(days=7), user_id="alice")

    await _incognito(store)
    assert await store.end_incognito("secret", grace=timedelta(minutes=5), user_id="alice")
    ended = await store.get("secret", user_id="alice")
    assert ended["metadata"][THREAD_INCOGNITO_ENDED_METADATA_KEY] is True
    # An end must not be undone by activity finishing inside the grace window.
    assert not await store.renew_incognito("secret", idle_ttl=timedelta(hours=24), max_lifetime=timedelta(days=7), user_id="alice")
    assert (await store.get("secret", user_id="alice"))["expires_at"] == ended["expires_at"]

    await store.begin_incognito_expiry("secret")
    assert not await store.renew_incognito("secret", idle_ttl=timedelta(hours=1), max_lifetime=timedelta(days=7), user_id="alice")


@pytest.mark.anyio
async def test_owner_end_requires_the_incognito_owner(store):
    await _incognito(store)

    assert not await store.end_incognito("secret", grace=timedelta(minutes=5), user_id="bob")
    assert not await store.end_incognito("missing", grace=timedelta(minutes=5), user_id="alice")


@pytest.mark.anyio
async def test_tombstone_clears_content_and_makes_the_thread_unreadable(store):
    await _incognito(store)

    assert await store.begin_incognito_expiry("secret")
    tombstone = await store.get("secret", user_id="alice")
    assert tombstone is not None
    assert tombstone["status"] == THREAD_INCOGNITO_EXPIRED_STATUS
    assert tombstone["display_name"] is None
    assert tombstone["metadata"] == {}
    assert tombstone["incognito"] is True
    assert is_incognito_expired(tombstone)
    assert not await store.check_access("secret", "alice", require_existing=True)
    # The row still owns the id, which is what stops resurrection.
    assert await store.get("secret", user_id="alice") is not None

    await store.finish_incognito_expiry("secret")
    assert (await store.get("secret", user_id="alice"))["expires_at"] is None
    assert is_incognito_expired(await store.get("secret", user_id="alice"))


@pytest.mark.anyio
async def test_due_list_holds_only_incognito_deadlines(store):
    await _incognito(store, thread_id="due", expires_in=-60)
    await _incognito(store, thread_id="later", expires_in=3600)
    await store.create("plain", user_id="alice", expires_at=datetime.now(UTC) - timedelta(hours=1))
    await _incognito(store, thread_id="purged", expires_in=-60)
    await store.begin_incognito_expiry("purged")
    await store.finish_incognito_expiry("purged")

    due = await store.list_due_incognito(limit=10)
    assert [row["thread_id"] for row in due] == ["due"]
    assert due[0]["user_id"] == "alice"


@pytest.mark.anyio
async def test_expired_deadline_hides_the_thread_before_the_sweep_runs(store):
    await _incognito(store, expires_in=-1)

    assert not await store.check_access("secret", "alice")
    assert is_incognito_expired(await store.get("secret", user_id="alice"))


@pytest.mark.anyio
async def test_sweep_tombstones_purges_and_keeps_the_row(tmp_path):
    from app.gateway import incognito as incognito_module
    from app.gateway.routers import threads as thread_routes

    store = MemoryThreadMetaStore(InMemoryStore())
    await _incognito(store, expires_in=-60)
    await _incognito(store, thread_id="later", expires_in=3600)

    reserved: list[tuple[str, dict]] = []

    class _RunManager:
        @asynccontextmanager
        async def reserve_thread_operation(self, thread_id, **kwargs):
            reserved.append((thread_id, kwargs))
            yield

        async def discard_thread_runs(self, thread_id):
            return None

    app = SimpleNamespace(
        state=SimpleNamespace(
            thread_store=store,
            run_manager=_RunManager(),
            checkpointer=None,
            run_store=None,
            run_event_store=None,
        )
    )

    with (
        patch.object(thread_routes, "_delete_thread_data", lambda *args, **kwargs: thread_routes.ThreadDeleteResponse(success=True, message="ok")),
        patch("deerflow.community.browser_automation.get_browser_session_manager", return_value=SimpleNamespace(close_session=_noop)),
        patch("deerflow.mcp.session_pool.get_session_pool", return_value=SimpleNamespace(close_thread_scope=_noop)),
    ):
        purged = await incognito_module.sweep_expired_incognito_threads(app, batch_size=10)

    assert purged == 1
    assert [thread_id for thread_id, _ in reserved] == ["secret"]
    tombstone = await store.get("secret", user_id="alice")
    assert tombstone["status"] == THREAD_INCOGNITO_EXPIRED_STATUS
    assert tombstone["display_name"] is None
    assert tombstone["expires_at"] is None
    assert (await store.get("later", user_id="alice"))["status"] == "idle"


@pytest.mark.anyio
async def test_sweep_defers_a_thread_whose_run_is_in_flight():
    from app.gateway import incognito as incognito_module

    store = MemoryThreadMetaStore(InMemoryStore())
    await _incognito(store, expires_in=-60)

    class _BusyRunManager:
        @asynccontextmanager
        async def reserve_thread_operation(self, thread_id, **kwargs):
            from deerflow.runtime.runs.manager import ConflictError

            raise ConflictError()
            yield  # pragma: no cover

    app = SimpleNamespace(state=SimpleNamespace(thread_store=store, run_manager=_BusyRunManager(), checkpointer=None))

    assert await incognito_module.sweep_expired_incognito_threads(app, batch_size=10) == 0
    record = await store.get("secret", user_id="alice")
    assert record["status"] == "idle"
    assert record["display_name"] == "private notes"


async def _noop(*args, **kwargs):
    return None


def test_run_admission_pins_incognito_and_renews_the_deadline():
    import asyncio

    from app.gateway.deps import _run_admission_hook
    from deerflow.config.incognito_config import IncognitoThreadsConfig
    from deerflow.runtime.context_keys import INCOGNITO_CONTEXT_KEY

    async def scenario():
        store = MemoryThreadMetaStore(InMemoryStore())
        await _incognito(store, expires_in=60)
        await store.create("plain", user_id="alice")
        hook = _run_admission_hook(
            checkpointer=object(),
            thread_store=store,
            app_config=SimpleNamespace(incognito=IncognitoThreadsConfig(idle_ttl_seconds=3600, max_lifetime_seconds=7 * 24 * 3600)),
        )
        secret_config: dict = {}
        plain_config: dict = {}
        await hook(SimpleNamespace(run_id="r1", thread_id="secret"), secret_config)
        await hook(SimpleNamespace(run_id="r2", thread_id="plain"), plain_config)
        assert secret_config["context"][INCOGNITO_CONTEXT_KEY] is True
        assert INCOGNITO_CONTEXT_KEY not in plain_config.get("context", {})
        assert datetime.fromisoformat((await store.get("secret", user_id="alice"))["expires_at"]) - datetime.now(UTC) > timedelta(minutes=50)

    asyncio.run(scenario())


def test_run_completion_renews_an_incognito_thread_only():
    import asyncio

    from app.gateway.deps import _run_completion_hook
    from deerflow.config.incognito_config import IncognitoThreadsConfig

    async def scenario():
        store = MemoryThreadMetaStore(InMemoryStore())
        await _incognito(store, expires_in=60)
        await store.create("plain", user_id="alice")
        hook = _run_completion_hook(
            scheduled_task_service=None,
            thread_store=store,
            app_config=SimpleNamespace(incognito=IncognitoThreadsConfig(idle_ttl_seconds=3600, max_lifetime_seconds=7 * 24 * 3600)),
        )
        await hook(SimpleNamespace(run_id="r1", thread_id="secret", user_id="alice"))
        await hook(SimpleNamespace(run_id="r2", thread_id="plain", user_id="alice"))
        renewed = await store.get("secret", user_id="alice")
        assert datetime.fromisoformat(renewed["expires_at"]) - datetime.now(UTC) > timedelta(minutes=50)
        assert (await store.get("plain", user_id="alice"))["expires_at"] is None

    asyncio.run(scenario())
