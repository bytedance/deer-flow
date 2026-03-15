"""Subscription tier definitions and enforcement limits.

This module is intentionally static and versioned with code deploys.
Subscription ownership stays downstream; this service validates the incoming
tier and applies local enforcement policies.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class SubscriptionTier(StrEnum):
    SOLO = "solo"
    POWER = "power"
    TEAM = "team"


class TierLimitsConfig(BaseModel):
    """Enforcement limits for a single subscription tier."""

    context_window_tokens: int = Field(ge=1000, description="Max context window in tokens allowed for this tier.")
    max_memory_facts: int = Field(ge=1, description="Max number of memory facts allowed for this tier.")


class SubscriptionConfig(BaseModel):
    """Per-tier subscription limit configuration. Loaded from config.yaml under 'subscription:'."""

    solo: TierLimitsConfig = Field(
        default_factory=lambda: TierLimitsConfig(context_window_tokens=32000, max_memory_facts=100),
    )
    power: TierLimitsConfig = Field(
        default_factory=lambda: TierLimitsConfig(context_window_tokens=64000, max_memory_facts=250),
    )
    team: TierLimitsConfig = Field(
        default_factory=lambda: TierLimitsConfig(context_window_tokens=100000, max_memory_facts=500),
    )


DEFAULT_SUBSCRIPTION_TIER = SubscriptionTier.SOLO

# Global singleton — updated at startup by load_subscription_config_from_dict.
_subscription_config: SubscriptionConfig = SubscriptionConfig()


def get_subscription_config() -> SubscriptionConfig:
    return _subscription_config


def set_subscription_config(config: SubscriptionConfig) -> None:
    global _subscription_config
    _subscription_config = config


def load_subscription_config_from_dict(config_dict: dict) -> None:
    global _subscription_config
    _subscription_config = SubscriptionConfig(**config_dict)


def normalize_subscription_tier(value: str | SubscriptionTier | None, *, strict: bool = False) -> SubscriptionTier:
    """Normalize incoming tier value.

    Args:
        value: Incoming tier value from request/runtime context.
        strict: If True, invalid values raise ValueError. If False, fallback to default tier.
    """
    if isinstance(value, SubscriptionTier):
        return value

    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in SubscriptionTier._value2member_map_:
            return SubscriptionTier(normalized)

    if strict:
        allowed = ", ".join(sorted(t.value for t in SubscriptionTier))
        raise ValueError(f"subscription_tier must be one of: {allowed}")

    return DEFAULT_SUBSCRIPTION_TIER


def get_limits_for_subscription(value: str | SubscriptionTier | None, *, strict: bool = False) -> TierLimitsConfig:
    tier = normalize_subscription_tier(value, strict=strict)
    return getattr(get_subscription_config(), tier.value)


def get_effective_max_memory_facts(global_max_facts: int, value: str | SubscriptionTier | None, *, strict: bool = False) -> int:
    """Compute effective memory cap with global safety ceiling.

    The global config remains a hard upper bound. Subscription caps can only
    reduce that maximum.
    """
    tier_cap = get_limits_for_subscription(value, strict=strict).max_memory_facts
    return min(global_max_facts, tier_cap)
