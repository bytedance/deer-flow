"""Tracing configuration is independent of portable Agent definition documents."""

from datetime import UTC, datetime

from sqlalchemy import JSON, BigInteger, DateTime, Index, Integer, String, Text, event, func
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.persistence.base import Base


class TracingProfileRow(Base):
    __tablename__ = "tracing_profiles"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    revision: Mapped[int] = mapped_column(Integer)
    providers_ciphertext: Mapped[str] = mapped_column(Text)
    allowed_user_ids: Mapped[list] = mapped_column(JSON)


class TracingProfileVersionRow(Base):
    __tablename__ = "tracing_profile_versions"

    profile_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    providers_ciphertext: Mapped[str] = mapped_column(Text)
    allowed_user_ids: Mapped[list] = mapped_column(JSON)


class AgentTracingBindingRow(Base):
    __tablename__ = "agent_tracing_bindings"

    owner_user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_name: Mapped[str] = mapped_column(String(128), primary_key=True)
    mode: Mapped[str] = mapped_column(String(16))
    profile_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    revision: Mapped[int] = mapped_column(Integer)
    agent_incarnation: Mapped[str | None] = mapped_column(String(256), nullable=True)


class RunTracingSnapshotRow(Base):
    __tablename__ = "run_tracing_snapshots"

    snapshot_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(String(64))
    agent_name: Mapped[str] = mapped_column(String(128))
    agent_incarnation: Mapped[str] = mapped_column(String(256))
    mode: Mapped[str] = mapped_column(String(16))
    binding_revision: Mapped[int] = mapped_column(Integer)
    profile_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    profile_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payload_ciphertext: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), server_default=func.current_timestamp())
    retention_state: Mapped[str] = mapped_column(String(16), default="unmanaged", server_default="unmanaged")

    __table_args__ = (Index("ix_run_tracing_snapshots_retention", "retention_state", "created_at"),)


class TracingAdmissionFenceRow(Base):
    """One shared writer lock orders activation against durable admission."""

    __tablename__ = "tracing_admission_fence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[int] = mapped_column(BigInteger, nullable=False)


@event.listens_for(TracingAdmissionFenceRow.__table__, "after_create")
def _initialize_admission_fence(table, connection, **kwargs):
    connection.execute(table.insert().values(id=1, version=0))
