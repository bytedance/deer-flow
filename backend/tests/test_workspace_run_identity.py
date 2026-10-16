"""Persist original native operation authority; never recover it from UI selection."""

import asyncio
from contextvars import Context
from dataclasses import asdict
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_workspace_executor_migration import executor_engine, native_engine  # noqa: F401


def test_native_admission_captures_identity_before_selection_changes(native_engine):  # noqa: F811
    from app.gateway.workspaces.service import WorkspaceService
    from deerflow.authz.workspace import reset_current_workspace, set_current_workspace
    from deerflow.persistence.run.model import RunRow
    from deerflow.persistence.run.sql import RunRepository
    from deerflow.persistence.thread_meta import ThreadMetaRepository
    from deerflow.persistence.user.model import UserRow
    from deerflow.persistence.workspaces.sql import WorkspaceRepository
    from deerflow.runtime import RunManager, ThreadOperationKind

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
            team = await workspaces.create_team("owner", "Execution identity", "execution-identity-main")
            original = await service.resolve_context("owner", team["id"])
            other = await service.resolve_context("owner", personal["id"])
            threads = ThreadMetaRepository(sf)
            runs = RunRepository(sf, workspace_required=True)
            manager = RunManager(store=runs, worker_id="identity-writer")
            token = set_current_workspace(original)
            try:
                parent = await threads.create("identity-main", user_id="owner")
                async with manager.reserve_thread_operation("identity-main", kind=ThreadOperationKind.checkpoint_write, user_id="owner"):
                    async with sf() as session:
                        row = await session.scalar(sa.select(RunRow).where(RunRow.thread_id == "identity-main"))
                        assert getattr(row, "workspace_context_json", None) == asdict(original), "native admission lost original permission versions"
                        assert row.thread_incarnation == parent["incarnation"]
                        persisted = runs._row_to_dict(row)
                    resident = await manager.get(row.run_id, user_id="owner")
                    assert resident.workspace_context == original
                    assert resident.thread_incarnation == parent["incarnation"]
                    set_current_workspace(other)
                    restored = manager._record_from_store(persisted)
                    assert restored.workspace_context == resident.workspace_context == original
                    assert restored.workspace_id == team["id"]
                    assert restored.thread_incarnation == parent["incarnation"]
                    # This is an identity snapshot, not a renewed live membership grant.
                    async with sf() as session:
                        await session.execute(sa.text("UPDATE workspaces SET policy_version=policy_version+1 WHERE id=:id"), {"id": team["id"]})
                        await session.commit()
                    assert manager._record_from_store(persisted).workspace_context == original
                async with sf() as session:
                    assert await session.get(RunRow, row.run_id) is None
            finally:
                reset_current_workspace(token)
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_native_identity_rejects_legacy_upsert_and_stale_local_replay(native_engine):  # noqa: F811
    from app.gateway.workspaces.service import WorkspaceService
    from deerflow.authz.workspace import reset_current_workspace, set_current_workspace
    from deerflow.persistence.run.model import RunRow
    from deerflow.persistence.run.sql import RunRepository
    from deerflow.persistence.thread_meta import ThreadMetaRepository
    from deerflow.persistence.user.model import UserRow
    from deerflow.persistence.workspaces.sql import WorkspaceAccessDenied, WorkspaceRepository
    from deerflow.runtime import RunManager, ThreadOperationKind

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
            team = await workspaces.create_team("owner", "Identity boundaries", "identity-boundaries")
            original = await service.resolve_context("owner", team["id"])
            other = await service.resolve_context("owner", personal["id"])
            runs = RunRepository(sf, workspace_required=True)
            manager = RunManager(store=runs, worker_id="identity-boundary-writer")
            token = set_current_workspace(original)
            record = None
            accepted = []
            try:
                threads = ThreadMetaRepository(sf)
                for thread_id in ("identity-boundary", "legacy-attempt", "upsert-target"):
                    await threads.create(thread_id, user_id="owner")
                record = await manager._admit_thread_operation("identity-boundary", operation_kind=ThreadOperationKind.checkpoint_write, user_id="owner", idempotency_key="identity-replay")
                try:
                    await manager.create("legacy-attempt", user_id="owner")
                    accepted.append("legacy scoped create")
                except WorkspaceAccessDenied:
                    pass

                async def unbound_put():
                    await RunRepository(sf).put(record.run_id, thread_id="upsert-target", user_id="owner", operation_kind="checkpoint_write")

                try:
                    await asyncio.create_task(unbound_put(), context=Context())
                    accepted.append("unbound upsert of scoped row")
                except WorkspaceAccessDenied:
                    pass
                set_current_workspace(other)
                try:
                    await manager._admit_thread_operation("identity-boundary", operation_kind=ThreadOperationKind.checkpoint_write, user_id="owner", idempotency_key="identity-replay")
                    accepted.append("cross-space local replay")
                except WorkspaceAccessDenied:
                    pass
                set_current_workspace(original)
                async with sf() as session:
                    await session.execute(sa.text("UPDATE threads_meta SET incarnation=:nonce WHERE thread_id=:id"), {"nonce": "b" * 32, "id": "identity-boundary"})
                    await session.commit()
                try:
                    await manager._admit_thread_operation("identity-boundary", operation_kind=ThreadOperationKind.checkpoint_write, user_id="owner", idempotency_key="identity-replay")
                    accepted.append("recreated-parent local replay")
                except WorkspaceAccessDenied:
                    pass
                peer = RunManager(store=runs, worker_id="identity-replay-peer")
                try:
                    await peer._admit_thread_operation("identity-boundary", operation_kind=ThreadOperationKind.checkpoint_write, user_id="owner", idempotency_key="identity-replay")
                    accepted.append("recreated-parent durable replay")
                except WorkspaceAccessDenied:
                    pass
                async with sf() as session:
                    await session.execute(sa.text("UPDATE threads_meta SET incarnation=:nonce WHERE thread_id=:id"), {"nonce": record.thread_incarnation, "id": "identity-boundary"})
                    await session.commit()
                async with sf() as session:
                    await session.execute(sa.text("UPDATE workspaces SET policy_version=policy_version+1 WHERE id=:id"), {"id": team["id"]})
                    await session.commit()
                try:
                    await manager._admit_thread_operation("identity-boundary", operation_kind=ThreadOperationKind.checkpoint_write, user_id="owner", idempotency_key="identity-replay")
                    accepted.append("revoked local replay")
                except WorkspaceAccessDenied:
                    pass
                assert accepted == [], "native identity bypasses: " + ", ".join(accepted)
                async with sf() as session:
                    row = await session.get(RunRow, record.run_id)
                    assert row.thread_id == "identity-boundary" and row.workspace_context_json == asdict(original)
            finally:
                if record is not None:
                    await runs.delete_thread_operation(record.run_id, user_id="owner", workspace_context=original, owner_worker_id="identity-boundary-writer")
                reset_current_workspace(token)
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_native_recovery_never_invents_or_accepts_conflicting_identity():
    from deerflow.authz.workspace import WorkspaceContext, reset_current_workspace, set_current_workspace
    from deerflow.persistence.workspaces.sql import WorkspaceAccessDenied
    from deerflow.runtime import RunManager

    context = WorkspaceContext("22222222-2222-2222-2222-222222222222", "owner", 2, 3)
    row = {"run_id": "original", "thread_id": "thread", "user_id": "owner", "workspace_id": context.workspace_id}
    token = set_current_workspace(context)
    try:
        historical = RunManager._record_from_store(row)
        assert historical.workspace_id == context.workspace_id and historical.workspace_context is None
        assert historical.thread_incarnation is None
        captured = {**row, "workspace_context_json": asdict(context), "thread_incarnation": "a" * 32}
        assert RunManager._record_from_store(captured).workspace_context == context
        assert RunManager._record_from_store({**captured, "thread_incarnation": "epoch"}).thread_incarnation == "epoch"
        for changes in (
            {"workspace_id": "33333333-3333-3333-3333-333333333333"},
            {"user_id": "other"},
            {"thread_incarnation": None},
            {"thread_incarnation": ""},
            {"workspace_context_json": {**asdict(context), "policy_version": True}},
            {"workspace_context_json": {**asdict(context), "extra": "untrusted"}},
            {"workspace_context_json": []},
            {"workspace_context_json": None},
        ):
            with pytest.raises(WorkspaceAccessDenied):
                RunManager._record_from_store({**captured, **changes})
    finally:
        reset_current_workspace(token)


def test_run_identity_parent_upgrade_preserves_history_without_granting_authority(native_engine):  # noqa: F811
    from alembic import command

    from deerflow.persistence import bootstrap

    columns = "run_id,thread_id,user_id,status,workspace_id,CAST(metadata_json AS TEXT),CAST(kwargs_json AS TEXT)"
    with native_engine.begin() as conn:
        before = conn.execute(sa.text("SELECT " + columns + " FROM runs ORDER BY run_id")).all()
        assert before, "fixture must contain actual historical native runs"
        # Reconstruct the parent Run columns on this disposable fixture database only.
        conn.execute(sa.text("ALTER TABLE runs DROP COLUMN workspace_context_json"))
        conn.execute(sa.text("ALTER TABLE runs DROP COLUMN thread_incarnation"))
        conn.execute(sa.text("UPDATE alembic_version SET version_num='0038_workspace_read_clocks'"))
        assert not {"workspace_context_json", "thread_incarnation"}.intersection(c["name"] for c in sa.inspect(conn).get_columns("runs"))
    driver = "sqlite+aiosqlite" if native_engine.dialect.name == "sqlite" else "postgresql+asyncpg"

    async def configuration():
        engine = create_async_engine(native_engine.url.set(drivername=driver))
        try:
            return bootstrap._get_alembic_config(engine)
        finally:
            await engine.dispose()

    cfg = asyncio.run(configuration())
    for _ in range(2):
        bootstrap._upgrade(cfg, "0039_run_workspace_identity")
        with native_engine.connect() as conn:
            assert conn.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one() == "0039_run_workspace_identity"
            assert conn.execute(sa.text("SELECT " + columns + " FROM runs ORDER BY run_id")).all() == before
            shape = {c["name"]: c for c in sa.inspect(conn).get_columns("runs")}
            assert shape["workspace_context_json"]["nullable"] and isinstance(shape["workspace_context_json"]["type"], sa.JSON)
            assert shape["thread_incarnation"]["nullable"] and str(shape["thread_incarnation"]["type"]) == "VARCHAR(32)"
            assert conn.execute(sa.text("SELECT COUNT(*) FROM runs WHERE workspace_context_json IS NOT NULL OR thread_incarnation IS NOT NULL")).scalar_one() == 0
    with pytest.raises(RuntimeError, match="matched backup"):
        command.downgrade(cfg, "0038_workspace_read_clocks")
    with native_engine.connect() as conn:
        assert conn.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one() == "0039_run_workspace_identity"
        assert conn.execute(sa.text("SELECT " + columns + " FROM runs ORDER BY run_id")).all() == before
        if native_engine.dialect.name == "postgresql":
            assert conn.execute(sa.text("SELECT COUNT(*) FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid()")).scalar_one() == 0, "refused migration leaked its own connection"
