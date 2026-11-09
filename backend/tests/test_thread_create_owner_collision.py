"""Thread ID collisions retain owner isolation and creation idempotency."""

from uuid import UUID

import httpx
import pytest
from _router_auth_helpers import make_authed_test_app
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.gateway.auth.models import User
from app.gateway.routers import threads
from deerflow.persistence.thread_meta import ThreadMetaRepository
from deerflow.persistence.thread_meta.memory import MemoryThreadMetaStore


@pytest.fixture(params=["memory", "sqlite"])
async def store(request, tmp_path):
    if request.param == "memory":
        yield MemoryThreadMetaStore(InMemoryStore())
        return
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine

    try:
        await init_engine("sqlite", url=f"sqlite+aiosqlite:///{tmp_path / 'owners.db'}", sqlite_dir=str(tmp_path))
        yield ThreadMetaRepository(get_session_factory())
    finally:
        await close_engine()


@pytest.mark.anyio
async def test_foreign_owner_create_is_non_disclosing_and_preserves_original(store):
    owner = User(id=UUID(int=1), email="owner@example.com", password_hash="x", system_role="user")
    other = User(id=UUID(int=2), email="other@example.com", password_hash="x", system_role="user")
    active_user = owner
    app = make_authed_test_app(user_factory=lambda: active_user, bind_current_user=True)
    saver = InMemorySaver()
    app.state.thread_store = store
    app.state.checkpointer = saver
    app.include_router(threads.router)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post("/api/threads", json={"thread_id": "collision", "metadata": {"marker": "original"}})
        assert created.status_code == 200
        checkpoint = await saver.aget_tuple({"configurable": {"thread_id": "collision", "checkpoint_ns": ""}})
        repeated = await client.post("/api/threads", json={"thread_id": "collision", "metadata": {"marker": "replacement"}})
        assert repeated.status_code == 200
        assert repeated.json() == created.json()

        active_user = other
        denied = await client.post("/api/threads", json={"thread_id": "collision", "metadata": {"marker": "foreign"}})
        assert denied.status_code == 404
        assert denied.json() == {"detail": "Thread not found"}
        assert (await client.get("/api/threads/collision")).status_code == 404
        fresh = await client.post("/api/threads", json={"thread_id": "other-thread"})
        assert fresh.status_code == 200

    original = await store.get("collision", user_id=str(owner.id))
    assert original["metadata"] == {"marker": "original"}
    assert original["user_id"] == str(owner.id)
    after = await saver.aget_tuple({"configurable": {"thread_id": "collision", "checkpoint_ns": ""}})
    assert after.config == checkpoint.config
    assert after.checkpoint == checkpoint.checkpoint


@pytest.mark.anyio
@pytest.mark.parametrize("same_owner", [False, True])
async def test_sql_insert_race_preserves_committed_owner_and_metadata(store, monkeypatch, same_owner):
    if not isinstance(store, ThreadMetaRepository):
        pytest.skip("SQL duplicate-insert recovery; memory behavior is covered above")
    user = User(id=UUID(int=2), email="caller@example.com", password_hash="x", system_role="user")
    first_owner = str(user.id) if same_owner else str(UUID(int=1))
    app = make_authed_test_app(user_factory=lambda: user, bind_current_user=True)
    app.state.thread_store = store
    saver = InMemorySaver()
    app.state.checkpointer = saver
    app.include_router(threads.router)
    original_create = store.create

    async def create_after_peer_commit(thread_id, **kwargs):
        # A second worker can commit after the HTTP owner-scoped lookup misses.
        # Execute both actual SQL inserts; do not manufacture IntegrityError.
        await original_create(thread_id, user_id=first_owner, metadata={"marker": "peer"})
        return await original_create(thread_id, **kwargs)

    monkeypatch.setattr(store, "create", create_after_peer_commit)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/threads", json={"thread_id": "raced", "metadata": {"marker": "caller"}})
    assert response.status_code == (200 if same_owner else 404)
    if same_owner:
        assert response.json()["metadata"] == {"marker": "peer"}
    else:
        assert response.json() == {"detail": "Thread not found"}
    row = await store.get("raced", user_id=first_owner)
    assert row["user_id"] == first_owner
    assert row["metadata"] == {"marker": "peer"}
    assert await saver.aget_tuple({"configurable": {"thread_id": "raced", "checkpoint_ns": ""}}) is None


@pytest.mark.anyio
async def test_normal_user_cannot_claim_legacy_unowned_thread(store):
    await store.create("legacy-unowned", user_id=None, metadata={"marker": "legacy"})
    original = await store.get("legacy-unowned", user_id=None)
    assert original["user_id"] is None
    user = User(id=UUID(int=1), email="caller@example.com", password_hash="x", system_role="user")
    app = make_authed_test_app(user_factory=lambda: user, bind_current_user=True)
    app.state.thread_store = store
    saver = InMemorySaver()
    app.state.checkpointer = saver
    app.include_router(threads.router)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/threads", json={"thread_id": "legacy-unowned", "metadata": {"marker": "replacement"}})
    assert response.status_code == 404
    assert response.json() == {"detail": "Thread not found"}
    assert await store.get("legacy-unowned", user_id=None) == original
    assert await store.get("legacy-unowned", user_id=str(user.id)) is None
    assert await saver.aget_tuple({"configurable": {"thread_id": "legacy-unowned", "checkpoint_ns": ""}}) is None


@pytest.mark.anyio
async def test_unrelated_sql_integrity_failure_remains_a_server_error(store):
    if not isinstance(store, ThreadMetaRepository):
        pytest.skip("Actual SQL integrity failure")
    async with store._sf() as session:
        await session.execute(text("CREATE TRIGGER reject_test_insert BEFORE INSERT ON threads_meta BEGIN SELECT RAISE(ABORT, 'synthetic integrity failure'); END"))
        await session.commit()
    owner = User(id=UUID(int=1), email="owner@example.com", password_hash="x", system_role="user")
    app = make_authed_test_app(user_factory=lambda: owner, bind_current_user=True)
    app.state.thread_store = store
    app.state.checkpointer = InMemorySaver()
    app.include_router(threads.router)
    with pytest.raises(IntegrityError, match="synthetic integrity failure"):
        await store.create("direct-failure", user_id=str(owner.id))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/threads", json={"thread_id": "failed"})
    assert response.status_code == 500
    assert response.json() == {"detail": "Failed to create thread"}
    assert await store.get("failed", user_id=str(owner.id)) is None
