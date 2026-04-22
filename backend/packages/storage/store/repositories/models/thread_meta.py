from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from store.persistence.base_model import Base, id_key


class ThreadMeta(Base):
    """Thread metadata table."""

    __tablename__ = "thread_meta"

    id: Mapped[id_key] = mapped_column(init=False)

    thread_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    assistant_id: Mapped[str | None] = mapped_column(String(64), default=None)
    user_id: Mapped[str | None] = mapped_column(String(64), default=None, index=True)
    display_name: Mapped[str | None] = mapped_column(String(255), default=None)
    status: Mapped[str] = mapped_column(String(32), default="idle", index=True)

    meta: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default_factory=dict)