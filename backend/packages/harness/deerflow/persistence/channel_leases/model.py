"""ORM model for the per-provider IM transport leader lease (``channel_leases``).

One row per IM provider (``telegram``, ``discord``, ...). The Gateway instance
named by ``owner_id`` holds the provider's platform connection until
``lease_expires_at``; it renews on a heartbeat, and a peer may take the row
over only once the lease has been expired for ``channels.leader_lease
.grace_seconds``. ``epoch`` grows by one on every acquisition, so a renewal or
release that carries an older epoch cannot touch a newer holder's lease.

Both timestamps are epoch seconds read from the **database** clock (see
:mod:`deerflow.persistence.channel_leases.sql`), never from an instance's own
wall clock: every comparison that decides who may connect runs inside one SQL
statement against one clock, so skew between hosts cannot hand the same
provider to two instances.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import BigInteger, Boolean, Double, PrimaryKeyConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.persistence.base import Base

#: Longest provider key (registry names are short; this leaves headroom).
CHANNEL_LEASE_PROVIDER_LENGTH = 64
#: Longest owner id. Matches ``runs.owner_worker_id``: the Gateway uses the
#: RunManager worker id (``hostname:uuid``) as the lease owner.
CHANNEL_LEASE_OWNER_LENGTH = 128


class ChannelLeaseRow(Base):
    __tablename__ = "channel_leases"

    provider: Mapped[str] = mapped_column(String(CHANNEL_LEASE_PROVIDER_LENGTH), nullable=False)
    owner_id: Mapped[str] = mapped_column(String(CHANNEL_LEASE_OWNER_LENGTH), nullable=False)
    epoch: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # Database-clock epoch seconds; see the module docstring.
    lease_expires_at: Mapped[float] = mapped_column(Double, nullable=False)
    # Whether the holder's transport was running at its last renewal, so a
    # peer's status endpoint can report "configured but not running".
    transport_running: Mapped[bool] = mapped_column(Boolean, nullable=False)
    updated_at: Mapped[float] = mapped_column(Double, nullable=False)

    __table_args__ = (PrimaryKeyConstraint("provider", name="pk_channel_leases"),)


@dataclass(frozen=True)
class ChannelLeaseGrant:
    """A lease this instance now holds: ``epoch`` fences every later renewal and release."""

    provider: str
    epoch: int
    lease_expires_at: float


@dataclass(frozen=True)
class ChannelLeaseState:
    """A provider's lease row as of one read, judged against the database clock of that read."""

    provider: str
    owner_id: str
    epoch: int
    lease_expires_at: float
    transport_running: bool
    live: bool
