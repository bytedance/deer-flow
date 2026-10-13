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
            runs = RunRepository(sf)
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
            token = set_current_workspace(contexts["team"])
            try:
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
        finally:
            await engine.dispose()

    asyncio.run(scenario())
