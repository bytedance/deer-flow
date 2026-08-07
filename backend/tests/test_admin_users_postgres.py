"""Optional live PostgreSQL concurrency coverage for admin role changes.

Set ``TEST_POSTGRES_URI`` (or ``DEERFLOW_TEST_POSTGRES_URL``) to exercise the
same database-wide advisory lock used by multi-worker deployments.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.gateway.auth.models import User
from app.gateway.auth.repositories.base import LastAdminError
from app.gateway.auth.repositories.sqlite import SQLiteUserRepository
from deerflow.persistence.base import Base
from deerflow.persistence.user.model import UserRow

POSTGRES_URL = os.environ.get("TEST_POSTGRES_URI") or os.environ.get("DEERFLOW_TEST_POSTGRES_URL")

pytestmark = pytest.mark.skipif(
    not POSTGRES_URL,
    reason="set TEST_POSTGRES_URI to run live PostgreSQL admin-role concurrency tests",
)

_LIBPQ_ONLY_QUERY_KEYS = {"sslmode", "channel_binding"}


def _asyncpg_url(url: str) -> str:
    if url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://") :]
    elif url.startswith("postgresql+psycopg://"):
        url = "postgresql+asyncpg://" + url[len("postgresql+psycopg://") :]
    parts = urlsplit(url)
    if parts.query:
        kept = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key not in _LIBPQ_ONLY_QUERY_KEYS]
        url = urlunsplit(parts._replace(query=urlencode(kept)))
    return url


@pytest.mark.asyncio
async def test_two_independent_postgres_engines_cannot_demote_both_admins():
    """The advisory lock prevents write skew across worker-local pools."""
    assert POSTGRES_URL is not None
    url = _asyncpg_url(POSTGRES_URL)
    schema = f"deerflow_admin_roles_{uuid.uuid4().hex[:12]}"
    bootstrap_engine = create_async_engine(url)
    engine_a = None
    engine_b = None
    try:
        async with bootstrap_engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))

        connect_args = {"server_settings": {"search_path": schema}}
        engine_a = create_async_engine(url, connect_args=connect_args)
        engine_b = create_async_engine(url, connect_args=connect_args)
        async with engine_a.begin() as connection:
            await connection.run_sync(
                Base.metadata.create_all,
                tables=[UserRow.__table__],
                checkfirst=True,
            )

        repo_a = SQLiteUserRepository(async_sessionmaker(engine_a, expire_on_commit=False))
        repo_b = SQLiteUserRepository(async_sessionmaker(engine_b, expire_on_commit=False))
        admin_a = await repo_a.create_user(
            User(
                email="admin-a@example.com",
                password_hash="hash-a",
                system_role="admin",
            )
        )
        admin_b = await repo_a.create_user(
            User(
                email="admin-b@example.com",
                password_hash="hash-b",
                system_role="admin",
            )
        )

        results = await asyncio.gather(
            repo_a.change_user_role(
                actor_id=str(admin_a.id),
                user_id=str(admin_a.id),
                system_role="user",
            ),
            repo_b.change_user_role(
                actor_id=str(admin_b.id),
                user_id=str(admin_b.id),
                system_role="user",
            ),
            return_exceptions=True,
        )

        assert sum(result.changed is True for result in results if not isinstance(result, BaseException)) == 1
        assert sum(isinstance(result, LastAdminError) for result in results) == 1
        assert await repo_a.count_admin_users() == 1
    finally:
        if engine_a is not None:
            await engine_a.dispose()
        if engine_b is not None:
            await engine_b.dispose()
        try:
            async with bootstrap_engine.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        finally:
            await bootstrap_engine.dispose()
