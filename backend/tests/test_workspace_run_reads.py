"""Native Run reads must filter trusted workspace before pagination/reduction."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_workspace_executor_migration import executor_engine, native_engine  # noqa: F401


def test_native_run_reads_keep_selected_private_thread_scope(native_engine):  # noqa: F811
    from app.gateway.workspaces.service import WorkspaceService
    from deerflow.authz.workspace import reset_current_workspace, set_current_workspace
    from deerflow.persistence.run.model import RunRow
    from deerflow.persistence.run.sql import RunRepository
    from deerflow.persistence.thread_meta import ThreadMetaRepository
    from deerflow.persistence.user.model import UserRow
    from deerflow.persistence.workspaces.sql import WorkspaceAccessDenied, WorkspaceRepository
    from deerflow.runtime import RunManager, RunStatus

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
            team = await workspaces.create_team("owner", "Run history", "run-read-main")
            contexts = {kind: await service.resolve_context("owner", row["id"]) for kind, row in (("personal", personal), ("team", team))}
            threads = ThreadMetaRepository(sf)
            unavailable = {"value": False}

            class AvailableRunRepository(RunRepository):
                async def get(self, *args, **kwargs):
                    if unavailable["value"]:
                        raise RuntimeError("Synthetic durable read outage")
                    return await super().get(*args, **kwargs)

                async def get_many_by_thread(self, *args, **kwargs):
                    if unavailable["value"]:
                        raise RuntimeError("Synthetic durable read outage")
                    return await super().get_many_by_thread(*args, **kwargs)

                async def list_by_thread(self, *args, **kwargs):
                    if unavailable["value"]:
                        raise RuntimeError("Synthetic durable read outage")
                    return await super().list_by_thread(*args, **kwargs)

            runs = AvailableRunRepository(sf)
            for kind in ("personal", "team"):
                token = set_current_workspace(contexts[kind])
                try:
                    await threads.create(kind + "-history", user_id="owner")
                finally:
                    reset_current_workspace(token)
            now = datetime.now(UTC)
            async with sf() as session:
                for index, (run_id, thread_id, workspace_id) in enumerate(
                    (
                        ("team-valid", "team-history", team["id"]),
                        ("personal-valid", "personal-history", personal["id"]),
                        ("wrong-parent", "team-history", personal["id"]),
                        ("null-scope", "team-history", None),
                        ("wrong-thread", "personal-history", team["id"]),
                    )
                ):
                    session.add(
                        RunRow(
                            run_id=run_id,
                            thread_id=thread_id,
                            workspace_id=workspace_id,
                            user_id="owner",
                            status="success",
                            change_seq=index + 1,
                            created_at=now + timedelta(seconds=index),
                            total_tokens=7,
                            idempotency_key=run_id,
                            metadata_json={"replay_kind": "edit", "regenerate_from_run_id": run_id + "-source"},
                        )
                    )
                await session.commit()
            # Populate the actual native resident registry from durable rows,
            # as native adoption/hydration does, without starting any Agent.
            manager = RunManager(store=runs)
            async with sf() as session:
                resident_rows = (await session.scalars(sa.select(RunRow))).all()
                for row in resident_rows:
                    record = manager._record_from_store(runs._row_to_dict(row))
                    record.store_only = False
                    manager._runs[record.run_id] = record
                    manager._index_run_locked(record)
            resident = manager._runs["team-valid"]
            resident.status = RunStatus.error  # Preserve native current-status precedence.
            token = set_current_workspace(contexts["team"])
            try:
                assert await manager.get("personal-valid", user_id="owner") is None, "resident Run bypassed workspace SQL authorization"
                assert await manager.get("team-valid", user_id="owner") is resident, "authorized reads must retain the live task/abort record"
                assert [r.run_id for r in await manager.list_by_thread("team-history", user_id="owner", limit=1)] == ["team-valid"]
                assert await manager.list_by_thread("personal-history", user_id="owner") == []
                assert set(await manager.get_many_by_thread("team-history", {"team-valid", "wrong-parent", "null-scope"}, user_id="owner")) == {"team-valid"}
                assert await manager.list_successful_regenerate_sources("team-history", user_id="owner") == set()
                visibility = await manager.list_edit_replay_visibility("team-history", user_id="owner")
                assert visibility.hidden_source_run_ids == set() and visibility.hidden_attempt_run_ids == {"team-valid"}
                unavailable["value"] = True
                try:
                    with pytest.raises(RuntimeError, match="durable read outage"):
                        await manager.get("team-valid", user_id="owner")
                    with pytest.raises(RuntimeError, match="durable read outage"):
                        await manager.list_by_thread("team-history", user_id="owner")
                finally:
                    unavailable["value"] = False
                assert await runs.get("personal-valid", user_id="owner") is None, "Run read exposes the same user's other workspace"
                assert (await runs.get("team-valid", user_id="owner"))["workspace_id"] == team["id"]
                for invisible in ("wrong-parent", "null-scope", "wrong-thread"):
                    assert await runs.get(invisible, user_id="owner") is None
                assert await runs.find_by_idempotency_key("personal-valid", user_id="owner", thread_id="personal-history") is None
                assert [r["run_id"] for r in await runs.list_changed(after_change_seq=0, after_run_id="", user_id="owner", limit=1)] == ["team-valid"]
                assert await runs.latest_change(user_id="owner") == (1, "team-valid")
                assert [r["run_id"] for r in await runs.list_by_thread("team-history", user_id="owner", limit=1)] == ["team-valid"]
                assert await runs.list_by_thread("personal-history", user_id="owner") == []
                assert await runs.list_by_thread_created_at("team-history", user_id="owner", created_at=(now + timedelta(seconds=2)).isoformat()) == []
                assert await runs.list_successful_regenerate_sources("team-history", user_id="owner") == {"team-valid-source"}
                assert [r["run_id"] for r in await runs.list_edit_regenerate_runs("team-history", user_id="owner")] == ["team-valid"]
                assert set(await runs.get_many_by_thread("team-history", ["team-valid", "wrong-parent", "null-scope"], user_id="owner")) == {"team-valid"}
                assert (await runs.aggregate_tokens_by_thread("team-history", user_id="owner"))["total_tokens"] == 7
                with pytest.raises(WorkspaceAccessDenied):
                    await runs.get("team-valid", user_id=None)
                async with sf() as session:
                    await session.execute(sa.text("UPDATE workspaces SET policy_version=policy_version+1 WHERE id=:id"), {"id": team["id"]})
                    await session.commit()
                assert await manager.get("team-valid", user_id="owner") is None, "revoked scope used resident Run data"
                assert await manager.list_by_thread("team-history", user_id="owner") == []
                assert await manager.get_many_by_thread("team-history", {"team-valid"}, user_id="owner") == {}
                fresh = await service.resolve_context("owner", team["id"])
                refreshed = set_current_workspace(fresh)
                try:
                    async with sf() as session:
                        await session.execute(sa.delete(RunRow).where(RunRow.run_id == "team-valid"))
                        await session.commit()
                    assert "team-valid" in manager._runs, "fixture must retain the old native cache entry"
                    assert await manager.get("team-valid", user_id="owner") is None, "deleted durable Run resurrected from cache"
                    assert await manager.list_by_thread("team-history", user_id="owner") == []
                    assert await manager.get_many_by_thread("team-history", {"team-valid"}, user_id="owner") == {}
                    assert await manager.list_successful_regenerate_sources("team-history", user_id="owner") == set()
                    assert (await manager.list_edit_replay_visibility("team-history", user_id="owner")).hidden_attempt_run_ids == set()
                finally:
                    reset_current_workspace(refreshed)
                assert await runs.get("team-valid", user_id="owner") is None
                assert await runs.latest_change(user_id="owner") is None
                assert await runs.list_changed(after_change_seq=0, after_run_id="", user_id="owner") == []
                assert (await runs.aggregate_tokens_by_thread("team-history", user_id="owner"))["total_runs"] == 0
            finally:
                reset_current_workspace(token)
            required = RunRepository(sf, workspace_required=True)
            with pytest.raises(WorkspaceAccessDenied):
                await required.get("team-valid", user_id="owner")
            with pytest.raises(WorkspaceAccessDenied):
                await required.get_many_by_thread("team-history", [], user_id="owner")
            required_manager = RunManager(store=required)
            required_manager._runs[resident.run_id] = resident
            required_manager._index_run_locked(resident)
            with pytest.raises(WorkspaceAccessDenied):
                await required_manager.get("team-valid", user_id="owner")
            with pytest.raises(WorkspaceAccessDenied):
                await required_manager.get_many_by_thread("team-history", set(), user_id="owner")
        finally:
            await engine.dispose()

    asyncio.run(scenario())
