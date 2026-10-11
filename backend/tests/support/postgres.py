"""Adapt libpq test URIs to SQLAlchemy's asyncpg connection options."""

from sqlalchemy.engine import make_url


def asyncpg_test_url(uri: str) -> str:
    url = make_url(uri)
    query = dict(url.query)
    if "sslmode" in query:
        sslmode = query.pop("sslmode")
        if "ssl" in query and query["ssl"] != sslmode:
            raise ValueError("Conflicting ssl and sslmode in the test PostgreSQL URI")
        query["ssl"] = sslmode
    query.pop("channel_binding", None)
    return url.set(drivername="postgresql+asyncpg", query=query).render_as_string(hide_password=False)
