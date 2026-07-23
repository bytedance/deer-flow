"""Feedback persistence — ORM row only.

The legacy SQL repository was replaced by the hexagonal slice:
port `deerflow.domain.feedback.ports.FeedbackRepository`, adapter
`app.infra.persistence.feedback.SqlFeedbackRepository`. The ORM row stays
here until PR-N moves engine/models/migrations into app/infra.
"""

from deerflow.persistence.feedback.model import FeedbackRow

__all__ = ["FeedbackRow"]
