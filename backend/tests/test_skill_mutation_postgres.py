"""Opt-in live PostgreSQL fence test; never substitute SQLite for PG locking."""

import asyncio
import os
import threading
import uuid

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from deerflow.config.database_config import DatabaseConfig
from deerflow.persistence.base import Base
from deerflow.persistence.run import RunRepository
from deerflow.persistence.run.model import CompletedRunSnapshotRow, RunRow
from deerflow.skills.mutations.topology import mutation_session_factory

pytestmark = pytest.mark.skipif(not os.environ.get("DEERFLOW_TEST_POSTGRES_URL"), reason="requires an explicit live DEERFLOW_TEST_POSTGRES_URL")


@pytest.mark.asyncio
async def test_run_deletion_waits_for_publication_source_share_lock():
    schema = "skill_evolution_test_" + uuid.uuid4().hex
    config = DatabaseConfig(backend="postgres", postgres_url=os.environ["DEERFLOW_TEST_POSTGRES_URL"], postgres_schema=schema)
    admin = create_engine(config.app_sync_sqlalchemy_url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    sync_engine, sessions = mutation_session_factory(config.app_sync_sqlalchemy_url, postgres_schema=schema)
    async_engine = create_async_engine(config.app_sqlalchemy_url, connect_args={"server_settings": {"search_path": schema}})
    sf = async_sessionmaker(async_engine, expire_on_commit=False)
    release, acquired = threading.Event(), threading.Event()
    worker = None
    deleting = None
    try:
        Base.metadata.create_all(sync_engine)
        with sessions.begin() as session:
            session.add(RunRow(run_id="run", thread_id="thread", user_id="owner", status="success"))
            session.flush()
            session.add(CompletedRunSnapshotRow(snapshot_ref="snapshot", run_id="run", scope_digest="scope", evidence_revision="revision", retention_revision=0, snapshot_json={}))

        def publication_fence():
            with sessions.begin() as session:
                session.scalar(select(RunRow).where(RunRow.run_id == "run").with_for_update(read=True))
                acquired.set()
                assert release.wait(5)

        worker = asyncio.create_task(asyncio.to_thread(publication_fence))
        assert await asyncio.to_thread(acquired.wait, 5)
        deleting = asyncio.create_task(RunRepository(sf).delete("run", user_id="owner"))
        await asyncio.sleep(0.2)
        assert not deleting.done(), "source deletion must wait for the accepted publication fence"
        release.set()
        await asyncio.wait_for(deleting, 5)
        await worker
        async with sf() as session:
            assert await session.get(RunRow, "run") is None
            assert await session.get(CompletedRunSnapshotRow, "snapshot") is None
    finally:
        release.set()
        if worker is not None:
            await worker
        if deleting is not None:
            await asyncio.gather(deleting, return_exceptions=True)
        await async_engine.dispose()
        sync_engine.dispose()
        # Exact, randomly-created test schema only; never a configured schema.
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()
