"""Focused real schema ownership, upgrade and activation boundaries."""

import pytest
import sqlalchemy as sa
from alembic.script import ScriptDirectory

from deerflow.persistence import bootstrap

HEAD = "0037_project_visibility"


def test_integrated_graph_retains_shipped_ancestry():
    script = ScriptDirectory(str(bootstrap._MIGRATIONS_DIR))
    assert script.get_heads() == [HEAD]
    assert script.get_revision("0018_thread_execution_bindings").down_revision == "0017_personal_access_tokens"
    assert script.get_revision("0019_scheduled_execution").down_revision == "0018_thread_execution_bindings"
    assert script.get_revision("0022_fleet_main_merge").down_revision == ("0019_scheduled_execution", "0019_thread_incarnations")
    assert script.get_revision(HEAD).down_revision == "0036_tenant_workspaces"
    assert script.get_revision("0036_tenant_workspaces").down_revision == "0035_native_fork_compatibility"
    assert script.get_revision("0035_native_fork_compatibility").down_revision == ("0034_run_event_seq_watermark", "0022_fleet_main_merge")


def test_executor_requires_version_and_preserves_unknown_reservation(tmp_path):
    from ecs_executor.job_store import _JOBS, JobStore
    from ecs_executor.schema import SchemaCompatibilityError, require_schema, upgrade_schema

    store = JobStore("sqlite:///" + str(tmp_path / "executor.db"))
    with pytest.raises(SchemaCompatibilityError):
        require_schema(store.engine)
    store.initialize()  # Explicit Python test/local bootstrap only.
    with store.engine.begin() as conn:
        conn.execute(_JOBS.insert().values(id="reserved", namespace="u", request_key="k", version=7, state="uncertain", record={"physical_stopped": False, "unknown": "retain"}))
    upgrade_schema(store.engine)
    require_schema(store.engine)
    assert store.get("reserved") == {"physical_stopped": False, "unknown": "retain"}
    with store.engine.begin() as conn:
        conn.execute(sa.text("UPDATE ecs_executor_alembic_version SET version_num='unknown'"))
    with pytest.raises(SchemaCompatibilityError):
        require_schema(store.engine)
    with pytest.raises(SchemaCompatibilityError):
        upgrade_schema(store.engine)


def test_executor_refuses_native_database_before_mutation(tmp_path):
    from ecs_executor.schema import SchemaCompatibilityError, upgrade_schema

    engine = sa.create_engine("sqlite:///" + str(tmp_path / "native.db"))
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE runs (id TEXT PRIMARY KEY)"))
    with pytest.raises(SchemaCompatibilityError, match="independent"):
        upgrade_schema(engine)
    assert sa.inspect(engine).get_table_names() == ["runs"]


def test_legacy_intents_are_preserved_and_block_activation(tmp_path):
    from deerflow.persistence.legacy_execution import LegacyExecutionQuarantined, inventory, require_no_legacy_execution

    engine = sa.create_engine("sqlite:///" + str(tmp_path / "legacy.db"))
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE thread_execution_bindings (user_id TEXT, thread_id TEXT, backend TEXT)"))
        conn.execute(sa.text("INSERT INTO thread_execution_bindings VALUES ('owner', 'old-thread', 'fleet')"))
        conn.execute(sa.text("CREATE TABLE scheduled_tasks (id TEXT, execution JSON, status TEXT)"))
        conn.execute(sa.text("INSERT INTO scheduled_tasks VALUES (:id, :intent, :status)"), {"id": "legacy-task", "intent": '{"backend":"fleet"}', "status": "enabled"})
        before = conn.execute(sa.text("SELECT execution FROM scheduled_tasks")).scalar_one()
        report = inventory(conn)
        assert report["bindings"] == [{"user_id": "owner", "thread_id": "old-thread", "backend": "fleet"}]
        assert report["scheduled_tasks"] == [{"id": "legacy-task", "status": "enabled"}]
        with pytest.raises(LegacyExecutionQuarantined):
            require_no_legacy_execution(conn)
        assert conn.execute(sa.text("SELECT execution FROM scheduled_tasks")).scalar_one() == before


@pytest.mark.asyncio
@pytest.mark.parametrize("previous", [None, "0034_run_event_seq_watermark", "0022_fleet_main_merge"])
async def test_real_postgres_upgrade_main_preserves_rows(previous):
    import asyncio
    import os
    import uuid

    from alembic import command
    from sqlalchemy.ext.asyncio import create_async_engine

    from deerflow.persistence.legacy_execution import LegacyExecutionQuarantined, require_activation
    from deerflow.persistence.postgres_schema import build_asyncpg_connect_args

    url = os.environ.get("TASK6A_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("requires owned Task6A PostgreSQL")
    schema = "task6a_" + uuid.uuid4().hex
    engine = create_async_engine(url.replace("postgresql+psycopg://", "postgresql+asyncpg://"), connect_args=build_asyncpg_connect_args(schema))
    config = bootstrap._get_alembic_config(engine, postgres_schema=schema)
    try:
        async with engine.begin() as conn:
            await conn.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
        if previous:
            await asyncio.to_thread(command.upgrade, config, previous)
            async with engine.begin() as conn:
                await conn.execute(
                    sa.text(
                        "INSERT INTO run_events (thread_id, run_id, event_type, category, content, event_metadata, seq, created_at) "
                        "VALUES ('native-thread', 'native-run', 'human_message', 'message', 'keep-native', '{}', 1, CURRENT_TIMESTAMP)"
                    )
                )
                if previous == "0022_fleet_main_merge":
                    await conn.execute(sa.text("INSERT INTO thread_execution_bindings (user_id, thread_id, backend, source_workspace) VALUES ('owner', 'legacy-thread', 'fleet', :workspace)"), {"workspace": '{"keep":"legacy"}'})
                    # Native scheduled row remains valid; its legacy JSON is additive.
                    await conn.execute(
                        sa.text(
                            "INSERT INTO scheduled_tasks (id,user_id,title,prompt,context_mode,schedule_type,schedule_spec,timezone,status,"
                            "overlap_policy,run_count,created_at,updated_at,execution) VALUES ('legacy-task','owner','keep','keep','same_thread','once','{}','UTC','paused','queue',0,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,:intent)"
                        ),
                        {"intent": '{"backend":"fleet","opaque":"preserve"}'},
                    )
        await asyncio.to_thread(command.upgrade, config, "head")
        async with engine.connect() as conn:
            assert (await conn.execute(sa.text("SELECT version_num FROM alembic_version"))).scalars().all() == [HEAD]
            if previous:
                assert (await conn.execute(sa.text("SELECT content FROM run_events WHERE run_id='native-run'"))).scalar_one() == "keep-native"
            if previous == "0022_fleet_main_merge":
                assert (await conn.execute(sa.text("SELECT source_workspace FROM thread_execution_bindings"))).scalar_one() == {"keep": "legacy"}
                assert (await conn.execute(sa.text("SELECT execution FROM scheduled_tasks"))).scalar_one() == {"backend": "fleet", "opaque": "preserve"}
        if previous == "0022_fleet_main_merge":
            with pytest.raises(LegacyExecutionQuarantined):
                await require_activation(engine)
        else:
            await require_activation(engine)
    finally:
        async with engine.begin() as conn:
            await conn.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()


def test_executor_adopts_exact_unversioned_ledger_without_replay(tmp_path):
    from ecs_executor.job_store import _JOBS, _METADATA
    from ecs_executor.schema import require_schema, upgrade_schema

    engine = sa.create_engine("sqlite:///" + str(tmp_path / "unversioned.db"))
    _METADATA.create_all(engine)  # Model of the accepted pre-versioning local ledger.
    with engine.begin() as conn:
        conn.execute(_JOBS.insert().values(id="unknown", namespace="owner", request_key="old", version=9, state="uncertain", record={"start_intent": True, "physical_stopped": False}))
    upgrade_schema(engine)
    require_schema(engine)
    with engine.connect() as conn:
        row = conn.execute(sa.select(_JOBS)).one()
        assert row.version == 9 and row.state == "uncertain"
        assert row.record == {"start_intent": True, "physical_stopped": False}


def test_worker_rejects_schema_capability_mismatch_before_claim(tmp_path):
    import httpx
    from ecs_executor.dispatch import OutboundStore

    (tmp_path / "pool-mount-id").write_text("mount", encoding="ascii")
    store = OutboundStore(url="http://executor", node_id="one", credential="test", artifact_root=tmp_path)
    store.client.close()
    store.client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"schema_revision": "unknown", "owned": [], "claim": None})))
    try:
        with pytest.raises(RuntimeError, match="schema"):
            store.expire_staged()
        assert store.claimed is None
    finally:
        store.client.close()


def test_autogenerate_cannot_retire_preserved_legacy_intent():
    from deerflow.persistence.migrations._env_filters import include_object

    legacy = sa.Table("thread_execution_bindings", sa.MetaData(), sa.Column("thread_id", sa.String()))
    schedules = sa.Table("scheduled_tasks", sa.MetaData(), sa.Column("execution", sa.JSON()))
    assert include_object(legacy, legacy.name, "table", True, None) is False
    assert include_object(schedules.c.execution, "execution", "column", True, None) is False
    assert include_object(schedules, schedules.name, "table", True, None) is True


def test_real_postgres_executor_upgrade_retains_unknown_reservations():
    import os

    from ecs_executor.agent_dispatch import _AFFINITY_METADATA
    from ecs_executor.job_store import _JOBS, _METADATA
    from ecs_executor.scheduling import _METADATA as nodes_metadata
    from ecs_executor.schema import SchemaCompatibilityError, require_schema, upgrade_schema

    url = os.environ.get("TASK6A_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("requires owned Task6A PostgreSQL")
    engine = sa.create_engine(url)
    try:
        _METADATA.create_all(engine)
        nodes_metadata.create_all(engine)
        _AFFINITY_METADATA.create_all(engine)
        with engine.begin() as conn:
            conn.execute(_JOBS.insert().values(id="pg-unknown", namespace="owner", request_key="unknown", version=11, state="uncertain", record={"physical_stopped": False, "start_intent": True, "node_id": "lost-node"}))
        with pytest.raises(SchemaCompatibilityError):
            require_schema(engine)
        upgrade_schema(engine)
        require_schema(engine)
        with engine.connect() as conn:
            row = conn.execute(sa.select(_JOBS)).one()
            assert row.version == 11 and row.state == "uncertain"
            assert row.record == {"physical_stopped": False, "start_intent": True, "node_id": "lost-node"}
    finally:
        engine.dispose()


@pytest.mark.parametrize("extra", ["CHECK(version <= 1)", "UNIQUE(state)"])
def test_executor_rejects_behavior_changing_constraints_before_adoption(tmp_path, extra):
    from ecs_executor.schema import SchemaCompatibilityError, upgrade_schema

    engine = sa.create_engine("sqlite:///" + str(tmp_path / "constrained.db"))
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "CREATE TABLE ecs_execution_jobs (id VARCHAR(64) NOT NULL PRIMARY KEY, "
                "namespace VARCHAR(64) NOT NULL, request_key VARCHAR(128) NOT NULL, version INTEGER NOT NULL, "
                "state VARCHAR(32) NOT NULL, record JSON NOT NULL, CONSTRAINT uq_ecs_execution_request UNIQUE(namespace, request_key), " + extra + ")"
            )
        )
        conn.execute(sa.text("CREATE INDEX ix_ecs_execution_jobs_state ON ecs_execution_jobs (state)"))
        conn.execute(sa.text("INSERT INTO ecs_execution_jobs VALUES ('keep', 'owner', 'key', 1, 'uncertain', '{}')"))
    with pytest.raises(SchemaCompatibilityError):
        upgrade_schema(engine)
    with engine.connect() as conn:
        assert conn.execute(sa.text("SELECT version FROM ecs_execution_jobs WHERE id='keep'")).scalar_one() == 1
        assert not sa.inspect(conn).has_table("ecs_executor_alembic_version")
    engine.dispose()


@pytest.mark.parametrize("module", ["ecs_executor.schema", "deerflow.persistence.legacy_execution"])
def test_private_cli_malformed_url_is_redacted(module):
    import os
    import subprocess
    import sys
    from pathlib import Path

    marker = "SYNTHETIC_PRIVATE_PORT_MARKER"
    backend = Path(__file__).resolve().parents[1]
    environment = {"PATH": os.defpath, "PYTHONPATH": str(backend) + os.pathsep + str(backend / "packages/ecs-executor"), "TASK6A_SYNTHETIC_PRIVATE_URL": "postgresql://user:synthetic@127.0.0.1:" + marker + "/db"}
    args = [sys.executable, "-m", module]
    if module == "ecs_executor.schema":
        args.append("check")
    args += ["--database-url-env", "TASK6A_SYNTHETIC_PRIVATE_URL"]
    result = subprocess.run(args, env=environment, capture_output=True, text=True, timeout=15)
    assert result.returncode != 0
    assert marker not in result.stdout + result.stderr
    assert "URL withheld" in result.stdout + result.stderr


def test_executor_rejects_case_insensitive_request_identity_before_adoption(tmp_path):
    from ecs_executor.schema import SchemaCompatibilityError, upgrade_schema

    engine = sa.create_engine("sqlite:///" + str(tmp_path / "nocase.db"))
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "CREATE TABLE ecs_execution_jobs (id VARCHAR(64) NOT NULL PRIMARY KEY, namespace VARCHAR(64) NOT NULL, "
                "request_key VARCHAR(128) COLLATE NOCASE NOT NULL, version INTEGER NOT NULL, state VARCHAR(32) NOT NULL, "
                "record JSON NOT NULL, CONSTRAINT uq_ecs_execution_request UNIQUE(namespace, request_key))"
            )
        )
        conn.execute(sa.text("CREATE INDEX ix_ecs_execution_jobs_state ON ecs_execution_jobs (state)"))
        conn.execute(sa.text("INSERT INTO ecs_execution_jobs VALUES ('keep', 'owner', 'CaseKey', 1, 'uncertain', '{}')"))
    with pytest.raises(SchemaCompatibilityError):
        upgrade_schema(engine)
    with engine.connect() as conn:
        assert conn.execute(sa.text("SELECT request_key FROM ecs_execution_jobs WHERE id='keep'")).scalar_one() == "CaseKey"
        assert not sa.inspect(conn).has_table("ecs_executor_alembic_version")
    engine.dispose()
