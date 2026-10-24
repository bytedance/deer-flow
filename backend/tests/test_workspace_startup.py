"""Workspace startup refuses unsafe modes before runtime recovery starts."""

import asyncio
import importlib
import importlib.util

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_workspace_executor_migration import executor_engine, native_engine  # noqa: F401


def test_workspace_startup_preserves_legacy_and_refuses_authorization_bypass(native_engine, monkeypatch):  # noqa: F811
    from deerflow.config.app_config import AppConfig
    from deerflow.persistence.workspaces.model import WorkspaceRow

    name = "app.gateway.workspaces.startup"
    assert importlib.util.find_spec(name) is not None, "Gateway has no workspace startup authorization gate"
    startup = importlib.import_module(name)
    assert "workspaces" in AppConfig.model_fields, "workspace activation must be typed operator configuration"
    legacy = AppConfig(sandbox={"use": "deerflow.sandbox.local:LocalSandboxProvider"})
    enabled = AppConfig(sandbox={"use": "deerflow.sandbox.local:LocalSandboxProvider"}, workspaces={"enabled": True})
    with pytest.raises(ValueError):
        AppConfig(sandbox={"use": "deerflow.sandbox.local:LocalSandboxProvider"}, workspaces={"enabled": "false"})
    monkeypatch.delenv("DEER_FLOW_AUTH_DISABLED", raising=False)
    driver = "sqlite+aiosqlite" if native_engine.dialect.name == "sqlite" else "postgresql+asyncpg"

    async def scenario():
        engine = create_async_engine(native_engine.url.set(drivername=driver))
        try:
            sf = async_sessionmaker(engine, expire_on_commit=False)
            assert await startup.validate_workspace_bootstrap(legacy, None) is None
            assert await startup.validate_workspace_bootstrap(legacy, sf) is None
            with pytest.raises(RuntimeError, match="persistent SQL"):
                await startup.validate_workspace_bootstrap(enabled, None)
            monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "1")
            with pytest.raises(RuntimeError, match="authenticated"):
                await startup.validate_workspace_bootstrap(enabled, sf)
            monkeypatch.delenv("DEER_FLOW_AUTH_DISABLED")
            # Both gates stay closed. The current fixture head can be newer
            # than the deliberately unreleased startup schema fence; in that
            # case schema rejection precedes the compiled integration refusal.
            # Do not patch either production guard to claim a tenant startup.
            assert startup._WORKSPACE_RUNTIME_INTEGRATED is False
            async with sf() as session:
                versions = (await session.scalars(sa.text("SELECT version_num FROM alembic_version"))).all()
            refusal = "entrypoint integration" if versions == [startup._NATIVE_WORKSPACE_SCHEMA] else "schema is incompatible"
            with pytest.raises(RuntimeError, match=refusal):
                await startup.validate_workspace_bootstrap(enabled, sf)
            async with sf() as session:
                session.add(WorkspaceRow(id="bb7cc038-790e-4dd7-bac5-ac8d24d0d96e", kind="team", name="Closed team", status="closed", policy_version=3))
                await session.commit()
            with pytest.raises(RuntimeError, match="team data"):
                await startup.validate_workspace_bootstrap(legacy, sf)
            if native_engine.dialect.name == "postgresql":
                from fastapi import FastAPI

                from app.gateway.deps import langgraph_runtime

                gateway = FastAPI()
                runtime_config = AppConfig(
                    sandbox={"use": "deerflow.sandbox.local:LocalSandboxProvider"},
                    database={"backend": "postgres", "postgres_url": native_engine.url.set(drivername=driver).render_as_string(hide_password=False)},
                )
                # Exercise the production bootstrap, not just its helper.
                # Rejection must happen before recovery owns any run manager.
                with pytest.raises(RuntimeError, match="team data"):
                    async with langgraph_runtime(gateway, runtime_config):
                        pytest.fail("legacy Gateway started with team data")
                assert not hasattr(gateway.state, "run_manager")
            async with sf() as session:
                await session.execute(sa.delete(WorkspaceRow))
                await session.execute(sa.text("UPDATE alembic_version SET version_num='0035_pre_tenant'"))
                await session.commit()
            with pytest.raises(RuntimeError, match="schema"):
                await startup.validate_workspace_bootstrap(enabled, sf)
        finally:
            await engine.dispose()

    asyncio.run(scenario())
    from app.gateway.app import create_app

    gateway = create_app()
    paths = {route.path for route in gateway.routes}
    assert "/api/workspaces" in paths and "/api/admin/workspaces" in paths
    assert gateway.state.workspace_service is None
