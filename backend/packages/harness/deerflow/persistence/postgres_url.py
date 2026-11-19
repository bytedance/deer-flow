"""Adapt PostgreSQL URLs for the async ORM without weakening security options."""

from urllib.parse import parse_qs, urlsplit

from sqlalchemy.engine import make_url


def normalize_asyncpg_url(uri: str) -> str:
    """Translate libpq SSL modes and reject unsupported authentication options."""
    url = make_url(uri)
    if url.drivername not in {"postgres", "postgresql", "postgresql+asyncpg"}:
        raise ValueError("Expected a PostgreSQL URL for asyncpg")
    # SQLAlchemy drops blank query values; validate security options before
    # an explicit empty setting could be mistaken for a missing setting.
    options = parse_qs(urlsplit(uri).query, keep_blank_values=True)
    if "channel_binding" in options:
        raise ValueError("channel_binding is not supported by asyncpg")
    for key in ("ssl", "sslmode"):
        values = options.get(key)
        if values is not None and (len(values) != 1 or values[0] not in {"disable", "allow", "prefer", "require", "verify-ca", "verify-full"}):
            raise ValueError(f"Invalid or repeated {key} in PostgreSQL URL")
    query = dict(url.query)
    if "sslmode" in query:
        mode = query.pop("sslmode")
        if "ssl" in query and query["ssl"] != mode:
            raise ValueError("Conflicting ssl and sslmode in PostgreSQL URL")
        query["ssl"] = mode
    return url.set(drivername="postgresql+asyncpg", query=query).render_as_string(hide_password=False)
