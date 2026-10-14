"""Native feedback SQL keeps private scope through read and mutation transactions."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_workspace_executor_migration import executor_engine, native_engine  # noqa: F401


def test_feedback_keeps_live_private_run_and_captured_thread(native_engine):  # noqa: F811
    from app.gateway.workspaces.service import WorkspaceService
    from deerflow.authz.workspace import reset_current_workspace, set_current_workspace
    from deerflow.persistence.feedback.model import FeedbackRow
    from deerflow.persistence.feedback.sql import FeedbackRepository
    from deerflow.persistence.run.model import RunRow
    from deerflow.persistence.thread_meta import ThreadMetaRepository
    from deerflow.persistence.thread_meta.model import ThreadMetaRow
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
            team = await workspaces.create_team("owner", "Feedback", "feedback-main")
            contexts = {kind: await service.resolve_context("owner", row["id"]) for kind, row in (("personal", personal), ("team", team))}
            nonces = {}
            for kind in contexts:
                token = set_current_workspace(contexts[kind])
                try:
                    nonces[kind] = (await ThreadMetaRepository(sf).create(kind + "-feedback", user_id="owner"))["incarnation"]
                finally:
                    reset_current_workspace(token)
            now = datetime.now(UTC)
            async with sf() as session:
                for run_id, thread_id, workspace_id, owner in (
                    ("team-valid", "team-feedback", team["id"], "owner"),
                    ("personal-valid", "personal-feedback", personal["id"], "owner"),
                    ("wrong-parent", "team-feedback", personal["id"], "owner"),
                    ("null-scope", "team-feedback", None, "owner"),
                    ("peer-run", "team-feedback", team["id"], "intruder"),
                ):
                    session.add(RunRow(run_id=run_id, thread_id=thread_id, workspace_id=workspace_id, user_id=owner, status="success"))
                    session.add(FeedbackRow(feedback_id=run_id, run_id=run_id, thread_id=thread_id, user_id="owner", rating=1, created_at=now + timedelta(hours=1) if run_id.endswith("valid") else now))
                session.add(FeedbackRow(feedback_id="orphan", run_id="missing", thread_id="team-feedback", user_id="owner", rating=-1))
                session.add(FeedbackRow(feedback_id="peer-feedback", run_id="team-valid", thread_id="team-feedback", user_id="intruder", rating=-1))
                await session.commit()
            feedback = FeedbackRepository(sf)
            token = set_current_workspace(contexts["team"])
            try:
                assert await feedback.get("personal-valid", user_id="owner") is None, "same-user feedback crossed workspace"
                assert [r["run_id"] for r in await feedback.list_by_thread("team-feedback", user_id="owner", limit=1)] == ["team-valid"]
                assert set(await feedback.list_by_thread_grouped("team-feedback", user_id="owner")) == {"team-valid"}
                assert set(await feedback.list_by_run_ids("team-feedback", {"team-valid", "wrong-parent", "null-scope", "peer-run", "missing"}, user_id="owner")) == {"team-valid"}
                assert len(await feedback.list_by_run("team-feedback", "team-valid", user_id="owner")) == 1
                assert (await feedback.aggregate_by_run("team-feedback", "team-valid", user_id="owner"))["total"] == 1
                assert (await feedback.aggregate_by_run("team-feedback", "wrong-parent", user_id="owner"))["total"] == 0
                for hidden in ("wrong-parent", "null-scope", "peer-run", "peer-feedback", "orphan"):
                    assert await feedback.get(hidden, user_id="owner") is None
                with pytest.raises(WorkspaceAccessDenied):
                    await feedback.upsert(thread_id="team-feedback", run_id="wrong-parent", user_id="owner", rating=-1, incarnation=nonces["team"])
                with pytest.raises(WorkspaceAccessDenied):
                    await feedback.create(thread_id="team-feedback", run_id="team-valid", user_id="owner", rating=-1)
                updated = await feedback.upsert(thread_id="team-feedback", run_id="team-valid", user_id="owner", rating=-1, comment="updated", incarnation=nonces["team"])
                assert updated["feedback_id"] == "team-valid" and updated["rating"] == -1
                async with sf() as session:
                    await session.execute(sa.update(ThreadMetaRow).where(ThreadMetaRow.thread_id == "team-feedback").values(incarnation="replacement"))
                    await session.commit()
                for write in (
                    lambda: feedback.upsert(thread_id="team-feedback", run_id="team-valid", user_id="owner", rating=1, incarnation=nonces["team"]),
                    lambda: feedback.delete("team-valid", user_id="owner", incarnation=nonces["team"]),
                    lambda: feedback.delete_by_run(thread_id="team-feedback", run_id="team-valid", user_id="owner", incarnation=nonces["team"]),
                ):
                    with pytest.raises(WorkspaceAccessDenied):
                        await write()
                assert (await feedback.get("team-valid", user_id="owner"))["rating"] == -1
                assert await feedback.delete("personal-valid", user_id="owner", incarnation="replacement") is False
                with pytest.raises(WorkspaceAccessDenied):
                    await feedback.delete_by_thread("team-feedback", user_id="owner")
                async with sf() as session:
                    await session.execute(sa.text("UPDATE workspaces SET policy_version=policy_version+1 WHERE id=:id"), {"id": team["id"]})
                    await session.commit()
                assert await feedback.get("team-valid", user_id="owner") is None
                with pytest.raises(WorkspaceAccessDenied):
                    await feedback.upsert(thread_id="team-feedback", run_id="team-valid", user_id="owner", rating=1, incarnation="replacement")
                fresh = set_current_workspace(await service.resolve_context("owner", team["id"]))
                try:
                    assert (await feedback.get("team-valid", user_id="owner"))["rating"] == -1
                    assert await feedback.delete_by_run(thread_id="team-feedback", run_id="team-valid", user_id="owner", incarnation="replacement")
                    created = await feedback.create(thread_id="team-feedback", run_id="team-valid", user_id="owner", rating=1, message_id="message", incarnation="replacement")
                    assert created["message_id"] == "message"
                    assert await feedback.delete(created["feedback_id"], user_id="owner", incarnation="replacement")
                    with pytest.raises(WorkspaceAccessDenied):
                        await feedback.get("personal-valid", user_id=None)
                finally:
                    reset_current_workspace(fresh)
            finally:
                reset_current_workspace(token)
            required = FeedbackRepository(sf, workspace_required=True)
            with pytest.raises(WorkspaceAccessDenied):
                await required.get("personal-valid", user_id="owner")
            with pytest.raises(WorkspaceAccessDenied):
                await required.list_by_run_ids("personal-feedback", set(), user_id="owner")
        finally:
            await engine.dispose()

    asyncio.run(scenario())
