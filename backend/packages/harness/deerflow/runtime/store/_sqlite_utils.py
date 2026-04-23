"""Shared SQLite connection utilities for store and checkpointer providers."""

from __future__ import annotations

import pathlib

from deerflow.config.paths import resolve_path


# def resolve_sqlite_conn_str(raw: str) -> str:
#     """Return a SQLite connection string ready for use with store/checkpointer backends.
#
#     SQLite special strings (``":memory:"`` and ``file:`` URIs) are returned
#     unchanged.  Plain filesystem paths — relative or absolute — are resolved
#     to an absolute string via :func:`resolve_path`.
#     """
#     if raw == ":memory:" or raw.startswith("file:"):
#         return raw
#     return str(resolve_path(raw))

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


def ensure_sqlite_parent_dir(conn_str: str) -> None:
    """Create parent directory for a SQLite filesystem path.

    No-op for in-memory databases (``":memory:"``) and ``file:`` URIs.
    """
    if conn_str != ":memory:" and not conn_str.startswith("file:"):
        pathlib.Path(conn_str).parent.mkdir(parents=True, exist_ok=True)
