"""ORM model registration entry point.

Importing this module ensures all ORM models are registered with
``Base.metadata`` so Alembic autogenerate detects every table.

The actual ORM classes have moved to entity-specific subpackages:
- ``deerflow.persistence.thread_meta``
- ``deerflow.persistence.run``
- ``deerflow.persistence.feedback``
- ``deerflow.persistence.user``

``RunEventRow`` remains in ``deerflow.persistence.models.run_event`` because
its storage implementation lives in ``deerflow.runtime.events.store.db`` and
there is no matching entity directory.
"""

from deerflow.persistence.feedback.model import FeedbackRow
from deerflow.persistence.knowledge_base.model import IndexJobRow, KnowledgeBaseDocumentRow, KnowledgeBaseRow
from deerflow.persistence.models.closure_ticket import ClosureSlaConfigRow, ClosureTicketEventRow, ClosureTicketRow
from deerflow.persistence.models.run_event import RunEventRow
from deerflow.persistence.run.model import RunRow
from deerflow.persistence.tenant.model import TenantRow
from deerflow.persistence.thread_meta.model import ThreadMetaRow
from deerflow.persistence.user.model import UserRow

__all__ = [
    "ClosureSlaConfigRow",
    "ClosureTicketEventRow",
    "ClosureTicketRow",
    "FeedbackRow",
    "IndexJobRow",
    "KnowledgeBaseDocumentRow",
    "KnowledgeBaseRow",
    "RunEventRow",
    "RunRow",
    "TenantRow",
    "ThreadMetaRow",
    "UserRow",
]
