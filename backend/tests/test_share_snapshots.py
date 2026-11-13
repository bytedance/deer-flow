"""Share capabilities persist copies, never grant access to the source thread."""

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from support.postgres import asyncpg_test_url

from deerflow.persistence.base import Base
from deerflow.persistence.postgres_schema import build_asyncpg_connect_args
from deerflow.persistence.thread_meta.model import ThreadMetaRow
from deerflow.persistence.thread_shares.model import ShareArtifactRow, ThreadShareRow
from deerflow.persistence.thread_shares.sql import ThreadShareRepository


@pytest_asyncio.fixture(params=["sqlite", "postgres"])
async def repository(tmp_path, request):
    schema = None
    if request.param == "sqlite":
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'shares.db'}")
    else:
        uri = os.environ.get("TEST_POSTGRES_URI")
        if not uri:
            pytest.skip("requires TEST_POSTGRES_URI")
        schema = "share_repository_" + uuid.uuid4().hex
        engine = create_async_engine(asyncpg_test_url(uri), connect_args=build_asyncpg_connect_args(schema))
    async with engine.begin() as connection:
        if schema:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        await connection.run_sync(Base.metadata.create_all, tables=[ThreadMetaRow.__table__, ThreadShareRow.__table__, ShareArtifactRow.__table__])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        session.add(ThreadMetaRow(thread_id="source", user_id="alice", incarnation="original"))
        await session.commit()
    try:
        yield ThreadShareRepository(factory), factory
    finally:
        if schema:
            async with engine.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()


async def create_share(repo, *, expires_at=None):
    return await repo.create(
        thread_id="source",
        owner_id="alice",
        incarnation="original",
        checkpoint_id="checkpoint-1",
        seq=42,
        snapshot={"title": "Report", "messages": [{"type": "human", "content": "Question"}]},
        artifacts=[{"path": "report.html", "content": b"<h1>Original</h1>", "mime_type": "text/html"}],
        expires_at=expires_at or datetime.now(UTC) + timedelta(days=1),
    )


@pytest.mark.asyncio
async def test_snapshot_is_durable_and_token_is_not_stored(repository):
    repo, factory = repository
    created = await create_share(repo)
    restarted = ThreadShareRepository(factory)
    snapshot = await restarted.get_public(created["token"])
    assert snapshot["snapshot"]["messages"][0]["content"] == "Question"
    assert snapshot["checkpoint_id"] == "checkpoint-1"
    assert snapshot["seq"] == 42
    assert (await restarted.get_artifact(created["token"], "report.html"))["content"] == b"<h1>Original</h1>"
    async with factory() as session:
        row = await session.get(ThreadShareRow, created["share_id"])
        assert created["token"] not in str(row.to_dict())
    assert "token" not in (await restarted.list_owned("source", "alice"))[0]
    assert await restarted.list_owned("source", "bob") == []
    assert await restarted.get_public("invalid") is None
    assert await restarted.get_artifact(created["token"], "../secret") is None


@pytest.mark.asyncio
async def test_revocation_checks_owner_and_closes_every_surface(repository):
    repo, _ = repository
    share = await create_share(repo)
    assert not await repo.revoke("source", share["share_id"], "bob")
    assert await repo.get_public(share["token"]) is not None
    assert await repo.revoke("source", share["share_id"], "alice")
    assert await repo.get_public(share["token"]) is None
    assert await repo.get_artifact(share["token"], "report.html") is None


@pytest.mark.asyncio
async def test_expired_and_recreated_sources_cannot_authorize_old_links(repository):
    repo, factory = repository
    expired = await create_share(repo, expires_at=datetime.now(UTC) - timedelta(seconds=1))
    assert await repo.get_public(expired["token"]) is None
    assert await repo.get_artifact(expired["token"], "report.html") is None
    current = await create_share(repo)
    async with factory() as session:
        source = await session.get(ThreadMetaRow, "source")
        source.incarnation = "replacement"
        await session.commit()
    assert await repo.get_public(current["token"]) is None


@pytest.mark.asyncio
async def test_active_link_remains_revocable_after_many_inactive_links(repository):
    repo, factory = repository
    active = await create_share(repo)
    now = datetime.now(UTC)
    async with factory() as session:
        session.add_all(
            [
                ThreadShareRow(
                    share_id=f"revoked-{i}", token_hash=f"digest-{i}", thread_id="source", owner_id="alice", incarnation="original", checkpoint_id="cp", seq=0, snapshot={}, created_at=now, expires_at=now + timedelta(days=1), revoked_at=now
                )
                for i in range(101)
            ]
        )
        await session.commit()
    assert await repo.count_active("source", "alice") == 1
    assert await repo.count_active("source", "bob") == 0
    assert (await repo.list_owned("source", "alice"))[0]["share_id"] == active["share_id"]
    await repo.revoke("source", active["share_id"], "alice")
    assert await repo.count_active("source", "alice") == 0


@pytest.mark.asyncio
async def test_expired_snapshot_remains_listed_and_revocation_purges_its_copy(repository):
    repo, factory = repository
    expired = await create_share(repo, expires_at=datetime.now(UTC) - timedelta(seconds=1))
    for _ in range(101):
        current = await create_share(repo)
        assert await repo.revoke("source", current["share_id"], "alice")
    assert (await repo.list_owned("source", "alice"))[0]["share_id"] == expired["share_id"]
    assert await repo.revoke("source", expired["share_id"], "alice")
    async with factory() as session:
        row = await session.get(ThreadShareRow, expired["share_id"])
        assert row.revoked_at is not None
        assert row.snapshot == {}
        assert await session.scalar(select(ShareArtifactRow).where(ShareArtifactRow.share_id == expired["share_id"])) is None
        assert (await session.get(ThreadMetaRow, "source")).incarnation == "original"
