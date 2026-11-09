"""Authentication provenance must remain separate from the storage user ID."""

import asyncio
from contextvars import Context
from types import SimpleNamespace

import pytest


@pytest.mark.no_auto_user
def test_user_context_or_client_metadata_is_not_authentication():
    from deerflow.runtime.user_context import get_authenticated_user_id, reset_current_user, set_current_user

    assert get_authenticated_user_id() is None
    token = set_current_user(SimpleNamespace(id="user", authenticated=True))
    try:
        assert get_authenticated_user_id() is None
    finally:
        reset_current_user(token)


def test_verified_identity_can_be_cleared_and_restored():
    from deerflow.runtime.user_context import bind_authenticated_user, get_authenticated_user_id

    with bind_authenticated_user("alice"):
        assert get_authenticated_user_id() == "alice"
        with bind_authenticated_user(None):
            assert get_authenticated_user_id() is None
        assert get_authenticated_user_id() == "alice"
        with pytest.raises(RuntimeError), bind_authenticated_user("bob"):
            raise RuntimeError("cancelled request")
        assert get_authenticated_user_id() == "alice"
    assert get_authenticated_user_id() is None


@pytest.mark.parametrize("invalid", ["", " ", " alice ", True, 1])
def test_verified_identity_rejects_invalid_host_bindings(invalid):
    from deerflow.runtime.user_context import bind_authenticated_user

    with pytest.raises(ValueError), bind_authenticated_user(invalid):
        pass


@pytest.mark.asyncio
async def test_verified_identity_survives_child_tasks_and_threads_without_cross_user_leaks():
    from deerflow.runtime.user_context import bind_authenticated_user, get_authenticated_user_id

    ready = asyncio.Event()

    async def child(user):
        await ready.wait()
        assert get_authenticated_user_id() == user
        return await asyncio.to_thread(get_authenticated_user_id)

    with bind_authenticated_user("alice"):
        alice = asyncio.create_task(child("alice"))
    with bind_authenticated_user("bob"):
        bob = asyncio.create_task(child("bob"))
    assert get_authenticated_user_id() is None
    ready.set()
    assert await asyncio.gather(alice, bob) == ["alice", "bob"]
    assert Context().run(get_authenticated_user_id) is None


@pytest.mark.asyncio
async def test_search_receives_host_proof_separately_from_its_user_id():
    from unittest.mock import AsyncMock

    from deerflow.knowledge import KnowledgeCapabilities, RetrievalResult
    from deerflow.knowledge.providers import search_provider
    from deerflow.runtime.user_context import bind_authenticated_user

    provider = SimpleNamespace(capabilities=KnowledgeCapabilities(), search_scoped=AsyncMock(return_value=RetrievalResult()))
    await search_provider(provider, "query", scope=None, user_id="alice", agent_name="lead_agent")
    assert provider.search_scoped.await_args.kwargs["context"].authenticated_user_id is None
    with bind_authenticated_user("alice"):
        await search_provider(provider, "query", scope=None, user_id="alice", agent_name="researcher")
    assert provider.search_scoped.await_args.kwargs["context"].authenticated_user_id == "alice"
