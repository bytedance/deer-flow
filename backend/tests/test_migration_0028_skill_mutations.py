"""Additive Skill host schema and current migration-chain head."""

import asyncio

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.ext.asyncio import create_async_engine

from deerflow.persistence import bootstrap
from deerflow.persistence.run.model import RunRow

REVISION = "0028_skill_mutations"
TABLES = {"skill_mutation_assets", "skill_mutation_owners", "skill_mutation_proposals", "skill_mutation_operations", "skill_mutation_scan_attempts"}


def test_0028_is_the_chain_head():
    assert bootstrap._get_head_revision() == REVISION


@pytest.mark.asyncio
async def test_0028_additive_upgrade_and_nullable_recovery_metadata(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'skill-host.db'}")
    config = bootstrap._get_alembic_config(engine)
    try:
        await asyncio.to_thread(bootstrap._upgrade, config, "0027_completed_run_evidence")
        # The historical create_all bootstrap uses today's metadata. Remove
        # exactly the new, empty tables to represent a real 0027 installation.
        async with engine.begin() as connection:
            for table in sorted(TABLES):
                await connection.execute(sa.text(f'DROP TABLE IF EXISTS "{table}"'))
            await connection.execute(RunRow.__table__.insert().values(run_id="legacy", thread_id="thread", status="success"))
        await asyncio.to_thread(bootstrap._upgrade, config, REVISION)
        async with engine.connect() as connection:
            names = await connection.run_sync(lambda sync: sa.inspect(sync).get_table_names())
            assert TABLES <= set(names)
            columns = await connection.run_sync(lambda sync: sa.inspect(sync).get_columns("skill_mutation_operations"))
            nullable = {column["name"]: column["nullable"] for column in columns}
            assert nullable["before_operation_id"]
            assert nullable["superseded_by_generation"]
            assert await connection.scalar(sa.text("SELECT status FROM runs WHERE run_id='legacy'")) == "success"
        await asyncio.to_thread(command.downgrade, config, "0027_completed_run_evidence")
        async with engine.connect() as connection:
            names = await connection.run_sync(lambda sync: sa.inspect(sync).get_table_names())
            assert not TABLES.intersection(names)
            assert await connection.scalar(sa.text("SELECT status FROM runs WHERE run_id='legacy'")) == "success"
    finally:
        await engine.dispose()
