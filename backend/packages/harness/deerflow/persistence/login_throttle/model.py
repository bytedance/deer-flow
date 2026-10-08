"""ORM model for the shared failed-login counter (``login_throttle``).

One row per client IP that failed at least one local login. Replicas sharing
the application database read and write the same row, so a lockout is
enforced wherever the load balancer sends the next attempt. Rows are swept
by :class:`~deerflow.persistence.login_throttle.sql.SqlLoginThrottleStore`
once a lock has served its sentence or a never-locked counter went stale.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Double, Integer, PrimaryKeyConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.persistence.base import Base

#: Longest row key. IPv6 fits in 45 characters; a trusted proxy may forward a
#: longer ``X-Real-IP`` and the store truncates it to this length.
LOGIN_THROTTLE_IP_LENGTH = 255


class LoginThrottleRow(Base):
    __tablename__ = "login_throttle"

    ip: Mapped[str] = mapped_column(String(LOGIN_THROTTLE_IP_LENGTH), nullable=False)
    fail_count: Mapped[int] = mapped_column(Integer, nullable=False)
    # Epoch seconds the lock started; NULL while the IP is only counting.
    locked_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    # Sentence committed for the lock (follows the live policy while active).
    lock_duration_seconds: Mapped[float | None] = mapped_column(Double, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))

    __table_args__ = (PrimaryKeyConstraint("ip", name="pk_login_throttle"),)
