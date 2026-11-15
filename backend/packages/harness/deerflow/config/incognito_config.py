"""Configuration for incognito (temporary) chat threads."""

from __future__ import annotations

from pydantic import BaseModel, Field


class IncognitoThreadsConfig(BaseModel):
    """Lifetime and sweep settings for incognito threads.

    An incognito thread is invisible to every list, search, project and share
    surface; it exists only for its owner until the lifetime sweep deletes it.
    ``expires_at`` is renewed on activity to ``min(now + idle_ttl_seconds,
    created_at + max_lifetime_seconds)``, so an idle thread disappears after
    the idle window and a long-lived one still disappears after the absolute
    maximum.
    """

    enabled: bool = Field(
        default=True,
        description="Operator switch. When disabled, clients cannot create incognito threads.",
    )
    idle_ttl_seconds: int = Field(
        default=24 * 60 * 60,
        ge=60,
        description="Idle window after the last activity before an incognito thread is deleted.",
    )
    end_grace_seconds: int = Field(
        default=60 * 60,
        ge=0,
        description="Grace period after an explicit end before the thread and its data are purged.",
    )
    max_lifetime_seconds: int = Field(
        default=7 * 24 * 60 * 60,
        ge=60,
        description="Absolute lifetime ceiling measured from creation, regardless of activity.",
    )
    sweep_interval_seconds: int = Field(
        default=60,
        ge=5,
        le=3600,
        description="How often the Gateway scans for expired incognito threads.",
    )
    sweep_batch_size: int = Field(
        default=100,
        ge=1,
        le=1000,
        description="Maximum expired incognito threads deleted per sweep batch.",
    )
