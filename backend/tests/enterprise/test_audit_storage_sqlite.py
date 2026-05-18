"""Tests for SQLite audit storage (plan M2-2).

We spin up a real ``sqlite+aiosqlite`` engine per test and create the
``audit_events`` table via ``Base.metadata.create_all`` rather than
running Alembic — the migration is covered separately and we want
these tests to stay independent of the Alembic environment.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from deerflow.enterprise.audit.events import AuditEvent, AuditEventType
from deerflow.enterprise.audit.signer import AuditSigner
from deerflow.enterprise.audit.storage import (
    AuditQueryFilter,
    SqliteAuditStorage,
)
from deerflow.persistence.base import Base


@pytest_asyncio.fixture
async def storage(tmp_path) -> SqliteAuditStorage:
    """Fresh SQLite audit storage with the ``audit_events`` table created."""
    url = f"sqlite+aiosqlite:///{tmp_path / 'audit.db'}"
    engine = create_async_engine(url)
    # Import the ORM model so it registers on Base.metadata before create_all.
    from deerflow.enterprise.audit.storage import AuditEventRow  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sf = async_sessionmaker(engine, expire_on_commit=False)
    yield SqliteAuditStorage(sf)
    await engine.dispose()


def _make_event(**overrides) -> AuditEvent:
    base = {
        "event_type": AuditEventType.AGENT_TASK_STARTED,
        "user_id": "alice",
        "resource": "thread:abc",
        "action": "agent.start",
        "details": {"k": "v"},
    }
    base.update(overrides)
    return AuditEvent(**base)


@pytest.mark.asyncio
async def test_append_and_query_round_trip(storage: SqliteAuditStorage):
    """A round-trip preserves every field, including ``details`` JSON."""
    event = _make_event()
    await storage.append(event)
    rows = await storage.query(AuditQueryFilter(limit=10))
    assert len(rows) == 1
    got = rows[0]
    assert got.id == event.id
    assert got.event_type == event.event_type
    assert got.user_id == event.user_id
    assert got.details == event.details


@pytest.mark.asyncio
async def test_query_filters_by_user(storage: SqliteAuditStorage):
    """``user_id`` filter is honoured and ignores other users."""
    await storage.append(_make_event(user_id="alice"))
    await storage.append(_make_event(user_id="bob"))
    rows = await storage.query(AuditQueryFilter(user_id="bob", limit=10))
    assert [r.user_id for r in rows] == ["bob"]


@pytest.mark.asyncio
async def test_query_filters_by_event_type(storage: SqliteAuditStorage):
    """``event_type`` filter narrows by canonical wire value."""
    await storage.append(_make_event(event_type=AuditEventType.AGENT_TASK_STARTED))
    await storage.append(_make_event(event_type=AuditEventType.DATA_EXPORTED))
    rows = await storage.query(AuditQueryFilter(event_type=AuditEventType.DATA_EXPORTED, limit=10))
    assert {r.event_type for r in rows} == {AuditEventType.DATA_EXPORTED}


@pytest.mark.asyncio
async def test_query_filters_by_timerange(storage: SqliteAuditStorage):
    """``since`` / ``until`` clip the result set inclusively."""
    now = datetime.now(timezone.utc)
    old = _make_event(timestamp=now - timedelta(days=2))
    fresh = _make_event(timestamp=now)
    await storage.append(old)
    await storage.append(fresh)
    rows = await storage.query(AuditQueryFilter(since=now - timedelta(hours=1), limit=10))
    assert {r.id for r in rows} == {fresh.id}


@pytest.mark.asyncio
async def test_query_orders_newest_first(storage: SqliteAuditStorage):
    """Default ordering returns the newest row first."""
    now = datetime.now(timezone.utc)
    older = _make_event(timestamp=now - timedelta(hours=1))
    newer = _make_event(timestamp=now)
    await storage.append(older)
    await storage.append(newer)
    rows = await storage.query(AuditQueryFilter(limit=10))
    assert [r.id for r in rows] == [newer.id, older.id]


@pytest.mark.asyncio
async def test_count_ignores_limit_and_offset(storage: SqliteAuditStorage):
    """``count`` returns the true filter cardinality regardless of paging."""
    for _ in range(5):
        await storage.append(_make_event())
    assert await storage.count(AuditQueryFilter(limit=1, offset=4)) == 5


@pytest.mark.asyncio
async def test_append_batch_writes_all_events(storage: SqliteAuditStorage):
    """The default fallback bulk path actually persists every event."""
    events = [_make_event() for _ in range(3)]
    await storage.append_batch(events)
    assert await storage.count(AuditQueryFilter(limit=1)) == 3


@pytest.mark.asyncio
async def test_verify_integrity_detects_tamper(storage: SqliteAuditStorage):
    """A row whose details we mutate post-signing flips verify_integrity to False."""
    signer = AuditSigner("k")
    event = _make_event()
    event.signature = signer.sign(event)
    await storage.append(event)
    assert await storage.verify_integrity(signer) is True

    # Manually corrupt the row by writing a second event with the same id
    # and a different details payload but the original signature.
    bad = _make_event(id=event.id, details={"k": "tampered"}, timestamp=event.timestamp)
    bad.signature = event.signature
    # Direct row mutation: bypass append to simulate tampering at the
    # DB layer (operator with raw SQL access).
    from deerflow.enterprise.audit.storage import _event_to_row

    async with storage._sf() as session:
        await session.merge(_event_to_row(bad))
        await session.commit()

    assert await storage.verify_integrity(signer) is False


@pytest.mark.asyncio
async def test_unknown_event_type_in_row_does_not_crash(storage: SqliteAuditStorage):
    """A row with an unknown ``event_type`` is coerced, not dropped."""
    from deerflow.enterprise.audit.storage import AuditEventRow

    async with storage._sf() as session:
        session.add(
            AuditEventRow(
                id="legacy-row",
                event_type="some.future.event",
                timestamp=datetime.now(timezone.utc),
                user_id="x",
                resource=None,
                action=None,
                details="{}",
                signature=None,
            ),
        )
        await session.commit()
    rows = await storage.query(AuditQueryFilter(limit=10))
    assert any(r.id == "legacy-row" for r in rows)
