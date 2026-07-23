from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

VALID_RATINGS = (-1, 1)

# Language-neutral reason slugs for thumbs-down feedback. The UI translates
# them for display; storage and analytics only ever see the slug, so feedback
# submitted under different UI languages stays aggregatable.
VALID_FEEDBACK_TAGS = frozenset(
    {
        "incorrect",
        "not_as_expected",
        "slow",
        "style_tone",
        "safety_legal",
        "other",
    }
)


class FeedbackError(Exception):
    """Base error for the feedback domain."""


class InvalidRatingError(FeedbackError):
    """Raised when a rating is not +1 or -1."""


class InvalidTagError(FeedbackError):
    """Raised when a feedback tag is not a known reason slug."""


class DuplicateFeedbackError(FeedbackError):
    """Raised when a concurrent upsert conflicts on the same run's feedback."""


class RunNotFoundError(FeedbackError):
    """Raised when the run does not exist or does not belong to the thread."""


@dataclass(frozen=True)
class Feedback:
    """A user's rating of a single run: at most one per (thread, run, user).

    Single-entity aggregate. ``message_id`` optionally narrows the rating
    to one message within the run instead of the whole run. ``tags`` carry
    optional thumbs-down reason slugs from the feedback dialog.
    """

    feedback_id: str
    run_id: str
    thread_id: str
    rating: int
    user_id: str | None = None
    message_id: str | None = None
    comment: str | None = None
    tags: tuple[str, ...] = ()
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self):
        if self.rating not in VALID_RATINGS:
            raise InvalidRatingError(f"rating must be +1 or -1, got {self.rating}")
        unknown = set(self.tags) - VALID_FEEDBACK_TAGS
        if unknown:
            raise InvalidTagError(f"unknown feedback tags: {sorted(unknown)}")

    @classmethod
    def create(
        cls,
        *,
        run_id: str,
        thread_id: str,
        rating: int,
        user_id: str | None = None,
        message_id: str | None = None,
        comment: str | None = None,
        tags: tuple[str, ...] | list[str] = (),
    ) -> Feedback:
        """Factory: generate identity and validate invariants."""
        return cls(
            feedback_id=str(uuid.uuid4()),
            run_id=run_id,
            thread_id=thread_id,
            rating=rating,
            user_id=user_id,
            message_id=message_id,
            comment=comment,
            tags=tuple(tags),
        )
