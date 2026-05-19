"""Aggregate imports of all DeerFlow ORM model modules.

Imported by ``init_engine()`` before ``Base.metadata.create_all`` so that
every table is registered with the declarative base at engine startup.
"""

from deerflow.persistence.agent.model import AgentPermissionRow, AgentRow
from deerflow.persistence.agent.usage_model import AgentUsageRow
from deerflow.persistence.feedback.model import FeedbackRow
from deerflow.persistence.http_connector.model import TenantHttpConnectorRow
from deerflow.persistence.knowledge_base.model import (
    IndexJobRow,
    KbPermissionRow,
    KnowledgeBaseDocumentRow,
    KnowledgeBaseRow,
)
from deerflow.persistence.mcp_server.model import TenantMcpServerRow
from deerflow.persistence.models.closure_ticket import ClosureSlaConfigRow, ClosureTicketEventRow, ClosureTicketRow
from deerflow.persistence.run.model import RunRow
from deerflow.persistence.tenant.model import TenantRow
from deerflow.persistence.thread_meta.model import ThreadMetaRow
from deerflow.persistence.user.model import UserRow

__all__ = [
    "AgentPermissionRow",
    "AgentRow",
    "AgentUsageRow",
    "ClosureSlaConfigRow",
    "ClosureTicketEventRow",
    "ClosureTicketRow",
    "FeedbackRow",
    "IndexJobRow",
    "KbPermissionRow",
    "KnowledgeBaseDocumentRow",
    "KnowledgeBaseRow",
    "RunRow",
    "TenantHttpConnectorRow",
    "TenantMcpServerRow",
    "TenantRow",
    "ThreadMetaRow",
    "UserRow",
]
