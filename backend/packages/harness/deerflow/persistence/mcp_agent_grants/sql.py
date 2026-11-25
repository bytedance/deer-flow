"""SQL-backed runtime MCP agent grants."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from deerflow.config.mcp_agent_auth_config import StoredMcpAgentGrant
from deerflow.persistence.agents.sql import get_sync_sessionmaker
from deerflow.persistence.mcp_agent_grants import McpAgentGrantStore
from deerflow.persistence.mcp_agent_grants.model import McpAgentGrantRow


class SqlMcpAgentGrantStore(McpAgentGrantStore):
    def __init__(self, url: str) -> None:
        self._Session = get_sync_sessionmaker(url)

    def get(self, binding_id: str) -> StoredMcpAgentGrant | None:
        with self._Session() as session:
            document = session.execute(select(McpAgentGrantRow.grant).where(McpAgentGrantRow.binding_id == binding_id)).scalar_one_or_none()
        return None if document is None else StoredMcpAgentGrant.model_validate(document)

    def list(self) -> dict[str, StoredMcpAgentGrant]:
        with self._Session() as session:
            rows = session.execute(select(McpAgentGrantRow.binding_id, McpAgentGrantRow.grant).order_by(McpAgentGrantRow.binding_id.asc())).all()
        return {binding_id: StoredMcpAgentGrant.model_validate(document) for binding_id, document in rows}

    def put(self, binding_id: str, grant: StoredMcpAgentGrant) -> None:
        values = {"binding_id": binding_id, "grant": grant.model_dump(mode="json"), "updated_at": datetime.now(UTC)}
        with self._Session() as session:
            insert = postgres_insert if session.get_bind().dialect.name == "postgresql" else sqlite_insert
            # Two first writers can both miss a SELECT; upsert on the key instead.
            stmt = insert(McpAgentGrantRow).values(**values)
            session.execute(stmt.on_conflict_do_update(index_elements=["binding_id"], set_={"grant": stmt.excluded.grant, "updated_at": stmt.excluded.updated_at}))
            session.commit()

    def delete(self, binding_id: str) -> bool:
        with self._Session() as session:
            result = session.execute(delete(McpAgentGrantRow).where(McpAgentGrantRow.binding_id == binding_id))
            session.commit()
        return result.rowcount > 0
