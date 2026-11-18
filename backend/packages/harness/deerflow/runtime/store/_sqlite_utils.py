"""Shared SQLite connection utilities for store and checkpointer providers."""

from __future__ import annotations

import pathlib

from deerflow.config.paths import resolve_path


def resolve_sqlite_conn_str(raw: str) -> str:
    """Return a SQLite connection string ready for use with store/checkpointer backends.

    ``":memory:"`` is returned unchanged.  Plain filesystem paths — relative or
    absolute — are resolved to an absolute string via :func:`resolve_path`.

    SQLite ``file:`` URIs are rejected: LangGraph's ``from_conn_string``
    factories connect without ``uri=True``, so SQLite would open a file
    literally named after the URI in the working directory.

    Raises:
        ValueError: If *raw* is a SQLite ``file:`` URI.
    """
    if raw.startswith("file:"):
        raise ValueError(f"SQLite URI connection strings are not supported: {raw!r}. Set checkpointer.connection_string to a filesystem path or ':memory:'.")
    if raw == ":memory:":
        return raw
    return str(resolve_path(raw))


def ensure_sqlite_parent_dir(conn_str: str) -> None:
    """Create parent directory for a SQLite filesystem path.

    No-op for in-memory databases (``":memory:"``).
    """
    if conn_str != ":memory:":
        pathlib.Path(conn_str).parent.mkdir(parents=True, exist_ok=True)
