"""Share payloads and their copied artifacts live in the application database."""

from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, Index, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.persistence.base import Base


class ThreadShareRow(Base):
    __tablename__ = "thread_shares"

    share_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    thread_id: Mapped[str] = mapped_column(String(64), ForeignKey("threads_meta.thread_id", ondelete="CASCADE"), nullable=False)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False)
    incarnation: Mapped[str | None] = mapped_column(String(32))
    checkpoint_id: Mapped[str] = mapped_column(String(128), nullable=False)
    seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_thread_shares_owner_thread", "owner_id", "thread_id"),)


class ShareArtifactRow(Base):
    __tablename__ = "share_artifacts"

    share_id: Mapped[str] = mapped_column(String(32), ForeignKey("thread_shares.share_id", ondelete="CASCADE"), primary_key=True)
    path: Mapped[str] = mapped_column(String(1024), primary_key=True)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
