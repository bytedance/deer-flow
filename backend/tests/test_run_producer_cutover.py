"""Strict fencing is a durable, executable cutover, not a hot config toggle."""

import os
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from deerflow.config.run_events_config import RunEventsConfig
from deerflow.persistence.base import Base
from deerflow.persistence.run.sql import RunRepository
from deerflow.runtime.events.store.db import DbRunEventStore


@pytest_asyncio.fixture
async def cutover_db():
    uri = os.environ.get("TEST_POSTGRES_URI")
    if not uri:
        pytest.skip("requires TEST_POSTGRES_URI")
    import deerflow.persistence.models  # noqa: F401

    schema = "cutover_" + uuid4().hex
    engine = create_async_engine(uri, pool_size=1, max_overflow=0, connect_args={"server_settings": {"search_path": schema, "application_name": schema}})
    async with engine.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield engine, async_sessionmaker(engine, expire_on_commit=False), schema
    finally:
        async with engine.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await engine.dispose()


def test_strict_requires_db_backend_and_explicit_cutover():
    with pytest.raises(ValueError):
        RunEventsConfig(backend="memory", producer_fencing="strict", producer_cutover_id="upgrade-1")
    with pytest.raises(ValueError):
        RunEventsConfig(backend="db", producer_fencing="strict")


@pytest.mark.asyncio
async def test_unaware_sql_writer_is_rejected_after_cutover(cutover_db):
    from deerflow.persistence.run.producer import activate_producer_fencing

    engine, sf, _ = cutover_db
    runs = RunRepository(sf)
    await runs.put("run", thread_id="thread", user_id="alice", status="success")
    await activate_producer_fencing(sf, cutover_id="upgrade-1")
    with pytest.raises(DBAPIError):
        async with engine.begin() as conn:
            await conn.execute(text("INSERT INTO run_events(thread_id,run_id,user_id,event_type,category,content,event_metadata,seq,created_at) VALUES ('thread','run','alice','middleware:old','trace','','{}',1,clock_timestamp())"))
    async with engine.connect() as conn:
        assert await conn.scalar(text("SELECT count(*) FROM run_events")) == 0
    with pytest.raises(RuntimeError):
        await DbRunEventStore(sf).validate_producer_fencing()
    with pytest.raises(RuntimeError):
        await DbRunEventStore(sf, producer_fencing="strict", producer_cutover_id="wrong").validate_producer_fencing()
    await DbRunEventStore(sf, producer_fencing="strict", producer_cutover_id="upgrade-1").validate_producer_fencing()


@pytest.mark.asyncio
async def test_cutover_refuses_live_run(cutover_db):
    from deerflow.persistence.run.producer import activate_producer_fencing

    _, sf, _ = cutover_db
    await RunRepository(sf).put("run", thread_id="thread", user_id="alice", status="running")
    with pytest.raises(RuntimeError, match="active"):
        await activate_producer_fencing(sf, cutover_id="upgrade-1")


@pytest.mark.asyncio
async def test_cutover_refuses_other_database_sessions(cutover_db):
    from deerflow.persistence.run.producer import activate_producer_fencing

    _, sf, schema = cutover_db
    other = create_async_engine(os.environ["TEST_POSTGRES_URI"], connect_args={"server_settings": {"search_path": schema}})
    try:
        async with other.connect():
            with pytest.raises(RuntimeError, match="sessions"):
                await activate_producer_fencing(sf, cutover_id="upgrade-1")
    finally:
        await other.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["put", "put_batch", "put_if_absent"])
async def test_original_apis_reject_missing_authority_and_metadata_forgery(cutover_db, method):
    from deerflow.persistence.run.producer import activate_producer_fencing
    from deerflow.runtime.events.producer import RunEventProducerRejected

    _, sf, _ = cutover_db
    runs = RunRepository(sf)
    await runs.put("run", thread_id="thread", user_id="alice", status="success")
    row = await runs.get("run", user_id="alice")
    await activate_producer_fencing(sf, cutover_id="upgrade-1")
    store = DbRunEventStore(sf, producer_fencing="strict", producer_cutover_id="upgrade-1")
    event = dict(thread_id="thread", run_id="run", event_type="middleware:old", category="trace", metadata={"producer_epoch": row["producer_epoch"], "run_incarnation": row["run_incarnation"], "trusted": True})
    with pytest.raises(RunEventProducerRejected):
        if method == "put_batch":
            await store.put_batch([event])
        else:
            await getattr(store, method)(**event)
    assert await store.list_events("thread", "run", user_id="alice") == []


@pytest.mark.asyncio
async def test_audit_grant_is_named_and_independent_of_closed_producer(cutover_db):
    from types import SimpleNamespace

    from deerflow.persistence.run.producer import activate_producer_fencing
    from deerflow.runtime.events.producer import RunEventProducerRejected, audit_authority, producer_authority, producer_scope

    _, sf, _ = cutover_db
    runs = RunRepository(sf)
    await runs.put("run", thread_id="thread", user_id="alice", status="success")
    record = SimpleNamespace(**await runs.get("run", user_id="alice"))
    await activate_producer_fencing(sf, cutover_id="upgrade-1")
    store = DbRunEventStore(sf, producer_fencing="strict", producer_cutover_id="upgrade-1")
    assert await store.close_producer(producer_authority(record))
    with pytest.raises(ValueError):
        audit_authority(record, event_types=("run.terminal",))
    with producer_scope(audit_authority(record, event_types=("audit.review",))):
        await store.put(thread_id="thread", run_id="run", event_type="audit.review", category="trace")
        with pytest.raises(RunEventProducerRejected):
            await store.put(thread_id="thread", run_id="run", event_type="audit.other", category="trace")
        await store.delete_by_run("thread", "run", user_id="alice")
        with pytest.raises(RunEventProducerRejected):
            await store.put(thread_id="thread", run_id="run", event_type="audit.review", category="trace")


@pytest.mark.asyncio
async def test_sqlite_strict_startup_fails(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'strict.db'}")
    try:
        with pytest.raises(RuntimeError, match="PostgreSQL"):
            await DbRunEventStore(async_sessionmaker(engine), producer_fencing="strict", producer_cutover_id="upgrade-1").validate_producer_fencing()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["memory", "jsonl"])
async def test_gateway_rejects_activated_database_with_downgraded_event_backend(cutover_db, monkeypatch, backend):
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    from fastapi import FastAPI

    from app.gateway.deps import langgraph_runtime
    from deerflow.persistence.run.producer import activate_producer_fencing

    _, sf, _ = cutover_db
    await activate_producer_fencing(sf, cutover_id="upgrade-1")

    @asynccontextmanager
    async def resource(_config):
        yield object()

    async def noop(*args):
        pass

    monkeypatch.setattr("deerflow.runtime.checkpointer.async_provider.make_checkpointer", resource)
    monkeypatch.setattr("deerflow.runtime.make_stream_bridge", resource)
    monkeypatch.setattr("deerflow.runtime.make_store", resource)
    monkeypatch.setattr("deerflow.persistence.engine.init_engine_from_config", noop)
    monkeypatch.setattr("deerflow.persistence.engine.close_engine", noop)
    monkeypatch.setattr("deerflow.persistence.engine.get_session_factory", lambda: sf)
    config = SimpleNamespace(database=SimpleNamespace(backend="postgres", checkpoint_channel_mode="full", checkpoint_delta=SimpleNamespace(snapshot_frequency=10)), run_events=RunEventsConfig(backend=backend))
    with pytest.raises(RuntimeError, match="unfenced Gateway"):
        async with langgraph_runtime(FastAPI(), config):
            pytest.fail("An activated SQL database allowed an unfenced event backend")
