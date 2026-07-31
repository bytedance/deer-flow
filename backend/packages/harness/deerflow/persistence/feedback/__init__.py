"""Feedback persistence — ORM row only.

The legacy SQL repository was replaced by the hexagonal slice:
port `deerflow.domain.feedback.ports.FeedbackRepository`, adapter
`app.adapters.feedback.feedback_repository.SqlFeedbackRepository`. The ORM
row stays here beside the harness-owned engine/models/migrations.
"""

from deerflow.persistence.feedback.model import FeedbackRow

__all__ = ["FeedbackRow"]
