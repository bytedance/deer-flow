"""Additive Skill host schema; the chain-head pin lives in ``test_migration_0047_mcp_oauth_tokens``."""

import asyncio

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy.ext.asyncio import create_async_engine

from deerflow.persistence import bootstrap
from deerflow.persistence.run.model import RunRow

REVISION = "0046_skill_mutations"
TABLES = {"skill_mutation_assets", "skill_mutation_owners", "skill_mutation_proposals", "skill_mutation_operations", "skill_mutation_scan_attempts"}


def test_0046_remains_in_the_single_migration_chain():
    script = ScriptDirectory(str(bootstrap._MIGRATIONS_DIR))
    assert len(script.get_heads()) == 1
    assert script.get_revision("0047_mcp_oauth_tokens").down_revision == REVISION
    assert script.get_revision(REVISION).down_revision == "0045_completed_run_evidence"
    assert script.get_revision("0045_completed_run_evidence").down_revision == "0044_channel_runtime_configs"
    assert script.get_revision("0044_channel_runtime_configs").down_revision == "0043_runtime_im_notices"


@pytest.mark.asyncio
async def test_0046_additive_upgrade_and_nullable_recovery_metadata(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'skill-host.db'}")
    config = bootstrap._get_alembic_config(engine)
    try:
        await asyncio.to_thread(bootstrap._upgrade, config, "0045_completed_run_evidence")
        # The historical create_all bootstrap uses today's metadata. Remove
        # exactly the new, empty tables to represent a real 0045 installation.
        async with engine.begin() as connection:
            for table in sorted(TABLES):
                await connection.execute(sa.text(f'DROP TABLE IF EXISTS "{table}"'))
            await connection.execute(RunRow.__table__.insert().values(run_id="legacy", thread_id="thread", status="success"))
            await connection.execute(sa.text("INSERT INTO channel_runtime_configs VALUES ('telegram', 'synthetic-ciphertext', 0, 7, 1.0)"))
        await asyncio.to_thread(bootstrap._upgrade, config, REVISION)
        async with engine.connect() as connection:
            names = await connection.run_sync(lambda sync: sa.inspect(sync).get_table_names())
            assert TABLES <= set(names)
            columns = await connection.run_sync(lambda sync: sa.inspect(sync).get_columns("skill_mutation_operations"))
            nullable = {column["name"]: column["nullable"] for column in columns}
            assert nullable["before_operation_id"]
            assert nullable["superseded_by_generation"]
            assert await connection.scalar(sa.text("SELECT status FROM runs WHERE run_id='legacy'")) == "success"
            assert (await connection.execute(sa.text("SELECT config_ciphertext, version FROM channel_runtime_configs WHERE provider='telegram'"))).one() == ("synthetic-ciphertext", 7)
        await asyncio.to_thread(command.downgrade, config, "0045_completed_run_evidence")
        async with engine.connect() as connection:
            names = await connection.run_sync(lambda sync: sa.inspect(sync).get_table_names())
            assert not TABLES.intersection(names)
            assert await connection.scalar(sa.text("SELECT status FROM runs WHERE run_id='legacy'")) == "success"
            assert (await connection.execute(sa.text("SELECT config_ciphertext, version FROM channel_runtime_configs WHERE provider='telegram'"))).one() == ("synthetic-ciphertext", 7)
    finally:
        await engine.dispose()
