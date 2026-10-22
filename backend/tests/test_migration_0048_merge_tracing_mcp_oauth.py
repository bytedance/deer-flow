"""Both published 0047 histories upgrade without losing their durable data."""

import asyncio

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.ext.asyncio import create_async_engine

from deerflow.persistence import bootstrap
from deerflow.persistence.run.model import RunRow

HEAD = "0049_tracing_retention"
TRACING = "0047_tracing_profiles"
OAUTH = "0047_mcp_oauth_tokens"
pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("previous", ["0046_skill_mutations", TRACING, OAUTH])
async def test_bootstrap_joins_either_0047_history_and_preserves_data(tmp_path, monkeypatch, previous):
    monkeypatch.setattr(bootstrap, "_HEAD_REVISION", None)
    monkeypatch.setattr(bootstrap, "_KNOWN_REVISIONS", None)
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'upgrade.db'}")
    cfg = bootstrap._get_alembic_config(engine)
    try:
        await asyncio.to_thread(command.upgrade, cfg, previous)
        async with engine.begin() as connection:
            await connection.execute(RunRow.__table__.insert().values(run_id="retained-run", thread_id="retained-thread", status="success"))
            if previous == TRACING:
                await connection.execute(sa.text("INSERT INTO tracing_profiles VALUES ('retained-profile', 'Profile', 7, 'retained-ciphertext', '[]')"))
                await connection.execute(sa.text("UPDATE tracing_admission_fence SET version=19 WHERE id=1"))
            if previous == OAUTH:
                await connection.execute(
                    sa.text(
                        "INSERT INTO mcp_oauth_tokens (scope, owner_user_id, server_key, config_fingerprint, access_token_enc, version, updated_at) "
                        "VALUES ('deployment', '', 'retained-server', 'fingerprint', 'retained-token', 8, 1700000000)"
                    )
                )
        await bootstrap.bootstrap_schema(engine, backend="sqlite")
        await bootstrap.bootstrap_schema(engine, backend="sqlite")
        async with engine.connect() as connection:
            tables = set(await connection.run_sync(lambda sync: sa.inspect(sync).get_table_names()))
            assert {"mcp_oauth_tokens", "tracing_profiles", "run_tracing_snapshots", "agent_tracing_bindings", "tracing_admission_fence"} <= tables
            assert (await connection.execute(sa.text("SELECT version_num FROM alembic_version"))).all() == [(HEAD,)]
            assert await connection.scalar(sa.text("SELECT status FROM runs WHERE run_id='retained-run'")) == "success"
            if previous == TRACING:
                assert (await connection.execute(sa.text("SELECT revision, providers_ciphertext FROM tracing_profiles WHERE id='retained-profile'"))).one() == (7, "retained-ciphertext")
                assert await connection.scalar(sa.text("SELECT version FROM tracing_admission_fence WHERE id=1")) == 19
            if previous == OAUTH:
                assert (await connection.execute(sa.text("SELECT version, access_token_enc FROM mcp_oauth_tokens WHERE server_key='retained-server'"))).one() == (8, "retained-token")
            assert await connection.scalar(sa.text("SELECT count(*) FROM tracing_admission_fence WHERE id=1")) == 1
    finally:
        await engine.dispose()


async def test_empty_database_bootstraps_both_branches_at_one_head(tmp_path, monkeypatch):
    monkeypatch.setattr(bootstrap, "_HEAD_REVISION", None)
    monkeypatch.setattr(bootstrap, "_KNOWN_REVISIONS", None)
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'fresh.db'}")
    try:
        await bootstrap.bootstrap_schema(engine, backend="sqlite")
        async with engine.connect() as connection:
            assert (await connection.execute(sa.text("SELECT version_num FROM alembic_version"))).all() == [(HEAD,)]
            assert await connection.scalar(sa.text("SELECT count(*) FROM tracing_admission_fence WHERE id=1")) == 1
            tables = set(await connection.run_sync(lambda sync: sa.inspect(sync).get_table_names()))
            assert {"mcp_oauth_tokens", "tracing_profiles"} <= tables
    finally:
        await engine.dispose()
