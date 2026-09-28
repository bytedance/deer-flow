"""Ownership-domain invariants for the shared MCP session pool.

Deployment configuration owns only ``deployment`` resources. Personal MCP
servers share the same pool under their own domain -- upstream derives runtime
names (``personal_<hash>``) that a deployment server may legally also use -- so
both identity and retirement must be domain-scoped. Only a true process-wide
reset (shutdown / the explicit admin reset) may retire both domains.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deerflow.mcp.session_pool import MCPPoolResource, MCPSessionPool
from deerflow.mcp.user_config import personal_server_name


def _connection(command: str = "npx") -> dict:
    return {"transport": "stdio", "command": command, "args": []}


def _session_cm() -> tuple[MagicMock, AsyncMock]:
    session = AsyncMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm, session


def _colliding_name() -> str:
    """A personal runtime name that a deployment server may legally also use."""
    return personal_server_name("alice", "notes", {"type": "stdio", "command": "npx", "args": []})


def _registered_sessions(pool: MCPSessionPool) -> list[object]:
    return [entry[0] for entry in pool._entries.values()]


@pytest.mark.asyncio
async def test_same_runtime_name_coexists_across_domains():
    """Deployment and personal may each own the same runtime name."""
    pool = MCPSessionPool()
    name = _colliding_name()

    deployment = pool.ensure_binding(name, "deployment-fp")
    personal = pool.ensure_binding(name, "personal-fp", domain="personal")

    assert deployment.resource == MCPPoolResource(domain="deployment", server_name=name)
    assert personal.resource == MCPPoolResource(domain="personal", server_name=name)
    assert deployment.fingerprint == "deployment-fp"
    assert personal.fingerprint == "personal-fp"

    with patch("langchain_mcp_adapters.sessions.create_session", side_effect=lambda *a, **k: _session_cm()[0]):
        deployment_session = await pool.get_session(name, "thread-1", _connection(), binding=deployment)
        personal_session = await pool.get_session(name, "thread-1", _connection(), binding=personal)

    assert deployment_session is not personal_session
    assert {key[0].domain for key in pool._entries} == {"deployment", "personal"}


@pytest.mark.asyncio
async def test_deployment_reconcile_leaves_personal_binding_and_session_alone():
    """No deployment reconcile path may touch a personal resource."""
    pool = MCPSessionPool()
    name = _colliding_name()
    personal = pool.ensure_binding(name, "personal-fp", domain="personal")
    cm, session = _session_cm()
    with patch("langchain_mcp_adapters.sessions.create_session", return_value=cm):
        await pool.get_session(name, "thread-1", _connection(), binding=personal)

    # An unrelated deployment edit, and a deployment removal, both stay inside
    # the deployment domain.
    pool.reconcile_bindings({"other": "fp"}, [], domain="deployment")
    pool.reconcile_bindings({}, ["other"], domain="deployment")

    assert pool.active_binding(name, domain="personal") == personal
    assert session in _registered_sessions(pool)


@pytest.mark.asyncio
async def test_deployment_domain_retirement_spares_personal_sessions():
    """A deployment whole-domain reset retires only deployment resources."""
    pool = MCPSessionPool()
    name = _colliding_name()
    deployment = pool.ensure_binding(name, "deployment-fp")
    personal = pool.ensure_binding(name, "personal-fp", domain="personal")
    cm, _ = _session_cm()
    with patch("langchain_mcp_adapters.sessions.create_session", return_value=cm):
        await pool.get_session(name, "thread-1", _connection(), binding=deployment)
        personal_session = await pool.get_session(name, "thread-1", _connection(), binding=personal)

    prepared = pool.prepare_retire_all(domain="deployment")

    assert prepared.entries, "the deployment owner must be handed back for teardown"
    assert all(key[0].domain == "personal" for key in pool._entries)
    assert pool.active_binding(name) is None  # deployment binding dropped
    assert pool.active_binding(name, domain="personal") == personal
    assert pool._retired is False
    assert personal_session in _registered_sessions(pool)


@pytest.mark.asyncio
async def test_process_wide_reset_retires_both_domains():
    """The process-wide reset keeps its original meaning."""
    pool = MCPSessionPool()
    name = _colliding_name()
    deployment = pool.ensure_binding(name, "deployment-fp")
    personal = pool.ensure_binding(name, "personal-fp", domain="personal")
    cm, _ = _session_cm()
    with patch("langchain_mcp_adapters.sessions.create_session", return_value=cm):
        await pool.get_session(name, "thread-1", _connection(), binding=deployment)
        await pool.get_session(name, "thread-1", _connection(), binding=personal)

    prepared = pool.prepare_retire_all()

    assert len(prepared.entries) == 2
    assert not pool._entries
    assert not pool._inflight
    assert pool._retired is True


@pytest.mark.asyncio
async def test_deployment_binding_does_not_block_a_personal_task_session():
    """A same-name deployment binding must not fence the personal task caller.

    ``McpTaskToolCaller`` resolves its session through this pool with
    ``connection_scope="personal"``, so a deployment server that happens to use
    the same runtime name must not make its status/cancel calls stale.
    """
    pool = MCPSessionPool()
    name = _colliding_name()
    pool.ensure_binding(name, "deployment-fp")

    personal = pool.ensure_binding(name, "personal-fp", domain="personal")
    cm, session = _session_cm()
    with patch("langchain_mcp_adapters.sessions.create_session", return_value=cm):
        task_session = await pool.get_session(name, "user-1:thread-1", _connection(), binding=personal)

    assert task_session is session
    assert pool.active_binding(name, domain="personal") == personal
