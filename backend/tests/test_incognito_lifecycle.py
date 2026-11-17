"""Incognito lifetime: deadline renewal, explicit end, tombstones and the sweep.

The visibility contract lives in ``test_incognito_threads_router.py``; these
tests cover the clock: an active thread keeps moving its deadline, an ended
one does not grow back, and an expired one becomes an unreadable tombstone
whose data the sweep purges without ever deleting the row.
"""

from __future__ import annotations

from contextlib import asynccontextmanager, contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from langgraph.store.memory import InMemoryStore
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from deerflow.persistence.thread_meta.base import (
    THREAD_INCOGNITO_ENDED_METADATA_KEY,
    THREAD_INCOGNITO_EXPIRED_STATUS,
    incognito_deadline,
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


def test_deadline_helper_caps_every_window_at_the_creation_ceiling():
    created = datetime(2026, 1, 1, tzinfo=UTC)

    # A window shorter than the ceiling wins unchanged.
    assert incognito_deadline(
        now=created + timedelta(minutes=10),
        created_at=created,
        window=timedelta(minutes=5),
        max_lifetime=timedelta(days=1),
    ) == created + timedelta(minutes=15)
    # Idle and grace windows both stop at the ceiling.
    for window in (timedelta(days=2), timedelta(days=30)):
        assert incognito_deadline(
            now=created + timedelta(hours=23),
            created_at=created,
            window=window,
            max_lifetime=timedelta(days=1),
        ) == created + timedelta(days=1)


@pytest.mark.anyio
async def test_end_schedules_grace_only_up_to_the_creation_ceiling(store):
    await _incognito(store)

    assert await store.end_incognito(
        "secret",
        grace=timedelta(days=30),
        max_lifetime=timedelta(minutes=30),
        user_id="alice",
    )
    ended = await store.get("secret", user_id="alice")
    created = datetime.fromisoformat(ended["created_at"])
    assert datetime.fromisoformat(ended["expires_at"]) == created + timedelta(minutes=30)


@pytest.mark.anyio
async def test_renewal_skips_ordinary_ended_and_tombstoned_threads(store):
    await store.create("plain", user_id="alice")
    assert not await store.renew_incognito("plain", idle_ttl=timedelta(hours=1), max_lifetime=timedelta(days=7), user_id="alice")

    await _incognito(store)
    assert await store.end_incognito("secret", grace=timedelta(minutes=5), max_lifetime=timedelta(days=7), user_id="alice")
    ended = await store.get("secret", user_id="alice")
    assert ended["metadata"][THREAD_INCOGNITO_ENDED_METADATA_KEY] is True
    # An end must not be undone by activity finishing inside the grace window.
    assert not await store.renew_incognito("secret", idle_ttl=timedelta(hours=24), max_lifetime=timedelta(days=7), user_id="alice")
    assert (await store.get("secret", user_id="alice"))["expires_at"] == ended["expires_at"]

    # The tombstone write only happens for a due row, so pass a moment past
    # the end grace window.
    assert await store.begin_incognito_expiry("secret", now=datetime.now(UTC) + timedelta(minutes=10))
    assert not await store.renew_incognito("secret", idle_ttl=timedelta(hours=1), max_lifetime=timedelta(days=7), user_id="alice")


@pytest.mark.anyio
async def test_owner_end_requires_the_incognito_owner(store):
    await _incognito(store)

    assert not await store.end_incognito("secret", grace=timedelta(minutes=5), max_lifetime=timedelta(days=7), user_id="bob")
    assert not await store.end_incognito("missing", grace=timedelta(minutes=5), max_lifetime=timedelta(days=7), user_id="alice")


@pytest.mark.anyio
async def test_tombstone_clears_content_and_makes_the_thread_unreadable(store):
    await _incognito(store)

    assert await store.begin_incognito_expiry("secret", now=datetime.now(UTC) + timedelta(hours=2))
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
async def test_renewal_refuses_a_deadline_that_already_passed(store):
    await _incognito(store, expires_in=-60)
    before = await store.get("secret", user_id="alice")

    assert not await store.renew_incognito("secret", idle_ttl=timedelta(hours=2), max_lifetime=timedelta(days=7), user_id="alice")

    unchanged = await store.get("secret", user_id="alice")
    assert unchanged["expires_at"] == before["expires_at"]
    # Only the sweep writes the tombstone, but activity must not pull an
    # already-expired row back from the due list.
    assert unchanged["status"] == "idle"
    assert is_incognito_expired(unchanged)


@pytest.mark.anyio
async def test_tombstone_survives_late_status_and_title_writes(store):
    await _incognito(store)
    assert await store.begin_incognito_expiry("secret", now=datetime.now(UTC) + timedelta(hours=2))

    # A run finalizing on another worker writes its title and status back after
    # the sweep. Those writes must not revive the tombstone, or reads resolve
    # again while ``expires_at`` is cleared and the sweep never returns.
    await store.update_display_name("secret", "leaked title")
    await store.update_status("secret", "running")
    await store.update_status("secret", "idle")

    record = await store.get("secret", user_id="alice")
    assert record["status"] == THREAD_INCOGNITO_EXPIRED_STATUS
    assert record["display_name"] is None
    assert is_incognito_expired(record)


@pytest.mark.anyio
async def test_begin_expiry_skips_a_row_renewed_after_the_due_snapshot(store):
    # The sweep's due list is a snapshot. Model the stale entry by renewing the
    # row before the tombstone write: the store must recheck the live deadline
    # instead of trusting the batch.
    await _incognito(store, expires_in=5)
    assert await store.renew_incognito("secret", idle_ttl=timedelta(hours=2), max_lifetime=timedelta(days=7), user_id="alice")
    assert not await store.begin_incognito_expiry("secret")
    record = await store.get("secret", user_id="alice")
    assert record["status"] == "idle"
    assert record["display_name"] == "private notes"

    # Once the renewed deadline passes, the same row is eligible again.
    assert await store.begin_incognito_expiry("secret", now=datetime.now(UTC) + timedelta(hours=3))
    assert (await store.get("secret", user_id="alice"))["status"] == THREAD_INCOGNITO_EXPIRED_STATUS


@pytest.mark.anyio
async def test_end_incognito_is_idempotent_and_keeps_the_first_deadline(store):
    await _incognito(store)
    moment = datetime.now(UTC)

    assert await store.end_incognito("secret", grace=timedelta(minutes=5), max_lifetime=timedelta(days=7), now=moment, user_id="alice")
    first = await store.get("secret", user_id="alice")
    # A repeated end (the caller retried or closed the tab twice) must not push
    # the purge deadline out again.
    assert await store.end_incognito("secret", grace=timedelta(minutes=5), max_lifetime=timedelta(days=7), now=moment + timedelta(minutes=3), user_id="alice")
    second = await store.get("secret", user_id="alice")
    assert second["expires_at"] == first["expires_at"]


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
            mcp_task_repo=SimpleNamespace(delete_by_thread=AsyncMock()),
        )
    )

    with (
        patch.object(thread_routes, "_delete_thread_data", lambda *args, **kwargs: thread_routes.ThreadDeleteResponse(success=True, message="ok")),
        patch("deerflow.community.browser_automation.get_browser_session_manager", return_value=SimpleNamespace(close_session=_noop)),
        patch("deerflow.mcp.session_pool.get_session_pool", return_value=SimpleNamespace(close_thread_scope=_noop)),
    ):
        purged = await incognito_module.sweep_expired_incognito_threads(app, batch_size=10)

    assert purged == 1
    # MCP task rows hold remote result payloads, so the purge removes them too.
    app.state.mcp_task_repo.delete_by_thread.assert_awaited_once_with("secret", user_id="alice")
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


class _RecordingRunManager:
    def __init__(self):
        self.reserved: list[tuple[str, dict]] = []

    @asynccontextmanager
    async def reserve_thread_operation(self, thread_id, **kwargs):
        self.reserved.append((thread_id, kwargs))
        yield

    async def discard_thread_runs(self, thread_id):
        return None


@contextmanager
def _sweep_patches(thread_routes):
    with (
        patch.object(thread_routes, "_delete_thread_data", lambda *args, **kwargs: thread_routes.ThreadDeleteResponse(success=True, message="ok")),
        patch("deerflow.community.browser_automation.get_browser_session_manager", return_value=SimpleNamespace(close_session=_noop)),
        patch("deerflow.mcp.session_pool.get_session_pool", return_value=SimpleNamespace(close_thread_scope=_noop)),
    ):
        yield


@pytest.mark.anyio
async def test_sweep_skips_a_row_renewed_after_the_due_list_was_read():
    from app.gateway import incognito as incognito_module

    class _RacyStore(MemoryThreadMetaStore):
        """Hand the sweep a stale due entry, then renew the live row."""

        async def list_due_incognito(self, *, now=None, limit=100):
            stale = await self.get("secret", user_id=None)
            assert await self.renew_incognito("secret", idle_ttl=timedelta(hours=2), max_lifetime=timedelta(days=7), user_id="alice")
            return [stale]

    store = _RacyStore(InMemoryStore())
    await _incognito(store, expires_in=5)
    app = SimpleNamespace(state=SimpleNamespace(thread_store=store, run_manager=_RecordingRunManager(), checkpointer=None))

    assert await incognito_module.sweep_expired_incognito_threads(app, batch_size=10) == 0
    record = await store.get("secret", user_id="alice")
    assert record["status"] == "idle"
    assert record["display_name"] == "private notes"
    assert record["expires_at"] is not None


@pytest.mark.anyio
async def test_failed_purge_keeps_the_retry_marker_and_succeeds_on_the_next_sweep():
    from app.gateway import incognito as incognito_module
    from app.gateway.routers import threads as thread_routes

    class _FailingRunStore:
        async def delete_by_thread(self, thread_id, *, user_id):
            raise RuntimeError("run store unavailable")

    class _WorkingRunStore:
        async def delete_by_thread(self, thread_id, *, user_id):
            return 0

    store = MemoryThreadMetaStore(InMemoryStore())
    await _incognito(store, expires_in=-60)
    state = SimpleNamespace(thread_store=store, run_manager=_RecordingRunManager(), checkpointer=None, run_store=_FailingRunStore(), run_event_store=None)

    with _sweep_patches(thread_routes):
        # The tombstone is written, but the failed run deletion raises so the
        # sweep does not clear ``expires_at``.
        assert await incognito_module.sweep_expired_incognito_threads(SimpleNamespace(state=state), batch_size=10) == 0
        tombstone = await store.get("secret", user_id="alice")
        assert tombstone["status"] == THREAD_INCOGNITO_EXPIRED_STATUS
        assert tombstone["expires_at"] is not None

        state.run_store = _WorkingRunStore()
        assert await incognito_module.sweep_expired_incognito_threads(SimpleNamespace(state=state), batch_size=10) == 1

    finished = await store.get("secret", user_id="alice")
    assert finished["expires_at"] is None


@pytest.mark.anyio
async def test_sweep_treats_a_failed_batch_cleanup_as_incomplete():
    from app.gateway import incognito as incognito_module
    from app.gateway.routers import threads as thread_routes

    class _FailingBatchRepo:
        async def suppress_thread_continuations(self, thread_id):
            raise RuntimeError("batch store unavailable")

        async def delete_by_thread(self, thread_id, *, user_id):
            raise AssertionError("suppression failed first")

    store = MemoryThreadMetaStore(InMemoryStore())
    await _incognito(store, expires_in=-60)
    state = SimpleNamespace(
        thread_store=store,
        run_manager=_RecordingRunManager(),
        checkpointer=None,
        subagent_batch_repo=_FailingBatchRepo(),
    )

    with _sweep_patches(thread_routes):
        # A failing batch repository must not abort the purge halfway through:
        # the tombstone is written, the remaining stores are still attempted,
        # and the strict contract keeps the retry marker.
        assert await incognito_module.sweep_expired_incognito_threads(SimpleNamespace(state=state), batch_size=10) == 0

    tombstone = await store.get("secret", user_id="alice")
    assert tombstone["status"] == THREAD_INCOGNITO_EXPIRED_STATUS
    assert tombstone["expires_at"] is not None


@pytest.mark.anyio
async def test_sweep_treats_a_failed_read_marker_cleanup_as_incomplete():
    from app.gateway import incognito as incognito_module
    from app.gateway.routers import threads as thread_routes

    class _FailingReadRepo:
        async def delete_by_thread(self, thread_id):
            raise RuntimeError("read store unavailable")

    store = MemoryThreadMetaStore(InMemoryStore())
    await _incognito(store, expires_in=-60)
    state = SimpleNamespace(
        thread_store=store,
        run_manager=_RecordingRunManager(),
        checkpointer=None,
        thread_read_repo=_FailingReadRepo(),
    )

    with _sweep_patches(thread_routes):
        # Read markers are persisted content, so their failure is part of the
        # strict contract: the row keeps its retry marker.
        assert await incognito_module.sweep_expired_incognito_threads(SimpleNamespace(state=state), batch_size=10) == 0

    tombstone = await store.get("secret", user_id="alice")
    assert tombstone["status"] == THREAD_INCOGNITO_EXPIRED_STATUS
    assert tombstone["expires_at"] is not None


@pytest.mark.anyio
async def test_best_effort_purge_survives_a_failed_batch_cleanup():
    from app.gateway.routers import threads as thread_routes

    class _FailingBatchRepo:
        async def suppress_thread_continuations(self, thread_id):
            raise RuntimeError("batch store unavailable")

        async def delete_by_thread(self, thread_id, *, user_id):
            raise AssertionError("suppression failed first")

    state = SimpleNamespace(
        run_manager=_RecordingRunManager(),
        checkpointer=None,
        subagent_batch_repo=_FailingBatchRepo(),
    )

    with _sweep_patches(thread_routes):
        # The interactive delete route is best-effort: a broken auxiliary store
        # must not turn the user's DELETE into a 500.
        response = await thread_routes.purge_thread_data("secret", app_state=state, user_id="alice", delete_meta_row=False)

    assert response.success


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
        # An ordinary thread is pinned as False, not left absent: the verdict
        # is established at admission so no later step has to guess it.
        assert plain_config["context"][INCOGNITO_CONTEXT_KEY] is False
        assert datetime.fromisoformat((await store.get("secret", user_id="alice"))["expires_at"]) - datetime.now(UTC) > timedelta(minutes=50)

    asyncio.run(scenario())


def test_run_admission_fails_closed_when_the_thread_store_is_unreadable():
    import asyncio

    from app.gateway.deps import _run_admission_hook
    from deerflow.config.incognito_config import IncognitoThreadsConfig
    from deerflow.runtime.runs import RunAdmissionRejected

    class _BrokenStore:
        async def get(self, *args, **kwargs):
            raise RuntimeError("thread store down")

        async def renew_incognito(self, *args, **kwargs):
            raise RuntimeError("thread store down")

    async def scenario():
        hook = _run_admission_hook(
            checkpointer=object(),
            thread_store=_BrokenStore(),
            app_config=SimpleNamespace(incognito=IncognitoThreadsConfig(idle_ttl_seconds=3600, max_lifetime_seconds=7 * 24 * 3600)),
        )
        # Without a pinned verdict the run cannot know which persistence
        # policy applies. Guessing "ordinary" would write memory and shared
        # blobs for an incognito thread, so admission fails instead.
        with pytest.raises(RunAdmissionRejected):
            await hook(SimpleNamespace(run_id="r1", thread_id="secret"), {})

    asyncio.run(scenario())


def test_run_admission_rejects_a_run_on_an_expired_thread():
    import asyncio

    from app.gateway.deps import _run_admission_hook
    from deerflow.config.incognito_config import IncognitoThreadsConfig
    from deerflow.runtime.runs import RunAdmissionRejected

    async def scenario():
        store = MemoryThreadMetaStore(InMemoryStore())
        await _incognito(store, expires_in=-60)
        hook = _run_admission_hook(
            checkpointer=object(),
            thread_store=store,
            app_config=SimpleNamespace(incognito=IncognitoThreadsConfig(idle_ttl_seconds=3600, max_lifetime_seconds=7 * 24 * 3600)),
        )
        with pytest.raises(RunAdmissionRejected):
            await hook(SimpleNamespace(run_id="r1", thread_id="secret"), {})

    asyncio.run(scenario())


def test_run_admission_rechecks_a_pinned_verdict_against_the_live_row():
    import asyncio

    from app.gateway.deps import _run_admission_hook
    from deerflow.config.incognito_config import IncognitoThreadsConfig
    from deerflow.runtime.context_keys import INCOGNITO_CONTEXT_KEY
    from deerflow.runtime.runs import RunAdmissionRejected

    async def scenario():
        store = MemoryThreadMetaStore(InMemoryStore())
        hook = _run_admission_hook(
            checkpointer=object(),
            thread_store=store,
            app_config=SimpleNamespace(incognito=IncognitoThreadsConfig(idle_ttl_seconds=3600, max_lifetime_seconds=7 * 24 * 3600)),
        )
        # The pinned verdict is only a hint: another process may have swept or
        # deleted the thread since start_run read it.
        with pytest.raises(RunAdmissionRejected):
            await hook(SimpleNamespace(run_id="r1", thread_id="secret"), {"context": {INCOGNITO_CONTEXT_KEY: True}})

        await _incognito(store, expires_in=60)
        await store.begin_incognito_expiry("secret", now=datetime.now(UTC) + timedelta(hours=2))
        with pytest.raises(RunAdmissionRejected):
            await hook(SimpleNamespace(run_id="r2", thread_id="secret"), {"context": {INCOGNITO_CONTEXT_KEY: True}})

        # A row recreated as an ordinary thread no longer matches the pinned
        # policy; starting an incognito run on it would be a guess.
        await store.create("ordinary", user_id="alice")
        with pytest.raises(RunAdmissionRejected):
            await hook(SimpleNamespace(run_id="r3", thread_id="ordinary"), {"context": {INCOGNITO_CONTEXT_KEY: True}})

    asyncio.run(scenario())


def test_run_admission_renewal_failure_never_flips_the_verdict():
    import asyncio

    from app.gateway.deps import _run_admission_hook
    from deerflow.config.incognito_config import IncognitoThreadsConfig
    from deerflow.runtime.context_keys import INCOGNITO_CONTEXT_KEY

    class _RenewFailsStore:
        async def get(self, *args, **kwargs):
            # A live incognito row: the hook rechecks the pinned verdict against
            # the store before it renews.
            return {
                "thread_id": "secret",
                "incognito": True,
                "status": "idle",
                "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            }

        async def renew_incognito(self, *args, **kwargs):
            raise RuntimeError("renewal failed")

    async def scenario():
        hook = _run_admission_hook(
            checkpointer=object(),
            thread_store=_RenewFailsStore(),
            app_config=SimpleNamespace(incognito=IncognitoThreadsConfig(idle_ttl_seconds=3600, max_lifetime_seconds=7 * 24 * 3600)),
        )
        config: dict = {"context": {INCOGNITO_CONTEXT_KEY: True}}
        # Renewal is activity bookkeeping: its failure keeps the old deadline
        # but must not turn an incognito run into an ordinary one.
        await hook(SimpleNamespace(run_id="r1", thread_id="secret"), config)
        assert config["context"][INCOGNITO_CONTEXT_KEY] is True

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
