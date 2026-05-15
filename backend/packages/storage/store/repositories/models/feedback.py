from __future__ import annotations

from datetime import datetime

from sqlalchemy import Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from store.persistence.base_model import DataClassBase, TimeZone, UniversalText, current_time


class Feedback(DataClassBase):
    """Feedback table (create-only, no updated_time)."""

    __tablename__ = "feedback"
    __table_args__ = (
        UniqueConstraint("thread_id", "run_id", "user_id", name="uq_feedback_thread_run_user"),
        {"comment": "Feedback table."},
    )

    feedback_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    thread_id: Mapped[str] = mapped_column(String(64), index=True)
    rating: Mapped[int] = mapped_column(Integer)

    user_id: Mapped[str | None] = mapped_column(String(64), default=None, index=True)
    message_id: Mapped[str | None] = mapped_column(String(64), default=None)
    comment: Mapped[str | None] = mapped_column(UniversalText, default=None)

    created_time: Mapped[datetime] = mapped_column(
        "created_at",
        TimeZone,
        init=False,
        default_factory=current_time,
        sort_order=999,
        comment="Created at",
    )
