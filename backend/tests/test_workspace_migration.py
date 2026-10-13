"""Tenant schema upgrades keep legacy identities and content without activation."""

import asyncio

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from deerflow.persistence import bootstrap


@pytest.mark.asyncio
async def test_workspace_schema_upgrade_preserves_legacy_data(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'tenant.db'}")
    cfg = bootstrap._get_alembic_config(engine)
    try:
        await asyncio.to_thread(bootstrap._upgrade, cfg, "0035_native_fork_compatibility")
        async with engine.begin() as conn:
            await conn.execute(text("INSERT INTO users (id,email,system_role,created_at,needs_setup,token_version) VALUES ('owner','owner@example.invalid','user',CURRENT_TIMESTAMP,FALSE,0)"))
            await conn.execute(text("INSERT INTO threads_meta (thread_id,user_id,status,metadata_json,created_at,updated_at) VALUES ('thread-owned','owner','idle','{}',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
            await conn.execute(text("INSERT INTO threads_meta (thread_id,user_id,status,metadata_json,created_at,updated_at) VALUES ('thread-orphan',NULL,'idle','{}',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
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
        await asyncio.to_thread(bootstrap._upgrade, cfg, "head")
        async with engine.connect() as conn:
            assert (await conn.execute(text("SELECT COUNT(*) FROM threads_meta"))).scalar_one() == 2
    finally:
        await engine.dispose()
