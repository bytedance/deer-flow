from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from store.persistence.base_model import DataClassBase, TimeZone, current_time


class ThreadMeta(DataClassBase):
    """Thread metadata table."""

    __tablename__ = "threads_meta"
    __table_args__ = {"comment": "Thread metadata table."}

    thread_id: Mapped[str] = mapped_column(String(64), primary_key=True)

    assistant_id: Mapped[str | None] = mapped_column(String(128), default=None, index=True)
    user_id: Mapped[str | None] = mapped_column(String(64), default=None, index=True)
    display_name: Mapped[str | None] = mapped_column(String(256), default=None)
    status: Mapped[str] = mapped_column(String(20), default="idle", index=True)

    meta: Mapped[dict[str, Any]] = mapped_column("metadata_json", JSON, default_factory=dict)

    created_time: Mapped[datetime] = mapped_column(
        "created_at",
        TimeZone,
        init=False,
        default_factory=current_time,
        sort_order=999,
        comment="Created at",
    )
    updated_time: Mapped[datetime | None] = mapped_column(
        "updated_at",
        TimeZone,
        init=False,
        default=None,
        onupdate=current_time,
        sort_order=999,
        comment="Updated at",
    )
