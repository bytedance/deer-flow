"""SQLAlchemy declarative base with automatic to_dict support.

All DeerFlow ORM models inherit from this Base. It provides a generic
to_dict() method via SQLAlchemy's inspect() so individual models don't
need to write their own serialization logic.

LangGraph's checkpointer tables are NOT managed by this Base.
"""

from __future__ import annotations

from functools import cache

from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import DeclarativeBase


@cache
def _column_keys(cls: type) -> tuple[str, ...]:
    """Mapped column keys for an ORM class, in mapper order.

    ``to_dict``/``__repr__`` run per row (e.g. once per event when serializing a
    messages page), so the SQLAlchemy mapper reflection is cached per class —
    the mapping is fixed at class-definition time, so this never goes stale.
    """
    return tuple(c.key for c in sa_inspect(cls).mapper.column_attrs)


class Base(DeclarativeBase):
    """Base class for all DeerFlow ORM models.

    Provides:
    - Automatic to_dict() via SQLAlchemy column inspection.
    - Standard __repr__() showing all column values.
    """

    def to_dict(self, *, exclude: set[str] | None = None) -> dict:
        """Convert ORM instance to plain dict.

        Uses cached mapped-column keys (see :func:`_column_keys`).

        Args:
            exclude: Optional set of column keys to omit.

        Returns:
            Dict of {column_key: value} for all mapped columns.
        """
        keys = _column_keys(type(self))
        if exclude:
            return {k: getattr(self, k) for k in keys if k not in exclude}
        return {k: getattr(self, k) for k in keys}

    def __repr__(self) -> str:
        cols = ", ".join(f"{k}={getattr(self, k)!r}" for k in _column_keys(type(self)))
        return f"{type(self).__name__}({cols})"
