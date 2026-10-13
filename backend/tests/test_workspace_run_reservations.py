"""Native durable non-run reservation admission and captured-scope release."""

import asyncio
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_workspace_executor_migration import executor_engine, native_engine  # noqa: F401


def test_private_thread_reservation_persists_scope_and_releases_only_its_row(native_engine):  # noqa: F811
    from app.gateway.workspaces.service import WorkspaceService
    from deerflow.authz.workspace import reset_current_workspace, set_current_workspace
    from deerflow.persistence.run.model import RunRow
    from deerflow.persistence.run.sql import RunRepository
    from deerflow.persistence.thread_meta import ThreadMetaRepository
    from deerflow.persistence.user.model import UserRow
    from deerflow.persistence.workspaces.sql import WorkspaceAccessDenied, WorkspaceRepository
    from deerflow.runtime import RunManager, ThreadOperationKind
    from deerflow.runtime.runs.manager import ConflictError

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
            team = await workspaces.create_team("owner", "Writes", "reservation-main")
            contexts = {kind: await service.resolve_context("owner", row["id"]) for kind, row in (("personal", personal), ("team", team))}
            threads = ThreadMetaRepository(sf)
            runs = RunRepository(sf)
            managers = [RunManager(store=runs, worker_id=worker) for worker in ("writer-a", "writer-b")]
            for kind in ("personal", "team"):
                token = set_current_workspace(contexts[kind])
                try:
                    await threads.create(kind + "-write", user_id="owner")
                finally:
                    reset_current_workspace(token)
            async with sf() as session:
                session.add(RunRow(run_id="foreign-history", thread_id="personal-write", workspace_id=personal["id"], user_id="owner", status="success", idempotency_key="foreign-key"))
                session.add(RunRow(run_id="team-history", thread_id="team-write", workspace_id=team["id"], user_id="owner", status="success"))
                await session.commit()
            token = set_current_workspace(contexts["team"])
            try:
                async with managers[0].reserve_thread_operation("team-write", kind=ThreadOperationKind.checkpoint_write, user_id="owner"):
                    async with sf() as session:
                        row = await session.scalar(sa.select(RunRow).where(RunRow.thread_id == "team-write", RunRow.operation_kind == "checkpoint_write"))
                        reservation_id = row.run_id
                        assert row.workspace_id == team["id"], "native reservation lost trusted workspace"
                        assert row.user_id == "owner" and row.owner_worker_id == "writer-a"
                    with pytest.raises(ConflictError):
                        async with managers[1].reserve_thread_operation("team-write", kind=ThreadOperationKind.checkpoint_write, user_id="owner"):
                            pytest.fail("peer writer admitted while durable reservation is held")
                    # A peer must not release a live reservation it does not own.
                    await runs.delete_thread_operation(reservation_id, user_id="owner", workspace_context=contexts["team"], owner_worker_id="writer-b")
                    async with sf() as session:
                        assert await session.get(RunRow, reservation_id) is not None
                    # Actual withdrawal and ambient selection change must not strand cleanup.
                    async with sf() as session:
                        await session.execute(sa.text("UPDATE workspaces SET policy_version=policy_version+1 WHERE id=:id"), {"id": team["id"]})
                        await session.commit()
                    # Leave the other selection through the manager's finally;
                    # the outer token restores this caller after cleanup.
                    set_current_workspace(contexts["personal"])
                async with sf() as session:
                    assert await session.get(RunRow, reservation_id) is None
                    assert await session.get(RunRow, "team-history") is not None
                reset_current_workspace(token)
                token = set_current_workspace(await service.resolve_context("owner", team["id"]))
                with pytest.raises(WorkspaceAccessDenied):
                    async with managers[0].reserve_thread_operation("personal-write", kind=ThreadOperationKind.checkpoint_write, user_id="owner"):
                        pytest.fail("foreign thread was reserved")
                with pytest.raises(WorkspaceAccessDenied):
                    await runs.create_thread_operation_atomic("collision", thread_id="team-write", user_id="owner", owner_worker_id="writer-a", lease_expires_at=None, operation_kind="checkpoint_write", idempotency_key="foreign-key")
                await runs.delete_thread_operation("team-history", user_id="owner", workspace_context=await service.resolve_context("owner", team["id"]), owner_worker_id="writer-a")
                async with sf() as session:
                    assert await session.get(RunRow, "team-history") is not None
                    assert await session.get(RunRow, "collision") is None
            finally:
                reset_current_workspace(token)
        finally:
            await engine.dispose()

    asyncio.run(scenario())
