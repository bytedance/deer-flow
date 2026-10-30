"""Route tests for ``PUT /api/threads/{thread_id}/runs/{run_id}/feedback``.

The route is documented as idempotent: two first submissions for one run by
one user (two tabs, two devices, a client retry) must both succeed and leave a
single feedback row.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import httpx
import pytest
from _router_auth_helpers import make_authed_test_app

from app.gateway.auth.models import User
from app.gateway.auth_disabled import AUTH_SOURCE_SESSION
from app.gateway.routers import feedback
from deerflow.persistence.feedback import FeedbackRepository

THREAD_ID = "11111111-2222-3333-4444-555555555555"
RUN_ID = "run-1"


def _user() -> User:
    return User(
        id=UUID("99999999-8888-7777-6666-555555555555"),
        email="alice@example.com",
        password_hash="x",
        system_role="user",
    )


class _SelectBarrierSession:
    """Hold each session after its first SELECT until every writer has run its own.

    Both requests then see no row and both INSERT, which is the interleaving
    that two concurrent first submissions produce on a real database.
    """

    def __init__(self, session, barrier: asyncio.Barrier):
        self._session = session
        self._barrier = barrier
        self._waited = False

    def __getattr__(self, name):
        return getattr(self._session, name)

    async def execute(self, *args, **kwargs):
        result = await self._session.execute(*args, **kwargs)
        if not self._waited:
            self._waited = True
            async with asyncio.timeout(5):
                await self._barrier.wait()
        return result

    async def __aenter__(self):
        await self._session.__aenter__()
        return self

    async def __aexit__(self, *args):
        return await self._session.__aexit__(*args)


@pytest.fixture
async def feedback_repo(tmp_path):
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine

    await init_engine("sqlite", url=f"sqlite+aiosqlite:///{tmp_path / 'feedback.db'}", sqlite_dir=str(tmp_path))
    try:
        yield FeedbackRepository(get_session_factory())
    finally:
        await close_engine()


@pytest.mark.anyio
async def test_concurrent_first_feedback_puts_both_succeed_with_one_row(feedback_repo):
    barrier = asyncio.Barrier(2)
    real_factory = feedback_repo._sf
    feedback_repo._sf = lambda: _SelectBarrierSession(real_factory(), barrier)

    app = make_authed_test_app(user_factory=_user)

    @app.middleware("http")
    async def _session_auth_source(request, call_next):
        # Production AuthMiddleware records how the user authenticated; the
        # route only reads the user id from a recognized source.
        request.state.auth_source = AUTH_SOURCE_SESSION
        return await call_next(request)

    run_store = MagicMock()
    run_store.get = AsyncMock(return_value={"run_id": RUN_ID, "thread_id": THREAD_ID})
    app.state.run_store = run_store
    app.state.feedback_repo = feedback_repo
    app.include_router(feedback.router)

    url = f"/api/threads/{THREAD_ID}/runs/{RUN_ID}/feedback"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test") as client:
        up, down = await asyncio.gather(
            client.put(url, json={"rating": 1}),
            client.put(url, json={"rating": -1}),
        )

    assert up.status_code == 200, up.text
    assert down.status_code == 200, down.text
    assert up.json()["user_id"] == str(_user().id)
    assert up.json()["feedback_id"] == down.json()["feedback_id"]
    feedback_repo._sf = real_factory
    rows = await feedback_repo.list_by_run(THREAD_ID, RUN_ID, user_id=str(_user().id))
    assert len(rows) == 1
    # The later commit wins, as with sequential submissions.
    assert rows[0]["rating"] in (1, -1)
