from __future__ import annotations

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

os.environ.setdefault("DEER_FLOW_CONFIG_PATH", str(Path(__file__).resolve().parents[2] / "config.example.yaml"))

from sqlalchemy import inspect
from store.persistence import create_persistence_from_database_config
from store.repositories import UserCreate, build_user_repository


def test_sqlite_persistence_from_database_config_creates_storage_tables(tmp_path):
    async def run() -> None:
        persistence = await create_persistence_from_database_config(
            SimpleNamespace(
                backend="sqlite",
                sqlite_dir=str(tmp_path),
                echo_sql=False,
                pool_size=5,
            )
        )
        assert persistence is not None
        try:
            await persistence.setup()

            async with persistence.engine.connect() as conn:
                tables = await conn.run_sync(lambda sync_conn: set(inspect(sync_conn).get_table_names()))

            assert {
                "users",
                "runs",
                "run_events",
                "threads_meta",
                "feedback",
            }.issubset(tables)

            async with persistence.session_factory() as session:
                repo = build_user_repository(session)
                user = await repo.create_user(
                    UserCreate(
                        id=str(uuid4()),
                        email="storage-user@example.com",
                        password_hash="hash",
                    )
                )
                await session.commit()

            async with persistence.session_factory() as session:
                repo = build_user_repository(session)
                assert await repo.get_user_by_id(user.id) == user
        finally:
            await persistence.aclose()

    asyncio.run(run())
