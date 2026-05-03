"""SQLAlchemy declarative base with automatic to_dict support.

All DeerFlow ORM models inherit from this Base. It provides a generic
to_dict() method via SQLAlchemy's inspect() so individual models don't
need to write their own serialization logic.

LangGraph's checkpointer tables are NOT managed by this Base.
"""

from __future__ import annotations

from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all DeerFlow ORM models.

    Provides:
    - Automatic to_dict() via SQLAlchemy column inspection.
    - Standard __repr__() showing all column values.
    """

    def to_dict(self, *, exclude: set[str] | None = None) -> dict:
        """Convert ORM instance to plain dict.

        Uses SQLAlchemy's inspect() to iterate mapped column attributes.

        Args:
            exclude: Optional set of column keys to omit.

        Returns:
            Dict of {column_key: value} for all mapped columns.
        """
        exclude = exclude or set()
        return {c.key: getattr(self, c.key) for c in sa_inspect(type(self)).mapper.column_attrs if c.key not in exclude}

    def __repr__(self) -> str:
        cols = ", ".join(f"{c.key}={getattr(self, c.key)!r}" for c in sa_inspect(type(self)).mapper.column_attrs)
        return f"{type(self).__name__}({cols})"
