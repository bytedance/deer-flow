"""Adapt libpq test URIs to SQLAlchemy's asyncpg connection options."""

from deerflow.persistence.postgres_url import normalize_asyncpg_url


def asyncpg_test_url(uri: str) -> str:
    return normalize_asyncpg_url(uri)
