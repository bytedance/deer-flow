"""ORM model for the shared inbound webhook dedupe table (issue #4120).

A single row records that a particular inbound webhook (identified by the
``_inbound_dedupe_key`` 4-tuple) has already been dispatched, so a redelivery
routed to a different gateway pod is still dropped as a duplicate. Rows expire
via lazy cleanup (see ``PostgresInboundDedupeStore``), which deletes rows older
than ``INBOUND_DEDUPE_TTL_SECONDS`` using the ``first_seen`` column.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, PrimaryKeyConstraint, String, func
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.persistence.base import Base


class WebhookDeliveryRow(Base):
    __tablename__ = "webhook_deliveries"

    # Composite primary key mirrors ChannelManager._inbound_dedupe_key exactly:
    # (channel, workspace_id, chat_id, message_id). Using the four columns
    # directly avoids any string-joined surrogate key — important because the
    # components can contain characters (e.g. NUL) that are illegal in a single
    # Postgres TEXT column, and keeps the ON CONFLICT target natural.
    channel: Mapped[str] = mapped_column(String(64), nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(512), nullable=False)
    chat_id: Mapped[str] = mapped_column(String(512), nullable=False)
    message_id: Mapped[str] = mapped_column(String(1024), nullable=False)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        PrimaryKeyConstraint("channel", "workspace_id", "chat_id", "message_id", name="pk_webhook_deliveries"),
        Index("ix_webhook_deliveries_first_seen", "first_seen"),
    )
