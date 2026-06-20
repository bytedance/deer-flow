"""Base.to_dict()/__repr__ caching + behavior.

These run once per row when serializing ORM rows (e.g. every event in a
messages page), so the mapped-column reflection is cached per class. Behavior
must stay identical.
"""

from __future__ import annotations

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.persistence.base import Base, _column_keys


class _Widget(Base):
    __tablename__ = "_widget_to_dict_test"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(32))
    color: Mapped[str] = mapped_column(String(16))


def test_to_dict_returns_all_columns():
    w = _Widget(id=1, name="gear", color="red")
    assert w.to_dict() == {"id": 1, "name": "gear", "color": "red"}


def test_to_dict_exclude():
    w = _Widget(id=2, name="cog", color="blue")
    assert w.to_dict(exclude={"color"}) == {"id": 2, "name": "cog"}
    # Empty exclude behaves like no exclude.
    assert w.to_dict(exclude=set()) == {"id": 2, "name": "cog", "color": "blue"}


def test_column_keys_are_cached_per_class():
    # Same tuple object returned across calls -> reflection ran once.
    assert _column_keys(_Widget) is _column_keys(_Widget)
    assert _column_keys(_Widget) == ("id", "name", "color")


def test_repr_lists_columns():
    w = _Widget(id=3, name="bolt", color="green")
    r = repr(w)
    assert r.startswith("_Widget(")
    assert "id=3" in r and "name='bolt'" in r and "color='green'" in r
