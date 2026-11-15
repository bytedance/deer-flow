"""Cross-owner thread_id creation returns 404, never 500 (SQL backend).

Regression for issue #8052: when a caller-supplied ``thread_id`` already
belongs to another user, the SQL-backed store rejects the duplicate primary
key with ``IntegrityError`` (the memory store raises the app-level
``ThreadOwnershipConflictError`` instead). The route's recovery path resolved
the surviving row through the *requesting* owner's scope, so a foreign row
could not be read back and the route surfaced a 500 instead of the documented
404 ownership-conflict response ("Thread not found").

The memory store does not have this bug, so the regression is exercised on the
sqlite backend only.
"""

from uuid import UUID

import httpx
import pytest
from _router_auth_helpers import make_authed_test_app
from langgraph.checkpoint.memory import InMemorySaver

from app.gateway.auth.models import User
from app.gateway.routers import threads
from deerflow.persistence.thread_meta import ThreadMetaRepository

USER_A = User(
    id=UUID("00000000-0000-0000-0000-0000000000a1"),
    email="owner-a@example.com",
    password_hash="x",
    system_role="admin",
)
USER_B = User(
    id=UUID("00000000-0000-0000-0000-0000000000b2"),
    email="owner-b@example.com",
    password_hash="x",
    system_role="admin",
)


@pytest.fixture
async def sql_thread_store(tmp_path):
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine

    await init_engine(
        "sqlite",
        url=f"sqlite+aiosqlite:///{tmp_path / 'threads.db'}",
        sqlite_dir=str(tmp_path),
    )
    try:
        yield ThreadMetaRepository(get_session_factory())
    finally:
        await close_engine()


def app_for(store, checkpointer, user):
    app = make_authed_test_app(user_factory=lambda: user, bind_current_user=True)
    app.state.thread_store = store
    app.state.checkpointer = checkpointer
    app.include_router(threads.router)
    return app


@pytest.mark.anyio
async def test_cross_owner_thread_id_returns_404(sql_thread_store):
    saver = InMemorySaver()
    app_a = app_for(sql_thread_store, saver, USER_A)
    app_b = app_for(sql_thread_store, saver, USER_B)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app_a), base_url="http://test") as client_a:
        created = await client_a.post(
            "/api/threads",
            json={"thread_id": "shared-client-id", "metadata": {"marker": "owner-a"}},
        )
    assert created.status_code == 200

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app_b), base_url="http://test") as client_b:
        conflict = await client_b.post(
            "/api/threads",
            json={"thread_id": "shared-client-id", "metadata": {"marker": "owner-b"}},
        )

    # The documented non-disclosing ownership-conflict response, not a 500.
    assert conflict.status_code == 404
    assert conflict.json()["detail"] == "Thread not found"
    # A's metadata is untouched and B cannot read the foreign row.
    assert await sql_thread_store.get("shared-client-id", user_id=str(USER_A.id)) is not None
    assert await sql_thread_store.get("shared-client-id", user_id=str(USER_B.id)) is None
