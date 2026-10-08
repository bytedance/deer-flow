"""Privilege revocation uses current accounts even with stale tools and caches."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from langchain_core.tools import StructuredTool, ToolException
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.gateway import personal_mcp_access as gateway_access
from app.gateway.auth.local_provider import LocalAuthProvider
from app.gateway.auth.models import User
from app.gateway.auth.repositories.sqlite import SQLiteUserRepository
from deerflow.config.extensions_config import ExtensionsConfig, McpServerConfig, atomic_write_extensions_config
from deerflow.config.paths import Paths
from deerflow.mcp import personal_access
from deerflow.mcp.task_tool_caller import McpTaskToolCaller
from deerflow.mcp.user_config import load_user_mcp_config, user_mcp_config_path
from deerflow.mcp.user_tools import _guard, _load
from deerflow.persistence.user.model import UserRow
from deerflow.runtime.user_context import reset_current_user, set_current_user


@pytest_asyncio.fixture
async def accounts(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/users.db")
    async with engine.begin() as connection:
        await connection.run_sync(UserRow.__table__.create)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    repository = SQLiteUserRepository(sessions)
    user = await repository.create_user(User(email="admin@example.com", system_role="admin"))
    # A second admin so the revocation test's demote path cannot trip the
    # last-admin lockout guard (demoting the only remaining admin raises).
    await repository.create_user(User(email="second-admin@example.com", system_role="admin"))
    monkeypatch.setattr(gateway_access, "get_local_provider", lambda: LocalAuthProvider(repository))
    monkeypatch.delenv("DEER_FLOW_AUTH_DISABLED", raising=False)
    monkeypatch.setattr("deerflow.mcp.user_config.get_paths", lambda: Paths(base_dir=tmp_path))
    monkeypatch.setattr(personal_access, "_admin_checker", None)
    try:
        yield repository, user, sessions
    finally:
        await engine.dispose()


def privileged_definition(kind):
    if kind == "stdio":
        return {"type": "stdio", "command": "npx", "args": ["example-package"], "personal_public_network": False}
    definition = {"type": "sse" if kind == "sse" else "http", "url": "http://127.0.0.1/mcp", "personal_public_network": False}
    if kind == "legacy":
        del definition["personal_public_network"]
    if kind == "oauth":
        definition["oauth"] = {"token_url": "http://127.0.0.1/token", "client_id": "test-client"}
    return definition


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["http", "sse", "stdio", "legacy", "oauth"])
@pytest.mark.parametrize("revocation", ["demote", "delete", "lookup_failure"])
async def test_revocation_blocks_discovery_existing_tools_and_cached_durable_calls(accounts, monkeypatch, kind, revocation):
    repository, user, sessions = accounts
    owner = str(user.id)
    path = user_mcp_config_path(owner)
    atomic_write_extensions_config(path, {"mcpServers": {"privileged": privileged_definition(kind), "public": {"type": "http", "url": "https://example.com/mcp", "personal_public_network": True}}})
    before = path.read_bytes()
    config = load_user_mcp_config(owner)
    privileged = next(name for name, server in config.mcp_servers.items() if personal_access.requires_admin(server))
    public = next(name for name in config.mcp_servers if name != privileged)
    observed = []

    async def execute():
        observed.append("executed")
        return "ok"

    class Client:
        def __init__(self, connections, **kwargs):
            observed.extend(connections)

        async def get_tools(self, server_name):
            return [StructuredTool.from_function(coroutine=execute, name=server_name + "_probe", description="Probe")]

    monkeypatch.setattr("langchain_mcp_adapters.client.MultiServerMCPClient", Client)
    oauth = AsyncMock(return_value={})
    monkeypatch.setattr("deerflow.mcp.tools.get_initial_oauth_headers", oauth)
    invoke = AsyncMock(return_value="ok")
    monkeypatch.setattr(McpTaskToolCaller, "_call_configured_tool", invoke)
    caller = McpTaskToolCaller(ExtensionsConfig())
    guarded = _guard(StructuredTool.from_function(coroutine=execute, name="probe", description="Probe"), owner, privileged)
    public_tool = _guard(StructuredTool.from_function(coroutine=execute, name="public", description="Public"), owner, public)
    token = set_current_user(SimpleNamespace(id=owner, system_role="admin"))
    try:
        async with gateway_access.personal_mcp_authority():
            assert len(await _load(owner, config)) == 2
            assert await guarded.ainvoke({}) == "ok"
            call = dict(server_name=privileged, tool_name="submit", arguments={}, user_id=owner, thread_id="thread", connection_scope="personal")
            assert await caller.call_tool(**call) == "ok"
            cached_caller = caller._personal_callers[owner][1]
            observed.clear()
            invoke.reset_mock()
            oauth.reset_mock()

            if revocation == "demote":
                # update_user is field-scoped (roles never written there);
                # update_system_role is the sole role writer.
                await repository.update_system_role(str(user.id), "user")
            elif revocation == "delete":
                async with sessions() as session:
                    await session.execute(delete(UserRow).where(UserRow.id == owner))
                    await session.commit()
            else:
                monkeypatch.setattr(repository, "get_user_by_id", AsyncMock(side_effect=RuntimeError("database unavailable")))

            tools = await _load(owner, config)
            assert len(tools) == 1
            assert observed == [public]
            assert set(oauth.call_args.args[0].mcp_servers) == {public}
            with pytest.raises(ToolException, match="Current administrator"):
                await guarded.ainvoke({})
            for operation in ("submit", "status", "cancel"):
                with pytest.raises(ToolException, match="Current administrator"):
                    await caller.call_tool(**(call | {"tool_name": operation, "request_scoped_headers": operation == "submit"}))
            assert caller._personal_callers[owner][1] is cached_caller
            invoke.assert_not_awaited()
            assert path.read_bytes() == before
            assert await public_tool.ainvoke({}) == "ok"
            # Deployment calls retain their existing policy and never query
            # personal ownership or the owner's current role.
            assert await caller.call_tool(**(call | {"connection_scope": "deployment"})) == "ok"
    finally:
        reset_current_user(token)


@pytest.mark.asyncio
async def test_authority_lookup_stays_on_gateway_loop_during_sync_discovery(accounts, monkeypatch):
    repository, user, _ = accounts
    owner = str(user.id)
    loop = asyncio.get_running_loop()
    original = repository.get_user_by_id
    reads = []

    async def get_user(user_id):
        reads.append(asyncio.get_running_loop())
        return await original(user_id)

    monkeypatch.setattr(repository, "get_user_by_id", get_user)
    server = McpServerConfig.model_validate(privileged_definition("http"))
    async with gateway_access.personal_mcp_authority():
        await asyncio.wait_for(asyncio.to_thread(lambda: asyncio.run(personal_access.require_personal_mcp_access(owner, server))), timeout=5)
    assert reads == [loop]
    assert personal_access._admin_checker is None
    with pytest.raises(ToolException, match="Current administrator"):
        await personal_access.require_personal_mcp_access(owner, server)


@pytest.mark.asyncio
@pytest.mark.parametrize("production", [False, True])
async def test_auth_disabled_authority_only_grants_the_default_local_user(accounts, monkeypatch, production):
    monkeypatch.setenv("DEER_FLOW_AUTH_DISABLED", "1")
    monkeypatch.setenv("DEER_FLOW_ENV", "production" if production else "development")
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    async with gateway_access.personal_mcp_authority():
        assert await personal_access._is_current_admin("default") is (not production)
        assert await personal_access._is_current_admin("missing-user") is False


@pytest.mark.asyncio
async def test_authority_registration_is_restored_after_startup_failure(monkeypatch):
    previous = AsyncMock(return_value=False)
    monkeypatch.setattr(personal_access, "_admin_checker", previous)
    with pytest.raises(RuntimeError, match="startup failed"):
        async with gateway_access.personal_mcp_authority():
            assert personal_access._admin_checker is not previous
            raise RuntimeError("startup failed")
    assert personal_access._admin_checker is previous
