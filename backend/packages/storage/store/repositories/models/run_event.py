from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from store.persistence.base_model import DataClassBase, TimeZone, UniversalText, id_key
from store.utils import get_timezone

_tz = get_timezone()


class RunEvent(DataClassBase):
    """Run event table."""

    __tablename__ = "run_events"
    __table_args__ = (
        UniqueConstraint("thread_id", "seq", name="uq_run_events_thread_seq"),
        {"comment": "Run event table."},
    )

    id: Mapped[id_key] = mapped_column(init=False)

    thread_id: Mapped[str] = mapped_column(String(64), index=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    seq: Mapped[int] = mapped_column(Integer, index=True)

    event_type: Mapped[str] = mapped_column(String(128), index=True)
    category: Mapped[str] = mapped_column(String(64), index=True)
    content: Mapped[str] = mapped_column(UniversalText, default="")
    meta: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default_factory=dict)
    created_at: Mapped[datetime] = mapped_column(
        TimeZone,
        init=False,
        default_factory=_tz.now,
        sort_order=999,
        comment="Event timestamp",
    )
