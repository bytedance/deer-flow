"""The known errors of the feedback context.

One family under one base class, so the primary adapter can map the whole
family onto protocol codes in a single table. Class names keep the PEP 8
``Error`` suffix; the module is named ``exceptions`` after the AWS
hexagonal guidance's domain folder of the same name.
"""


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
