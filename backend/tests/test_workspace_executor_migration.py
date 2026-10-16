"""Versioned executor scope upgrade must preserve uncertain physical work."""

import json
import os
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config


@pytest.fixture(params=["sqlite", "postgres"])
def executor_engine(tmp_path, request):
    admin = None
    database = None
    if request.param == "sqlite":
        engine = sa.create_engine(f"sqlite:///{tmp_path / 'executor.db'}")
    else:
        uri = os.environ.get("TEST_EXECUTOR_POSTGRES_URL")
        if not uri:
            pytest.skip("requires dedicated TEST_EXECUTOR_POSTGRES_URL for independent executor databases")
        admin = sa.create_engine(uri, isolation_level="AUTOCOMMIT")
        database = "tenant_executor_" + uuid.uuid4().hex
        with admin.connect() as conn:
            conn.execute(sa.text(f'CREATE DATABASE "{database}"'))
        engine = sa.create_engine(admin.url.set(database=database))
    try:
        cfg = Config()
        import ecs_executor.schema as schema

        cfg.set_main_option("script_location", str(Path(schema.__file__).parent / "migrations"))
        with engine.begin() as conn:
            cfg.attributes["connection"] = conn
            command.upgrade(cfg, "e0001_execution_ledger")
            conn.execute(sa.text("INSERT INTO ecs_execution_jobs (id,namespace,request_key,version,state,record) VALUES ('unknown','owner','old',7,'uncertain',:record)"), {"record": '{"physical_stopped":false,"start_intent":true}'})
            conn.execute(sa.text("INSERT INTO ecs_native_affinities (user_id,thread_id,incarnation,node_id) VALUES ('owner','thread','epoch','node')"))
        yield engine
    finally:
        engine.dispose()
        if admin is not None:
            try:
                with admin.connect() as conn:
                    conn.execute(sa.text(f'DROP DATABASE "{database}"'))
            finally:
                admin.dispose()


def test_executor_scope_upgrade_refuses_old_runtime_and_retains_reservations(executor_engine):
    from ecs_executor.schema import SchemaCompatibilityError, require_schema, upgrade_schema

    with executor_engine.connect() as conn:
        before = conn.execute(sa.text("SELECT CAST(record AS TEXT) FROM ecs_execution_jobs WHERE id='unknown'")).scalar_one()
    with pytest.raises(SchemaCompatibilityError):
        require_schema(executor_engine)
    upgrade_schema(executor_engine)
    assert require_schema(executor_engine) == "e0002_workspace_scope"
    with executor_engine.connect() as conn:
        inspector = sa.inspect(conn)
        for name in ("ecs_execution_jobs", "ecs_native_affinities"):
            column = next(c for c in inspector.get_columns(name) if c["name"] == "workspace_id")
            assert column["nullable"] and str(column["type"]) == "VARCHAR(36)"
            assert any(i["column_names"] == ["workspace_id"] for i in inspector.get_indexes(name))
        row = conn.execute(sa.text("SELECT version,state,workspace_id,record FROM ecs_execution_jobs WHERE id='unknown'")).one()
        assert row[:3] == (7, "uncertain", None)
        assert (json.loads(row.record) if isinstance(row.record, str) else row.record) == {"physical_stopped": False, "start_intent": True}
        assert conn.execute(sa.text("SELECT CAST(record AS TEXT) FROM ecs_execution_jobs WHERE id='unknown'")).scalar_one() == before
        assert conn.execute(sa.text("SELECT node_id,workspace_id FROM ecs_native_affinities")).one() == ("node", None)
    upgrade_schema(executor_engine)
    assert require_schema(executor_engine) == "e0002_workspace_scope"


def test_new_executor_record_binds_immutable_workspace(executor_engine):
    from ecs_executor.job_store import JobStore
    from ecs_executor.schema import upgrade_schema

    upgrade_schema(executor_engine)
    store = JobStore(executor_engine.url.render_as_string(hide_password=False))
    workspace = "bb7cc038-790e-4dd7-bac5-ac8d24d0d96e"
    try:
        job = store.create(namespace="owner", request_key="new", spec_digest="digest", record={"workspace_id": workspace})
        with executor_engine.connect() as conn:
            assert conn.execute(sa.text("SELECT workspace_id FROM ecs_execution_jobs WHERE id=:id"), {"id": job["id"]}).scalar_one() == workspace
        with pytest.raises(ValueError, match="workspace"):
            store.create(namespace="owner", request_key="new", spec_digest="digest", record={"workspace_id": "833f0ed9-1d0a-4407-bfa4-0c0f7a00f6eb"})
        with pytest.raises(ValueError, match="workspace"):
            store.mutate(job["id"], lambda record: record.update(workspace_id="833f0ed9-1d0a-4407-bfa4-0c0f7a00f6eb"))
        assert store.get(job["id"])["workspace_id"] == workspace
    finally:
        store.engine.dispose()


@pytest.fixture()
def native_engine(executor_engine, tmp_path):
    import asyncio

    from sqlalchemy.ext.asyncio import create_async_engine

    from deerflow.persistence import bootstrap
    from deerflow.persistence.run.model import RunRow
    from deerflow.persistence.thread_meta.model import ThreadMetaRow
    from deerflow.persistence.user.model import UserRow

    admin = None
    database = None
    if executor_engine.dialect.name == "sqlite":
        engine = sa.create_engine(f"sqlite:///{tmp_path / 'native.db'}")
        async_url = engine.url.set(drivername="sqlite+aiosqlite")
        backend = "sqlite"
    else:
        admin = sa.create_engine(os.environ["TEST_EXECUTOR_POSTGRES_URL"], isolation_level="AUTOCOMMIT")
        database = "tenant_native_" + uuid.uuid4().hex
        with admin.connect() as conn:
            conn.execute(sa.text(f'CREATE DATABASE "{database}"'))
        engine = sa.create_engine(admin.url.set(database=database))
        async_url = engine.url.set(drivername="postgresql+asyncpg")
        backend = "postgres"
    try:

        async def bootstrap_owned_native():
            async_engine = create_async_engine(async_url)
            try:
                await bootstrap.bootstrap_schema(async_engine, backend=backend)
            finally:
                await async_engine.dispose()

        asyncio.run(bootstrap_owned_native())
        with engine.begin() as conn:
            conn.execute(sa.insert(UserRow).values(id="owner", email="owner@example.invalid"))
            conn.execute(sa.insert(ThreadMetaRow).values(thread_id="thread", user_id="owner", incarnation="epoch"))
            conn.execute(sa.insert(RunRow).values(run_id="run", thread_id="thread", user_id="owner", status="success"))
            conn.execute(sa.insert(ThreadMetaRow).values(thread_id="orphan", user_id=None))
            conn.execute(sa.insert(RunRow).values(run_id="foreign-run", thread_id="thread", user_id="intruder", status="success"))
        yield engine
    finally:
        engine.dispose()
        if admin is not None:
            try:
                with admin.connect() as conn:
                    conn.execute(sa.text(f'DROP DATABASE "{database}"'))
            finally:
                admin.dispose()


def test_paired_attribution_preserves_payloads_and_unknown_physical_work(executor_engine, native_engine):
    import importlib
    import importlib.util

    from ecs_executor.job_store import _JOBS
    from ecs_executor.schema import upgrade_schema

    from deerflow.persistence.workspaces.backfill import apply_personal_backfill

    with native_engine.begin() as conn:
        apply_personal_backfill(conn)
        workspace = conn.execute(sa.text("SELECT workspace_id FROM threads_meta WHERE thread_id='thread'")).scalar_one()
        assert conn.execute(sa.text("SELECT workspace_id FROM runs WHERE run_id='run'")).scalar_one() == workspace
    bindings = {
        "native_revision": "0040_mcp_workspace_identity",
        "threads": [{"user_id": "owner", "thread_id": "thread", "incarnation": "epoch", "workspace_id": workspace}],
        "runs": [{"user_id": "owner", "thread_id": "thread", "incarnation": "epoch", "run_id": "run", "workspace_id": workspace}],
    }
    from deerflow.persistence.workspaces import backfill as native_backfill

    assert hasattr(native_backfill, "export_native_workspace_bindings"), "production native ownership export is not implemented"
    with native_engine.connect() as conn:
        assert native_backfill.export_native_workspace_bindings(conn) == bindings
        assert conn.execute(sa.text("SELECT workspace_id FROM runs WHERE run_id='foreign-run'")).scalar_one() is None
    upgrade_schema(executor_engine)
    originals = {
        "known-B": {"kind": "B", "user_id": "owner", "thread_id": "thread", "incarnation": "epoch", "run_id": "run", "state": "uncertain", "physical_stopped": False, "start_intent": True, "spec_digest": "retain-B"},
        "known-C": {"kind": "C", "native": {"user_id": "owner", "thread_id": "thread", "incarnation": "epoch", "run_id": "run", "opaque": "retain-snapshot"}, "state": "completed", "physical_stopped": True, "spec_digest": "retain-C"},
        "conflict": {"kind": "C", "native": {"user_id": "other", "thread_id": "thread", "incarnation": "epoch", "run_id": "run"}, "state": "completed", "physical_stopped": True},
    }
    with executor_engine.begin() as conn:
        for identity, record in originals.items():
            conn.execute(_JOBS.insert().values(id=identity, namespace="test-" + identity, request_key=identity, version=5, state=record["state"], record=record))
    name = "ecs_executor.tenant_backfill"
    assert importlib.util.find_spec(name) is not None, "paired executor workspace attribution is not implemented"
    backfill = importlib.import_module(name)
    with executor_engine.begin() as conn:
        plan = backfill.plan_workspace_attribution(conn, bindings)
        assert len(plan["jobs"]) == 2 and len(plan["affinities"]) == 1
        assert {item["id"] for item in plan["quarantined"]} == {"unknown", "conflict"}
        assert conn.execute(sa.text("SELECT COUNT(*) FROM ecs_execution_jobs WHERE workspace_id IS NOT NULL")).scalar_one() == 0
        first = backfill.apply_workspace_attribution(conn, bindings)
        assert first["assigned_jobs"] == 2 and first["assigned_affinities"] == 1
    with executor_engine.begin() as conn:
        second = backfill.apply_workspace_attribution(conn, bindings)
        assert second["assigned_jobs"] == 0 and second["assigned_affinities"] == 0
        assert conn.execute(sa.text("SELECT version,state,workspace_id FROM ecs_execution_jobs WHERE id='unknown'")).one() == (7, "uncertain", None)
        for identity, original in originals.items():
            row = conn.execute(sa.select(_JOBS).where(_JOBS.c.id == identity)).one()
            record = dict(row.record)
            if identity != "conflict":
                assert row.workspace_id == record.pop("workspace_id") == workspace
            else:
                assert row.workspace_id is None
            assert record == original and row.version == 5 and row.state == original["state"]
        assert conn.execute(sa.text("SELECT node_id,workspace_id FROM ecs_native_affinities")).one() == ("node", workspace)
