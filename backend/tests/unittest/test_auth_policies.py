from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from starlette.requests import Request
from unittest.mock import AsyncMock

from app.plugins.auth.authorization import AuthContext, Permissions
from app.plugins.auth.authorization.policies import require_thread_owner
from app.plugins.auth.domain.models import User


def _make_auth_context() -> AuthContext:
    user = User(id=uuid4(), email="user@example.com", password_hash="hash")
    return AuthContext(user=user, permissions=[Permissions.THREADS_READ, Permissions.RUNS_READ])


def _make_request(*, thread_repo, run_repo=None, checkpointer=None) -> Request:
    app = SimpleNamespace(
        state=SimpleNamespace(
            thread_meta_repo=thread_repo,
            run_store=run_repo,
            checkpointer=checkpointer,
        )
    )
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/threads/thread-1/runs",
        "headers": [],
        "app": app,
        "route": SimpleNamespace(path="/api/threads/{thread_id}/runs"),
        "path_params": {"thread_id": "thread-1"},
    }
    return Request(scope)


@pytest.mark.anyio
async def test_require_thread_owner_uses_thread_row_user_id() -> None:
    auth = _make_auth_context()
    thread_repo = SimpleNamespace(
        get_thread_meta=AsyncMock(
            return_value=SimpleNamespace(
                user_id=str(auth.user.id),
                metadata={"user_id": "someone-else"},
            )
        )
    )
    request = _make_request(thread_repo=thread_repo)

    await require_thread_owner(request, auth, thread_id="thread-1", require_existing=True)


@pytest.mark.anyio
async def test_require_thread_owner_falls_back_to_user_owned_runs() -> None:
    auth = _make_auth_context()
    thread_repo = SimpleNamespace(get_thread_meta=AsyncMock(return_value=None))
    run_repo = SimpleNamespace(
        list_by_thread=AsyncMock(return_value=[{"run_id": "run-1", "thread_id": "thread-1"}])
    )
    request = _make_request(thread_repo=thread_repo, run_repo=run_repo)

    await require_thread_owner(request, auth, thread_id="thread-1", require_existing=True)

    run_repo.list_by_thread.assert_awaited_once_with("thread-1", limit=1, user_id=str(auth.user.id))


@pytest.mark.anyio
async def test_require_thread_owner_falls_back_to_checkpoint_threads() -> None:
    auth = _make_auth_context()
    thread_repo = SimpleNamespace(get_thread_meta=AsyncMock(return_value=None))
    run_repo = SimpleNamespace(list_by_thread=AsyncMock(return_value=[]))
    checkpointer = SimpleNamespace(aget_tuple=AsyncMock(return_value=object()))
    request = _make_request(thread_repo=thread_repo, run_repo=run_repo, checkpointer=checkpointer)

    await require_thread_owner(request, auth, thread_id="thread-1", require_existing=True)

    checkpointer.aget_tuple.assert_awaited_once_with(
        {"configurable": {"thread_id": "thread-1", "checkpoint_ns": ""}}
    )


@pytest.mark.anyio
async def test_require_thread_owner_denies_missing_thread() -> None:
    auth = _make_auth_context()
    thread_repo = SimpleNamespace(get_thread_meta=AsyncMock(return_value=None))
    run_repo = SimpleNamespace(list_by_thread=AsyncMock(return_value=[]))
    checkpointer = SimpleNamespace(aget_tuple=AsyncMock(return_value=None))
    request = _make_request(thread_repo=thread_repo, run_repo=run_repo, checkpointer=checkpointer)

    with pytest.raises(Exception) as exc_info:
        await require_thread_owner(request, auth, thread_id="thread-1", require_existing=True)

    assert getattr(exc_info.value, "status_code", None) == 404
    assert getattr(exc_info.value, "detail", "") == "Thread thread-1 not found"
