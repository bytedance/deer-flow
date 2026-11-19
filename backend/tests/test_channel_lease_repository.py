"""``channel_leases`` repository: the per-provider IM leader lease shared by every Gateway instance.

Each case runs on SQLite and, when ``TEST_POSTGRES_URI`` is set, on PostgreSQL
in a throwaway schema. Expiry is staged by writing ``lease_expires_at``
relative to the database clock (``db_now``) instead of sleeping, so the cases
are deterministic and exercise the same clock the repository decides with.
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from support.postgres import asyncpg_test_url

from deerflow.persistence.base import Base
from deerflow.persistence.channel_leases import ChannelLeaseRow, SqlChannelLeaseRepository, db_now
from deerflow.persistence.postgres_schema import build_asyncpg_connect_args

pytestmark = pytest.mark.asyncio

TTL = 30.0
GRACE = 10.0


@dataclass
class Database:
    dialect: str
    engines: list[AsyncEngine]

    def repo(self, index: int = 0) -> SqlChannelLeaseRepository:
        return SqlChannelLeaseRepository(async_sessionmaker(self.engines[index], expire_on_commit=False))

    async def set_expiry(self, provider: str, *, seconds_from_now: float) -> None:
        """Move the row's expiry relative to the database clock."""
        async with self.engines[0].begin() as conn:
            await conn.execute(sa.update(ChannelLeaseRow).where(ChannelLeaseRow.provider == provider).values(lease_expires_at=db_now(self.dialect) + seconds_from_now))


@pytest_asyncio.fixture(params=["sqlite", "postgres"])
async def db(request, tmp_path) -> AsyncIterator[Database]:
    """Two engines over one database: two Gateway instances sharing the table."""
    if request.param == "sqlite":
        url = f"sqlite+aiosqlite:///{(tmp_path / 'leases.db').as_posix()}"
        engines = [create_async_engine(url) for _ in range(2)]
        async with engines[0].begin() as conn:
            await conn.run_sync(Base.metadata.create_all, tables=[ChannelLeaseRow.__table__])
        try:
            yield Database("sqlite", engines)
        finally:
            for engine in engines:
                await engine.dispose()
        return

    uri = os.environ.get("TEST_POSTGRES_URI")
    if not uri:
        pytest.skip("requires TEST_POSTGRES_URI (channel_leases on PostgreSQL)")
    schema = f"channel_leases_{uuid.uuid4().hex}"
    engines = [create_async_engine(asyncpg_test_url(uri), connect_args=build_asyncpg_connect_args(schema)) for _ in range(2)]
    try:
        async with engines[0].begin() as conn:
            await conn.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
            await conn.run_sync(Base.metadata.create_all, tables=[ChannelLeaseRow.__table__])
        yield Database("postgresql", engines)
    finally:
        async with engines[0].begin() as conn:
            await conn.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        for engine in engines:
            await engine.dispose()


async def test_db_now_reads_epoch_seconds(db):
    """The clock expression is in seconds since the epoch, not days or a timestamp string."""
    async with db.engines[0].connect() as conn:
        value = (await conn.execute(sa.select(db_now(db.dialect)))).scalar_one()
    assert abs(float(value) - time.time()) < 60


async def test_first_acquire_creates_the_row_and_a_peer_is_refused_while_it_is_live(db):
    a, b = db.repo(0), db.repo(1)

    grant = await a.acquire("telegram", "A", ttl_seconds=TTL, grace_seconds=GRACE)
    assert grant is not None and grant.epoch == 1
    assert await b.acquire("telegram", "B", ttl_seconds=TTL, grace_seconds=GRACE) is None

    state = await b.get("telegram")
    assert (state.owner_id, state.epoch, state.live, state.transport_running) == ("A", 1, True, False)
    # Providers are independent rows.
    assert (await b.acquire("discord", "B", ttl_seconds=TTL, grace_seconds=GRACE)).epoch == 1
    assert [s.provider for s in await a.list_all()] == ["discord", "telegram"]


async def test_renew_extends_only_the_holders_epoch_and_reports_the_transport(db):
    a = db.repo(0)
    grant = await a.acquire("telegram", "A", ttl_seconds=TTL, grace_seconds=GRACE)

    assert await a.renew("telegram", "A", grant.epoch, ttl_seconds=TTL, transport_running=True) is True
    assert (await a.get("telegram")).transport_running is True
    # Another owner, or the right owner at a stale epoch, cannot renew.
    assert await a.renew("telegram", "B", grant.epoch, ttl_seconds=TTL, transport_running=True) is False
    assert await a.renew("telegram", "A", grant.epoch + 1, ttl_seconds=TTL, transport_running=True) is False
    assert await a.renew("slack", "A", 1, ttl_seconds=TTL, transport_running=True) is False


async def test_an_expired_lease_is_not_revived_by_renewal(db):
    """Renewal only extends a live lease; a lapsed holder must re-acquire (and bump the epoch)."""
    a = db.repo(0)
    grant = await a.acquire("telegram", "A", ttl_seconds=TTL, grace_seconds=GRACE)
    await db.set_expiry("telegram", seconds_from_now=-1)

    assert await a.renew("telegram", "A", grant.epoch, ttl_seconds=TTL, transport_running=True) is False
    again = await a.acquire("telegram", "A", ttl_seconds=TTL, grace_seconds=GRACE)
    assert again is not None and again.epoch == grant.epoch + 1


async def test_a_peer_takes_an_expired_lease_only_after_the_grace_period(db):
    a, b = db.repo(0), db.repo(1)
    first = await a.acquire("telegram", "A", ttl_seconds=TTL, grace_seconds=GRACE)

    await db.set_expiry("telegram", seconds_from_now=-(GRACE - 2))  # expired, still inside the grace window
    assert await b.acquire("telegram", "B", ttl_seconds=TTL, grace_seconds=GRACE) is None
    assert (await b.get("telegram")).live is False

    await db.set_expiry("telegram", seconds_from_now=-(GRACE + 2))
    taken = await b.acquire("telegram", "B", ttl_seconds=TTL, grace_seconds=GRACE)
    assert taken is not None and taken.epoch == first.epoch + 1
    # The previous holder is fenced out of the new epoch.
    assert await a.renew("telegram", "A", first.epoch, ttl_seconds=TTL, transport_running=True) is False
    assert await a.release("telegram", "A", first.epoch) is False
    assert (await a.get("telegram")).owner_id == "B"


async def test_the_holder_reacquiring_bumps_the_epoch_and_fences_its_old_one(db):
    a = db.repo(0)
    first = await a.acquire("telegram", "A", ttl_seconds=TTL, grace_seconds=GRACE)
    second = await a.acquire("telegram", "A", ttl_seconds=TTL, grace_seconds=GRACE)

    assert second.epoch == first.epoch + 1
    assert await a.renew("telegram", "A", first.epoch, ttl_seconds=TTL, transport_running=False) is False
    assert await a.renew("telegram", "A", second.epoch, ttl_seconds=TTL, transport_running=False) is True


async def test_release_hands_the_lease_over_at_once(db):
    a, b = db.repo(0), db.repo(1)
    grant = await a.acquire("telegram", "A", ttl_seconds=TTL, grace_seconds=GRACE)
    await a.renew("telegram", "A", grant.epoch, ttl_seconds=TTL, transport_running=True)

    assert await a.release("telegram", "A", grant.epoch) is True
    state = await b.get("telegram")
    assert (state.live, state.transport_running) == (False, False)
    # No waiting out lease + grace after a release.
    taken = await b.acquire("telegram", "B", ttl_seconds=TTL, grace_seconds=GRACE)
    assert taken is not None and taken.epoch == grant.epoch + 1
    # A second release at the old epoch cannot undo the new holder's lease.
    assert await a.release("telegram", "A", grant.epoch) is False
    assert (await b.get("telegram")).live is True


async def test_racing_instances_get_exactly_one_grant(db):
    """Concurrent first acquisitions (an empty table) and takeovers both have a single winner."""
    repos = [db.repo(i % 2) for i in range(8)]

    grants = await asyncio.gather(*(repo.acquire("discord", f"owner-{i}", ttl_seconds=TTL, grace_seconds=GRACE) for i, repo in enumerate(repos)))
    winners = [i for i, grant in enumerate(grants) if grant is not None]
    assert len(winners) == 1
    assert (await repos[0].get("discord")).owner_id == f"owner-{winners[0]}"

    await db.set_expiry("discord", seconds_from_now=-(GRACE + 5))
    grants = await asyncio.gather(*(repo.acquire("discord", f"next-{i}", ttl_seconds=TTL, grace_seconds=GRACE) for i, repo in enumerate(repos)))
    assert len([grant for grant in grants if grant is not None]) == 1
    assert (await repos[0].get("discord")).epoch == 2


async def test_writes_do_not_trust_returning_rows_under_a_concurrent_read(tmp_path):
    """Review follow-up on #6843: the supervisor reads the whole table while it renews.

    Through SQLAlchemy's aiosqlite adapter, an ``UPDATE ... RETURNING`` running
    while another connection reads the table intermittently handed back one of
    its own bind values (the provider name) instead of ``lease_expires_at``, on
    fresh engines in roughly a third of the rounds. Renew, release and acquire
    therefore decide by affected-row count; every round here must confirm both
    renewals and leave real numbers in the row.
    """
    for scenario in range(12):
        url = f"sqlite+aiosqlite:///{(tmp_path / f'leases-{scenario}.db').as_posix()}"
        engine = create_async_engine(url)
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all, tables=[ChannelLeaseRow.__table__])
            repo = SqlChannelLeaseRepository(async_sessionmaker(engine, expire_on_commit=False))
            grants = {provider: await repo.acquire(provider, "A", ttl_seconds=TTL, grace_seconds=GRACE) for provider in ("discord", "telegram")}
            for _ in range(2):
                read, *renewed = await asyncio.gather(
                    repo.list_all(),
                    repo.renew("discord", "A", grants["discord"].epoch, ttl_seconds=TTL, transport_running=False),
                    repo.renew("telegram", "A", grants["telegram"].epoch, ttl_seconds=TTL, transport_running=True),
                )
                assert renewed == [True, True]
                assert {state.provider for state in read} == {"discord", "telegram"}
            async with engine.connect() as conn:
                kinds = (await conn.execute(sa.text("SELECT typeof(lease_expires_at), typeof(updated_at) FROM channel_leases"))).all()
            assert set(kinds) == {("real", "real")}
        finally:
            await engine.dispose()
