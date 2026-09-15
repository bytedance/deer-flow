"""add nullable thread incarnation columns.

Revision ID: 0019_thread_incarnations
Revises: 0021_batch_acceptance
Create Date: 2026-09-05

This is the expand-only schema step. Existing rows remain nullable and no
runtime behavior consumes either column in this phase.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from deerflow.persistence.migrations._helpers import safe_add_column, safe_drop_column

revision: str = "0019_thread_incarnations"
down_revision: str | Sequence[str] | None = "0021_batch_acceptance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SQLITE_BATCH_TABLES = (
    ("mcp_tasks", "_alembic_tmp_mcp_tasks"),
    ("threads_meta", "_alembic_tmp_threads_meta"),
)
_NULL_VARCHAR_CAST = re.compile(r"(?:character\s+varying|varchar|text)(?:\s*\(\s*\d+\s*\))?", re.IGNORECASE)


def _cleanup_sqlite_downgrade_retry() -> None:
    """Remove batch tables left by an interrupted prior downgrade attempt."""
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        return
    table_names = set(sa.inspect(bind).get_table_names())
    for source_name, temp_name in _SQLITE_BATCH_TABLES:
        if temp_name not in table_names:
            continue
        if source_name not in table_names:
            raise RuntimeError(f"Refusing to drop {temp_name}: {source_name} is missing and the batch table may be the only remaining copy")
        op.drop_table(temp_name)


def _is_null_server_default(value: object) -> bool:
    """Return whether reflection reports no default or a SQL NULL default."""
    if value is None:
        return True
    text = str(value).strip()
    while text.startswith("(") and text.endswith(")"):
        text = text[1:-1].strip()
    base, separator, cast = text.partition("::")
    while base.startswith("(") and base.endswith(")"):
        base = base[1:-1].strip()
    return base.casefold() == "null" and (not separator or _NULL_VARCHAR_CAST.fullmatch(cast.strip()) is not None)


def _assert_existing_column_compatible(table: str, column_name: str) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if table not in inspector.get_table_names():
        return
    existing = {column["name"]: column for column in inspector.get_columns(table)}
    actual = existing.get(column_name)
    if actual is None:
        return

    actual_type = actual.get("type")
    length = getattr(actual_type, "length", None)
    varchar_compatible = isinstance(actual_type, sa.VARCHAR) and (length is None or length >= 32)
    actual_nullable = actual.get("nullable", True)
    nullable_compatible = bool(actual_nullable)
    actual_default = actual.get("default")
    default_compatible = _is_null_server_default(actual_default)
    if not varchar_compatible or not nullable_compatible or not default_compatible:
        raise RuntimeError(
            f"Incompatible pre-existing column {table}.{column_name}: expected nullable VARCHAR(32) or wider with no default or DEFAULT NULL, got type={actual_type!r}, nullable={actual_nullable!r}, server_default={actual_default!r}"
        )


def upgrade() -> None:
    columns = (
        ("threads_meta", sa.Column("incarnation", sa.VARCHAR(length=32), nullable=True)),
        ("mcp_tasks", sa.Column("thread_incarnation", sa.VARCHAR(length=32), nullable=True)),
    )
    # Preflight every pre-existing column before changing either table. Expand
    # must not silently accept a narrow, non-VARCHAR, NOT NULL, or value-defaulted
    # manual column. In particular, finish both tables' preflight before DDL.
    for table, column in columns:
        _assert_existing_column_compatible(table, str(column.name))
    for table, column in columns:
        safe_add_column(table, column)


def downgrade() -> None:
    _cleanup_sqlite_downgrade_retry()
    safe_drop_column("mcp_tasks", "thread_incarnation")
    safe_drop_column("threads_meta", "incarnation")
