"""ORM model for projects.

One row per user-owned project. ``id`` (uuid4 hex) is the only external
identity; ``name``/``presentation`` are display attributes — renaming touches
exactly this row and never affects membership (threads reference
``threads_meta.project_id``). ``instructions`` is user-authored project
context; Phase 1 stores and PATCHes it, Phase 2 injects it. There is
deliberately no ``memory_mode``/sharing/agent-config column: no consumer
exists in Phase 1/2 (RFC v2 §3, §4.1).
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.persistence.base import Base


class ProjectRow(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(128))
    instructions: Mapped[str] = mapped_column(Text, default="")
    presentation: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
