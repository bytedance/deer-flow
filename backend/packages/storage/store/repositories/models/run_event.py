from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from store.persistence.base_model import (
    DataClassBase,
    TimeZone,
    UniversalText,
    current_time,
    id_key,
)


class RunEvent(DataClassBase):
    """Run event table."""

    __tablename__ = "run_events"
    __table_args__ = (
        UniqueConstraint("thread_id", "seq", name="uq_events_thread_seq"),
        Index("ix_events_thread_cat_seq", "thread_id", "category", "seq"),
        Index("ix_events_run", "thread_id", "run_id", "seq"),
        {"comment": "Run event table."},
    )

    id: Mapped[id_key] = mapped_column(init=False)

    thread_id: Mapped[str] = mapped_column(String(64), index=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    event_type: Mapped[str] = mapped_column(String(32), index=True)
    category: Mapped[str] = mapped_column(String(16), index=True)

    user_id: Mapped[str | None] = mapped_column(String(64), default=None, index=True)
    seq: Mapped[int] = mapped_column(BigInteger, default=0, index=True)
    content: Mapped[str] = mapped_column(UniversalText, default="")
    meta: Mapped[dict[str, Any]] = mapped_column("event_metadata", JSON, default_factory=dict)
    created_at: Mapped[datetime] = mapped_column(
        TimeZone,
        init=False,
        default_factory=current_time,
        sort_order=999,
        comment="Event timestamp",
    )
