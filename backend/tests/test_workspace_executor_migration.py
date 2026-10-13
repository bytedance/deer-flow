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
