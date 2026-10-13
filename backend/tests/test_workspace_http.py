"""Real JWT/RBAC/CSRF and native SQL for managed workspace onboarding."""

import asyncio
import importlib
import importlib.util
import zipfile
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
import sqlalchemy as sa
from fastapi import FastAPI, HTTPException, Request
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_workspace_executor_migration import executor_engine, native_engine  # noqa: F401


def test_managed_workspace_http_uses_native_auth_and_live_scope(native_engine, monkeypatch, tmp_path):  # noqa: F811
    from langgraph.checkpoint.memory import InMemorySaver

    import deerflow.config as config_facade
    from app.gateway import deps
    from app.gateway.auth import config as auth_config
    from app.gateway.auth import create_access_token
    from app.gateway.auth.local_provider import LocalAuthProvider
    from app.gateway.auth.password import hash_password
    from app.gateway.auth.repositories.sqlite import SQLiteUserRepository
    from app.gateway.auth_middleware import AuthMiddleware
    from app.gateway.csrf_middleware import CSRFMiddleware
    from app.gateway.routers import artifacts, project_documents, projects, threads, uploads
    from deerflow.config import app_config
    from deerflow.config import paths as paths_module
    from deerflow.config.app_config import AppConfig
    from deerflow.config.paths import Paths
    from deerflow.persistence.projects import ProjectDocumentRepository, ProjectRepository
    from deerflow.persistence.projects.model import ProjectDocumentRow, ProjectRow
    from deerflow.persistence.thread_meta import ThreadMetaRepository
    from deerflow.persistence.thread_meta.model import ThreadMetaRow
    from deerflow.persistence.user.model import UserRow
    from deerflow.persistence.workspaces.sql import WorkspaceRepository
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
    monkeypatch.setattr(paths_module, "_paths", Paths(tmp_path / "files"))
    monkeypatch.setattr(uploads, "get_sandbox_provider", lambda: LocalSandboxProvider())
    monkeypatch.setattr(auth_config, "_auth_config", auth_config.AuthConfig(jwt_secret="synthetic-isolated-workspace-http-key-64-characters-for-test-only!!"))
    monkeypatch.delenv("DEER_FLOW_AUTH_DISABLED", raising=False)
    driver = "sqlite+aiosqlite" if native_engine.dialect.name == "sqlite" else "postgresql+asyncpg"

    async def scenario():
        engine = create_async_engine(native_engine.url.set(drivername=driver))
        try:
            sf = async_sessionmaker(engine, expire_on_commit=False)
            user_repo = SQLiteUserRepository(sf)
            monkeypatch.setattr(deps, "_cached_repo", user_repo)
            monkeypatch.setattr(deps, "_cached_local_provider", LocalAuthProvider(repository=user_repo))
            service = service_module.WorkspaceService(WorkspaceRepository(sf))
            app = FastAPI()
            app.state.workspace_service = service
            delete_revocation = {}

            class RevokingThreadRepository(ThreadMetaRepository):
                async def check_access(self, thread_id, user_id, *, require_existing=False):
                    allowed = await super().check_access(thread_id, user_id, require_existing=require_existing)
                    workspace_id = delete_revocation.pop("workspace_id", None)
                    if allowed and workspace_id is not None:
                        # Actual persisted withdrawal between owner admission and filesystem mutation.
                        async with sf() as session:
                            await session.execute(sa.text("UPDATE workspaces SET policy_version=policy_version+1 WHERE id=:id"), {"id": workspace_id})
                            await session.commit()
                    return allowed

            app.state.thread_store = RevokingThreadRepository(sf, workspace_required=True)
            app.state.checkpointer = InMemorySaver()
            app.state.project_repo = ProjectRepository(sf)
            app.state.project_document_repo = ProjectDocumentRepository(sf)
            app.include_router(routes.router)
            app.include_router(admin_routes.router)
            app.include_router(artifacts.router)
            app.include_router(uploads.router)
            app.include_router(threads.router)
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

            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost", headers={"Origin": "http://localhost", "X-CSRF-Token": "synthetic-csrf"}) as client:
                assert (await client.get("/api/workspaces")).status_code == 401

                def as_user(name):
                    client.cookies.clear()
                    client.cookies.set("access_token", create_access_token(identities[name]))
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
            await engine.dispose()

    asyncio.run(scenario())
