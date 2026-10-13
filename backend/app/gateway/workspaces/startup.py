"""Read-only workspace startup fence, before runtime recovery or dispatch."""

from sqlalchemy import inspect, select, text

from app.gateway.auth_disabled import is_auth_disabled_requested
from app.gateway.workspaces.service import WorkspaceService
from deerflow.config.workspaces_config import WorkspacesConfig
from deerflow.persistence.workspaces.model import WorkspaceRow
from deerflow.persistence.workspaces.sql import workspace_repository

# This is a code coverage gate, not an operator bypass. Resource/files,
# background/credential isolation and paired rollout are still being integrated.
# Change only with their complete M3-M11 implementation and release evidence.
_WORKSPACE_RUNTIME_INTEGRATED = False
_NATIVE_WORKSPACE_SCHEMA = "0037_project_visibility"


async def validate_workspace_bootstrap(config, session_factory):
    settings = getattr(config, "workspaces", None)
    if settings is None:
        settings = WorkspacesConfig()
    if not isinstance(settings, WorkspacesConfig):
        raise RuntimeError("workspace startup requires typed operator configuration")
    if settings.enabled:
        if session_factory is None:
            raise RuntimeError("workspace mode requires persistent SQL storage")
        if is_auth_disabled_requested():
            raise RuntimeError("workspace mode requires authenticated callers")
    if session_factory is None:
        return None
    async with session_factory() as session:
        connection = await session.connection()
        has_workspaces = await connection.run_sync(lambda conn: inspect(conn).has_table("workspaces"))
        if not settings.enabled:
            if has_workspaces and await session.scalar(select(WorkspaceRow.id).where(WorkspaceRow.kind == "team").limit(1)) is not None:
                raise RuntimeError("existing team data requires workspace authorization; legacy startup refused")
            return None
        has_versions = await connection.run_sync(lambda conn: inspect(conn).has_table("alembic_version"))
        versions = (await session.execute(text("SELECT version_num FROM alembic_version"))).scalars().all() if has_versions else []
        if not has_workspaces or versions != [_NATIVE_WORKSPACE_SCHEMA]:
            raise RuntimeError("workspace schema is incompatible; use the paired migration procedure")
    if not _WORKSPACE_RUNTIME_INTEGRATED:
        raise RuntimeError("workspace entrypoint integration is incomplete; this build cannot activate tenant mode")
    return WorkspaceService(workspace_repository(session_factory, enabled=True))
