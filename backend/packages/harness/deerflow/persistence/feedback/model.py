"""ORM model for user feedback on runs."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.persistence.base import Base


class FeedbackRow(Base):
    __tablename__ = "feedback"

    feedback_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    thread_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    owner_id: Mapped[str | None] = mapped_column(String(64), index=True)
    message_id: Mapped[str | None] = mapped_column(String(64))
    # message_id is an optional RunEventStore event identifier —
    # allows feedback to target a specific message or the entire run

    rating: Mapped[int] = mapped_column(nullable=False)
    # +1 (thumbs-up) or -1 (thumbs-down)

    comment: Mapped[str | None] = mapped_column(Text)
    # Optional text feedback from the user

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
