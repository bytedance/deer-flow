"""Tenant schema upgrades keep legacy identities and content without activation."""

import asyncio
import os
import uuid

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine
from support.postgres import asyncpg_test_url

from deerflow.persistence import bootstrap
from deerflow.persistence.postgres_schema import build_asyncpg_connect_args


async def _isolated_database(tmp_path, backend):
    if backend == "sqlite":
        return create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'tenant.db'}"), None
    uri = os.environ.get("TEST_POSTGRES_URI")
    if not uri:
        pytest.skip("requires a dedicated TEST_POSTGRES_URI for tenant migration verification")
    schema = f"tenant_case_{uuid.uuid4().hex}"
    engine = create_async_engine(asyncpg_test_url(uri), connect_args=build_asyncpg_connect_args(schema))
    async with engine.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    return engine, schema


async def _dispose_database(engine, schema):
    if schema:
        async with engine.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
async def test_workspace_schema_upgrade_preserves_legacy_data(tmp_path, backend):
    engine, schema = await _isolated_database(tmp_path, backend)
    cfg = bootstrap._get_alembic_config(engine, postgres_schema=schema or "")
    try:
        await asyncio.to_thread(bootstrap._upgrade, cfg, "0035_native_fork_compatibility")
        async with engine.begin() as conn:
            await conn.execute(text("INSERT INTO users (id,email,system_role,created_at,needs_setup,token_version) VALUES ('owner','owner@example.invalid','user',CURRENT_TIMESTAMP,FALSE,0)"))
            await conn.execute(
                text("INSERT INTO projects (id,user_id,name,instructions,presentation,status,created_at,updated_at) VALUES ('legacy-project','owner','Existing private source','','{}','active',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)")
            )
            await conn.execute(text("INSERT INTO threads_meta (thread_id,user_id,status,metadata_json,created_at,updated_at) VALUES ('thread-owned','owner','idle','{}',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
            await conn.execute(text("INSERT INTO threads_meta (thread_id,user_id,status,metadata_json,created_at,updated_at) VALUES ('thread-orphan',NULL,'idle','{}',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
            await conn.execute(text("INSERT INTO thread_read_versions (user_id,version) VALUES ('owner',23)"))
        await asyncio.to_thread(bootstrap._upgrade, cfg, "head")
        async with engine.connect() as conn:
            tables = await conn.run_sync(lambda sync: set(inspect(sync).get_table_names()))
            assert {
                "workspaces",
                "workspace_memberships",
                "workspace_invitations",
                "auth_action_tokens",
                "workspace_connections",
                "workspace_knowledge_bindings",
                "workspace_quotas",
                "workspace_usage",
                "workspace_audit_events",
                "workspace_operation_outbox",
            } <= tables, "tenant schema has not been introduced"
            for table in ("threads_meta", "runs", "projects", "project_documents", "mcp_tasks", "scheduled_tasks", "scheduled_task_runs", "scheduled_task_events", "run_events"):
                columns = await conn.run_sync(lambda sync: {column["name"] for column in inspect(sync).get_columns(table)})
                assert "workspace_id" in columns, table
            assert (await conn.execute(text("SELECT email,email_verified_at,account_status FROM users WHERE id='owner'"))).one() == ("owner@example.invalid", None, "active")
            rows = (await conn.execute(text("SELECT thread_id,user_id,workspace_id FROM threads_meta ORDER BY thread_id"))).all()
            assert rows == [("thread-orphan", None, None), ("thread-owned", "owner", None)]
            assert (await conn.execute(text("SELECT COUNT(*) FROM workspaces"))).scalar_one() == 0, "DDL must not invent tenant ownership"
            assert "workspace_thread_read_versions" in tables, "workspace read clock schema is missing"
            assert (await conn.execute(text("SELECT version FROM thread_read_versions WHERE user_id='owner'"))).scalar_one() == 23
            assert (await conn.execute(text("SELECT COUNT(*) FROM workspace_thread_read_versions"))).scalar_one() == 0, "DDL must not invent workspace clock attribution"
            assert (await conn.execute(text("SELECT user_id,workspace_id,visibility FROM projects WHERE id='legacy-project'"))).one() == ("owner", None, "private")
            assert any(item["name"] == "ck_project_visibility" for item in await conn.run_sync(lambda sync: inspect(sync).get_check_constraints("projects")))
        await asyncio.to_thread(bootstrap._upgrade, cfg, "head")
        async with engine.connect() as conn:
            assert (await conn.execute(text("SELECT COUNT(*) FROM threads_meta"))).scalar_one() == 2
    finally:
        await _dispose_database(engine, schema)


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
async def test_explicit_personal_backfill_is_idempotent_and_quarantines_conflicts(tmp_path, backend):
    import importlib
    import importlib.util

    from deerflow.persistence.base import Base

    engine, schema = await _isolated_database(tmp_path, backend)
    try:
        await bootstrap.bootstrap_schema(engine, backend=backend, postgres_schema=schema or "")
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO users (id,email,system_role,created_at,needs_setup,token_version) VALUES ('owner','owner@example.invalid','user',CURRENT_TIMESTAMP,FALSE,0),('other','other@example.invalid','user',CURRENT_TIMESTAMP,FALSE,0)"
                )
            )
            await conn.execute(
                text(
                    "INSERT INTO threads_meta (thread_id,user_id,status,metadata_json,created_at,updated_at) VALUES ('owned','owner','idle','{}',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP),"
                    "('orphan',NULL,'idle','{}',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
                )
            )
            await conn.execute(text("INSERT INTO projects (id,user_id,name,instructions,presentation,status,created_at,updated_at) VALUES ('foreign-project','other','Legacy research','','{}','active',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
            await conn.execute(
                text(
                    "INSERT INTO project_documents (id,project_id,user_id,name,stored_relpath,sha256,size_bytes,created_at,updated_at) VALUES ('conflicting-doc','foreign-project','owner','source.txt',"
                    "'retained/source.txt','aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',14,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
                )
            )
        module_name = "deerflow.persistence.workspaces.backfill"
        assert importlib.util.find_spec(module_name) is not None, "explicit ownership backfill is not implemented"
        backfill = importlib.import_module(module_name)
        async with engine.begin() as conn:
            plan = await conn.run_sync(backfill.plan_personal_backfill)
            assert len(plan["users"]) == 2
            assert (await conn.execute(text("SELECT COUNT(*) FROM workspaces"))).scalar_one() == 0, "planning mutated tenant state"
            assert {item["id"] for item in plan["quarantined"]} == {"orphan", "conflicting-doc"}
            receipt = await conn.run_sync(backfill.apply_personal_backfill)
            assert receipt["created_workspaces"] == 2
            assert receipt["assigned_resources"] == 2
        async with engine.begin() as conn:
            second = await conn.run_sync(backfill.apply_personal_backfill)
            assert second["created_workspaces"] == 0
            assert second["assigned_resources"] == 0
            assert (await conn.execute(text("SELECT COUNT(*) FROM workspaces"))).scalar_one() == 2
            assert (await conn.execute(text("SELECT COUNT(*) FROM workspace_memberships WHERE role='owner' AND status='active'"))).scalar_one() == 2
            personal = (await conn.execute(text("SELECT id FROM workspaces WHERE personal_user_id='owner'"))).scalar_one()
            assert (await conn.execute(text("SELECT user_id,workspace_id FROM threads_meta WHERE thread_id='owned'"))).one() == ("owner", personal)
            assert (await conn.execute(text("SELECT workspace_id FROM threads_meta WHERE thread_id='orphan'"))).scalar_one() is None
            assert (await conn.execute(text("SELECT workspace_id,stored_relpath FROM project_documents WHERE id='conflicting-doc'"))).one() == (None, "retained/source.txt")
            assert (await conn.execute(text("SELECT email_verified_at FROM users WHERE id='owner'"))).scalar_one() is None
            assert set(Base.metadata.tables) <= await conn.run_sync(lambda sync: set(inspect(sync).get_table_names()))
    finally:
        await _dispose_database(engine, schema)
