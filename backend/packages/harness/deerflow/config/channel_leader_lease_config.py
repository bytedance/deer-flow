"""``channels.leader_lease``: one Gateway instance per IM platform connection.

Every IM channel connects outbound to its platform (Telegram long polling,
Discord / Slack / Feishu / DingTalk WebSockets). With several Gateway
instances each one would open that connection with the same bot credentials:
Telegram rejects the second poller with ``409 Conflict``, Discord delivers
every message to every session so the user is answered twice, and the
per-process ``ChannelManager`` state diverges between instances.

The leader lease arbitrates that: a ``channel_leases`` row per provider in the
shared database, held by one instance and renewed on a heartbeat, so only the
holder starts the provider's transport (``app.channels.leadership`` and
``ChannelService``). This module owns the configuration section; the startup
gate and ``ChannelService.from_app_config`` consume it.

``channels`` is not part of the ``AppConfig`` Pydantic schema (its provider
blocks carry raw credentials), so this model is validated from the
``channels.leader_lease`` mapping by :func:`channel_leader_lease_config`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

#: The key under ``channels`` that holds this section.
CHANNEL_LEADER_LEASE_KEY = "leader_lease"

#: Dotted path used in refusal text and the reload-boundary registry.
CHANNEL_LEADER_LEASE_FIELD = f"channels.{CHANNEL_LEADER_LEASE_KEY}"


class ChannelLeaderLeaseConfig(BaseModel):
    """Operator settings for the per-provider IM transport leader lease."""

    # ``extra="forbid"``: a misspelled key here silently keeps every instance
    # connecting, which is exactly what the section exists to prevent.
    model_config = ConfigDict(extra="forbid")

    enabled: bool | Literal["auto"] = Field(
        default="auto",
        description=(
            "auto (default) turns the lease on whenever the Gateway sees a multi-process signal (GATEWAY_WORKERS / WEB_CONCURRENCY > 1, "
            "deployment.multi_instance: true or DEER_FLOW_MULTI_INSTANCE=1) and leaves a single instance untouched; true always turns it on "
            "(it needs a sqlite or postgres database); false never does. While it is on, only the instance holding a provider's lease opens that "
            "platform connection (GitHub webhooks stay on every instance). A multi-process deployment with IM channels enabled refuses to start when this is false."
        ),
    )
    lease_seconds: int = Field(
        default=30,
        ge=3,
        description="How long a held lease stays valid without renewal; the holder renews every lease_seconds // 3 seconds. Bounds failover after a crash together with grace_seconds.",
    )
    grace_seconds: int = Field(
        default=10,
        ge=0,
        description="Extra time after lease_expires_at before a peer may take an expired lease, absorbing a slow renewal. Worst-case failover is lease_seconds + grace_seconds.",
    )

    @property
    def explicitly_disabled(self) -> bool:
        """True only for a literal ``enabled: false``; ``auto`` is never disabled."""
        return self.enabled is False

    def resolve(self, *, multi_process: bool) -> bool:
        """Return whether the lease is active for this process.

        ``auto`` follows the multi-process signal, so a single-instance
        deployment never writes lease rows and behaves exactly as before.
        """
        if self.enabled == "auto":
            return multi_process
        return bool(self.enabled)


class ChannelLeaderLeaseConfigError(ValueError):
    """``channels.leader_lease`` is present but not a valid section."""


def channel_leader_lease_config(channels_section: Any) -> ChannelLeaderLeaseConfig:
    """Validate the ``leader_lease`` block of a ``channels`` mapping.

    A missing ``channels`` section, a missing ``leader_lease`` key, or an empty
    block all mean the defaults. Anything else must validate, and the error
    names the dotted path so an operator can find it in config.yaml.
    """
    raw: Any = None
    if isinstance(channels_section, Mapping):
        raw = channels_section.get(CHANNEL_LEADER_LEASE_KEY)
    if raw is None:
        return ChannelLeaderLeaseConfig()
    if not isinstance(raw, Mapping):
        raise ChannelLeaderLeaseConfigError(f"{CHANNEL_LEADER_LEASE_FIELD} must be a mapping with enabled / lease_seconds / grace_seconds, got {type(raw).__name__}")
    try:
        return ChannelLeaderLeaseConfig.model_validate(dict(raw))
    except ValidationError as exc:
        problems = "; ".join(f"{'.'.join(str(part) for part in error['loc']) or CHANNEL_LEADER_LEASE_KEY}: {error['msg']}" for error in exc.errors())
        raise ChannelLeaderLeaseConfigError(f"{CHANNEL_LEADER_LEASE_FIELD} is invalid: {problems}") from None


def channel_leader_lease_from_app_config(app_config: Any) -> ChannelLeaderLeaseConfig:
    """Read ``channels.leader_lease`` from an ``AppConfig`` (or a test double).

    ``channels`` lives in ``AppConfig.model_extra``; objects without it (the
    gate tests use ``SimpleNamespace``) get the defaults.
    """
    extra = getattr(app_config, "model_extra", None) or {}
    channels = extra.get("channels") if isinstance(extra, Mapping) else None
    return channel_leader_lease_config(channels)
