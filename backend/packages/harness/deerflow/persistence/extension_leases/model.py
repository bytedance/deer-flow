"""Lease rows shared by extension coordination and the host admission transaction."""

from sqlalchemy import BigInteger, Double, String
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.persistence.base import Base


class ExtensionExecutionLeaseRow(Base):
    __tablename__ = "extension_execution_leases"

    namespace: Mapped[str] = mapped_column(String(96), primary_key=True)
    resource_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    holder_id: Mapped[str] = mapped_column(String(128), nullable=False)
    epoch: Mapped[int] = mapped_column(BigInteger, nullable=False)
    expires_at: Mapped[float] = mapped_column(Double, nullable=False)
