"""Integration test: two ChannelManagers share one Postgres dedupe table.

Mirrors ``test_multi_worker_run_ownership.py``'s "two managers sharing a DB"
pattern. Skipped unless a real Postgres backend is configured via
``DEDUPE_TEST_POSTGRES_URL`` (the dev container runs sqlite), so it only runs
where cross-pod dedupe actually matters — CI with Postgres, or a local run with
a throwaway Postgres. See issue #4120.
"""

from __future__ import annotations

import os
import uuid
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import pytest
import pytest_asyncio

from app.channels.dedupe_store import INBOUND_DEDUPE_TTL_SECONDS, PostgresInboundDedupeStore

POSTGRES_URL = os.environ.get("DEDUPE_TEST_POSTGRES_URL")

# libpq/psycopg-only query parameters that asyncpg's ``connect()`` rejects. CI
# hands over ``TEST_POSTGRES_URI`` as ``postgresql://...?sslmode=disable``; left
# in place these raise ``TypeError: connect() got an unexpected keyword argument
# 'sslmode'`` once the URL is routed to the asyncpg driver, so strip them here.
_LIBPQ_ONLY_QUERY_KEYS = {"sslmode", "channel_binding"}


def _asyncpg_url(url: str | None) -> str | None:
    """Normalize a sync ``postgresql://`` URL to the async driver SQLAlchemy needs.

    ``init_engine`` builds an *async* engine, so a bare ``postgresql://`` would fall
    back to the synchronous psycopg2 driver and fail. Accept either form so the test
    runs whether CI hands over ``TEST_POSTGRES_URI`` (``postgresql://...``) or a
    caller passes ``postgresql+asyncpg://...`` directly. libpq-only query params
    (e.g. ``sslmode``) are dropped because asyncpg does not understand them.
    """
    if not url:
        return url
    if url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://") :]
    parts = urlsplit(url)
    if parts.query:
        kept = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k not in _LIBPQ_ONLY_QUERY_KEYS]
        url = urlunsplit(parts._replace(query=urlencode(kept)))
    return url


pytestmark = pytest.mark.skipif(
    not POSTGRES_URL,
    reason="requires DEDUPE_TEST_POSTGRES_URL (real Postgres for cross-pod dedupe)",
)


@pytest_asyncio.fixture(autouse=True)
async def _postgres_engine():
    """Initialize the Postgres engine within the test's event loop.

    Doing this inside the loop (not at import time) avoids the "connection
    attached to a different loop" error that arises when the engine is built in
    a loop that pytest-asyncio later closes.
    """
    from deerflow.persistence.engine import close_engine, init_engine

    await init_engine("postgres", url=_asyncpg_url(POSTGRES_URL))
    try:
        yield
    finally:
        await close_engine()


@pytest.mark.asyncio
async def test_two_stores_share_dedupe_state_across_pods():
    from deerflow.persistence.base import Base
    from deerflow.persistence.engine import get_engine, get_session_factory
    from deerflow.persistence.webhook_delivery.model import WebhookDeliveryRow

    engine = get_engine()
    sf = get_session_factory()
    # Ensure the table exists regardless of whether the alembic migration ran.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=[WebhookDeliveryRow.__table__], checkfirst=True)

    store_a = PostgresInboundDedupeStore(session_factory=sf)
    store_b = PostgresInboundDedupeStore(session_factory=sf)
    unique = uuid.uuid4().hex
    key = ("github", "repo", "repo", f"d-{unique}:uA:agentX")
    claim = None
    try:
        # First pod records the delivery and proceeds.
        claim = await store_a.try_record(key)
        assert claim is not None
        # A redelivery landing on the second pod hits the same table -> duplicate.
        assert await store_b.try_record(key) is None
    finally:
        if claim is not None:
            await store_a.release(claim)


@pytest.mark.asyncio
async def test_manager_injects_shared_store_and_dedupes_cross_pod():
    """End-to-end: two ChannelManagers wired to the *same* Postgres store drop a
    redelivery routed to the second manager, exactly as the production dispatch
    loop would (``if await self._is_duplicate_inbound(msg): continue``)."""
    from app.channels.manager import ChannelManager
    from app.channels.message_bus import InboundMessage, MessageBus
    from app.channels.store import JsonChannelStore
    from deerflow.persistence.engine import get_session_factory

    sf = get_session_factory()
    shared_store = PostgresInboundDedupeStore(session_factory=sf)
    manager_a = ChannelManager(bus=MessageBus(), store=JsonChannelStore(), inbound_dedupe_store=shared_store)
    manager_b = ChannelManager(bus=MessageBus(), store=JsonChannelStore(), inbound_dedupe_store=shared_store)

    msg = InboundMessage(
        channel_name="github",
        chat_id="repo",
        user_id="alice",
        text="@bot review",
        topic_id="7:agent",
        workspace_id="repo",
        metadata={"message_id": "d-crosspod:agent"},
    )
    try:
        # First manager records the delivery and lets it through.
        assert await manager_a._is_duplicate_inbound(msg) is False
        # Same redelivery on the second manager hits the shared table -> dropped.
        assert await manager_b._is_duplicate_inbound(msg) is True
    finally:
        await manager_a._release_inbound_dedupe_key(msg)


@pytest.mark.asyncio
async def test_expired_unreleased_row_is_reclaimed_on_next_redelivery():
    """P1 end-to-end: a row past the TTL that was never released must be
    reclaimed so the next redelivery is re-admitted (not dropped forever)."""
    from sqlalchemy import text

    from deerflow.persistence.base import Base
    from deerflow.persistence.engine import get_engine, get_session_factory
    from deerflow.persistence.webhook_delivery.model import WebhookDeliveryRow

    engine = get_engine()
    sf = get_session_factory()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=[WebhookDeliveryRow.__table__], checkfirst=True)

    store = PostgresInboundDedupeStore(session_factory=sf)
    unique = uuid.uuid4().hex
    channel, workspace_id, chat_id, message_id = ("github", "repo", "repo", f"d-{unique}:expired")
    key = (channel, workspace_id, chat_id, message_id)
    claim = None
    try:
        # Seed an already-expired, unreleased row for this key.
        async with sf() as session:
            async with session.begin():
                await session.execute(
                    text("INSERT INTO webhook_deliveries (channel, workspace_id, chat_id, message_id, first_seen) VALUES (:c, :w, :ch, :m, now() - make_interval(secs => :age))"),
                    {"c": channel, "w": workspace_id, "ch": chat_id, "m": message_id, "age": INBOUND_DEDUPE_TTL_SECONDS + 1},
                )
        # The expired row is reclaimed -> redelivery re-admitted (not a duplicate).
        claim = await store.try_record(key)
        assert claim is not None
        # Its first_seen is refreshed to ~now (well within the TTL).
        async with sf() as session:
            row = (
                await session.execute(
                    text("SELECT (now() - first_seen) < make_interval(secs => :ttl) AS fresh FROM webhook_deliveries WHERE channel = :c AND workspace_id = :w AND chat_id = :ch AND message_id = :m"),
                    {"c": channel, "w": workspace_id, "ch": chat_id, "m": message_id, "ttl": INBOUND_DEDUPE_TTL_SECONDS},
                )
            ).fetchone()
        assert row is not None and row[0] is True
    finally:
        if claim is not None:
            await store.release(claim)


@pytest.mark.asyncio
@pytest.mark.parametrize("retirement", ["expired", "released", "outage"])
async def test_old_manager_cannot_release_another_pods_claim(tmp_path, retirement):
    """Retired admissions and recovered fail-open attempts require scoped cleanup."""
    from unittest.mock import MagicMock

    from sqlalchemy import text

    from app.channels.manager import ChannelManager
    from app.channels.message_bus import InboundMessage, MessageBus
    from app.channels.store import JsonChannelStore
    from deerflow.persistence.base import Base
    from deerflow.persistence.engine import get_engine, get_session_factory
    from deerflow.persistence.webhook_delivery.model import WebhookDeliveryRow

    sf = get_session_factory()
    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=[WebhookDeliveryRow.__table__], checkfirst=True)
    store_a = PostgresInboundDedupeStore(session_factory=MagicMock(side_effect=RuntimeError("controlled storage outage")) if retirement == "outage" else sf)
    store_b = PostgresInboundDedupeStore(session_factory=sf)
    manager_a = ChannelManager(bus=MessageBus(), store=JsonChannelStore(path=tmp_path / "a.json"), inbound_dedupe_store=store_a)
    manager_b = ChannelManager(bus=MessageBus(), store=JsonChannelStore(path=tmp_path / "b.json"), inbound_dedupe_store=store_b)
    message_id = f"claim-{uuid.uuid4().hex}"
    params = {"c": "slack", "w": "T1", "ch": "C1", "m": message_id}
    predicate = "channel = :c AND workspace_id = :w AND chat_id = :ch AND message_id = :m"

    def message():
        return InboundMessage(channel_name="slack", chat_id="C1", user_id="U1", text="same provider payload", workspace_id="T1", metadata={"message_id": message_id})

    async def stored_row():
        async with sf() as session:
            return (await session.execute(text(f"SELECT * FROM webhook_deliveries WHERE {predicate}"), params)).one_or_none()

    old, replacement = message(), message()
    try:
        assert await manager_a._is_duplicate_inbound(old) is False
        if retirement == "expired":
            async with sf() as session:
                async with session.begin():
                    await session.execute(
                        text(f"UPDATE webhook_deliveries SET first_seen = now() - make_interval(secs => :age) WHERE {predicate}"),
                        {**params, "age": INBOUND_DEDUPE_TTL_SECONDS + 1},
                    )
        elif retirement == "released":
            await manager_a._release_inbound_dedupe_key(old)
            assert await stored_row() is None
        else:
            assert await stored_row() is None
            # The old manager's DB recovers before its later failure cleanup.
            store_a._session_factory = sf

        assert await manager_b._is_duplicate_inbound(replacement) is False
        replacement_row = await stored_row()
        assert replacement_row is not None
        await manager_a._release_inbound_dedupe_key(old)
        assert await stored_row() == replacement_row
        assert await manager_b._is_duplicate_inbound(message()) is True

        # Repeating retired cleanup must remain harmless, while the current
        # claimant must still be able to make an ordinary failure retryable.
        await manager_a._release_inbound_dedupe_key(old)
        assert await stored_row() == replacement_row
        await manager_b._release_inbound_dedupe_key(replacement)
        assert await stored_row() is None
        assert await manager_b._is_duplicate_inbound(message()) is False
    finally:
        async with sf() as session:
            async with session.begin():
                await session.execute(text(f"DELETE FROM webhook_deliveries WHERE {predicate}"), params)
