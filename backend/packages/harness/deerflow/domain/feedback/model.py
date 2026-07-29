from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from deerflow.domain.feedback import InvalidRatingError, InvalidTagError

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


@dataclass(frozen=True)
class Feedback:
    """A user's rating of a single run: at most one per (thread, run, user).

    Single-entity aggregate. ``tags`` carry optional thumbs-down reason
    slugs from the feedback dialog.
    """

    feedback_id: str
    run_id: str
    thread_id: str
    rating: int
    user_id: str | None = None
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
            comment=comment,
            tags=tuple(tags),
        )
