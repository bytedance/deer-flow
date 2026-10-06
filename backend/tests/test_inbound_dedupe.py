"""Unit tests for the inbound dedupe store (issue #4120).

Covers config resolution (memory / postgres / auto), the multi-worker
misconfiguration WARNING, and the Postgres store's atomic insert / fail-open
behavior with a mocked session factory.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.channels.dedupe_store import (
    MemoryInboundDedupeStore,
    PostgresInboundDedupeStore,
    make_inbound_dedupe_store,
)


@pytest.fixture(autouse=True)
def isolated_worker_env(monkeypatch):
    """Keep config-resolution tests independent of the invoking shell.

    ``WEB_CONCURRENCY`` is a common ambient convention on uvicorn/gunicorn/PaaS hosts,
    and it now decides whether a deployment counts as multi-worker here too. The tests
    that exercise that path set the spelling they mean to exercise.
    """
    monkeypatch.delenv("GATEWAY_WORKERS", raising=False)
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    monkeypatch.delenv("DEER_FLOW_MULTI_INSTANCE", raising=False)


class _FakeDedupe:
    def __init__(self, backend: str) -> None:
        self.backend = backend  # plain string, mimics DedupeStorageBackend.value


class _FakeDb:
    def __init__(self, backend: str) -> None:
        self.backend = backend


class _FakeApp:
    def __init__(self, dedupe: str, db: str) -> None:
        self.dedupe_storage = _FakeDedupe(dedupe)
        self.database = _FakeDb(db)


def test_factory_default_is_memory():
    assert isinstance(make_inbound_dedupe_store(None), MemoryInboundDedupeStore)


def test_factory_explicit_memory_is_memory():
    app = _FakeApp("memory", "sqlite")
    assert isinstance(make_inbound_dedupe_store(app), MemoryInboundDedupeStore)


def test_factory_auto_with_sqlite_resolves_memory():
    app = _FakeApp("auto", "sqlite")
    assert isinstance(make_inbound_dedupe_store(app), MemoryInboundDedupeStore)


def test_factory_auto_with_postgres_and_multi_worker_resolves_postgres_store(monkeypatch):
    # 'auto' shares Postgres state whenever the DB is Postgres, even with a single
    # worker: the common K8s case is N pods x 1 worker sharing one DB, and gating on
    # the in-pod worker count would silently disable cross-pod dedupe there. See the
    # sibling ..._regardless_of_workers test for the documented behavior.
    monkeypatch.setenv("GATEWAY_WORKERS", "2")
    app = _FakeApp("auto", "postgres")
    assert isinstance(make_inbound_dedupe_store(app), PostgresInboundDedupeStore)


def test_factory_auto_with_postgres_resolves_postgres_store_regardless_of_workers():
    # 'auto' shares Postgres dedupe state whenever the DB is Postgres, including
    # the common Kubernetes case of many replicas each running a single worker
    # (GATEWAY_WORKERS=1) that still share one Postgres DB. Cross-pod dedupe must
    # not depend on the in-pod worker count (issue #4120).
    app = _FakeApp("auto", "postgres")
    assert isinstance(make_inbound_dedupe_store(app), PostgresInboundDedupeStore)


def test_factory_explicit_postgres_resolves_postgres_store():
    app = _FakeApp("postgres", "postgres")
    assert isinstance(make_inbound_dedupe_store(app), PostgresInboundDedupeStore)


def test_factory_explicit_postgres_without_postgres_db_falls_back_to_memory_and_warns(monkeypatch, caplog):
    import logging

    # Explicit 'postgres' but the application DB is not Postgres: must warn and
    # fall back to the in-process store rather than silently disabling dedupe.
    app = _FakeApp("postgres", "sqlite")
    with caplog.at_level(logging.WARNING):
        store = make_inbound_dedupe_store(app)
    assert isinstance(store, MemoryInboundDedupeStore)
    assert any("dedupe_storage=postgres requires database.backend='postgres'" in r.message for r in caplog.records)


def test_factory_warns_when_memory_explicit_under_multi_worker(monkeypatch, caplog):
    import logging

    monkeypatch.setenv("GATEWAY_WORKERS", "2")
    app = _FakeApp("memory", "sqlite")
    with caplog.at_level(logging.WARNING):
        store = make_inbound_dedupe_store(app)
    assert isinstance(store, MemoryInboundDedupeStore)
    assert any("dedupe_storage=memory with GATEWAY_WORKERS>1" in r.message for r in caplog.records)


def test_factory_warns_when_memory_explicit_under_a_declared_multi_instance_deployment(monkeypatch, caplog):
    """Kubernetes replicas run one worker each and declare their peers instead of a worker count."""
    import logging

    monkeypatch.setenv("DEER_FLOW_MULTI_INSTANCE", "1")
    app = _FakeApp("memory", "sqlite")
    with caplog.at_level(logging.WARNING):
        store = make_inbound_dedupe_store(app)
    assert isinstance(store, MemoryInboundDedupeStore)
    assert any("dedupe_storage=memory with DEER_FLOW_MULTI_INSTANCE=1" in r.message for r in caplog.records)


def test_factory_warns_when_auto_resolves_memory_under_a_declared_multi_instance_deployment(monkeypatch, caplog):
    import logging

    monkeypatch.setenv("DEER_FLOW_MULTI_INSTANCE", "true")
    app = _FakeApp("auto", "sqlite")
    with caplog.at_level(logging.WARNING):
        store = make_inbound_dedupe_store(app)
    assert isinstance(store, MemoryInboundDedupeStore)
    assert any("Multi-worker deployment detected but dedupe_storage=auto" in r.message for r in caplog.records)


def test_factory_warns_when_auto_resolves_memory_under_multi_worker(monkeypatch, caplog):
    import logging

    monkeypatch.setenv("GATEWAY_WORKERS", "2")
    app = _FakeApp("auto", "sqlite")
    with caplog.at_level(logging.WARNING):
        store = make_inbound_dedupe_store(app)
    assert isinstance(store, MemoryInboundDedupeStore)
    assert any("Multi-worker deployment detected but dedupe_storage=auto" in r.message for r in caplog.records)


def test_factory_warns_under_the_uvicorn_worker_fallback(monkeypatch, caplog):
    import logging

    # backend/Dockerfile and scripts/serve.sh start uvicorn with no --workers, so
    # WEB_CONCURRENCY is what decides how many processes share no dedupe state.
    monkeypatch.delenv("GATEWAY_WORKERS", raising=False)
    monkeypatch.setenv("WEB_CONCURRENCY", "2")
    app = _FakeApp("memory", "sqlite")
    with caplog.at_level(logging.WARNING):
        store = make_inbound_dedupe_store(app)
    assert isinstance(store, MemoryInboundDedupeStore)
    assert any("dedupe_storage=memory with WEB_CONCURRENCY>1" in r.message for r in caplog.records)


def test_factory_warns_when_an_unparsable_knob_hides_the_fallback_count(monkeypatch, caplog):
    import logging

    # GATEWAY_WORKERS never reaches uvicorn on the launchers that pass no --workers, so
    # an unusable value there must not report the deployment as single-worker while
    # WEB_CONCURRENCY still starts the processes.
    monkeypatch.setenv("GATEWAY_WORKERS", "abc")
    monkeypatch.setenv("WEB_CONCURRENCY", "4")
    app = _FakeApp("memory", "sqlite")
    with caplog.at_level(logging.WARNING):
        make_inbound_dedupe_store(app)
    assert any("dedupe_storage=memory with WEB_CONCURRENCY>1" in r.message for r in caplog.records)


def test_factory_prefers_the_documented_knob_when_both_are_set(monkeypatch, caplog):
    import logging

    # docker-compose forwards GATEWAY_WORKERS as --workers, which outranks the
    # WEB_CONCURRENCY uvicorn would otherwise read.
    monkeypatch.setenv("GATEWAY_WORKERS", "1")
    monkeypatch.setenv("WEB_CONCURRENCY", "4")
    app = _FakeApp("memory", "sqlite")
    with caplog.at_level(logging.WARNING):
        make_inbound_dedupe_store(app)
    assert not any("dedupe_storage=memory with" in r.message for r in caplog.records)


def test_factory_treats_a_blank_gateway_workers_as_unset(monkeypatch, caplog):
    import logging

    # The compose command spells the fallback ${GATEWAY_WORKERS:-1}, so an exported
    # empty value means "unset" rather than "no workers".
    monkeypatch.setenv("GATEWAY_WORKERS", "   ")
    monkeypatch.setenv("WEB_CONCURRENCY", "3")
    app = _FakeApp("auto", "sqlite")
    with caplog.at_level(logging.WARNING):
        make_inbound_dedupe_store(app)
    assert any("Multi-worker deployment detected" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# PostgresInboundDedupeStore (unit, mocked session factory)
# ---------------------------------------------------------------------------


def _fake_session_factory(*, insert_rowcount: int = 1, execute_raises: BaseException | None = None):
    """Build a fake async session factory whose single session returns the
    given upsert result (fetchone -> a row when admitted, None on live conflict)
    or raises for ``execute``.

    ``try_record`` issues up to two executes: (0) the conditional upsert
    ``INSERT ... ON CONFLICT DO UPDATE ... RETURNING`` (admitted -> row returned)
    and, only when admitted, (1) the cross-table lazy cleanup ``DELETE``. On a
    live conflict only the upsert runs (no row returned -> no cleanup).
    """
    insert_result = MagicMock()
    insert_result.rowcount = insert_rowcount
    # A truthy fetchone means the key was admitted (new delivery or an expired row
    # re-admitted); None means a live conflict (duplicate). Mirrors the RETURNING
    # channel contract.
    insert_result.fetchone.return_value = ("c",)
    session = AsyncMock()
    if execute_raises is not None:
        session.execute = AsyncMock(side_effect=execute_raises)
    else:
        session.execute = AsyncMock(
            side_effect=[
                insert_result,  # conditional upsert result (fetchone -> row when admitted)
                MagicMock(),  # lazy cleanup DELETE result (only when admitted)
            ]
        )
    begin_cm = AsyncMock()
    begin_cm.__aenter__ = AsyncMock(return_value=None)
    begin_cm.__aexit__ = AsyncMock(return_value=False)
    session.begin = MagicMock(return_value=begin_cm)

    factory_cm = AsyncMock()
    factory_cm.__aenter__ = AsyncMock(return_value=session)
    factory_cm.__aexit__ = AsyncMock(return_value=False)
    factory = MagicMock()
    factory.return_value = factory_cm
    return factory, session


@pytest.mark.asyncio
async def test_postgres_try_record_new_then_conflict():
    factory, session = _fake_session_factory(insert_rowcount=1)
    store = PostgresInboundDedupeStore(session_factory=factory)
    key = ("github", "repo", "repo", "d1:uA:agentX")
    # First delivery is inserted -> proceed (not a duplicate).
    assert await store.try_record(key) is False
    # Redelivery (same key) on a still-live row: ON CONFLICT -> DO UPDATE WHERE
    # fails -> no row returned -> duplicate -> drop. Only the upsert runs.
    session.execute.side_effect = [MagicMock(fetchone=MagicMock(return_value=None))]
    assert await store.try_record(key) is True


@pytest.mark.asyncio
async def test_postgres_try_record_uses_atomic_on_conflict_and_lazy_cleanup():
    factory, session = _fake_session_factory()
    store = PostgresInboundDedupeStore(session_factory=factory)
    await store.try_record(("slack", "T1", "C1", "123.456"))
    # call 0: conditional upsert (INSERT ... ON CONFLICT DO UPDATE ... WHERE TTL);
    # call 1: lazy cross-table cleanup (only on admit).
    upsert_sql = session.execute.call_args_list[0].args[0].text
    cleanup_sql = session.execute.call_args_list[1].args[0].text
    assert "ON CONFLICT" in upsert_sql
    assert "DO UPDATE SET first_seen = now()" in upsert_sql
    assert "first_seen < now()" in upsert_sql  # TTL reclamation condition
    assert "RETURNING" in upsert_sql
    assert "make_interval" in cleanup_sql


@pytest.mark.asyncio
async def test_postgres_try_record_reclaims_expired_unreleased_row():
    # Reproduces the P1 defect: a key's row has passed the TTL but was never
    # released (e.g. a crashed run). With the conditional upsert, the conflict
    # fires DO UPDATE (WHERE first_seen < TTL is true), refreshes first_seen and
    # RETURNS the row, so the redelivery is re-admitted (proceed, not dropped).
    factory, session = _fake_session_factory()
    store = PostgresInboundDedupeStore(session_factory=factory)
    key = ("slack", "T1", "C1", "123.456")
    # The upsert result returns a row, meaning the expired row was re-admitted
    # (proceed, not a duplicate).
    assert await store.try_record(key) is False

    upsert_sql = session.execute.call_args_list[0].args[0].text
    # The reclaim is part of the atomic upsert: a conditional DO UPDATE gated on
    # the TTL, not a separate PK-scoped DELETE.
    assert "ON CONFLICT" in upsert_sql
    assert "DO UPDATE SET first_seen = now()" in upsert_sql
    assert "first_seen < now() - make_interval" in upsert_sql
    # Exactly two executes: the upsert (admitted/refreshed=True) + lazy cleanup.
    assert len(session.execute.call_args_list) == 2


@pytest.mark.asyncio
async def test_postgres_try_record_alive_row_still_deduped_without_cleanup():
    # A still-live (not expired) row for this key must remain a duplicate, and
    # because no row is returned the lazy cleanup is skipped (only 1 execute).
    factory, session = _fake_session_factory()
    store = PostgresInboundDedupeStore(session_factory=factory)
    key = ("slack", "T1", "C1", "123.456")
    session.execute.side_effect = [
        MagicMock(fetchone=MagicMock(return_value=None)),  # upsert: live conflict, no row
    ]
    assert await store.try_record(key) is True
    assert len(session.execute.call_args_list) == 1


@pytest.mark.asyncio
async def test_postgres_try_record_fail_open_on_exception():
    factory, _ = _fake_session_factory(execute_raises=RuntimeError("db down"))
    store = PostgresInboundDedupeStore(session_factory=factory)
    # Storage error must NOT drop the webhook: fail open = proceed (return False).
    assert await store.try_record(("discord", "G1", "C1", "111")) is False


@pytest.mark.asyncio
async def test_postgres_release_deletes_key():
    factory, session = _fake_session_factory()
    store = PostgresInboundDedupeStore(session_factory=factory)
    await store.release(("telegram", "chat1", "chat1", "55"))
    sql = session.execute.call_args_list[0].args[0].text
    assert "DELETE FROM webhook_deliveries WHERE channel = " in sql
    assert "AND message_id = " in sql


@pytest.mark.asyncio
async def test_postgres_try_record_fail_open_when_no_session_factory(monkeypatch):
    # When Postgres is selected but no session factory is available, the store
    # must fail open (allow the message) rather than crash startup/handling.
    import deerflow.persistence.engine as engine_mod

    monkeypatch.setattr(engine_mod, "get_session_factory", lambda: None)
    store = PostgresInboundDedupeStore()  # no injected factory -> resolved lazily
    # No DB available must NOT drop the message: fail open = proceed (return False).
    assert await store.try_record(("discord", "G1", "C1", "111")) is False


def test_factory_resolves_postgres_store_when_db_is_postgres():
    app = _FakeApp("postgres", "postgres")
    store = make_inbound_dedupe_store(app)
    assert isinstance(store, PostgresInboundDedupeStore)
