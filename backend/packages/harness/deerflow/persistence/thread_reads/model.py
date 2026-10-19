"""ORM models for per-user thread read markers and the per-user read clock.

A marker stores the highest ``runs.change_seq`` of a thread the user has seen;
a thread is unread while a server-originated run of that user changed after
it. ``thread_read_versions`` is a per-user counter raised whenever a marker
moves forward, so another device notices a read without a run change.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import BigInteger, DateTime, Index, PrimaryKeyConstraint, String, text
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.persistence.base import Base


class ThreadReadMarkerRow(Base):
    __tablename__ = "thread_read_markers"

    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    thread_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # Never moves backwards: concurrent reads from several devices keep the max.
    seen_change_seq: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default=text("0"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))

    __table_args__ = (
        PrimaryKeyConstraint("user_id", "thread_id", name="pk_thread_read_markers"),
        Index("ix_thread_read_markers_thread_id", "thread_id"),
    )


class ThreadReadVersionRow(Base):
    __tablename__ = "thread_read_versions"

    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default=text("0"))

    __table_args__ = (PrimaryKeyConstraint("user_id", name="pk_thread_read_versions"),)
