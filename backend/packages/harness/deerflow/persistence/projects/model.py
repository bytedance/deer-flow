"""ORM models for projects.

``ProjectRow``: one row per user-owned project. ``id`` (uuid4 hex) is the only
external identity; ``name``/``presentation`` are display attributes — renaming
touches exactly this row and never affects membership (threads reference
``threads_meta.project_id``). ``instructions`` is user-authored project
context; Phase 1 stores and PATCHes it, Phase 2 injects it. There is
deliberately no ``memory_mode``/sharing/agent-config column: no consumer
exists in Phase 1/2 (RFC v2 §3, §4.1).

``ProjectDocumentRow``: one row per project shelf document. ``stored_relpath``
is a server-generated content address relative to ``users/{user_id}/projects/``
that embeds both ``sha256`` and the row's own ``id``, so rows never share
files and a re-upload after trash always lands in a fresh namespace. Text
detection is a sampled read at serve time, and the shelf has no history by
design — hence no ``mime``/``is_text``/``version``/``deleted_by`` columns
(Phase-2 spec §6.1). ``source_*`` records promotion provenance (Slice C);
``trashed_at``/``trash_origin`` implement the recoverable trash tier: every
read query filters ``trashed_at IS NULL`` so trashed rows are invisible to the
index, tools, and listing APIs.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Integer, String, Text
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


class ProjectDocumentRow(Base):
    __tablename__ = "project_documents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(255))
    stored_relpath: Mapped[str] = mapped_column(String)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    size_bytes: Mapped[int] = mapped_column(Integer)
    source_thread_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_kind: Mapped[str | None] = mapped_column(String(16), nullable=True)
    source_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    trashed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    trash_origin: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
