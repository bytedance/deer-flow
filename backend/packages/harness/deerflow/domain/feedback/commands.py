"""Commands of the feedback context.

One frozen dataclass per state-changing use case -- the named carrier of
"the information required to perform an operation on the domain" (AWS
hexagonal guidance). Commands are dumb data on purpose: business
validation stays on the aggregate (``Feedback.__post_init__``) and
structural validation stays on the primary adapter's api model, so error
attribution (invalid rating reported before an unknown run) is unchanged.

Queries are deliberately NOT commands: the read methods on
``FeedbackService`` keep plain parameters -- a command expresses an
intent to change state, and wrapping reads would be pure boilerplate.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RateRun:
    """Set the user's current rating for a run (idempotent upsert)."""

    thread_id: str
    run_id: str
    rating: int
    user_id: str | None
    comment: str | None = None
    tags: tuple[str, ...] = field(default=())


@dataclass(frozen=True)
class RetractRunRating:
    """Withdraw the user's rating for a run (clicking the active button again)."""

    thread_id: str
    run_id: str
    user_id: str | None
