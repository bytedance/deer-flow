"""Private native thread scope with actual SQL memberships and shared parents."""

import asyncio
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_workspace_executor_migration import executor_engine, native_engine  # noqa: F401


def test_private_threads_keep_workspace_and_owner_on_shared_projects(native_engine):  # noqa: F811
    from app.gateway.workspaces.service import WorkspaceService
    from deerflow.authz.workspace import reset_current_workspace, set_current_workspace
    from deerflow.persistence.projects import ProjectRepository
    from deerflow.persistence.thread_meta import ThreadMetaRepository
    from deerflow.persistence.user.model import UserRow
    from deerflow.persistence.workspaces.sql import WorkspaceAccessDenied, WorkspaceRepository

    with native_engine.begin() as conn:
        conn.execute(sa.update(UserRow).where(UserRow.id == "owner").values(email_verified_at=datetime.now(UTC)))
        conn.execute(sa.insert(UserRow).values(id="peer", email="peer@example.invalid", email_verified_at=datetime.now(UTC)))
    driver = "sqlite+aiosqlite" if native_engine.dialect.name == "sqlite" else "postgresql+asyncpg"

    async def scenario():
        engine = create_async_engine(native_engine.url.set(drivername=driver))
        try:
            sf = async_sessionmaker(engine, expire_on_commit=False)
            workspaces = WorkspaceRepository(sf)
            service = WorkspaceService(workspaces)
            personal = await workspaces.provision_personal("owner")
            team = await workspaces.create_team("owner", "Research", "thread-scope-main")
            await workspaces.add_member(team["id"], "owner", "peer", role="member")
            personal_context = await service.resolve_context("owner", personal["id"])
            team_context = await service.resolve_context("owner", team["id"])
            peer_context = await service.resolve_context("peer", team["id"])
            projects = ProjectRepository(sf)
            threads = ThreadMetaRepository(sf)
            token = set_current_workspace(personal_context)
            try:
                personal_project = await projects.create(name="Private research", user_id="owner")
                row = await threads.create("personal-thread", user_id="owner", project_id=personal_project["id"])
                assert row["workspace_id"] == personal["id"], "native thread create lost trusted workspace"
            finally:
                reset_current_workspace(token)
            token = set_current_workspace(team_context)
            try:
                shared = await projects.create(name="Shared source", visibility="workspace", user_id="owner")
                row = await threads.create("team-thread", user_id="owner", project_id=shared["id"])
                assert row["workspace_id"] == team["id"] and row["user_id"] == "owner"
                assert await threads.get("personal-thread", user_id="owner") is None
                assert not await threads.check_access("personal-thread", "owner")
                assert not await threads.check_access("unknown-thread", "owner")
                assert not await threads.check_access("orphan", "owner")
                assert [row["thread_id"] for row in await threads.search(user_id="owner", limit=1)] == ["team-thread"]
                assert not await threads.set_project("team-thread", personal_project["id"], user_id="owner")
                await threads.update_metadata("personal-thread", {"foreign_write": True}, user_id="owner")
                await threads.update_display_name("team-thread", "Private team conversation", user_id="owner")
                await threads.update_status("team-thread", "busy", user_id="owner")
                row = await threads.get("team-thread", user_id="owner")
                assert row["display_name"] == "Private team conversation" and row["status"] == "busy"
                before = row["updated_at"]
                await threads.update_metadata("team-thread", {"deerflow_pinned": True}, touch=False, user_id="owner")
                assert (await threads.get("team-thread", user_id="owner"))["updated_at"] == before
                with pytest.raises(WorkspaceAccessDenied):
                    await threads.get("team-thread", user_id=None)
                with pytest.raises(WorkspaceAccessDenied):
                    await threads.claim_unowned("orphan", "owner")
                with pytest.raises(WorkspaceAccessDenied):
                    await threads.update_owner("team-thread", "peer", user_id="owner")
            finally:
                reset_current_workspace(token)
            token = set_current_workspace(peer_context)
            try:
                row = await threads.create("peer-thread", user_id="peer", project_id=shared["id"])
                assert row["workspace_id"] == team["id"] and row["user_id"] == "peer"
                assert await threads.get("team-thread", user_id="peer") is None
                assert not await threads.check_access("team-thread", "peer")
                assert [row["thread_id"] for row in await threads.search(user_id="peer")] == ["peer-thread"]
            finally:
                reset_current_workspace(token)
            token = set_current_workspace(team_context)
            try:
                assert await threads.get("peer-thread", user_id="owner") is None
                assert await projects.delete(shared["id"], user_id="owner")
                assert "deerflow_project_id" not in (await threads.get("team-thread", user_id="owner"))["metadata"]
                async with sf() as session:
                    await session.execute(sa.text("UPDATE workspaces SET policy_version=policy_version+1 WHERE id=:id"), {"id": team["id"]})
                    await session.commit()
                assert await threads.get("team-thread", user_id="owner") is None
                with pytest.raises(WorkspaceAccessDenied):
                    await threads.update_status("team-thread", "idle", user_id="owner")
            finally:
                reset_current_workspace(token)
            token = set_current_workspace(await service.resolve_context("peer", team["id"]))
            try:
                assert "deerflow_project_id" not in (await threads.get("peer-thread", user_id="peer"))["metadata"]
                await threads.delete("peer-thread", user_id="peer")
                assert not await threads.check_access("peer-thread", "peer", require_existing=True)
            finally:
                reset_current_workspace(token)
            token = set_current_workspace(personal_context)
            try:
                assert "foreign_write" not in (await threads.get("personal-thread", user_id="owner"))["metadata"]
            finally:
                reset_current_workspace(token)
            guarded = ThreadMetaRepository(sf, workspace_required=True)
            with pytest.raises(WorkspaceAccessDenied):
                await guarded.get("personal-thread", user_id="owner")
        finally:
            await engine.dispose()

    asyncio.run(scenario())
