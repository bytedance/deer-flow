"""Workspace-private native read markers and clocks with actual SQL rows."""

import asyncio
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_workspace_executor_migration import executor_engine, native_engine  # noqa: F401


def test_read_markers_filter_run_parent_scope_and_keep_space_clocks(native_engine):  # noqa: F811
    from app.gateway.workspaces.service import WorkspaceService
    from deerflow.authz.workspace import reset_current_workspace, set_current_workspace
    from deerflow.persistence.run.model import RunRow
    from deerflow.persistence.thread_meta import ThreadMetaRepository
    from deerflow.persistence.thread_reads import ThreadReadRepository
    from deerflow.persistence.thread_reads.model import ThreadReadMarkerRow
    from deerflow.persistence.user.model import UserRow
    from deerflow.persistence.workspaces.sql import WorkspaceAccessDenied, WorkspaceRepository

    with native_engine.begin() as conn:
        conn.execute(sa.update(UserRow).where(UserRow.id == "owner").values(email_verified_at=datetime.now(UTC)))
    driver = "sqlite+aiosqlite" if native_engine.dialect.name == "sqlite" else "postgresql+asyncpg"

    async def scenario():
        engine = create_async_engine(native_engine.url.set(drivername=driver))
        try:
            sf = async_sessionmaker(engine, expire_on_commit=False)
            workspaces = WorkspaceRepository(sf)
            service = WorkspaceService(workspaces)
            personal = await workspaces.provision_personal("owner")
            team = await workspaces.create_team("owner", "Reading", "read-clock-main")
            contexts = {kind: await service.resolve_context("owner", row["id"]) for kind, row in (("personal", personal), ("team", team))}
            threads = ThreadMetaRepository(sf)
            reads = ThreadReadRepository(sf)
            required_reads = ThreadReadRepository(sf, workspace_required=True)
            with pytest.raises(WorkspaceAccessDenied):
                await required_reads.mark_read(user_id="owner", thread_id="personal-read")
            with pytest.raises(WorkspaceAccessDenied):
                await required_reads.read_version(user_id="owner")
            with pytest.raises(WorkspaceAccessDenied):
                await required_reads.unread_thread_ids(user_id="owner", thread_ids=[])

            for kind in ("personal", "team"):
                token = set_current_workspace(contexts[kind])
                try:
                    await threads.create(kind + "-read", user_id="owner")
                finally:
                    reset_current_workspace(token)
            async with sf() as session:
                for run_id, thread_id, workspace_id, seq in (
                    ("personal-read-run", "personal-read", personal["id"], 5),
                    ("team-read-run", "team-read", team["id"], 9),
                    ("foreign-parent", "team-read", personal["id"], 999),
                    ("null-parent", "team-read", None, 1000),
                ):
                    session.add(RunRow(run_id=run_id, thread_id=thread_id, workspace_id=workspace_id, user_id="owner", status="success", change_seq=seq, origin_kind="schedule"))
                await session.commit()
            token = set_current_workspace(contexts["team"])
            try:
                assert await reads.unread_thread_ids(user_id="owner", thread_ids=["personal-read", "team-read"]) == {"team-read"}, "unread query exposes other-space runs"
                assert await reads.read_version(user_id="owner") == 0
                assert await reads.mark_read(user_id="owner", thread_id="team-read") == 9, "read position includes mismatched or unscoped run parents"
                assert await reads.read_version(user_id="owner") == 1
                assert await reads.mark_read(user_id="owner", thread_id="team-read") == 9
                assert await reads.read_version(user_id="owner") == 1
                with pytest.raises(WorkspaceAccessDenied):
                    await reads.mark_read(user_id="owner", thread_id="personal-read")
                assert await reads.unread_thread_ids(user_id="owner", thread_ids=["team-read"]) == set()
            finally:
                reset_current_workspace(token)
            token = set_current_workspace(contexts["personal"])
            try:
                assert await reads.read_version(user_id="owner") == 0, "team read changed personal read clock"
                assert await reads.mark_read(user_id="owner", thread_id="personal-read") == 5
                assert await reads.read_version(user_id="owner") == 1
            finally:
                reset_current_workspace(token)
            token = set_current_workspace(contexts["team"])
            try:
                assert await reads.read_version(user_id="owner") == 1
                async with sf() as session:
                    await session.execute(sa.update(RunRow).where(RunRow.run_id == "team-read-run").values(change_seq=12))
                    await session.execute(sa.text("UPDATE workspaces SET policy_version=policy_version+1 WHERE id=:id"), {"id": team["id"]})
                    await session.commit()
                with pytest.raises(WorkspaceAccessDenied):
                    await reads.mark_read(user_id="owner", thread_id="team-read")
                async with sf() as session:
                    marker = await session.get(ThreadReadMarkerRow, ("owner", "team-read"))
                    assert marker.seen_change_seq == 9
            finally:
                reset_current_workspace(token)
        finally:
            await engine.dispose()

    asyncio.run(scenario())
