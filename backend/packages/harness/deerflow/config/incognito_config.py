"""Configuration for incognito (temporary) chat threads."""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class IncognitoThreadsConfig(BaseModel):
    """Lifetime and sweep settings for incognito threads.

    An incognito thread is invisible to every list, search, project and share
    surface; it exists only for its owner until the lifetime sweep deletes it.
    ``expires_at`` is renewed on activity to ``min(now + idle_ttl_seconds,
    created_at + max_lifetime_seconds)``, so an idle thread disappears after
    the idle window and a long-lived one still disappears after the absolute
    maximum. Creation and an explicit end use the same ceiling, and the idle
    window may not exceed it; setting both equal means the absolute lifetime
    alone decides.

    The idle floor is one hour because renewal happens on runs only: typing,
    reading or leaving the window open is not activity, and a window shorter
    than a single run would expire the chat right after the answer. The
    lifetime ceiling stays below a year because a larger value overflows the
    ``datetime`` arithmetic that schedules the deadline.
    """

    enabled: bool = Field(
        default=True,
        description="Operator switch. When disabled, clients cannot create incognito threads.",
    )
    idle_ttl_seconds: int = Field(
        default=24 * 60 * 60,
        ge=60 * 60,
        description="Idle window after the last run before an incognito thread is deleted.",
    )
    end_grace_seconds: int = Field(
        default=60 * 60,
        ge=0,
        description="Grace period after an explicit end before the thread and its data are purged.",
    )
    max_lifetime_seconds: int = Field(
        default=7 * 24 * 60 * 60,
        ge=60 * 60,
        le=365 * 24 * 60 * 60,
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

    @model_validator(mode="after")
    def _idle_window_fits_within_lifetime(self) -> IncognitoThreadsConfig:
        """Reject an idle window longer than the absolute lifetime.

        The pair would contradict itself: creation would schedule a deadline
        past the ceiling and the first activity renewal would pin it back, so
        ``idle_ttl_seconds`` would silently do nothing.
        """
        if self.idle_ttl_seconds > self.max_lifetime_seconds:
            raise ValueError(f"incognito.idle_ttl_seconds ({self.idle_ttl_seconds}) must not exceed incognito.max_lifetime_seconds ({self.max_lifetime_seconds})")
        return self
