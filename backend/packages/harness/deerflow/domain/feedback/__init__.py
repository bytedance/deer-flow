"""Feedback bounded context: a user's rating of a single run.

Public API of the context. Import domain objects and the service from
here; import ports (FeedbackRepository, RunLookup) from
`deerflow.domain.feedback.ports` -- they are contracts consumed by
adapters and tests, not everyday call-site symbols.
"""

from deerflow.domain.feedback.model import (
    DuplicateFeedbackError,
    Feedback,
    FeedbackError,
    InvalidRatingError,
    InvalidTagError,
    RunNotFoundError,
)
from deerflow.domain.feedback.service import FeedbackService

__all__ = [
    "DuplicateFeedbackError",
    "Feedback",
    "FeedbackError",
    "FeedbackService",
    "InvalidRatingError",
    "InvalidTagError",
    "RunNotFoundError",
]
