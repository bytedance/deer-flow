"""Shared validation for PostgreSQL schema names."""

from __future__ import annotations

import re

POSTGRES_SCHEMA_PATTERN = r"^[A-Za-z_][A-Za-z0-9_]{0,62}$"
_POSTGRES_SCHEMA_RE = re.compile(POSTGRES_SCHEMA_PATTERN)


def validate_postgres_schema(value: str) -> str:
    """Validate the v1 plain-identifier PostgreSQL schema contract."""
    if value == "":
        return value
    if not _POSTGRES_SCHEMA_RE.match(value):
        raise ValueError(
            "postgres_schema must be a plain PostgreSQL identifier "
            f"matching {POSTGRES_SCHEMA_PATTERN}; got {value!r}. "
            "Quoted identifiers are not supported."
        )
    return value
