"""Extension-private declarative base.

The extension owns its schema end to end: its models must NOT register on the host's
``deerflow.persistence.base.Base``, or the host's empty-database ``create_all`` would
create the knowledge tables on installs that never enabled the extension (migrations
AGENTS.md, "Extension-owned tables"). Every table here carries :data:`TABLE_PREFIX`,
declared to the host as ``plugins[].table_prefix`` so the host's alembic autogenerate
excludes them instead of proposing to drop them.

The ``to_dict`` / ``__repr__`` helpers mirror the host base so the rows keep the same
surface the extension's stores and tests already rely on.
"""

from __future__ import annotations

from functools import cache

from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import DeclarativeBase

#: Table-name prefix this extension owns; also declared in the ``plugins:`` record.
TABLE_PREFIX = "kb_"


@cache
def _column_keys(cls: type) -> tuple[str, ...]:
    return tuple(c.key for c in sa_inspect(cls).mapper.column_attrs)


class Base(DeclarativeBase):
    """Base class for the knowledge extension's own ORM models."""

    def to_dict(self, *, exclude: set[str] | None = None) -> dict:
        """Convert the ORM instance to a plain dict of its mapped columns."""
        keys = _column_keys(type(self))
        if exclude:
            return {k: getattr(self, k) for k in keys if k not in exclude}
        return {k: getattr(self, k) for k in keys}

    def __repr__(self) -> str:
        cols = ", ".join(f"{k}={getattr(self, k)!r}" for k in _column_keys(type(self)))
        return f"{type(self).__name__}({cols})"
