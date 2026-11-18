"""ORM model for UI-entered IM channel runtime configuration (``channel_runtime_configs``).

One row per IM provider (``slack``, ``telegram``, ...), shared by every Gateway
instance using the application database. It replaces the per-host
``{base_dir}/channels/runtime-config.json``:

- ``config_ciphertext`` is the provider's whole runtime config block (bot
  tokens, app secrets, ``enabled``, the Telegram deep-link username) as JSON,
  encrypted with the deployment credentials key (``DEER_FLOW_CREDENTIALS_KEY``,
  ``deerflow.config.credentials_key``). It is NULL for a disconnect.
- ``disconnected`` marks a disconnect from the web UI: a tombstone that keeps
  overriding a ``config.yaml`` block for the provider. It carries no secret, so
  it stays plaintext and still applies when the key cannot decrypt anything.
- ``version`` grows by one on every save, so an instance that applied version
  ``n`` notices a save made on a peer by comparing numbers, without decrypting.
  Rows are never deleted, so a provider's version never restarts.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import BigInteger, Boolean, Double, PrimaryKeyConstraint, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.persistence.base import Base

#: Longest provider key (registry names are short; this leaves headroom).
CHANNEL_RUNTIME_CONFIG_PROVIDER_LENGTH = 64


class ChannelRuntimeConfigRow(Base):
    __tablename__ = "channel_runtime_configs"

    provider: Mapped[str] = mapped_column(String(CHANNEL_RUNTIME_CONFIG_PROVIDER_LENGTH), nullable=False)
    config_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    disconnected: Mapped[bool] = mapped_column(Boolean, nullable=False)
    version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # Epoch seconds of the last save, for operators; nothing compares it.
    updated_at: Mapped[float] = mapped_column(Double, nullable=False)

    __table_args__ = (PrimaryKeyConstraint("provider", name="pk_channel_runtime_configs"),)


@dataclass(frozen=True)
class StoredChannelRuntimeConfig:
    """One provider's row as stored: the ciphertext is opaque to this layer."""

    provider: str
    config_ciphertext: str | None
    disconnected: bool
    version: int
