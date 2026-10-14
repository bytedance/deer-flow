"""Native event SQL must filter private workspace before paging or reduction."""

import asyncio
import json
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_workspace_executor_migration import executor_engine, native_engine  # noqa: F401


def test_event_reads_keep_private_workspace_and_branch_history(native_engine):  # noqa: F811
    from app.gateway.workspaces.service import WorkspaceService
    from deerflow.authz.workspace import reset_current_workspace, set_current_workspace
    from deerflow.persistence.models.run_event import RunEventRow
    from deerflow.persistence.thread_meta import ThreadMetaRepository
    from deerflow.persistence.user.model import UserRow
    from deerflow.persistence.workspaces.sql import WorkspaceAccessDenied, WorkspaceRepository
    from deerflow.runtime.events.store.db import DbRunEventStore

    with native_engine.begin() as conn:
        conn.execute(sa.update(UserRow).where(UserRow.id == "owner").values(email_verified_at=datetime.now(UTC)))
    driver = "sqlite+aiosqlite" if native_engine.dialect.name == "sqlite" else "postgresql+asyncpg"

    async def scenario():
        engine = create_async_engine(native_engine.url.set(drivername=driver))
        try:
            sf = async_sessionmaker(engine, expire_on_commit=False)
            repo = WorkspaceRepository(sf)
            service = WorkspaceService(repo)
            spaces = {"personal": await repo.provision_personal("owner"), "team": await repo.create_team("owner", "Event history", "event-read-main")}
            contexts = {kind: await service.resolve_context("owner", row["id"]) for kind, row in spaces.items()}
            threads = ThreadMetaRepository(sf)
            for kind, context in contexts.items():
                token = set_current_workspace(context)
                try:
                    await threads.create(kind + "-events", user_id="owner")
                finally:
                    reset_current_workspace(token)
            async with sf() as session:
                # Branch history legitimately uses inherited or synthetic Run IDs
                # without copying/executing that Run in the new conversation.
                for message_id, thread_id, workspace_id, user_id, seq in (
                    ("team-first", "team-events", spaces["team"]["id"], "owner", 1),
                    ("foreign-stamp", "team-events", spaces["personal"]["id"], "owner", 2),
                    ("team-last", "team-events", spaces["team"]["id"], "owner", 3),
                    ("legacy-null", "team-events", None, "owner", 4),
                    ("peer-private", "team-events", spaces["team"]["id"], "other", 5),
                    ("personal-first", "personal-events", spaces["personal"]["id"], "owner", 1),
                    ("wrong-parent", "personal-events", spaces["team"]["id"], "owner", 2),
                ):
                    session.add(
                        RunEventRow(
                            thread_id=thread_id,
                            run_id="branch-source",
                            workspace_id=workspace_id,
                            user_id=user_id,
                            seq=seq,
                            event_type="llm.ai.response",
                            category="message",
                            content=json.dumps({"type": "ai", "id": message_id, "content": message_id}),
                            event_metadata={"content_is_json": True},
                        )
                    )
                await session.commit()
            events = DbRunEventStore(sf)
            token = set_current_workspace(contexts["team"])
            try:
                assert await events.list_events("personal-events", "branch-source", user_id="owner") == [], "event read disclosed another workspace"
                first = await events.list_messages("team-events", limit=1, after_seq=0, user_id="owner")
                assert [r["seq"] for r in first] == [1]
                assert [r["seq"] for r in await events.list_messages("team-events", limit=1, after_seq=1, user_id="owner")] == [3]
                assert [r["seq"] for r in await events.list_messages("team-events", limit=1, user_id="owner")] == [3]
                assert [r["seq"] for r in await events.list_messages_by_run("team-events", "branch-source", user_id="owner")] == [1, 3]
                assert [r["seq"] for r in await events.list_events("team-events", "branch-source", user_id="owner")] == [1, 3]
                assert await events.count_messages("team-events", user_id="owner") == 2
                assert await events.get_last_visible_ai_seq_by_run("team-events", ["branch-source"], user_id="owner") == {"branch-source": 3}
                identities = ["message:team-first", "message:foreign-stamp", "message:legacy-null", "message:peer-private"]
                assert await events.get_message_seqs("team-events", identities, user_id="owner") == {"message:team-first": 1}
                assert await events.find_latest_ai_message_run_ids("team-events", {"team-last", "foreign-stamp"}, user_id="owner") == {"team-last": "branch-source"}
                with pytest.raises(WorkspaceAccessDenied):
                    await events.count_messages("team-events", user_id=None)
                async with sf() as session:
                    await session.execute(sa.text("UPDATE workspaces SET policy_version=policy_version+1 WHERE id=:id"), {"id": spaces["team"]["id"]})
                    await session.commit()
                assert await events.list_messages("team-events", user_id="owner") == []
                assert await events.count_messages("team-events", user_id="owner") == 0
                assert await events.get_message_seqs("team-events", identities, user_id="owner") == {}
                assert await events.get_last_visible_ai_seq_by_run("team-events", ["branch-source"], user_id="owner") == {}
            finally:
                reset_current_workspace(token)
            required = DbRunEventStore(sf, workspace_required=True)
            with pytest.raises(WorkspaceAccessDenied):
                await required.list_messages("team-events", user_id="owner")
            with pytest.raises(WorkspaceAccessDenied):
                await required.get_message_seqs("team-events", [], user_id="owner")
            with pytest.raises(WorkspaceAccessDenied):
                await required.get_last_visible_ai_seq_by_run("team-events", [], user_id="owner")
        finally:
            await engine.dispose()

    asyncio.run(scenario())
