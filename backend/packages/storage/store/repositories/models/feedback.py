from __future__ import annotations

from datetime import datetime

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from store.persistence.base_model import DataClassBase, TimeZone, UniversalText, id_key
from store.utils import get_timezone

_tz = get_timezone()


class Feedback(DataClassBase):
    """Feedback table (create-only, no updated_time)."""

    __tablename__ = "feedback"

    id: Mapped[id_key] = mapped_column(init=False)

    feedback_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    thread_id: Mapped[str] = mapped_column(String(64), index=True)
    rating: Mapped[int] = mapped_column(Integer)

    user_id: Mapped[str | None] = mapped_column(String(64), default=None, index=True)
    message_id: Mapped[str | None] = mapped_column(String(64), default=None)
    comment: Mapped[str | None] = mapped_column(UniversalText, default=None)

    created_time: Mapped[datetime] = mapped_column(
        TimeZone,
        init=False,
        default_factory=_tz.now,
        sort_order=999,
        comment="Created at",
    )