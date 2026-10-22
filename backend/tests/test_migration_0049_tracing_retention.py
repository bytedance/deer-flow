"""Existing encrypted snapshots stay unmanaged across retention upgrades."""

import asyncio

from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from deerflow.persistence import bootstrap


def test_retention_is_single_head_after_the_merge():
    script = ScriptDirectory(str(bootstrap._MIGRATIONS_DIR))
    assert script.get_heads() == ["0049_tracing_retention"]
    assert script.get_revision("0049_tracing_retention").down_revision == "0048_merge_tracing_mcp_oauth"


def test_upgrade_backfills_unknown_rows_without_rewriting_ciphertext(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path / 'migration.db'}"
    async_engine = create_async_engine(url)
    cfg = bootstrap._get_alembic_config(async_engine)
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    try:
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "0048_merge_tracing_mcp_oauth")
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO run_tracing_snapshots (snapshot_id,owner_user_id,agent_name,agent_incarnation,mode,binding_revision,payload_ciphertext) "
                    "VALUES (:id,'alice','lead_agent','builtin:lead_agent','inherit',0,'retained-old-ciphertext')"
                ),
                {"id": "a" * 32},
            )
        command.upgrade(cfg, "head")
        with engine.connect() as connection:
            row = connection.execute(text("SELECT retention_state, created_at, payload_ciphertext FROM run_tracing_snapshots")).one()
            assert row[0] == "unmanaged" and row[1] is not None and row[2] == "retained-old-ciphertext"
            columns = {column["name"]: column for column in inspect(connection).get_columns("run_tracing_snapshots")}
            assert not columns["created_at"]["nullable"] and not columns["retention_state"]["nullable"]
            assert "ix_run_tracing_snapshots_retention" in {index["name"] for index in inspect(connection).get_indexes("run_tracing_snapshots")}
        command.downgrade(cfg, "0048_merge_tracing_mcp_oauth")
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT payload_ciphertext FROM run_tracing_snapshots")) == "retained-old-ciphertext"
        command.upgrade(cfg, "head")
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT retention_state FROM run_tracing_snapshots")) == "unmanaged"
    finally:
        engine.dispose()
        asyncio.run(async_engine.dispose())
