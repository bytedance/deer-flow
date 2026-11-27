"""Administrator API for runtime MCP agent credential grants.

``config.yaml`` keeps which server is protected and which OAuth client each
binding uses. For a binding declared with ``grants: runtime``, administrators
maintain the owners and approved definition digests here; each change applies
to the next call and run without a Gateway restart. A grant covers the agent,
server, destination and OAuth client the binding had when it was approved; if
``config.yaml`` later changes one of them, the grant admits nobody (``approval:
stale``) until an administrator replaces it. A grant whose binding was removed
from ``config.yaml`` is listed as ``approval: retired``. Stale and retired
grants, and grants of disabled bindings, keep their owners reserved for the
agent and server they were approved for, because a configuration rollback or
re-enabling the binding can make them current again; deleting the grant
releases them.
"""

from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel

from app.gateway.deps import require_admin_user
from app.gateway.persistent_writes import run_drained_write
from deerflow.config.app_config import AppConfig, get_app_config
from deerflow.config.mcp_agent_auth_config import BindingId, McpAgentCredentialBinding, McpAgentGrant, StoredMcpAgentGrant
from deerflow.config.paths import get_paths
from deerflow.mcp.agent_auth import grant_subject
from deerflow.persistence.mcp_agent_grants import make_mcp_agent_grant_store

router = APIRouter(prefix="/api/mcp/agent-auth", tags=["mcp"])
_ADMIN_REQUIRED_DETAIL = "Admin privileges required to manage MCP agent credentials."


class _InvalidOwner(ValueError):
    """An owner id that file-backed agent storage cannot hold."""


class McpAgentStoredGrantResponse(BaseModel):
    """A runtime grant still stored for a binding that now keeps its grants in config.yaml."""

    server: str
    agent: str
    owners: list[str]
    definition_digests: list[str]


class McpAgentBindingResponse(BaseModel):
    binding: str
    server: str
    agent: str
    enabled: bool
    grants: Literal["config", "runtime"]
    # config: owners and digests come from config.yaml. current: the runtime
    # grant is in force. stale: it was approved for another agent, server,
    # destination or OAuth client and admits nobody. none: no runtime grant.
    # retired: a stored grant whose binding is no longer configured; server and
    # agent are the ones it was approved for.
    approval: Literal["config", "current", "stale", "none", "retired"]
    owners: list[str]
    definition_digests: list[str]
    # A grants: config binding whose earlier runtime grant is still stored: it
    # admits nobody but keeps its owners reserved for the server and agent it was
    # approved for until it is deleted. None otherwise.
    stored_grant: McpAgentStoredGrantResponse | None = None


class McpAgentBindingsResponse(BaseModel):
    bindings: list[McpAgentBindingResponse]


class McpAgentDefinitionDigestResponse(BaseModel):
    binding: str
    agent: str
    owner: str
    definition_digest: str


def _config() -> AppConfig:
    return get_app_config(use_runtime_override=False)


def _binding(config: AppConfig, binding_id: str) -> McpAgentCredentialBinding:
    binding = config.mcp_agent_auth.get(binding_id)
    if binding is None:
        raise HTTPException(status_code=404, detail=f"MCP agent binding '{binding_id}' is not configured")
    return binding


def _runtime_binding(config: AppConfig, binding_id: str) -> McpAgentCredentialBinding:
    binding = _binding(config, binding_id)
    if binding.grants != "runtime":
        raise HTTPException(status_code=409, detail=f"MCP agent binding '{binding_id}' keeps its grants in config.yaml (grants: config)")
    return binding


def _response(config: AppConfig, binding_id: str, binding: McpAgentCredentialBinding, grant: StoredMcpAgentGrant | None) -> McpAgentBindingResponse:
    """Owners and digests as configured or stored; ``approval`` says whether a stored grant is in force."""
    stored_grant = None
    if binding.grants == "config" and grant is not None:
        stored_grant = McpAgentStoredGrantResponse(
            server=grant.approved_for.server,
            agent=grant.approved_for.agent,
            owners=list(grant.owners),
            definition_digests=list(grant.definition_digests),
        )
    if binding.grants == "config":
        owners, digests, approval = binding.owners, binding.definition_digests, "config"
    elif grant is None:
        owners, digests, approval = [], [], "none"
    else:
        owners, digests = grant.owners, grant.definition_digests
        approval = "current" if grant.approved_for == grant_subject(config, binding) else "stale"
    return McpAgentBindingResponse(
        binding=binding_id,
        server=binding.server,
        agent=binding.agent,
        enabled=binding.enabled,
        grants=binding.grants,
        approval=approval,
        owners=list(owners),
        definition_digests=list(digests),
        stored_grant=stored_grant,
    )


def _retired_response(binding_id: str, grant: StoredMcpAgentGrant) -> McpAgentBindingResponse:
    """A stored grant whose binding is no longer configured, described by what it was approved for."""
    return McpAgentBindingResponse(
        binding=binding_id,
        server=grant.approved_for.server,
        agent=grant.approved_for.agent,
        enabled=False,
        grants="runtime",
        approval="retired",
        owners=list(grant.owners),
        definition_digests=list(grant.definition_digests),
    )


def _overlapping_binding(config: AppConfig, binding_id: str, binding: McpAgentCredentialBinding, grant: McpAgentGrant) -> str | None:
    """Return another binding that grants, or may grant again, one of these owners the same server and agent.

    A stored runtime grant reserves its owners for the agent and server it was
    approved for even while it is stale or its binding is gone from
    ``config.yaml``: a configuration rollback can make it current again, and
    two matching grants would then reject the agent at admission. Deleting the
    grant releases the owners. A disabled binding reserves its owners too, and
    writing a grant to a disabled binding is checked the same way: enabling it
    again must not make admission reject both bindings.
    """
    owners = set(grant.owners)
    for other_id, other in config.mcp_agent_auth.items():
        if other_id == binding_id or other.grants != "config":
            continue
        if other.server == binding.server and other.agent == binding.agent and owners & set(other.owners):
            return other_id
    for other_id, other_grant in make_mcp_agent_grant_store(config).list().items():
        if other_id == binding_id:
            continue
        subject = other_grant.approved_for
        if subject.server == binding.server and subject.agent == binding.agent and owners & set(other_grant.owners):
            return other_id
    return None


@router.get("", response_model=McpAgentBindingsResponse, summary="List MCP Agent Credential Bindings")
async def list_bindings(request: Request) -> McpAgentBindingsResponse:
    """List every configured binding with the owners and digests in force, then retired grants; OAuth settings are never returned."""
    await require_admin_user(request, detail=_ADMIN_REQUIRED_DETAIL)
    config = await asyncio.to_thread(_config)
    stored = await asyncio.to_thread(lambda: make_mcp_agent_grant_store(config).list())
    bindings = [_response(config, binding_id, binding, stored.get(binding_id)) for binding_id, binding in sorted(config.mcp_agent_auth.items())]
    bindings += [_retired_response(binding_id, grant) for binding_id, grant in sorted(stored.items()) if binding_id not in config.mcp_agent_auth]
    return McpAgentBindingsResponse(bindings=bindings)


@router.get("/{binding_id}", response_model=McpAgentBindingResponse, summary="Get MCP Agent Credential Binding")
async def get_binding(binding_id: BindingId, request: Request) -> McpAgentBindingResponse:
    await require_admin_user(request, detail=_ADMIN_REQUIRED_DETAIL)
    config = await asyncio.to_thread(_config)
    binding = config.mcp_agent_auth.get(binding_id)
    if binding is None:
        retired = await asyncio.to_thread(lambda: make_mcp_agent_grant_store(config).get(binding_id))
        if retired is None:
            raise HTTPException(status_code=404, detail=f"MCP agent binding '{binding_id}' is not configured")
        return _retired_response(binding_id, retired)
    grant = await asyncio.to_thread(lambda: make_mcp_agent_grant_store(config).get(binding_id))
    return _response(config, binding_id, binding, grant)


@router.put("/{binding_id}/grants", response_model=McpAgentBindingResponse, summary="Replace Runtime MCP Agent Grant")
async def put_grant(binding_id: BindingId, grant: McpAgentGrant, request: Request) -> McpAgentBindingResponse:
    """Replace the owners and approved digests of a ``grants: runtime`` binding.

    Removing an owner denies that owner's next call; removing a digest stops
    new runs of that definition, while admitted runs keep the definition they
    started with. The grant is recorded for the binding's current agent,
    server, destination and OAuth client, and stays in force only while they
    are unchanged; rotating the client secret keeps it.
    """
    await require_admin_user(request, detail=_ADMIN_REQUIRED_DETAIL)
    config = await asyncio.to_thread(_config)
    binding = _runtime_binding(config, binding_id)
    subject = grant_subject(config, binding)
    if subject is None:
        raise HTTPException(status_code=409, detail=f"MCP server '{binding.server}' of binding '{binding_id}' is not configured")
    stored = StoredMcpAgentGrant(**grant.model_dump(), approved_for=subject)
    overlap = await asyncio.to_thread(_overlapping_binding, config, binding_id, binding, grant)
    if overlap is not None:
        raise HTTPException(status_code=409, detail=f"Owners overlap with MCP agent binding '{overlap}' for the same server and agent")
    try:
        await run_drained_write("Replace MCP agent grant", lambda: make_mcp_agent_grant_store(config).put(binding_id, stored), (ValueError,))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return _response(config, binding_id, binding, stored)


@router.delete("/{binding_id}/grants", status_code=204, summary="Delete Runtime MCP Agent Grant")
async def delete_grant(binding_id: BindingId, request: Request) -> Response:
    """Delete the grant; the binding then admits nobody.

    A stored grant left behind after its binding was removed from
    ``config.yaml`` or moved to ``grants: config`` can be deleted too; that
    releases the owners it reserves.
    """
    await require_admin_user(request, detail=_ADMIN_REQUIRED_DETAIL)
    config = await asyncio.to_thread(_config)
    if await run_drained_write("Delete MCP agent grant", lambda: make_mcp_agent_grant_store(config).delete(binding_id)):
        return Response(status_code=204)
    binding = config.mcp_agent_auth.get(binding_id)
    if binding is None:
        raise HTTPException(status_code=404, detail=f"MCP agent binding '{binding_id}' is not configured and has no stored grant")
    _runtime_binding(config, binding_id)
    raise HTTPException(status_code=404, detail=f"MCP agent binding '{binding_id}' has no runtime grant")


@router.get("/{binding_id}/definition-digest", response_model=McpAgentDefinitionDigestResponse, summary="Compute an Agent Definition Digest")
async def definition_digest(binding_id: BindingId, request: Request, owner: str = Query(min_length=1)) -> McpAgentDefinitionDigestResponse:
    """Digest of ``owner``'s stored copy of the binding's agent, as run admission computes it.

    Review that copy before approving its digest: approval covers its settings
    and exact SOUL, and any user holding an identical copy who is an owner.
    """
    await require_admin_user(request, detail=_ADMIN_REQUIRED_DETAIL)
    config = await asyncio.to_thread(_config)
    binding = _binding(config, binding_id)

    def compute() -> str | None:
        from deerflow.config.agents_config import load_agent_config, load_agent_soul
        from deerflow.mcp.agent_auth import agent_definition_digest

        if config.agent_storage.backend != "db":
            # File-backed agents live under the owner's user directory, so an
            # owner id that cannot name one (e.g. "../alice") has no agent there.
            try:
                get_paths().user_dir(owner)
            except ValueError as exc:
                raise _InvalidOwner(str(exc)) from None
        try:
            agent_config = load_agent_config(binding.agent, user_id=owner)
        except FileNotFoundError:
            return None
        return agent_definition_digest(agent_config, load_agent_soul(binding.agent, user_id=owner) or "")

    try:
        digest = await asyncio.to_thread(compute)
    except _InvalidOwner as exc:
        raise HTTPException(status_code=422, detail=f"Invalid owner for file-backed agent storage: {exc}") from None
    if digest is None:
        raise HTTPException(status_code=404, detail=f"User '{owner}' has no agent '{binding.agent}'")
    return McpAgentDefinitionDigestResponse(binding=binding_id, agent=binding.agent, owner=owner, definition_digest=digest)
