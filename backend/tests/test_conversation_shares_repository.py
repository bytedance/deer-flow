"""Tests for the conversation share repository (#4548)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio

from deerflow.config.database_config import DatabaseConfig
from deerflow.persistence.conversation_shares import ConversationShareRepository
from deerflow.persistence.engine import close_engine, get_session_factory, init_engine_from_config

_SNAPSHOT = {"version": 1, "title": "t", "messages": [{"id": "m1", "role": "user", "content": "hi"}]}


@pytest_asyncio.fixture(autouse=True)
async def _close_persistence_engine():
    yield
    await close_engine()


async def _make_repo(tmp_path) -> ConversationShareRepository:
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    session_factory = get_session_factory()
    assert session_factory is not None
    return ConversationShareRepository(session_factory)


async def _create_share(repo: ConversationShareRepository, **overrides) -> dict:
    kwargs = dict(
        thread_id="thread-1",
        owner_user_id="user-1",
        token_hash="hash-" + str(overrides.get("token_hash", "a")),
        title="Weekly sync",
        snapshot_json=_SNAPSHOT,
    )
    kwargs.update(overrides)
    return await repo.create(**kwargs)


@pytest.mark.asyncio
async def test_create_and_resolve_by_token_hash_roundtrip(tmp_path):
    repo = await _make_repo(tmp_path)
    created = await _create_share(repo, token_hash="tok-1")

    resolved = await repo.get_active_by_token_hash("tok-1")
    assert resolved is not None
    assert resolved["id"] == created["id"]
    assert resolved["thread_id"] == "thread-1"
    assert resolved["owner_user_id"] == "user-1"
    assert resolved["snapshot_json"] == _SNAPSHOT
    assert resolved["snapshot_version"] == 1
    # Unknown tokens resolve to None.
    assert await repo.get_active_by_token_hash("tok-other") is None


@pytest.mark.asyncio
async def test_expired_share_no_longer_resolves(tmp_path):
    repo = await _make_repo(tmp_path)
    await _create_share(repo, token_hash="tok-exp", expires_at=datetime.now(UTC) - timedelta(seconds=1))

    assert await repo.get_active_by_token_hash("tok-exp") is None
    # The row itself stays readable for owner-side history.
    assert await repo.get((await repo.list_by_thread("thread-1", "user-1"))[0]["id"]) is not None


@pytest.mark.asyncio
async def test_revoked_share_no_longer_resolves(tmp_path):
    repo = await _make_repo(tmp_path)
    created = await _create_share(repo, token_hash="tok-rev")

    assert await repo.revoke(created["id"], "thread-1", "user-1") is True
    # Revoking twice is a no-op.
    assert await repo.revoke(created["id"], "thread-1", "user-1") is False
    assert await repo.get_active_by_token_hash("tok-rev") is None


@pytest.mark.asyncio
async def test_revoke_is_scoped_to_owner_and_thread(tmp_path):
    repo = await _make_repo(tmp_path)
    created = await _create_share(repo, token_hash="tok-scope")

    # Wrong owner, right thread.
    assert await repo.revoke(created["id"], "thread-1", "user-2") is False
    # Right owner, wrong thread.
    assert await repo.revoke(created["id"], "thread-2", "user-1") is False
    assert await repo.get_active_by_token_hash("tok-scope") is not None


@pytest.mark.asyncio
async def test_list_by_thread_is_isolated_per_owner(tmp_path):
    repo = await _make_repo(tmp_path)
    mine = await _create_share(repo, token_hash="tok-mine", owner_user_id="user-1")
    await _create_share(repo, thread_id="thread-1", owner_user_id="user-2", token_hash="tok-theirs", title="theirs")
    await _create_share(repo, thread_id="thread-9", owner_user_id="user-1", token_hash="tok-other-thread", title="other")

    listed = await repo.list_by_thread("thread-1", "user-1")
    assert [row["id"] for row in listed] == [mine["id"]]
    # Lifecycle fields ride along for the management view.
    assert listed[0]["revoked_at"] is None
    assert listed[0]["expires_at"] is None


@pytest.mark.asyncio
async def test_token_hash_unique_constraint(tmp_path):
    repo = await _make_repo(tmp_path)
    await _create_share(repo, token_hash="tok-dup")
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        await _create_share(repo, token_hash="tok-dup")
