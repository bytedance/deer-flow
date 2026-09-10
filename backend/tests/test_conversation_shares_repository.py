"""Tests for the conversation share repository (#4548)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import event

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
async def test_list_by_thread_projects_metadata_only(tmp_path):
    """The management list must not materialize snapshot payloads.

    Each share's snapshot can be as large as the share cap, and revoked rows
    stay listed for history — dozens of shares would otherwise deserialize
    hundreds of MiB for a response that only ever reads the summary fields.
    Pinned at the SQL level (the heavy columns are never projected) and at
    the contract level (the dicts carry metadata only).
    """
    repo = await _make_repo(tmp_path)
    first = await _create_share(repo, token_hash="tok-meta-1")
    second = await _create_share(repo, token_hash="tok-meta-2", title="second")

    statements: list[str] = []

    def _capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    session_factory = get_session_factory()
    engine = session_factory.kw["bind"]
    event.listen(engine.sync_engine, "before_cursor_execute", _capture)
    try:
        listed = await repo.list_by_thread("thread-1", "user-1")
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", _capture)

    selects = [s for s in statements if "FROM conversation_shares" in s]
    assert len(selects) == 1
    # The heavy columns are never projected...
    assert "snapshot_json" not in selects[0]
    assert "token_hash" not in selects[0]
    # ...while every field the management summary reads is.
    for column in ("id", "title", "expires_at", "revoked_at", "created_at"):
        assert f"conversation_shares.{column}" in selects[0]
    # The returned dicts match the projection: metadata only, newest first.
    assert [row["id"] for row in listed] == [second["id"], first["id"]]
    assert set(listed[0]) == {"id", "title", "expires_at", "revoked_at", "created_at"}


@pytest.mark.asyncio
async def test_count_by_owner_counts_all_rows_across_threads_and_states(tmp_path):
    """The per-owner quota counts every stored row: payload survives
    revocation, so lifecycle state and thread do not change the footprint."""
    repo = await _make_repo(tmp_path)
    other_thread = await _create_share(repo, token_hash="tok-count-1", thread_id="thread-2")
    await _create_share(repo, token_hash="tok-count-2")
    await _create_share(repo, token_hash="tok-count-3", owner_user_id="user-2")

    assert await repo.revoke(other_thread["id"], "thread-2", "user-1") is True
    # Revoked rows still count for the owner; other owners are isolated.
    assert await repo.count_by_owner("user-1") == 2
    assert await repo.count_by_owner("user-2") == 1
    assert await repo.count_by_owner("user-nobody") == 0


@pytest.mark.asyncio
async def test_create_admits_atomically_under_concurrency(tmp_path):
    """Concurrent creations for one owner cannot overshoot the cap.

    A pre-checked COUNT-then-INSERT races (each request passes the count,
    then every request inserts); admission must be a single atomic
    statement whose guard carries the cap, so racing requests serialize on
    the owner's counter instead.
    """
    repo = await _make_repo(tmp_path)
    results = await asyncio.gather(*[_create_share(repo, token_hash=f"tok-race-{i}", quota_limit=3) for i in range(5)])

    succeeded = [record for record in results if record is not None]
    assert len(succeeded) == 3
    assert await repo.count_by_owner("user-1") == 3
    # The cap holds for later requests too — admission is durable.
    assert await _create_share(repo, token_hash="tok-after-race", quota_limit=3) is None


@pytest.mark.asyncio
async def test_failed_insert_rolls_back_quota_admission(tmp_path):
    """A create that fails after admission must not consume a slot."""
    from sqlalchemy.exc import IntegrityError

    repo = await _make_repo(tmp_path)
    assert await _create_share(repo, token_hash="tok-base-quota", quota_limit=2) is not None
    with pytest.raises(IntegrityError):
        await _create_share(repo, token_hash="tok-base-quota", quota_limit=2)

    # The failed duplicate did not consume the owner's second slot...
    assert await _create_share(repo, token_hash="tok-ok-1", quota_limit=2) is not None
    # ...and the cap still refuses the third stored row.
    assert await _create_share(repo, token_hash="tok-ok-2", quota_limit=2) is None


def _capture_statements(statements: list[str]):
    def _capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    return _capture


@pytest.mark.asyncio
async def test_revoked_token_resolution_never_materializes_snapshot(tmp_path):
    """A retained token for a dead share must not load its payload.

    Revocation is SQL-filtered before any heavy column is projected: the
    public resolve path stays cheap no matter how large the stored
    snapshots are.
    """
    repo = await _make_repo(tmp_path)
    created = await _create_share(repo, token_hash="tok-dead-revoked")
    assert await repo.revoke(created["id"], "thread-1", "user-1") is True

    session_factory = get_session_factory()
    engine = session_factory.kw["bind"]
    listener = _capture_statements(statements := [])
    event.listen(engine.sync_engine, "before_cursor_execute", listener)
    try:
        assert await repo.get_active_by_token_hash("tok-dead-revoked") is None
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", listener)

    selects = [s for s in statements if "FROM conversation_shares" in s]
    assert len(selects) == 1
    assert "snapshot_json" not in selects[0]
    assert "title" not in selects[0]


@pytest.mark.asyncio
async def test_expired_token_resolution_never_materializes_snapshot(tmp_path):
    """Same contract for expired shares: the liveness probe reads id and
    expiry only; the payload is fetched only for live shares."""
    repo = await _make_repo(tmp_path)
    await _create_share(repo, token_hash="tok-dead-expired", expires_at=datetime.now(UTC) - timedelta(seconds=1))

    session_factory = get_session_factory()
    engine = session_factory.kw["bind"]
    listener = _capture_statements(statements := [])
    event.listen(engine.sync_engine, "before_cursor_execute", listener)
    try:
        assert await repo.get_active_by_token_hash("tok-dead-expired") is None
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", listener)

    selects = [s for s in statements if "FROM conversation_shares" in s]
    assert len(selects) == 1
    assert "snapshot_json" not in selects[0]


@pytest.mark.asyncio
async def test_token_hash_unique_constraint(tmp_path):
    repo = await _make_repo(tmp_path)
    await _create_share(repo, token_hash="tok-dup")
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        await _create_share(repo, token_hash="tok-dup")
