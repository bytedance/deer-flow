"""Administrator API for runtime MCP agent credential grants.

``config.yaml`` keeps which server is protected and which OAuth client each
binding uses. For a binding declared with ``grants: runtime``, administrators
maintain the owners and approved definition digests here; each change applies
to the next call and run without a Gateway restart.
"""

from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel

from app.gateway.deps import require_admin_user
from app.gateway.persistent_writes import run_drained_write
from deerflow.config.app_config import AppConfig, get_app_config
from deerflow.config.mcp_agent_auth_config import BindingId, McpAgentCredentialBinding, McpAgentGrant
from deerflow.persistence.mcp_agent_grants import make_mcp_agent_grant_store

router = APIRouter(prefix="/api/mcp/agent-auth", tags=["mcp"])
_ADMIN_REQUIRED_DETAIL = "Admin privileges required to manage MCP agent credentials."


class McpAgentBindingResponse(BaseModel):
    binding: str
    server: str
    agent: str
    enabled: bool
    grants: Literal["config", "runtime"]
    owners: list[str]
    definition_digests: list[str]


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


def _response(binding_id: str, binding: McpAgentCredentialBinding, grant: McpAgentGrant | None) -> McpAgentBindingResponse:
    if binding.grants == "config":
        owners, digests = binding.owners, binding.definition_digests
    else:
        owners, digests = (grant.owners, grant.definition_digests) if grant is not None else ([], [])
    return McpAgentBindingResponse(
        binding=binding_id,
        server=binding.server,
        agent=binding.agent,
        enabled=binding.enabled,
        grants=binding.grants,
        owners=list(owners),
        definition_digests=list(digests),
    )


def _overlapping_binding(config: AppConfig, binding_id: str, binding: McpAgentCredentialBinding, grant: McpAgentGrant) -> str | None:
    """Return another enabled binding that already grants one of these owners the same server and agent."""
    stored = make_mcp_agent_grant_store(config).list()
    for other_id, other in config.mcp_agent_auth.items():
        if other_id == binding_id or not other.enabled or other.server != binding.server or other.agent != binding.agent:
            continue
        other_owners = other.owners if other.grants == "config" else (stored[other_id].owners if other_id in stored else [])
        if set(other_owners) & set(grant.owners):
            return other_id
    return None


@router.get("", response_model=McpAgentBindingsResponse, summary="List MCP Agent Credential Bindings")
async def list_bindings(request: Request) -> McpAgentBindingsResponse:
    """List every configured binding with the owners and digests in force; OAuth settings are never returned."""
    await require_admin_user(request, detail=_ADMIN_REQUIRED_DETAIL)
    config = await asyncio.to_thread(_config)
    stored = await asyncio.to_thread(make_mcp_agent_grant_store(config).list)
    return McpAgentBindingsResponse(bindings=[_response(binding_id, binding, stored.get(binding_id)) for binding_id, binding in sorted(config.mcp_agent_auth.items())])


@router.get("/{binding_id}", response_model=McpAgentBindingResponse, summary="Get MCP Agent Credential Binding")
async def get_binding(binding_id: BindingId, request: Request) -> McpAgentBindingResponse:
    await require_admin_user(request, detail=_ADMIN_REQUIRED_DETAIL)
    config = await asyncio.to_thread(_config)
    binding = _binding(config, binding_id)
    grant = await asyncio.to_thread(make_mcp_agent_grant_store(config).get, binding_id) if binding.grants == "runtime" else None
    return _response(binding_id, binding, grant)


@router.put("/{binding_id}/grants", response_model=McpAgentBindingResponse, summary="Replace Runtime MCP Agent Grant")
async def put_grant(binding_id: BindingId, grant: McpAgentGrant, request: Request) -> McpAgentBindingResponse:
    """Replace the owners and approved digests of a ``grants: runtime`` binding.

    Removing an owner denies that owner's next call; removing a digest stops
    new runs of that definition, while admitted runs keep the definition they
    started with.
    """
    await require_admin_user(request, detail=_ADMIN_REQUIRED_DETAIL)
    config = await asyncio.to_thread(_config)
    binding = _runtime_binding(config, binding_id)
    if binding.enabled:
        overlap = await asyncio.to_thread(_overlapping_binding, config, binding_id, binding, grant)
        if overlap is not None:
            raise HTTPException(status_code=409, detail=f"Owners overlap with MCP agent binding '{overlap}' for the same server and agent")
    store = make_mcp_agent_grant_store(config)
    try:
        await run_drained_write("Replace MCP agent grant", store.put, (ValueError,), binding_id, grant)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return _response(binding_id, binding, grant)


@router.delete("/{binding_id}/grants", status_code=204, summary="Delete Runtime MCP Agent Grant")
async def delete_grant(binding_id: BindingId, request: Request) -> Response:
    """Delete the grant; the binding then admits nobody."""
    await require_admin_user(request, detail=_ADMIN_REQUIRED_DETAIL)
    config = await asyncio.to_thread(_config)
    _runtime_binding(config, binding_id)
    store = make_mcp_agent_grant_store(config)
    if not await run_drained_write("Delete MCP agent grant", store.delete, (), binding_id):
        raise HTTPException(status_code=404, detail=f"MCP agent binding '{binding_id}' has no runtime grant")
    return Response(status_code=204)


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

        try:
            agent_config = load_agent_config(binding.agent, user_id=owner)
        except FileNotFoundError:
            return None
        return agent_definition_digest(agent_config, load_agent_soul(binding.agent, user_id=owner) or "")

    digest = await asyncio.to_thread(compute)
    if digest is None:
        raise HTTPException(status_code=404, detail=f"User '{owner}' has no agent '{binding.agent}'")
    return McpAgentDefinitionDigestResponse(binding=binding_id, agent=binding.agent, owner=owner, definition_digest=digest)
