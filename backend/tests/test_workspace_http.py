"""Real JWT/RBAC/CSRF and native SQL for managed workspace onboarding."""

import asyncio
import importlib
import importlib.util
import json
import zipfile
from datetime import UTC, datetime
from itertools import repeat as repeat_summary
from uuid import uuid4

import httpx
import pytest
import sqlalchemy as sa
from fastapi import FastAPI, HTTPException, Request
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_workspace_executor_migration import executor_engine, native_engine  # noqa: F401


def test_managed_workspace_http_uses_native_auth_and_live_scope(native_engine, monkeypatch, tmp_path, caplog):  # noqa: F811
    import aiosqlite
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
    from langchain_core.messages import AIMessage, HumanMessage
    from langgraph.checkpoint.base import empty_checkpoint
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    import deerflow.config as config_facade
    from app.gateway import deps, services
    from app.gateway.auth import config as auth_config
    from app.gateway.auth import create_access_token
    from app.gateway.auth.local_provider import LocalAuthProvider
    from app.gateway.auth.password import hash_password
    from app.gateway.auth.repositories.sqlite import SQLiteUserRepository
    from app.gateway.auth_middleware import AuthMiddleware
    from app.gateway.csrf_middleware import CSRFMiddleware
    from app.gateway.routers import artifacts, project_documents, projects, runs, thread_activity, thread_runs, threads, uploads
    from deerflow.agents.middlewares import summarization_middleware as summary_module
    from deerflow.config import app_config
    from deerflow.config import paths as paths_module
    from deerflow.config.app_config import AppConfig
    from deerflow.config.paths import Paths
    from deerflow.persistence.feedback.model import FeedbackRow
    from deerflow.persistence.feedback.sql import FeedbackRepository
    from deerflow.persistence.models.run_event import RunEventRow
    from deerflow.persistence.projects import ProjectDocumentRepository, ProjectRepository
    from deerflow.persistence.projects.model import ProjectDocumentRow, ProjectRow
    from deerflow.persistence.run.model import RunRow
    from deerflow.persistence.run.sql import RunRepository
    from deerflow.persistence.scheduled_task_events.model import ScheduledTaskEventRow
    from deerflow.persistence.thread_meta import ThreadMetaRepository
    from deerflow.persistence.thread_meta.model import ThreadMetaRow
    from deerflow.persistence.thread_reads import ThreadReadRepository
    from deerflow.persistence.thread_reads.model import ThreadReadMarkerRow
    from deerflow.persistence.user.model import UserRow
    from deerflow.persistence.workspaces.sql import WorkspaceRepository
    from deerflow.runtime import DisconnectMode, MemoryStreamBridge, RunManager, RunStatus, ThreadOperationKind, context_compaction
    from deerflow.runtime.events.store.db import DbRunEventStore
    from deerflow.runtime.events.store.memory import MemoryRunEventStore
    from deerflow.runtime.goal import build_goal_state, write_thread_goal
    from deerflow.runtime.runs.stream_cleanup import close_agent_stream
    from deerflow.sandbox.local.local_sandbox_provider import LocalSandboxProvider

    names = ("app.gateway.workspaces.service", "app.gateway.workspaces.dependencies", "app.gateway.routers.workspaces", "app.gateway.routers.admin_workspaces")
    for name in names:
        assert importlib.util.find_spec(name.rsplit(".", 1)[0]) is not None and importlib.util.find_spec(name) is not None, "managed workspace HTTP surface is not implemented"
    service_module, dependencies, routes, admin_routes = [importlib.import_module(name) for name in names]
    identities = {name: str(uuid4()) for name in ("admin", "alice", "bob")}
    password_hash = hash_password("synthetic-native-transfer-password")
    with native_engine.begin() as conn:
        for name, user_id in identities.items():
            conn.execute(sa.insert(UserRow).values(id=user_id, email=name + "@example.com", password_hash=password_hash, email_verified_at=datetime.now(UTC), system_role="admin" if name == "admin" else "user"))
    configuration = AppConfig.model_validate(
        {
            "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
            "models": [{"name": "fixture", "use": "langchain_openai:ChatOpenAI", "model": "fixture", "api_key": "synthetic-no-model-call"}],
            "memory": {"enabled": False},
            "authorization": {
                "enabled": True,
                "provider": {
                    "use": "deerflow.authz.rbac:RbacAuthorizationProvider",
                    "config": {"roles": {"admin": {"routes": {"allow": "*"}}, "user": {"routes": {"allow": "*"}}, "limited": {"routes": {"allow": "*", "deny": ["projects:write"]}}}},
                },
            },
        }
    )
    monkeypatch.setattr(config_facade, "get_app_config", lambda: configuration)
    monkeypatch.setattr(app_config, "get_app_config", lambda: configuration)
    monkeypatch.setattr(deps, "get_app_config", lambda: configuration)
    monkeypatch.setattr(services, "get_app_config", lambda: configuration)
    monkeypatch.setattr(context_compaction, "get_app_config", lambda: configuration)
    monkeypatch.setattr(paths_module, "_paths", Paths(tmp_path / "files"))
    monkeypatch.setattr(uploads, "get_sandbox_provider", lambda: LocalSandboxProvider())
    monkeypatch.setattr(auth_config, "_auth_config", auth_config.AuthConfig(jwt_secret="synthetic-isolated-workspace-http-key-64-characters-for-test-only!!"))
    monkeypatch.delenv("DEER_FLOW_AUTH_DISABLED", raising=False)
    driver = "sqlite+aiosqlite" if native_engine.dialect.name == "sqlite" else "postgresql+asyncpg"

    async def scenario():
        engine = create_async_engine(native_engine.url.set(drivername=driver))
        checkpoint_connection = await aiosqlite.connect(str(tmp_path / "checkpoints.sqlite"))
        try:
            sf = async_sessionmaker(engine, expire_on_commit=False)
            user_repo = SQLiteUserRepository(sf)
            monkeypatch.setattr(deps, "_cached_repo", user_repo)
            monkeypatch.setattr(deps, "_cached_local_provider", LocalAuthProvider(repository=user_repo))
            service = service_module.WorkspaceService(WorkspaceRepository(sf))
            app = FastAPI()
            app.state.workspace_service = service
            delete_revocation = {}
            checkpoint_replacement = {}
            owner_replacement = {}
            initialization_goals = {}
            deletion_probe = {}
            deletion_attempts = {}
            deletion_admission = {}
            activity_revocation = {}

            class RevokingRunRepository(RunRepository):
                async def latest_change(self, **kwargs):
                    result = await super().latest_change(**kwargs)
                    workspace_id = activity_revocation.pop("workspace_id", None)
                    if workspace_id:
                        async with sf() as session:
                            await session.execute(sa.text("UPDATE workspaces SET policy_version=policy_version+1 WHERE id=:id"), {"id": workspace_id})
                            await session.commit()
                    return result

                async def create_thread_operation_atomic(self, *args, **kwargs):
                    result = await super().create_thread_operation_atomic(*args, **kwargs)
                    workspace_id = deletion_admission.pop("workspace_id", None) if kwargs.get("operation_kind") == "delete" else None
                    if workspace_id:
                        async with sf() as session:
                            await session.execute(sa.text("UPDATE workspaces SET policy_version=policy_version+1 WHERE id=:id"), {"id": workspace_id})
                            await session.commit()
                    return result

            class ReplacingCheckpointSaver(AsyncSqliteSaver):
                async def adelete_thread(self, thread_id):
                    deletion_attempts[thread_id] = deletion_attempts.get(thread_id, 0) + 1
                    probe = dict(deletion_probe) if deletion_probe.get("thread_id") == thread_id else {}
                    if probe:
                        deletion_probe.clear()
                        if probe.get("fail"):
                            raise RuntimeError("Synthetic checkpoint deletion failure; do not replay unknown cleanup")
                    await super().adelete_thread(thread_id)
                    if probe:
                        async with sf() as session:
                            assert (await session.get(ThreadMetaRow, thread_id)).status == "deleting", "cleanup did not persist its lifecycle fence"
                            assert await session.scalar(sa.select(sa.func.count()).select_from(RunRow).where(RunRow.thread_id == thread_id, RunRow.operation_kind == "delete", RunRow.status == "pending")) == 1
                        nested = probe["client"]
                        assert (await nested.get("/api/threads/" + thread_id + "/state", headers=probe["headers"])).status_code == 404
                        assert (await nested.post("/api/threads/" + thread_id + "/uploads", headers=probe["headers"], files={"files": ("during.txt", b"must not publish", "text/plain")})).status_code == 404
                        assert (await nested.post("/api/threads", headers=probe["headers"], json={"thread_id": thread_id})).status_code == 404

                async def aget_tuple(self, config):
                    result = await super().aget_tuple(config)
                    thread_id = config.get("configurable", {}).get("thread_id")
                    if checkpoint_replacement.get("thread_id") == thread_id:
                        checkpoint_replacement.clear()
                        async with sf() as session:
                            await session.execute(sa.text("UPDATE threads_meta SET incarnation=:incarnation WHERE thread_id=:id"), {"incarnation": uuid4().hex, "id": thread_id})
                            await session.commit()
                    return result

            class RevokingThreadRepository(ThreadMetaRepository):
                async def create(self, thread_id, **kwargs):
                    row = await super().create(thread_id, **kwargs)
                    objective = initialization_goals.pop(thread_id, None)
                    if objective is not None:
                        # A real native writer commits after metadata allocation
                        # and before the creating HTTP request initializes root.
                        async with app.state.run_manager.reserve_thread_operation(thread_id, kind=ThreadOperationKind.checkpoint_write, user_id=row["user_id"]):
                            await write_thread_goal(app.state.checkpointer, thread_id, build_goal_state(objective), create_if_missing=True)
                    return row

                async def check_access(self, thread_id, user_id, *, require_existing=False):
                    allowed = await super().check_access(thread_id, user_id, require_existing=require_existing)
                    if allowed and owner_replacement.get("thread_id") == thread_id:
                        owner_replacement.clear()
                        async with sf() as session:
                            await session.execute(sa.text("UPDATE threads_meta SET incarnation=:incarnation WHERE thread_id=:id"), {"incarnation": uuid4().hex, "id": thread_id})
                            await session.commit()
                    workspace_id = delete_revocation.pop("workspace_id", None)
                    if allowed and workspace_id is not None:
                        # Actual persisted withdrawal between owner admission and resource mutation.
                        async with sf() as session:
                            await session.execute(sa.text("UPDATE workspaces SET policy_version=policy_version+1 WHERE id=:id"), {"id": workspace_id})
                            await session.commit()
                    return allowed

            app.state.thread_store = RevokingThreadRepository(sf, workspace_required=True)
            app.state.thread_read_repo = ThreadReadRepository(sf, workspace_required=True)
            app.state.run_store = RevokingRunRepository(sf, workspace_required=True)
            app.state.run_manager = RunManager(store=app.state.run_store, worker_id="checkpoint-http-writer")
            app.state.checkpointer = ReplacingCheckpointSaver(checkpoint_connection)
            await app.state.checkpointer.setup()
            app.state.run_event_store = MemoryRunEventStore()
            app.state.feedback_repo = FeedbackRepository(sf)
            app.state.project_repo = ProjectRepository(sf)
            app.state.project_document_repo = ProjectDocumentRepository(sf)
            app.include_router(routes.router)
            app.include_router(admin_routes.router)
            app.include_router(artifacts.router)
            app.include_router(uploads.router)
            app.include_router(threads.router)
            app.include_router(thread_activity.router)
            app.include_router(runs.router)
            app.include_router(thread_runs.router)
            app.include_router(projects.router)
            app.include_router(project_documents.router)
            app.add_middleware(AuthMiddleware)
            app.add_middleware(CSRFMiddleware)

            @app.api_route("/api/workspace-proof/{project_id}", methods=["GET", "POST"])
            async def read_resource(request: Request, project_id: str):
                context = await dependencies.resolve_workspace_context(request)
                async with sf() as session:
                    project = await session.get(ProjectRow, project_id)
                    assert project is not None
                    await service.authorize_resource(
                        context,
                        request.state.auth,
                        resource_workspace_id=project.workspace_id,
                        owner_user_id=project.user_id,
                        visibility="private",
                        action="read" if request.method == "GET" else "write",
                        native_permission="projects:read" if request.method == "GET" else "projects:write",
                    )
                return {"authorized": True}

            @app.get("/api/workspace-delayed-file/{project_id}/{document_id}")
            async def delayed_file(request: Request, project_id: str, document_id: str):
                response = await project_documents.get_project_document_content(project_id=project_id, document_id=document_id, request=request, download=True, workspace_id=None)
                async with sf() as session:
                    await session.execute(sa.text("UPDATE workspaces SET policy_version=policy_version+1 WHERE id=:id"), {"id": request.headers["X-Deerflow-Workspace"]})
                    await session.commit()
                return response

            @app.get("/api/workspace-delayed-artifact/{thread_id}/{path:path}")
            async def delayed_artifact(request: Request, thread_id: str, path: str):
                response = await artifacts.get_artifact(thread_id=thread_id, path=path, request=request, download=False)
                async with sf() as session:
                    await session.execute(sa.text("UPDATE workspaces SET policy_version=policy_version+1 WHERE id=:id"), {"id": request.headers["X-Deerflow-Workspace"]})
                    await session.commit()
                return response

            @app.get("/api/workspace-delayed-observer/{thread_id}/{run_id}")
            async def delayed_observer(request: Request, thread_id: str, run_id: str):
                response = await thread_runs.join_run(thread_id=thread_id, run_id=run_id, request=request)
                async with sf() as session:
                    await session.execute(sa.text("UPDATE workspaces SET policy_version=policy_version+1 WHERE id=:id"), {"id": request.headers["X-Deerflow-Workspace"]})
                    await session.commit()
                return response

            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost", headers={"Origin": "http://localhost", "X-CSRF-Token": "synthetic-csrf"}) as client:
                assert (await client.get("/api/workspaces")).status_code == 401

                session_versions = {}

                def as_user(name):
                    client.cookies.clear()
                    client.cookies.set("access_token", create_access_token(identities[name], token_version=session_versions.get(name, 0)))
                    client.cookies.set("csrf_token", "synthetic-csrf")

                as_user("bob")
                payload = {"owner_user_id": identities["alice"], "kind": "personal", "idempotency_key": "managed-once"}
                assert (await client.post("/api/admin/workspaces", json=payload)).status_code == 403
                as_user("admin")
                response = await client.post("/api/admin/workspaces", json=payload)
                assert response.status_code == 200, response.text
                personal = response.json()["id"]
                assert (await client.get("/api/workspaces/current", headers={"X-Deerflow-Workspace": personal})).status_code == 404
                as_user("alice")
                current = await client.get("/api/workspaces/current")
                assert current.status_code == 200 and current.json()["workspace_id"] == personal and current.json()["actor_user_id"] == identities["alice"]
                team_payload = {"name": "Research", "idempotency_key": "team-once"}
                team_response = await client.post("/api/workspaces", json=team_payload)
                assert team_response.status_code == 200, team_response.text
                team = team_response.json()["id"]
                assert (await client.post("/api/workspaces", json={**team_payload, "actor_user_id": identities["bob"]})).status_code == 422
                team_headers = {"X-Deerflow-Workspace": team}
                created = await client.post("/api/projects", headers=team_headers, json={"name": "Team source"})
                assert created.status_code == 201, created.text
                team_project = created.json()["id"]
                async with sf() as session:
                    stored = await session.get(ProjectRow, team_project)
                    assert stored.workspace_id == team, "actual project API lost the server-selected workspace"
                    assert stored.user_id == identities["alice"]
                created = await client.post("/api/projects", json={"name": "Personal source"})
                assert created.status_code == 201, created.text
                personal_project = created.json()["id"]
                assert (await client.post("/api/projects", headers=team_headers, json={"name": "Forged", "workspace_id": personal})).status_code == 422
                created_thread = await client.post(
                    "/api/threads",
                    headers=team_headers,
                    json={"thread_id": "team-research-thread", "project_id": team_project, "metadata": {"workspace_id": personal, "actor_user_id": identities["bob"], "membership_version": 99, "policy_version": 99}},
                )
                assert created_thread.status_code == 200, created_thread.text
                assert not ({"workspace_id", "actor_user_id", "membership_version", "policy_version"} & created_thread.json()["metadata"].keys())
                async with sf() as session:
                    row = await session.get(ThreadMetaRow, "team-research-thread")
                    assert row.workspace_id == team and row.user_id == identities["alice"]
                personal_thread = await client.post("/api/threads", json={"thread_id": "personal-research-thread", "project_id": personal_project})
                assert personal_thread.status_code == 200, personal_thread.text
                for entry, namespace in (("thread", ""), ("goal", ""), ("thread", "legacy-subgraph")):
                    orphan_id = str(uuid4())
                    orphan_config = {"configurable": {"thread_id": orphan_id, "checkpoint_ns": namespace}}
                    orphan_checkpoint = empty_checkpoint()
                    orphan_checkpoint["channel_values"] = {"messages": [HumanMessage(content="unattributed legacy private sentinel")]}
                    orphan_checkpoint["channel_versions"] = {"messages": app.state.checkpointer.get_next_version(None, None)}
                    await app.state.checkpointer.aput(orphan_config, orphan_checkpoint, {"step": 0, "source": "update", "writes": {}, "parents": {}}, orphan_checkpoint["channel_versions"])
                    before_claim = await app.state.checkpointer.aget_tuple(orphan_config)
                    if entry == "thread":
                        refused = await client.post("/api/threads", headers=team_headers, json={"thread_id": orphan_id})
                    else:
                        refused = await client.put("/api/threads/" + orphan_id + "/goal", headers=team_headers, json={"objective": "New objective must not adopt legacy data"})
                    assert refused.status_code == 404, "checkpoint-only ID was claimed through " + entry + ": " + refused.text
                    async with sf() as session:
                        assert await session.get(ThreadMetaRow, orphan_id) is None, "refused checkpoint claim still allocated metadata"
                    after_claim = await app.state.checkpointer.aget_tuple(orphan_config)
                    assert after_claim.config == before_claim.config
                    assert after_claim.checkpoint["channel_values"]["messages"][0].content == "unattributed legacy private sentinel"
                interleaved_id = str(uuid4())
                initialization_goals[interleaved_id] = "Already committed native goal"
                interleaved_create = await client.post("/api/threads", headers=team_headers, json={"thread_id": interleaved_id})
                assert interleaved_create.status_code == 200, interleaved_create.text
                preserved_goal = await client.get("/api/threads/" + interleaved_id + "/goal", headers=team_headers)
                assert preserved_goal.status_code == 200 and preserved_goal.json()["goal"]["objective"] == "Already committed native goal", "thread initialization overwrote admitted native goal"
                for thread_id, marker in (("team-research-thread", "team checkpoint sentinel"), ("personal-research-thread", "personal checkpoint sentinel")):
                    old = await app.state.checkpointer.aget_tuple({"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}})
                    checkpoint = empty_checkpoint()
                    checkpoint["channel_values"] = {"messages": [HumanMessage(content=marker, id=thread_id + "-message")], "title": marker, "goal": build_goal_state(marker + " objective")}
                    checkpoint["channel_versions"] = {channel: app.state.checkpointer.get_next_version(None, None) for channel in ("messages", "title", "goal")}
                    await app.state.checkpointer.aput(old.config, checkpoint, {"step": 0, "source": "update", "writes": {}, "parents": {}}, checkpoint["channel_versions"])
                # Reopen a durable native checkpoint connection before exercising REST reads.
                await checkpoint_connection.close()
                checkpoint_connection = await aiosqlite.connect(str(tmp_path / "checkpoints.sqlite"))
                app.state.checkpointer = ReplacingCheckpointSaver(checkpoint_connection)
                for thread_id, marker, headers in (("team-research-thread", "team checkpoint sentinel", team_headers), ("personal-research-thread", "personal checkpoint sentinel", {})):
                    info = await client.get("/api/threads/" + thread_id, headers=headers)
                    assert info.status_code == 200, info.text
                    assert info.json()["values"]["messages"][0]["content"] == marker
                    state = await client.get("/api/threads/" + thread_id + "/state", headers=headers)
                    assert state.status_code == 200, state.text
                    assert state.json()["values"]["messages"][0]["content"] == marker
                    history = await client.post("/api/threads/" + thread_id + "/history", headers=headers, json={"limit": 1})
                    assert history.status_code == 200, history.text
                    assert history.json()[0]["values"]["messages"][0]["content"] == marker
                    goal = await client.get("/api/threads/" + thread_id + "/goal", headers=headers)
                    assert goal.status_code == 200 and goal.json()["goal"]["objective"] == marker + " objective", goal.text
                for suffix in ("", "/state", "/goal"):
                    assert (await client.get("/api/threads/team-research-thread" + suffix)).status_code == 404
                    assert (await client.get("/api/threads/personal-research-thread" + suffix, headers=team_headers)).status_code == 404
                assert (await client.post("/api/threads/team-research-thread/history", json={"limit": 1})).status_code == 404
                assert (await client.post("/api/threads/personal-research-thread/history", headers=team_headers, json={"limit": 1})).status_code == 404
                assert not any("Agent factory unavailable" in record.message for record in caplog.records), "state acceptance must use the native compiled graph, not degraded raw reads"
                checkpoint_replacement["thread_id"] = "team-research-thread"
                stale_state = await client.get("/api/threads/team-research-thread/state", headers=team_headers)
                assert stale_state.status_code == 404, "prepared state outlived its admitted thread incarnation"
                assert b"team checkpoint sentinel" not in stale_state.content
                assert (await client.get("/api/threads/team-research-thread/state", headers=team_headers)).status_code == 200
                new_goal_id = str(uuid4())
                goal_created = await client.put("/api/threads/" + new_goal_id + "/goal", headers=team_headers, json={"objective": "New team research objective"})
                assert goal_created.status_code == 200, goal_created.text
                assert goal_created.json()["goal"]["objective"] == "New team research objective"
                async with sf() as session:
                    new_goal_thread = await session.get(ThreadMetaRow, new_goal_id)
                    assert new_goal_thread.workspace_id == team and new_goal_thread.user_id == identities["alice"]
                    assert (await session.scalar(sa.select(sa.func.count()).select_from(RunRow).where(RunRow.operation_kind != "run"))) == 0
                state_updated = await client.post("/api/threads/team-research-thread/state", headers=team_headers, json={"values": {"title": "Updated team title"}})
                assert state_updated.status_code == 200 and state_updated.json()["values"]["title"] == "Updated team title", state_updated.text
                async with sf() as session:
                    assert (await session.get(ThreadMetaRow, "team-research-thread")).display_name == "Updated team title"
                personal_state = await client.get("/api/threads/personal-research-thread/state")
                assert personal_state.json()["values"]["title"] == "personal checkpoint sentinel"
                for method, suffix, payload in (("PUT", "/goal", {"objective": "Foreign goal"}), ("POST", "/state", {"values": {"title": "Foreign title"}}), ("DELETE", "/goal", None)):
                    response = await client.request(method, "/api/threads/team-research-thread" + suffix, json=payload)
                    assert response.status_code == 404, response.text
                cleared = await client.delete("/api/threads/" + new_goal_id + "/goal", headers=team_headers)
                assert cleared.status_code == 200 and cleared.json()["goal"] is None, cleared.text
                assert (await client.get("/api/threads/" + new_goal_id + "/goal", headers=team_headers)).json()["goal"] is None
                before_replaced = await app.state.checkpointer.aget_tuple({"configurable": {"thread_id": "team-research-thread", "checkpoint_ns": ""}})
                checkpoint_replacement["thread_id"] = "team-research-thread"
                replaced_update = await client.post("/api/threads/team-research-thread/state", headers=team_headers, json={"values": {"title": "Replaced thread title"}})
                assert replaced_update.status_code == 404, replaced_update.text
                after_replaced = await app.state.checkpointer.aget_tuple({"configurable": {"thread_id": "team-research-thread", "checkpoint_ns": ""}})
                assert after_replaced.config == before_replaced.config, "state committed across changed thread incarnation"
                for method, suffix, payload in (("PUT", "/goal", {"objective": "Replaced owner goal"}), ("POST", "/state", {"values": {"title": "Replaced owner title"}}), ("DELETE", "/goal", None)):
                    before_owner_change = await app.state.checkpointer.aget_tuple({"configurable": {"thread_id": "team-research-thread", "checkpoint_ns": ""}})
                    owner_replacement["thread_id"] = "team-research-thread"
                    rejected = await client.request(method, "/api/threads/team-research-thread" + suffix, headers=team_headers, json=payload)
                    assert rejected.status_code == 404, rejected.text
                    after_owner_change = await app.state.checkpointer.aget_tuple({"configurable": {"thread_id": "team-research-thread", "checkpoint_ns": ""}})
                    assert after_owner_change.config == before_owner_change.config, "owner admission replacement still committed checkpoint bytes"
                # Withdrawal after genuine native owner admission must not mutate checkpoints.
                before_denied = await app.state.checkpointer.aget_tuple({"configurable": {"thread_id": "team-research-thread", "checkpoint_ns": ""}})
                delete_revocation["workspace_id"] = team
                denied_update = await client.post("/api/threads/team-research-thread/state", headers=team_headers, json={"values": {"title": "Withdrawn title"}})
                assert denied_update.status_code == 404, denied_update.text
                after_denied = await app.state.checkpointer.aget_tuple({"configurable": {"thread_id": "team-research-thread", "checkpoint_ns": ""}})
                assert after_denied.config == before_denied.config
                delete_revocation["workspace_id"] = team
                denied_goal = await client.put("/api/threads/team-research-thread/goal", headers=team_headers, json={"objective": "Withdrawn objective"})
                assert denied_goal.status_code == 404, denied_goal.text
                after_denied_goal = await app.state.checkpointer.aget_tuple({"configurable": {"thread_id": "team-research-thread", "checkpoint_ns": ""}})
                assert after_denied_goal.config == before_denied.config
                async with sf() as session:
                    session.add(RunRow(run_id="team-read-http", thread_id="team-research-thread", workspace_id=team, user_id=identities["alice"], status="success", change_seq=10, origin_kind="schedule"))
                    await session.commit()
                read = await client.post("/api/threads/team-research-thread/read", headers=team_headers)
                assert read.status_code == 200 and read.json()["read_version"] == 1, read.text
                repeat = await client.post("/api/threads/team-research-thread/read", headers=team_headers)
                assert repeat.status_code == 200 and repeat.json()["read_version"] == 1
                personal_read = await client.post("/api/threads/personal-research-thread/read")
                assert personal_read.status_code == 200 and personal_read.json()["read_version"] == 0, personal_read.text
                assert (await client.post("/api/threads/team-research-thread/read")).status_code == 404
                async with sf() as session:
                    await session.execute(sa.update(RunRow).where(RunRow.run_id == "team-read-http").values(change_seq=11))
                    await session.commit()
                delete_revocation["workspace_id"] = team
                assert (await client.post("/api/threads/team-research-thread/read", headers=team_headers)).status_code == 404
                async with sf() as session:
                    position = await session.scalar(sa.text("SELECT seen_change_seq FROM thread_read_markers WHERE user_id=:user AND thread_id='team-research-thread'"), {"user": identities["alice"]})
                    assert position == 10, "withdrawn read admission mutated the marker"
                # One viewer, independent activity/read heads in two spaces.
                async with sf() as session:
                    session.add(ThreadMetaRow(thread_id="peer-activity", workspace_id=team, user_id=identities["bob"], incarnation=uuid4().hex))
                    session.add_all(
                        [
                            RunRow(run_id="peer-activity-run", thread_id="peer-activity", workspace_id=team, user_id=identities["bob"], status="success", change_seq=9, origin_kind="schedule"),
                            RunRow(run_id="team-interactive-http", thread_id="team-research-thread", workspace_id=team, user_id=identities["alice"], status="success", change_seq=12),
                            RunRow(run_id="personal-activity-http", thread_id="personal-research-thread", workspace_id=personal, user_id=identities["alice"], status="success", change_seq=22, origin_kind="schedule"),
                            RunRow(run_id="foreign-stamp-http", thread_id="team-research-thread", workspace_id=personal, user_id=identities["alice"], status="success", change_seq=25, origin_kind="schedule"),
                        ]
                    )
                    await session.commit()
                team_head = await client.get("/api/thread-activity", headers=team_headers)
                assert team_head.status_code == 200, team_head.text
                assert team_head.json() == {"cursor": "12:team-interactive-http", "threads": [], "truncated": False, "read_version": 1}
                personal_head = await client.get("/api/thread-activity")
                assert personal_head.status_code == 200, personal_head.text
                assert personal_head.json() == {"cursor": "22:personal-activity-http", "threads": [], "truncated": False, "read_version": 0}
                team_activity = await client.get("/api/thread-activity?cursor=0:&limit=1", headers=team_headers)
                assert team_activity.status_code == 200, team_activity.text
                assert team_activity.json()["threads"] == [{"thread_id": "team-research-thread", "origin_kind": "schedule", "status": "success"}]
                assert team_activity.json()["truncated"] is True
                next_activity = await client.get("/api/thread-activity", headers=team_headers, params={"cursor": team_activity.json()["cursor"], "limit": 1})
                assert next_activity.json() == team_head.json(), "interactive changes must advance only this space's cursor"
                own_activity = await client.get("/api/thread-activity?cursor=0:")
                assert own_activity.status_code == 200, own_activity.text
                assert own_activity.json()["threads"] == [{"thread_id": "personal-research-thread", "origin_kind": "schedule", "status": "success"}]
                activity_revocation["workspace_id"] = team
                assert (await client.get("/api/thread-activity", headers=team_headers)).status_code == 404
                thread_upload = await client.post("/api/threads/team-research-thread/uploads", headers=team_headers, files={"files": ("team.txt", b"private thread source", "text/plain")})
                assert thread_upload.status_code == 200, thread_upload.text
                private_upload = await client.post("/api/threads/personal-research-thread/uploads", files={"files": ("team.txt", b"personal different bytes", "text/plain")})
                assert private_upload.status_code == 200, private_upload.text
                team_root = tmp_path / "files" / "workspaces" / team / "users" / identities["alice"] / "threads" / "team-research-thread" / "user-data" / "uploads"
                personal_root = tmp_path / "files" / "workspaces" / personal / "users" / identities["alice"] / "threads" / "personal-research-thread" / "user-data" / "uploads"
                assert (team_root / "team.txt").read_bytes() == b"private thread source"
                assert (personal_root / "team.txt").read_bytes() == b"personal different bytes"
                artifact_url = thread_upload.json()["files"][0]["artifact_url"]
                assert "workspace_id=" + team in artifact_url, "thread file links lose their trusted workspace locator"
                downloaded = await client.get(artifact_url)
                assert downloaded.status_code == 200 and downloaded.content == b"private thread source"
                assert downloaded.headers["cache-control"] == "private, no-store"
                ranged = await client.get(artifact_url, headers={"Range": "bytes=0-6"})
                assert ranged.status_code == 206 and ranged.content == b"private"
                assert (await client.get(artifact_url, headers={"X-Deerflow-Workspace": personal})).status_code == 404
                assert (await client.get(artifact_url.split("?", 1)[0])).status_code == 404
                with zipfile.ZipFile(team_root / "notes.skill", "w") as archive:
                    archive.writestr("SKILL.md", b"# private pack")
                skill_path = "mnt/user-data/uploads/notes.skill/SKILL.md"
                skill_url = "/api/threads/team-research-thread/artifacts/" + skill_path + "?workspace_id=" + team
                packed = await client.get(skill_url)
                assert packed.status_code == 200 and packed.content == b"# private pack"
                assert packed.headers["cache-control"] == "private, no-store"
                delayed = await client.get("/api/workspace-delayed-artifact/team-research-thread/mnt/user-data/uploads/team.txt", headers=team_headers)
                assert delayed.status_code == 404 and b"private thread source" not in delayed.content
                delayed = await client.get("/api/workspace-delayed-artifact/team-research-thread/" + skill_path, headers=team_headers)
                assert delayed.status_code == 404 and b"# private pack" not in delayed.content
                revocable = await client.post("/api/threads/team-research-thread/uploads", headers=team_headers, files={"files": ("revocation.txt", b"must survive withdrawn deletion", "text/plain")})
                assert revocable.status_code == 200, revocable.text
                delete_revocation["workspace_id"] = team
                denied_delete = await client.delete("/api/threads/team-research-thread/uploads/revocation.txt", headers=team_headers)
                assert denied_delete.status_code == 404, denied_delete.text
                assert (team_root / "revocation.txt").is_file(), "withdrawn deletion removed the private file before final authorization"
                assert (team_root / "revocation.txt").read_bytes() == b"must survive withdrawn deletion"
                valid_delete = await client.delete("/api/threads/team-research-thread/uploads/revocation.txt", headers=team_headers)
                assert valid_delete.status_code == 200, valid_delete.text
                assert not (team_root / "revocation.txt").exists()
                assert (await client.get("/api/threads/team-research-thread/uploads/list")).status_code == 404
                assert (await client.post("/api/threads/team-research-thread/uploads", files={"files": ("foreign.txt", b"foreign write", "text/plain")})).status_code == 404
                assert [r["thread_id"] for r in (await client.post("/api/threads/search", headers=team_headers, json={"limit": 1})).json()] == ["team-research-thread"]
                assert [r["thread_id"] for r in (await client.post("/api/threads/search", json={})).json()] == ["personal-research-thread"]
                patched = await client.patch("/api/threads/team-research-thread", headers=team_headers, json={"metadata": {"deerflow_pinned": True}})
                assert patched.status_code == 200, patched.text
                assert patched.json()["metadata"]["deerflow_pinned"] is True
                assert (await client.patch("/api/threads/team-research-thread", json={"metadata": {"leak": True}})).status_code == 404
                assert (await client.post("/api/threads/team-research-thread/move", headers=team_headers, json={"project_id": personal_project})).status_code == 404
                retry = await client.post("/api/threads", headers=team_headers, json={"thread_id": "team-research-thread"})
                assert retry.status_code == 200 and retry.json()["metadata"]["deerflow_project_id"] == team_project
                collision = await client.post("/api/threads", json={"thread_id": "team-research-thread"})
                assert collision.status_code == 404, collision.text
                assert [r["thread_id"] for r in (await client.get("/api/projects/" + team_project + "/threads", headers=team_headers)).json()] == ["team-research-thread"]
                assert (await client.get("/api/projects/" + team_project + "/threads")).status_code == 404
                team_docs = "/api/projects/" + team_project + "/documents"
                uploaded = await client.post(team_docs, headers=team_headers, files={"file": ("team.txt", b"team private notes", "text/plain")})
                assert uploaded.status_code == 201, uploaded.text
                team_document = uploaded.json()["document"]["id"]
                attach_url = team_docs + "/" + team_document + "/attach-to-thread/team-research-thread"
                attached = await client.post(attach_url, headers=team_headers)
                assert attached.status_code == 200, attached.text
                assert attached.json()["filename"] == "team_1.txt"
                assert (team_root / "team_1.txt").read_bytes() == b"team private notes"
                assert (team_root / "team.txt").read_bytes() == b"private thread source"
                assert (await client.post(attach_url)).status_code == 404
                assert (await client.post(team_docs + "/" + team_document + "/attach-to-thread/personal-research-thread", headers=team_headers)).status_code == 404
                async with sf() as session:
                    document = await session.get(ProjectDocumentRow, team_document)
                    assert document.workspace_id == team, "uploaded document lost workspace ownership"
                    original = tmp_path / "files" / "workspaces" / team / "projects" / document.stored_relpath / "original" / "team.txt"
                    assert original.read_bytes() == b"team private notes"
                personal_docs = "/api/projects/" + personal_project + "/documents"
                uploaded = await client.post(personal_docs, files={"file": ("personal.txt", b"personal private notes", "text/plain")})
                assert uploaded.status_code == 201, uploaded.text
                personal_document = uploaded.json()["document"]["id"]
                page = (await client.get(team_docs + "?limit=1&offset=0", headers=team_headers)).json()
                assert page["total"] == 1 and [r["id"] for r in page["documents"]] == [team_document]
                assert (await client.get(team_docs, headers={"X-Deerflow-Workspace": personal})).status_code == 404
                content = team_docs + "/" + team_document + "/content"
                response = await client.get(content, headers=team_headers)
                assert response.status_code == 200 and response.content == b"team private notes"
                assert response.headers["cache-control"] == "private, no-store"
                assert (await client.get(content)).status_code == 404
                response = await client.get(content + "?download=true&workspace_id=" + team)
                assert response.status_code == 200 and response.content == b"team private notes"
                assert (await client.get(content + "?workspace_id=" + personal, headers=team_headers)).status_code == 404
                assert (await client.get(team_docs + "/" + personal_document + "/content", headers=team_headers)).status_code == 404
                delayed = await client.get("/api/workspace-delayed-file/" + team_project + "/" + team_document, headers=team_headers)
                assert delayed.status_code == 404 and b"team private notes" not in delayed.content
                assert (await client.delete(team_docs + "/" + team_document, headers={"X-Deerflow-Workspace": personal})).status_code == 404
                assert (await client.delete(team_docs + "/" + team_document, headers=team_headers)).status_code == 204
                assert (await client.get(content, headers=team_headers)).status_code == 404
                promoted = await client.post(team_docs + "/from-thread", headers=team_headers, json={"thread_id": "team-research-thread", "kind": "upload", "name": "team.txt"})
                assert promoted.status_code == 201, promoted.text
                promoted_document = promoted.json()["document"]
                assert promoted_document["source_thread_id"] == "team-research-thread"
                result = await client.get(team_docs + "/" + promoted_document["id"] + "/content", headers=team_headers)
                assert result.status_code == 200 and result.content == b"private thread source"
                assert (team_root / "team.txt").read_bytes() == b"private thread source"
                assert (await client.post(team_docs + "/from-thread", headers=team_headers, json={"thread_id": "personal-research-thread", "kind": "upload", "name": "team.txt"})).status_code == 404
                assert [r["id"] for r in (await client.get("/api/projects", headers=team_headers)).json()["projects"]] == [team_project]
                assert [r["id"] for r in (await client.get("/api/projects")).json()["projects"]] == [personal_project]
                personal_headers = {"X-Deerflow-Workspace": personal}
                project_url = "/api/projects/" + team_project
                assert (await client.get(project_url, headers=personal_headers)).status_code == 404
                assert (await client.patch(project_url, headers=personal_headers, json={"name": "Cross-space edit"})).status_code == 404
                assert (await client.post(project_url + "/archive", headers=personal_headers)).status_code == 404
                assert (await client.delete(project_url, headers=personal_headers)).status_code == 404
                assert (await client.patch(project_url, headers=team_headers, json={"name": "Updated team source"})).status_code == 200
                assert (await client.post(project_url + "/archive", headers=team_headers)).status_code == 200
                assert [r["id"] for r in (await client.get("/api/projects?status=archived", headers=team_headers)).json()["projects"]] == [team_project]
                assert (await client.post(project_url + "/restore", headers=team_headers)).status_code == 200
                old_project_context = await service.resolve_context(identities["alice"], team)
                async with sf() as session:
                    await session.execute(sa.text("UPDATE workspaces SET policy_version=policy_version+1 WHERE id=:id"), {"id": team})
                    await session.commit()
                from deerflow.persistence.workspaces.sql import WorkspaceAccessDenied

                with pytest.raises(WorkspaceAccessDenied):
                    await app.state.project_repo.create(name="Stale write", user_id=identities["alice"], workspace_context=old_project_context)
                guarded = ProjectRepository(sf, workspace_required=True)
                with pytest.raises(WorkspaceAccessDenied):
                    await guarded.get(team_project, user_id=identities["alice"])
                assert await guarded.get(team_project, user_id=identities["alice"], workspace_context=old_project_context) is None
                async with sf() as session:
                    session.add(
                        ProjectDocumentRow(id="foreign-child", project_id=team_project, workspace_id=personal, user_id=identities["alice"], name="Metadata-only fixture", stored_relpath="synthetic.txt", sha256="0" * 64, size_bytes=1)
                    )
                    await session.commit()
                assert (await client.delete(project_url, headers=team_headers)).status_code == 404
                async with sf() as session:
                    assert (await session.get(ProjectDocumentRow, "foreign-child")).trashed_at is None
                    await session.execute(sa.delete(ProjectDocumentRow).where(ProjectDocumentRow.id == "foreign-child"))
                    await session.commit()
                assert (await client.delete(project_url, headers=team_headers)).status_code == 204
                assert (await client.get(project_url, headers=team_headers)).status_code == 404
                members_url = "/api/workspaces/" + team + "/members"
                members = await client.get(members_url, headers=team_headers)
                assert members.status_code == 200, members.text
                assert [member["user_id"] for member in members.json()] == [identities["alice"]]
                as_user("bob")
                assert (await client.get("/api/workspaces/current", headers=team_headers)).status_code == 404
                as_user("alice")
                await service.repository.add_member(team, identities["alice"], identities["bob"], role="member")
                shared = await client.post("/api/projects", headers=team_headers, json={"name": "Shared research", "visibility": "workspace"})
                assert shared.status_code == 201, shared.text
                shared_project = shared.json()["id"]
                assert shared.json()["visibility"] == "workspace"
                private = await client.post("/api/projects", headers=team_headers, json={"name": "Private team draft"})
                assert private.status_code == 201, private.text
                private_project = private.json()["id"]
                shared_docs = "/api/projects/" + shared_project + "/documents"
                uploaded = await client.post(shared_docs, headers=team_headers, files={"file": ("shared.txt", b"team published source", "text/plain")})
                assert uploaded.status_code == 201, uploaded.text
                shared_document = uploaded.json()["document"]["id"]
                shared_content = shared_docs + "/" + shared_document + "/content"
                as_user("bob")
                assert (await client.get("/api/projects/" + private_project, headers=team_headers)).status_code == 404
                assert (await client.get("/api/projects/" + shared_project, headers=team_headers)).status_code == 200
                peer_thread = await client.post("/api/threads", headers=team_headers, json={"thread_id": "bob-shared-research", "project_id": shared_project})
                assert peer_thread.status_code == 200, peer_thread.text
                assert (await client.get(artifact_url)).status_code == 404
                shared_attached = await client.post(shared_docs + "/" + shared_document + "/attach-to-thread/bob-shared-research", headers=team_headers)
                assert shared_attached.status_code == 200, shared_attached.text
                peer_upload = tmp_path / "files" / "workspaces" / team / "users" / identities["bob"] / "threads" / "bob-shared-research" / "user-data" / "uploads" / "shared.txt"
                assert peer_upload.read_bytes() == b"team published source"
                assert (await client.post(shared_docs + "/" + shared_document + "/attach-to-thread/team-research-thread", headers=team_headers)).status_code == 404
                assert [r["thread_id"] for r in (await client.get("/api/projects/" + shared_project + "/threads", headers=team_headers)).json()] == ["bob-shared-research"]
                assert (await client.patch("/api/threads/team-research-thread", headers=team_headers, json={"metadata": {"member_write": True}})).status_code == 404
                listed = (await client.get("/api/projects", headers=team_headers)).json()["projects"]
                assert [row["id"] for row in listed] == [shared_project]
                page = (await client.get(shared_docs, headers=team_headers)).json()
                assert page["total"] == 1 and page["documents"][0]["id"] == shared_document
                content = await client.get(shared_content, headers=team_headers)
                assert content.status_code == 200 and content.content == b"team published source"
                assert (await client.get(shared_content)).status_code == 404
                assert (await client.post(shared_docs, headers=team_headers, files={"file": ("forbidden.txt", b"member edit", "text/plain")})).status_code == 403
                assert (await client.patch("/api/projects/" + shared_project, headers=team_headers, json={"name": "Member edit"})).status_code == 403
                assert (await client.post("/api/projects", headers=team_headers, json={"name": "Member publish", "visibility": "workspace"})).status_code == 403
                as_user("alice")
                assert (await client.post("/api/projects", json={"name": "Personal shared", "visibility": "workspace"})).status_code == 403
                published = await client.patch("/api/projects/" + private_project, headers=team_headers, json={"visibility": "workspace"})
                assert published.status_code == 200 and published.json()["visibility"] == "workspace"
                as_user("bob")
                assert (await client.get("/api/projects/" + private_project, headers=team_headers)).status_code == 200
                as_user("alice")
                bob_context = await service.resolve_context(identities["bob"], team)
                as_user("bob")
                assert (await client.patch(members_url + "/" + identities["alice"], json={"role": "admin"}, headers=team_headers)).status_code == 403
                as_user("alice")
                assert (await client.patch(members_url + "/" + identities["bob"], json={"role": "admin"}, headers=team_headers)).status_code == 200
                with pytest.raises(HTTPException) as stale_member:
                    await service.revalidate(bob_context)
                assert stale_member.value.status_code == 404
                as_user("bob")
                uploaded = await client.post(shared_docs, headers=team_headers, files={"file": ("admin.txt", b"admin published source", "text/plain")})
                assert uploaded.status_code == 201, uploaded.text
                admin_document = uploaded.json()["document"]["id"]
                async with sf() as session:
                    persisted = await session.get(ProjectDocumentRow, admin_document)
                    assert persisted.user_id == identities["bob"] and persisted.workspace_id == team
                as_user("alice")
                content = await client.get(shared_docs + "/" + admin_document + "/content", headers=team_headers)
                assert content.status_code == 200 and content.content == b"admin published source"
                # Replace only model output; keep native compaction selection,
                # summary middleware, graph mutation and durable storage real.
                summary_inputs = []
                summary_fault = {}

                class DeterministicSummaryModel(GenericFakeChatModel):
                    async def ainvoke(self, input, config=None, **kwargs):
                        summary_inputs.append(str(input))
                        workspace_id = summary_fault.pop("workspace_id", None)
                        replaced_id = summary_fault.pop("thread_id", None)
                        if workspace_id or replaced_id:
                            async with sf() as session:
                                if workspace_id:
                                    await session.execute(sa.text("UPDATE workspaces SET policy_version=policy_version+1 WHERE id=:id"), {"id": workspace_id})
                                if replaced_id:
                                    await session.execute(sa.text("UPDATE threads_meta SET incarnation=:incarnation WHERE thread_id=:id"), {"incarnation": uuid4().hex, "id": replaced_id})
                                await session.commit()
                        return await super().ainvoke(input, config=config, **kwargs)

                monkeypatch.setattr(summary_module, "create_chat_model", lambda *args, **kwargs: DeterministicSummaryModel(messages=repeat_summary("Deterministic summary of older team messages")))
                configuration.summarization.enabled = True
                compact_body = {"force": True, "keep": {"type": "messages", "value": 2}}
                for compaction_case in ("success", "withdrawal", "replacement"):
                    compact_id = str(uuid4())
                    compact_created = await client.post("/api/threads", headers=team_headers, json={"thread_id": compact_id})
                    assert compact_created.status_code == 200, compact_created.text
                    compact_config = {"configurable": {"thread_id": compact_id, "checkpoint_ns": ""}}
                    compact_root = await app.state.checkpointer.aget_tuple(compact_config)
                    compact_checkpoint = empty_checkpoint()
                    compact_checkpoint["channel_values"] = {
                        "messages": [
                            HumanMessage(id="old-human", content="Older team question " + compaction_case),
                            AIMessage(id="old-ai", content="Older team answer"),
                            HumanMessage(id="latest-human", content="Latest team question"),
                            AIMessage(id="latest-ai", content="Latest team answer"),
                        ]
                    }
                    compact_checkpoint["channel_versions"] = {"messages": app.state.checkpointer.get_next_version(None, None)}
                    await app.state.checkpointer.aput(compact_root.config, compact_checkpoint, {"step": 0, "source": "update", "writes": {}, "parents": {}}, compact_checkpoint["channel_versions"])
                    before_compact = await app.state.checkpointer.aget_tuple(compact_config)
                    calls_before = len(summary_inputs)
                    if compaction_case == "withdrawal":
                        summary_fault["workspace_id"] = team
                    elif compaction_case == "replacement":
                        summary_fault["thread_id"] = compact_id
                    compacted = await client.post("/api/threads/" + compact_id + "/compact", headers=team_headers, json=compact_body)
                    assert len(summary_inputs) == calls_before + 1, "native summarizer did not reach deterministic model boundary"
                    if compaction_case == "success":
                        assert compacted.status_code == 200 and compacted.json()["compacted"] is True, compacted.text
                        assert compacted.json()["removed_message_count"] == 2 and compacted.json()["preserved_message_count"] == 2
                        compact_state = await client.get("/api/threads/" + compact_id + "/state", headers=team_headers)
                        assert compact_state.json()["values"]["summary_text"] == "Deterministic summary of older team messages"
                        assert [m["id"] for m in compact_state.json()["values"]["messages"]] == ["latest-human", "latest-ai"]
                        assert "Older team question success" in summary_inputs[-1] and "personal checkpoint sentinel" not in summary_inputs[-1]
                    else:
                        assert compacted.status_code == 404, compacted.text
                        after_compact = await app.state.checkpointer.aget_tuple(compact_config)
                        assert after_compact.config == before_compact.config, "withdrawn/replaced compaction committed checkpoint bytes"
                calls_before = len(summary_inputs)
                checkpoint_replacement["thread_id"] = compact_id
                assert (await client.post("/api/threads/" + compact_id + "/compact", headers=team_headers, json=compact_body)).status_code == 404
                assert len(summary_inputs) == calls_before, "replaced snapshot was sent to the summary model"
                assert (await client.post("/api/threads/" + compact_id + "/compact", json=compact_body)).status_code == 404
                as_user("bob")
                assert (await client.post("/api/threads/" + compact_id + "/compact", headers=team_headers, json=compact_body)).status_code == 404
                assert len(summary_inputs) == calls_before
                as_user("alice")
                configuration.summarization.enabled = False
                delete_ids = {}
                for delete_space, delete_headers, delete_workspace in (("team", team_headers, team), ("personal", {}, personal)):
                    delete_id = str(uuid4())
                    delete_ids[delete_space] = delete_id
                    assert (await client.post("/api/threads", headers=delete_headers, json={"thread_id": delete_id})).status_code == 200
                    assert (await client.post("/api/threads/" + delete_id + "/uploads", headers=delete_headers, files={"files": ("delete.txt", (delete_space + " private bytes").encode(), "text/plain")})).status_code == 200
                    async with sf() as session:
                        session.add(RunRow(run_id=delete_id + "-run", thread_id=delete_id, workspace_id=delete_workspace, user_id=identities["alice"], status="success", change_seq=200))
                        session.add(
                            RunEventRow(
                                thread_id=delete_id,
                                run_id=delete_id + "-run",
                                workspace_id=delete_workspace,
                                user_id=identities["alice"],
                                event_type="llm.ai.response",
                                category="message",
                                content=json.dumps({"type": "ai", "id": delete_id + "-message", "content": delete_space + " private response"}),
                                event_metadata={"content_is_json": True},
                                seq=1,
                            )
                        )
                        session.add(FeedbackRow(feedback_id=delete_id, run_id=delete_id + "-run", thread_id=delete_id, user_id=identities["alice"], rating=1))
                        session.add(ThreadReadMarkerRow(user_id=identities["alice"], thread_id=delete_id, seen_change_seq=200))
                        session.add(
                            ScheduledTaskEventRow(
                                id=delete_id, task_id=delete_id, thread_id=delete_id, workspace_id=delete_workspace, user_id=identities["alice"], anchor="fixture", event="task_finished", reason_code="completed", payload_json={}
                            )
                        )
                        await session.commit()
                    await app.state.run_event_store.put(thread_id=delete_id, run_id=delete_id + "-run", event_type="llm.ai.response", category="message", content="owned history")
                # Read actual durable history via native HTTP and SQL event storage.
                memory_events = app.state.run_event_store
                app.state.run_event_store = DbRunEventStore(sf, workspace_required=True)
                team_run = delete_ids["team"] + "-run"
                personal_run = delete_ids["personal"] + "-run"
                team_run_base = "/api/threads/" + delete_ids["team"]
                personal_run_base = "/api/threads/" + delete_ids["personal"]
                run_list = await client.get(team_run_base + "/runs", headers=team_headers)
                assert run_list.status_code == 200, run_list.text
                assert [row["run_id"] for row in run_list.json()] == [team_run]
                run_page = await client.get(team_run_base + "/runs/page?limit=1", headers=team_headers)
                assert run_page.status_code == 200 and [r["run_id"] for r in run_page.json()["data"]] == [team_run], run_page.text
                run_detail = await client.get(team_run_base + "/runs/" + team_run, headers=team_headers)
                assert run_detail.status_code == 200 and run_detail.json()["status"] == "success", run_detail.text
                assert (await client.get(team_run_base + "/runs/" + personal_run, headers=team_headers)).status_code == 404
                for suffix in ("/runs", "/runs/page", "/runs/" + team_run, "/messages", "/messages/page", "/runs/" + team_run + "/messages", "/runs/" + team_run + "/events"):
                    assert (await client.get(team_run_base + suffix)).status_code == 404
                for base, headers, run_id, expected in ((team_run_base, team_headers, team_run, "team private response"), (personal_run_base, {}, personal_run, "personal private response")):
                    for suffix in ("/messages", "/messages/page?limit=1", "/runs/" + run_id + "/messages", "/runs/" + run_id + "/events"):
                        visible = await client.get(base + suffix, headers=headers)
                        assert visible.status_code == 200, visible.text
                        rows = visible.json() if isinstance(visible.json(), list) else visible.json()["data"]
                        assert len(rows) == 1 and rows[0]["content"]["content"] == expected, visible.text
                # Global run locators must bind the same live private space as thread routes.
                for headers, run_id, expected in ((team_headers, team_run, "team private response"), ({}, personal_run, "personal private response")):
                    global_messages = await client.get("/api/runs/" + run_id + "/messages?limit=1", headers=headers)
                    assert global_messages.status_code == 200, global_messages.text
                    assert global_messages.json()["data"][0]["content"]["content"] == expected
                    global_feedback = await client.get("/api/runs/" + run_id + "/feedback", headers=headers)
                    assert global_feedback.status_code == 200, global_feedback.text
                    assert len(global_feedback.json()) == 1 and global_feedback.json()[0]["run_id"] == run_id
                for suffix in ("/messages", "/feedback"):
                    assert (await client.get("/api/runs/" + team_run + suffix)).status_code == 404
                    assert (await client.get("/api/runs/" + personal_run + suffix, headers=team_headers)).status_code == 404
                    as_user("bob")
                    assert (await client.get("/api/runs/" + team_run + suffix, headers=team_headers)).status_code == 404
                    as_user("alice")

                async def rotate_private_parent():
                    async with sf() as session:
                        await session.execute(sa.text("UPDATE threads_meta SET incarnation=:nonce WHERE thread_id=:id"), {"nonce": uuid4().hex, "id": delete_ids["team"]})
                        await session.commit()

                # Change the actual parent after SQL materialization, before response publication.
                for method, repository, suffix in (("list_messages_by_run", app.state.run_event_store, "/messages"), ("list_by_run", app.state.feedback_repo, "/feedback")):
                    original_read = getattr(repository, method)

                    async def read_then_replace(*args, _read=original_read, **kwargs):
                        result = await _read(*args, **kwargs)
                        await rotate_private_parent()
                        return result

                    with monkeypatch.context() as patch:
                        patch.setattr(repository, method, read_then_replace)
                        replaced = await client.get("/api/runs/" + team_run + suffix, headers=team_headers)
                        assert replaced.status_code == 404, replaced.text
                    assert (await client.get("/api/runs/" + team_run + suffix, headers=team_headers)).status_code == 200
                foreign_events = await client.get(team_run_base + "/runs/" + personal_run + "/events", headers=team_headers)
                assert foreign_events.status_code == 404, foreign_events.text
                foreign_messages = await client.get(team_run_base + "/runs/" + personal_run + "/messages", headers=team_headers)
                assert foreign_messages.status_code == 404, foreign_messages.text
                as_user("bob")
                assert (await client.get(team_run_base + "/messages", headers=team_headers)).status_code == 404
                as_user("alice")
                owner_replacement["thread_id"] = delete_ids["team"]
                assert (await client.get(team_run_base + "/messages", headers=team_headers)).status_code == 404

                class ScopeChangingBridge(MemoryStreamBridge):
                    def __init__(self, mode):
                        super().__init__()
                        self.mode = mode
                        self.active_observers = 0

                    async def subscribe(self, run_id, **kwargs):
                        self.active_observers += 1
                        source = super().subscribe(run_id, **kwargs)
                        try:
                            async for entry in source:
                                yield entry
                                if getattr(entry, "event", None) == "values" and self.mode is not None:
                                    mode, self.mode = self.mode, None
                                    async with sf() as session:
                                        if mode == "policy":
                                            await session.execute(sa.text("UPDATE workspaces SET policy_version=policy_version+1 WHERE id=:id"), {"id": team})
                                        elif mode == "incarnation":
                                            await session.execute(sa.text("UPDATE threads_meta SET incarnation=:nonce WHERE thread_id=:id"), {"nonce": uuid4().hex, "id": delete_ids["team"]})
                                        elif mode == "token_version":
                                            await session.execute(sa.text("UPDATE users SET token_version=token_version+1 WHERE id=:id"), {"id": identities["alice"]})
                                        elif mode == "route_policy":
                                            configuration.authorization = configuration.authorization.model_copy(deep=True)
                                            configuration.authorization.provider.config["roles"]["user"]["routes"]["deny"] = ["runs:read"]
                                        await session.commit()
                        finally:
                            await close_agent_stream(source)
                            self.active_observers -= 1

                for stream_case in (None, "policy", "incarnation", "token_version", "route_policy"):
                    previous_authorization = configuration.authorization
                    bridge = ScopeChangingBridge(stream_case)
                    app.state.stream_bridge = bridge
                    async with sf() as session:
                        await session.execute(sa.update(RunRow).where(RunRow.run_id == team_run).values(status="running"))
                        await session.commit()
                        stored = await session.get(RunRow, team_run)
                        observer_record = app.state.run_manager._record_from_store(app.state.run_store._row_to_dict(stored))
                    observer_record.store_only = False
                    observer_record.on_disconnect = DisconnectMode.cancel
                    async with app.state.run_manager._lock:
                        app.state.run_manager._runs[team_run] = observer_record
                        app.state.run_manager._index_run_locked(observer_record)
                    try:
                        await bridge.publish(team_run, "values", {"title": "first authorized frame"})
                        await bridge.publish(team_run, "values", {"title": "second private frame"})
                        await bridge.publish_end(team_run)
                        first_event_id = bridge._streams[team_run].events[0].id
                        streamed = await client.get(team_run_base + "/runs/" + team_run + "/join", headers=team_headers)
                        assert streamed.status_code == 200, streamed.text
                        assert "first authorized frame" in streamed.text
                        if stream_case is None:
                            assert "second private frame" in streamed.text and "event: end" in streamed.text
                            resumed = await client.get(team_run_base + "/runs/" + team_run + "/stream", headers={**team_headers, "Last-Event-ID": first_event_id})
                            assert resumed.status_code == 200 and "first authorized frame" not in resumed.text and "second private frame" in resumed.text, resumed.text
                            delayed_stream = await client.get("/api/workspace-delayed-observer/" + delete_ids["team"] + "/" + team_run, headers=team_headers)
                            assert delayed_stream.status_code == 404 and "first authorized frame" not in delayed_stream.text
                            assert (await client.get(team_run_base + "/runs/" + team_run + "/join")).status_code == 404
                            as_user("bob")
                            assert (await client.get(team_run_base + "/runs/" + team_run + "/stream", headers=team_headers)).status_code == 404
                            as_user("alice")
                        else:
                            assert "second private frame" not in streamed.text, "observer forwarded data after captured authority changed"
                            assert "event: end" not in streamed.text, "observer closure must not claim the Run completed"
                        assert bridge.active_observers == 0, "response abandoned its native bridge subscription"
                        assert observer_record.status == RunStatus.running and not observer_record.abort_event.is_set(), "closing an observer cancelled background work"
                        async with sf() as session:
                            assert (await session.get(RunRow, team_run)).status == "running"
                        if stream_case == "token_version":
                            assert (await client.get(team_run_base + "/runs/" + team_run + "/join", headers=team_headers)).status_code == 401
                            session_versions["alice"] = 1
                            as_user("alice")
                    finally:
                        async with sf() as session:
                            await session.execute(sa.update(RunRow).where(RunRow.run_id == team_run).values(status="success"))
                            await session.commit()
                        configuration.authorization = previous_authorization
                        observer_record.status = RunStatus.success
                        await app.state.run_manager.cleanup(team_run, delay=0)
                app.state.run_event_store = memory_events
                delete_id = delete_ids["team"]
                assert (await client.delete("/api/threads/" + delete_id)).status_code == 404
                as_user("bob")
                assert (await client.delete("/api/threads/" + delete_id, headers=team_headers)).status_code == 404
                as_user("alice")
                deletion_admission["workspace_id"] = team
                refused_delete = await client.delete("/api/threads/" + delete_id, headers=team_headers)
                assert refused_delete.status_code == 404, refused_delete.text
                async with sf() as session:
                    assert (await session.get(ThreadMetaRow, delete_id)).status == "idle"
                delete_path = tmp_path / "files" / "workspaces" / team / "users" / identities["alice"] / "threads" / delete_id
                assert (delete_path / "user-data" / "uploads" / "delete.txt").read_bytes() == b"team private bytes"
                deletion_probe.update(thread_id=delete_id, client=client, headers=team_headers)
                deleted = await client.delete("/api/threads/" + delete_id, headers=team_headers)
                assert deleted.status_code == 200 and deleted.json()["success"] is True, deleted.text
                assert not delete_path.exists()
                assert await app.state.checkpointer.aget_tuple({"configurable": {"thread_id": delete_id, "checkpoint_ns": ""}}) is None
                async with sf() as session:
                    assert await session.get(ThreadMetaRow, delete_id) is None
                    assert await session.get(ThreadMetaRow, delete_ids["personal"]) is not None
                    for table in (RunRow, RunEventRow, FeedbackRow, ThreadReadMarkerRow, ScheduledTaskEventRow):
                        assert await session.scalar(sa.select(sa.func.count()).select_from(table).where(table.thread_id == delete_id)) == 0
                        assert await session.scalar(sa.select(sa.func.count()).select_from(table).where(table.thread_id == delete_ids["personal"])) == 1
                assert await app.state.run_event_store.list_events(delete_id, delete_id + "-run", limit=100, user_id=identities["alice"]) == []
                assert len(await app.state.run_event_store.list_events(delete_ids["personal"], delete_ids["personal"] + "-run", limit=100, user_id=identities["alice"])) == 1
                uncertain_id = str(uuid4())
                assert (await client.post("/api/threads", headers=team_headers, json={"thread_id": uncertain_id})).status_code == 200
                deletion_probe.update(thread_id=uncertain_id, fail=True)
                uncertain = await client.delete("/api/threads/" + uncertain_id, headers=team_headers)
                assert uncertain.status_code == 503, "uncertain deletion reported success: " + uncertain.text
                async with sf() as session:
                    assert (await session.get(ThreadMetaRow, uncertain_id)).status == "deleting"
                assert (await client.get("/api/threads/" + uncertain_id + "/state", headers=team_headers)).status_code == 404
                assert (await client.post("/api/threads", headers=team_headers, json={"thread_id": uncertain_id})).status_code == 404
                assert (await client.delete("/api/threads/" + uncertain_id, headers=team_headers)).status_code == 409
                assert deletion_attempts[uncertain_id] == 1, "unknown physical cleanup was replayed"
                # A real slow multipart request outlives delete + same-ID recreate.
                # Its rejection/cleanup must preserve files in the new generation.
                reused_id = str(uuid4())
                assert (await client.post("/api/threads", headers=team_headers, json={"thread_id": reused_id})).status_code == 200
                original_stream = uploads._stream_upload_file
                replacement_during_stream = {"armed": True}

                async def recreate_after_staging(file):
                    async for chunk in original_stream(file):
                        yield chunk
                    if file.filename == "late.txt" and replacement_during_stream.pop("armed", False):
                        removed = await client.delete("/api/threads/" + reused_id, headers=team_headers)
                        assert removed.status_code == 200, removed.text
                        recreated = await client.post("/api/threads", headers=team_headers, json={"thread_id": reused_id})
                        assert recreated.status_code == 200, recreated.text
                        fresh = await client.post("/api/threads/" + reused_id + "/uploads", headers=team_headers, files={"files": ("first.txt", b"new generation bytes", "text/plain")})
                        assert fresh.status_code == 200, fresh.text

                monkeypatch.setattr(uploads, "_stream_upload_file", recreate_after_staging)
                stale_upload = await client.post("/api/threads/" + reused_id + "/uploads", headers=team_headers, files=[("files", ("first.txt", b"old first file", "text/plain")), ("files", ("late.txt", b"old delayed file", "text/plain"))])
                monkeypatch.setattr(uploads, "_stream_upload_file", original_stream)
                reused_root = tmp_path / "files" / "workspaces" / team / "users" / identities["alice"] / "threads" / reused_id / "user-data" / "uploads"
                assert (reused_root / "first.txt").read_bytes() == b"new generation bytes", "old request cleanup deleted the recreated conversation's file"
                assert stale_upload.status_code == 404, stale_upload.text
                assert not (reused_root / "late.txt").exists(), "old request published into the recreated conversation"
                owner_replacement["thread_id"] = reused_id
                stale_unlink = await client.delete("/api/threads/" + reused_id + "/uploads/first.txt", headers=team_headers)
                assert stale_unlink.status_code == 404, stale_unlink.text
                assert (reused_root / "first.txt").read_bytes() == b"new generation bytes"
                branch_source = str(uuid4())
                created_source = await client.post("/api/threads", headers=team_headers, json={"thread_id": branch_source, "project_id": shared_project})
                assert created_source.status_code == 200, created_source.text
                branch_upload = await client.post("/api/threads/" + branch_source + "/uploads", headers=team_headers, files={"files": ("branch.txt", b"source branch private bytes", "text/plain")})
                assert branch_upload.status_code == 200, branch_upload.text
                source_config = {"configurable": {"thread_id": branch_source, "checkpoint_ns": ""}}
                source_root = await app.state.checkpointer.aget_tuple(source_config)
                source_checkpoint = empty_checkpoint()
                source_checkpoint["channel_values"] = {"messages": [HumanMessage(id="branch-human", content="Private branch question"), AIMessage(id="branch-answer", content="Private branch answer")], "title": "Private branch source"}
                source_checkpoint["channel_versions"] = {channel: app.state.checkpointer.get_next_version(None, None) for channel in ("messages", "title")}
                await app.state.checkpointer.aput(source_root.config, source_checkpoint, {"step": 0, "source": "update", "writes": {}, "parents": {}}, source_checkpoint["channel_versions"])
                branch_body = {"message_id": "branch-answer"}
                branched = await client.post("/api/threads/" + branch_source + "/branches", headers=team_headers, json=branch_body)
                assert branched.status_code == 200, branched.text
                branch_id = branched.json()["thread_id"]
                assert branched.json()["workspace_clone_mode"] == "current_thread_best_effort"
                assert branched.json()["history_seed_mode"] == "seeded"
                async with sf() as session:
                    child = await session.get(ThreadMetaRow, branch_id)
                    assert child.workspace_id == team and child.user_id == identities["alice"] and child.project_id == shared_project
                branch_state = await client.get("/api/threads/" + branch_id + "/state", headers=team_headers)
                assert branch_state.status_code == 200, branch_state.text
                assert [m["content"] for m in branch_state.json()["values"]["messages"]] == ["Private branch question", "Private branch answer"]
                child_file = tmp_path / "files" / "workspaces" / team / "users" / identities["alice"] / "threads" / branch_id / "user-data" / "uploads" / "branch.txt"
                source_file = child_file.parents[3] / branch_source / "user-data" / "uploads" / "branch.txt"
                assert child_file.read_bytes() == source_file.read_bytes() == b"source branch private bytes"
                assert (await client.get("/api/threads/" + branch_id + "/state")).status_code == 404
                assert (await client.post("/api/threads/" + branch_source + "/branches", json=branch_body)).status_code == 404
                as_user("bob")
                assert (await client.post("/api/threads/" + branch_source + "/branches", headers=team_headers, json=branch_body)).status_code == 404
                assert (await client.get("/api/threads/" + branch_id + "/state", headers=team_headers)).status_code == 404
                as_user("alice")
                async with sf() as session:
                    before_branch_ids = set((await session.execute(sa.select(ThreadMetaRow.thread_id))).scalars())
                checkpoint_replacement["thread_id"] = branch_source
                replaced_branch = await client.post("/api/threads/" + branch_source + "/branches", headers=team_headers, json=branch_body)
                assert replaced_branch.status_code == 404, replaced_branch.text
                async with sf() as session:
                    after_branch_ids = set((await session.execute(sa.select(ThreadMetaRow.thread_id))).scalars())
                    assert after_branch_ids == before_branch_ids, "replaced source still published branch metadata"
                as_user("bob")
                assert (await client.delete("/api/projects/" + shared_project, headers=team_headers)).status_code == 204
                async with sf() as session:
                    assert (await session.get(ProjectDocumentRow, shared_document)).trashed_at is not None
                    assert (await session.get(ProjectDocumentRow, admin_document)).trashed_at is not None
                assert (await client.delete(members_url + "/" + identities["alice"], headers=team_headers)).status_code == 403
                as_user("alice")
                transfer_url = "/api/workspaces/" + team + "/ownership-transfer"
                transfer = {"new_owner_user_id": identities["bob"], "reauth_password": "wrong-password"}
                assert (await client.post(transfer_url, json=transfer, headers=team_headers)).status_code == 401
                transfer["reauth_password"] = "synthetic-native-transfer-password"
                transferred = await client.post(transfer_url, json=transfer, headers=team_headers)
                assert transferred.status_code == 200, transferred.text
                assert transfer["reauth_password"] not in transferred.text
                as_user("bob")
                assert (await client.post("/api/workspaces/" + team + "/leave", headers=team_headers)).status_code == 409
                members = (await client.get(members_url, headers=team_headers)).json()
                assert [member["user_id"] for member in members if member["role"] == "owner"] == [identities["bob"]]
                assert (await client.delete(members_url + "/" + identities["alice"], headers=team_headers)).status_code == 200
                as_user("alice")
                assert (await client.get("/api/workspaces/current", headers=team_headers)).status_code == 404
                async with sf() as session:
                    session.add(ProjectRow(id="proof", user_id=identities["alice"], workspace_id=personal, name="private source"))
                    await session.commit()
                assert (await client.get("/api/workspace-proof/proof", headers={"X-Deerflow-Workspace": personal})).status_code == 200
                assert (await client.get("/api/workspace-proof/proof", headers={"X-Deerflow-Workspace": team})).status_code == 404
                as_user("bob")
                assert (await client.get("/api/workspaces/current", headers=team_headers)).status_code == 200
                async with sf() as session:
                    await session.execute(sa.update(UserRow).where(UserRow.id == identities["alice"]).values(system_role="limited"))
                    await session.commit()
                as_user("alice")
                assert (await client.post("/api/workspace-proof/proof", headers={"X-Deerflow-Workspace": personal})).status_code == 403
                old_context = await service.resolve_context(identities["alice"], personal)
                async with sf() as session:
                    await session.execute(sa.text("UPDATE workspaces SET policy_version=policy_version+1 WHERE id=:id"), {"id": personal})
                    await session.commit()
                with pytest.raises(HTTPException) as refused:
                    await service.revalidate(old_context)
                assert refused.value.status_code == 404
        finally:
            await checkpoint_connection.close()
            await engine.dispose()

    asyncio.run(scenario())
