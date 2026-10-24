"""IM opt-outs migrate independently of auth users and browser preferences."""

import asyncio
import json
import os
import subprocess
import sys
import textwrap
import uuid

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.ext.asyncio import create_async_engine
from support.postgres import asyncpg_test_url

from deerflow.persistence import bootstrap
from deerflow.persistence.base import Base
from deerflow.persistence.postgres_schema import build_asyncpg_connect_args
from deerflow.persistence.user.model import UserPreferenceRow, UserRow

REVISION = "0041_im_notice_preferences"
PREVIOUS = "0040_scheduled_group_notice"
TABLE = "im_notification_preferences"


def test_im_notice_preferences_follow_0040_in_the_single_chain():
    script = ScriptDirectory(str(bootstrap._MIGRATIONS_DIR))
    assert len(script.get_heads()) == 1
    assert REVISION in {revision.revision for revision in script.walk_revisions()}
    assert script.get_revision(REVISION).down_revision == PREVIOUS
    assert len(REVISION) <= 32


def _engine(tmp_path, backend):
    if backend == "postgres":
        uri = os.environ.get("TEST_POSTGRES_URI")
        if not uri:
            pytest.skip("requires TEST_POSTGRES_URI (real Postgres migration 0041)")
        schema = f"im_notice_{uuid.uuid4().hex}"
        return create_async_engine(asyncpg_test_url(uri), connect_args=build_asyncpg_connect_args(schema)), schema
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'migration.db'}")

    @sa.event.listens_for(engine.sync_engine, "connect")
    def enable_foreign_keys(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine, None


def _schema_diff(connection):
    # Import only through the production registration module, not the new model.
    import deerflow.persistence.models  # noqa: F401

    context = MigrationContext.configure(
        connection,
        opts={
            "include_object": lambda _obj, name, type_, _reflected, _compare_to: type_ != "table" or name == TABLE,
            "compare_type": True,
            "compare_server_default": True,
        },
    )
    return compare_metadata(context, Base.metadata)


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
async def test_im_preferences_upgrade_retry_downgrade_and_schema_parity(tmp_path, backend):
    engine, schema = _engine(tmp_path, backend)
    cfg = bootstrap._get_alembic_config(engine, postgres_schema=schema or "")
    try:
        if schema:
            async with engine.begin() as connection:
                await connection.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
        await asyncio.to_thread(command.upgrade, cfg, PREVIOUS)
        async with engine.begin() as connection:
            assert not await connection.run_sync(lambda conn: sa.inspect(conn).has_table(TABLE))
            await connection.execute(sa.insert(UserRow).values(id="alice", email="alice@example.test"))
            await connection.execute(sa.insert(UserPreferenceRow).values(user_id="alice", key="notification_enabled", value=False))

        await asyncio.to_thread(command.upgrade, cfg, REVISION)
        async with engine.begin() as connection:
            if backend == "sqlite":
                assert (await connection.execute(sa.text("PRAGMA foreign_keys"))).scalar_one() == 1
            shape = await connection.run_sync(lambda conn: sa.inspect(conn).get_columns(TABLE))
            assert {column["name"] for column in shape} == {"owner_user_id", "provider", "enabled"}
            assert all(column["nullable"] is False for column in shape)
            assert await connection.run_sync(lambda conn: sa.inspect(conn).get_pk_constraint(TABLE)["constrained_columns"]) == ["owner_user_id", "provider"]
            assert await connection.run_sync(lambda conn: sa.inspect(conn).get_foreign_keys(TABLE)) == []
            assert await connection.run_sync(_schema_diff) == []
            # No fake auth row is needed, even when SQLite enforces foreign keys.
            assert (await connection.execute(sa.select(UserRow.id).where(UserRow.id == "default"))).scalar_one_or_none() is None
            await connection.execute(sa.text(f"INSERT INTO {TABLE} (owner_user_id,provider,enabled) VALUES ('default','feishu',false)"))
            # The durable server default, not an ORM client default, preserves opt-in.
            await connection.execute(sa.text(f"INSERT INTO {TABLE} (owner_user_id,provider) VALUES ('default','wecom')"))

        with pytest.raises(sa.exc.IntegrityError):
            async with engine.begin() as connection:
                await connection.execute(sa.text(f"INSERT INTO {TABLE} (owner_user_id,provider) VALUES ('default','feishu')"))

        # Simulate retry after DDL/data committed but revision stamping did not.
        await asyncio.to_thread(command.stamp, cfg, PREVIOUS)
        await asyncio.to_thread(command.upgrade, cfg, REVISION)
        async with engine.connect() as connection:
            assert (await connection.execute(sa.text(f"SELECT provider,enabled FROM {TABLE} ORDER BY provider"))).all() == [("feishu", False), ("wecom", True)]
            assert (await connection.execute(sa.select(UserPreferenceRow.value).where(UserPreferenceRow.user_id == "alice"))).scalar_one() is False

        await asyncio.to_thread(command.downgrade, cfg, PREVIOUS)
        async with engine.connect() as connection:
            assert not await connection.run_sync(lambda conn: sa.inspect(conn).has_table(TABLE))
            assert (await connection.execute(sa.select(UserPreferenceRow.value).where(UserPreferenceRow.user_id == "alice"))).scalar_one() is False
        # Retrying a completed downgrade is also harmless.
        await asyncio.to_thread(command.stamp, cfg, REVISION)
        await asyncio.to_thread(command.downgrade, cfg, PREVIOUS)
        await asyncio.to_thread(command.upgrade, cfg, REVISION)
        async with engine.connect() as connection:
            assert await connection.run_sync(_schema_diff) == []
            assert (await connection.execute(sa.text(f"SELECT COUNT(*) FROM {TABLE}"))).scalar_one() == 0
            assert (await connection.execute(sa.select(UserRow.id).where(UserRow.id == "default"))).scalar_one_or_none() is None
    finally:
        if schema:
            async with engine.begin() as connection:
                await connection.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()


def test_fresh_bootstrap_registers_preferences_without_an_auth_user(tmp_path):
    # Fresh interpreter: another collected test must not accidentally register
    # the model and hide a missing import from persistence.models.
    program = textwrap.dedent("""
        import asyncio, json, sys
        import sqlalchemy as sa
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
        from deerflow.persistence import bootstrap

        async def main():
            engine = create_async_engine(f"sqlite+aiosqlite:///{sys.argv[1]}")
            @sa.event.listens_for(engine.sync_engine, "connect")
            def foreign_keys(connection, _):
                cursor = connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()
            try:
                await bootstrap.bootstrap_schema(engine, backend="sqlite")
                await bootstrap.bootstrap_schema(engine, backend="sqlite")
                async with engine.connect() as connection:
                    assert (await connection.execute(sa.text("PRAGMA foreign_keys"))).scalar_one() == 1
                    assert await connection.run_sync(lambda conn: sa.inspect(conn).has_table("im_notification_preferences"))
                    assert (await connection.execute(sa.text("SELECT COUNT(*) FROM users"))).scalar_one() == 0
                from deerflow.persistence.user.im_notifications import ImNotificationPreferencesRepository
                repo = ImNotificationPreferencesRepository(async_sessionmaker(engine, expire_on_commit=False))
                assert (await repo.patch("default", {"qq": False}))["qq"] is False
                assert (await repo.get("default"))["qq"] is False
                async with engine.connect() as connection:
                    assert (await connection.execute(sa.text("SELECT COUNT(*) FROM users"))).scalar_one() == 0
                print(json.dumps({"fresh_bootstrap": True, "synthetic_owner_without_auth_row": True}))
            finally:
                await engine.dispose()
        asyncio.run(main())
    """)
    result = subprocess.run([sys.executable, "-c", program, str(tmp_path / "fresh.db")], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.strip()) == {"fresh_bootstrap": True, "synthetic_owner_without_auth_row": True}
