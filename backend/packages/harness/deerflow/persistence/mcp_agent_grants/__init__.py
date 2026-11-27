"""Runtime grants for ``grants: runtime`` MCP agent credential bindings."""

from __future__ import annotations

import abc
from typing import TYPE_CHECKING

from deerflow.config.mcp_agent_auth_config import McpAgentGrant, StoredMcpAgentGrant
from deerflow.persistence.mcp_agent_grants.model import McpAgentGrantRow

if TYPE_CHECKING:
    from deerflow.config.app_config import AppConfig

__all__ = ["McpAgentGrant", "McpAgentGrantRow", "McpAgentGrantStore", "StoredMcpAgentGrant", "make_mcp_agent_grant_store"]


class McpAgentGrantStore(abc.ABC):
    """Owners, approved definition digests and their approval subject per binding ID.

    Readers run on every protected MCP call, so a store error must propagate:
    callers deny the call rather than guess a grant.
    """

    @abc.abstractmethod
    def get(self, binding_id: str) -> StoredMcpAgentGrant | None:
        """Return the grant, or ``None`` when the binding has none."""

    @abc.abstractmethod
    def list(self) -> dict[str, StoredMcpAgentGrant]:
        """Return every stored grant by binding ID."""

    @abc.abstractmethod
    def put(self, binding_id: str, grant: StoredMcpAgentGrant) -> None:
        """Create or replace the grant of one binding."""

    @abc.abstractmethod
    def delete(self, binding_id: str) -> bool:
        """Delete one grant and return whether it existed."""


_file_store_singleton: McpAgentGrantStore | None = None


def make_mcp_agent_grant_store(config: AppConfig) -> McpAgentGrantStore:
    """Use the same backend as custom agent definitions and managed subagents."""
    if config.agent_storage.backend == "db":
        if config.database.backend not in ("sqlite", "postgres"):
            raise ValueError("MCP agent grant database storage requires database.backend to be 'sqlite' or 'postgres'.")
        from deerflow.persistence.mcp_agent_grants.sql import SqlMcpAgentGrantStore

        return SqlMcpAgentGrantStore(config.database.app_sync_sqlalchemy_url)
    global _file_store_singleton
    if _file_store_singleton is None:
        from deerflow.persistence.mcp_agent_grants.file import FileMcpAgentGrantStore

        _file_store_singleton = FileMcpAgentGrantStore()
    return _file_store_singleton
