"""Real JWT/RBAC/CSRF and native SQL for managed workspace onboarding."""

import asyncio
import importlib
import importlib.util
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
import sqlalchemy as sa
from fastapi import FastAPI, HTTPException, Request
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_workspace_executor_migration import executor_engine, native_engine  # noqa: F401


def test_managed_workspace_http_uses_native_auth_and_live_scope(native_engine, monkeypatch):  # noqa: F811
    from app.gateway import deps
    from app.gateway.auth import config as auth_config
    from app.gateway.auth import create_access_token
    from app.gateway.auth.local_provider import LocalAuthProvider
    from app.gateway.auth.repositories.sqlite import SQLiteUserRepository
    from app.gateway.auth_middleware import AuthMiddleware
    from app.gateway.csrf_middleware import CSRFMiddleware
    from deerflow.config import app_config
    from deerflow.config.app_config import AppConfig
    from deerflow.persistence.projects.model import ProjectRow
    from deerflow.persistence.user.model import UserRow
    from deerflow.persistence.workspaces.sql import WorkspaceRepository

    names = ("app.gateway.workspaces.service", "app.gateway.workspaces.dependencies", "app.gateway.routers.workspaces", "app.gateway.routers.admin_workspaces")
    for name in names:
        assert importlib.util.find_spec(name.rsplit(".", 1)[0]) is not None and importlib.util.find_spec(name) is not None, "managed workspace HTTP surface is not implemented"
    service_module, dependencies, routes, admin_routes = [importlib.import_module(name) for name in names]
    identities = {name: str(uuid4()) for name in ("admin", "alice", "bob")}
    with native_engine.begin() as conn:
        for name, user_id in identities.items():
            conn.execute(sa.insert(UserRow).values(id=user_id, email=name + "@example.com", email_verified_at=datetime.now(UTC), system_role="admin" if name == "admin" else "user"))
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
    monkeypatch.setattr(app_config, "get_app_config", lambda: configuration)
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
            app.include_router(routes.router)
            app.include_router(admin_routes.router)
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
                async with sf() as session:
                    session.add(ProjectRow(id="proof", user_id=identities["alice"], workspace_id=personal, name="private source"))
                    await session.commit()
                assert (await client.get("/api/workspace-proof/proof", headers={"X-Deerflow-Workspace": personal})).status_code == 200
                assert (await client.get("/api/workspace-proof/proof", headers={"X-Deerflow-Workspace": team})).status_code == 404
                as_user("bob")
                assert (await client.get("/api/workspaces/current", headers={"X-Deerflow-Workspace": team})).status_code == 404
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
