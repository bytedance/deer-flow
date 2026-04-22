"""db connection string helpers for backends."""

from __future__ import annotations

import glob
import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
import pathlib
from typing import Any

from deerflow.config.paths import resolve_path

# Single unquoted PostgreSQL identifier (schema name).
_SCHEMA_OK = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
_COLL_OK = re.compile(r"^[a-zA-Z0-9_-]{1,120}$")
_PREFIX_OK = re.compile(r"^[a-zA-Z0-9_:.-]{1,200}$")

def _matches_filter(value: dict[str, Any], flt: dict[str, Any] | None) -> bool:
    if not flt:
        return True
    return all(value.get(k) == v for k, v in flt.items())

def validate_mongo_collection_name(name: str) -> str:
    n = str(name).strip()
    if not _COLL_OK.match(n):
        raise ValueError(
            f"Invalid mongo collection name {name!r}: use 1–120 chars of letters, digits, underscore, hyphen."
        )
    return n

def validate_redis_key_prefix(prefix: str) -> str:
    p = str(prefix).strip()
    if not _PREFIX_OK.match(p):
        raise ValueError(
            f"Invalid redis_key_prefix {prefix!r}: use 1–200 chars of letters, digits, underscore, colon, dot, hyphen."
        )
    return p

def sanitize_sqlite_path_segment(value: str, *, kind: str = "segment") -> str:
    """Make a single path component safe for use under a base checkpoint/store directory.

    Rejects empty values, path separators, and ``..`` so resolved paths cannot
    escape the intended tree (e.g. ``.deer-flow/{user_id}/{thread_id}/db.sqlite``).
    """
    t = str(value).strip()
    if not t:
        raise ValueError(f"Invalid empty {kind} for SQLite path segment")
    if ".." in t or "/" in t or "\\" in t or "\x00" in t:
        raise ValueError(
            f"Invalid {kind} for SQLite path segment (no '/', '\\\\', '..', or NUL): {value!r}"
        )
    if len(t) > 200:
        raise ValueError(f"Invalid {kind}: exceeds 200 characters")
    return t


def resolve_sqlite_conn_str(
    raw: str,
    *,
    user_id: str | None = None,
    thread_id: str | None = None,
) -> str:
    """Return a SQLite connection string ready for use with store/checkpointer backends.

    SQLite special strings (``":memory:"`` and ``file:`` URIs) are returned
    unchanged.  Plain filesystem paths — relative or absolute — are resolved
    to an absolute string via :func:`resolve_path`.

    **Per-user / per-thread files:** include placeholders in the path, for example::

        .deer-flow/checkpoints/{user_id}/{thread_id}/state.db

    Then call with ``user_id=...`` and ``thread_id=...``. Each segment is
    sanitized with :func:`sanitize_sqlite_path_segment`. Placeholders can be
    used independently (only ``{user_id}``, only ``{thread_id}``, or both).

    Note: the gateway opens **one** global checkpointer at startup; paths with
    placeholders are not valid there unless you resolve them per request with
    a different lifecycle (e.g. postgres for shared multi-tenant checkpoints).
    """
    s = str(raw).strip()
    if s == ":memory:" or s.startswith("file:"):
        return s
    needs_uid = "{user_id}" in s
    needs_tid = "{thread_id}" in s
    if needs_uid:
        if user_id is None or not str(user_id).strip():
            raise ValueError(
                "SQLite path contains {user_id}; pass user_id= to resolve_sqlite_conn_str(...)"
            )
        s = s.replace("{user_id}", sanitize_sqlite_path_segment(user_id, kind="user_id"))
    if needs_tid:
        if thread_id is None or not str(thread_id).strip():
            raise ValueError(
                "SQLite path contains {thread_id}; pass thread_id= to resolve_sqlite_conn_str(...)"
            )
        s = s.replace("{thread_id}", sanitize_sqlite_path_segment(thread_id, kind="thread_id"))
    return str(resolve_path(s))


def assert_sqlite_path_no_user_thread_placeholders(raw: str | None, *, role: str) -> str:
    """Reject ``{user_id}`` / ``{thread_id}`` for singleton (app-lifetime) sqlite backends."""
    t = (raw or "store.db").strip()
    if "{user_id}" in t or "{thread_id}" in t:
        raise ValueError(
            f"{role}: sqlite path must not contain {{user_id}} or {{thread_id}} when opening a single "
            f"global connection. Use a fixed path, postgres, or resolve_sqlite_conn_str(..., user_id=..., "
            f"thread_id=...) in a per-request code path."
        )
    return t


def resolve_per_user_thread_sqlite_conn_str(
    raw: str,
    *,
    user_id: str,
    thread_id: str,
) -> str:
    """Resolve a per-user/per-thread SQLite path.

    If *raw* already contains ``{user_id}`` / ``{thread_id}``, those placeholders
    are expanded. Otherwise a plain filesystem path like ``checkpoints.db`` is
    nested under ``{user_id}/{thread_id}/`` before being resolved against
    ``base_dir``.
    """
    s = str(raw).strip()
    if s == ":memory:" or s.startswith("file:"):
        return s
    if "{user_id}" in s or "{thread_id}" in s:
        return resolve_sqlite_conn_str(s, user_id=user_id, thread_id=thread_id)

    safe_user = sanitize_sqlite_path_segment(user_id, kind="user_id")
    safe_thread = sanitize_sqlite_path_segment(thread_id, kind="thread_id")
    p = pathlib.Path(s)
    if p.is_absolute():
        nested = p.parent / safe_user / safe_thread / p.name
        return str(nested.resolve())
    return str(resolve_path(str(pathlib.Path(safe_user) / safe_thread / p)))


def iter_per_user_thread_sqlite_conn_strs(raw: str) -> list[str]:
    """Return existing per-user/per-thread SQLite files for *raw* template/path."""
    s = str(raw).strip()
    if s == ":memory:" or s.startswith("file:"):
        return [s]

    if "{user_id}" in s or "{thread_id}" in s:
        pattern = s.replace("{user_id}", "*").replace("{thread_id}", "*")
        if not pathlib.Path(pattern).is_absolute():
            pattern = str(resolve_path(pattern))
    else:
        p = pathlib.Path(s)
        if p.is_absolute():
            pattern = str(p.parent / "*" / "*" / p.name)
        else:
            pattern = str(resolve_path(str(pathlib.Path("*") / "*" / p)))

    return sorted(str(pathlib.Path(path).resolve()) for path in glob.glob(pattern) if pathlib.Path(path).is_file())


def ensure_sqlite_parent_dir(conn_str: str) -> None:
    """Create parent directory for a SQLite filesystem path.

    No-op for in-memory databases (``":memory:"``) and ``file:`` URIs.
    """
    if conn_str != ":memory:" and not conn_str.startswith("file:"):
        pathlib.Path(conn_str).parent.mkdir(parents=True, exist_ok=True)


def validate_postgres_identifier(name: str, *, kind: str = "identifier") -> str:
    """Validate a single unquoted PostgreSQL identifier (schema, table, etc.)."""
    n = str(name).strip()
    if not _SCHEMA_OK.match(n):
        raise ValueError(
            f"Invalid postgres {kind} {name!r}: use one unquoted SQL identifier "
            "(ASCII letters, digits, underscore; must not start with a digit)."
        )
    return n


def apply_postgres_schema_to_conn_string(conn_string: str, schema: str | None) -> str:
    """Return a DSN that sets ``search_path`` so unqualified DDL/DML hits the given schema.

    LangGraph's checkpoint and store packages use unqualified table names; PostgreSQL
    resolves them via ``search_path``. We append ``schema,public`` so shared extensions
    in ``public`` remain visible if needed.

    Merges with the ``options`` query parameter on the URL when present.
    """
    if not schema or not str(schema).strip():
        return conn_string
    name = validate_postgres_identifier(schema, kind="schema")
    parts = urlparse(conn_string)
    q = list(parse_qsl(parts.query, keep_blank_values=True))
    suffix = f"-csearch_path={name},public"
    replaced = False
    for i, (key, val) in enumerate(q):
        if key == "options":
            merged = f"{suffix} {val}".strip() if val else suffix
            q[i] = (key, merged)
            replaced = True
            break
    if not replaced:
        q.append(("options", suffix))
    new_query = urlencode(q)
    return urlunparse(parts._replace(query=new_query))


def ensure_postgres_schema_exists(conn_string: str, schema: str | None) -> None:
    """Create the PostgreSQL schema when ``postgres_schema`` is set and it is missing.

    Uses the raw DSN (no ``search_path`` URL options) so this completes even when
    the schema is not yet on ``search_path``. Idempotent: ``IF NOT EXISTS``.
    Requires a DB role with ``CREATE`` on the database (or schema creation rights).
    """
    if not schema or not str(schema).strip():
        return
    name = validate_postgres_identifier(schema, kind="schema")
    raw = str(conn_string).strip()
    import psycopg
    from psycopg import sql as pgsql

    with psycopg.connect(raw) as conn:
        with conn.cursor() as cur:
            cur.execute(pgsql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(pgsql.Identifier(name)))
        conn.commit()
