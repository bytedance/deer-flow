"""Host-admitted agent identities for deployment MCP calls."""

from __future__ import annotations

import asyncio
import logging
import threading
from collections import OrderedDict
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Literal

from deerflow_extension_api import canonical_hash, canonical_json
from langchain_core.tools import ToolException
from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from deerflow.config.agents_config import AgentConfig, load_agent_soul
from deerflow.config.extensions_config import ExtensionsConfig, McpServerConfig, get_extensions_config
from deerflow.config.mcp_agent_auth_config import BindingId, DefinitionDigest, McpAgentCredentialBinding, McpAgentGrantSubject, StoredMcpAgentGrant
from deerflow.mcp.headers import apply_header_overrides, header_spellings
from deerflow.mcp.oauth import OAuthTokenManager
from deerflow.runtime.context_keys import AGENT_AUTH_CONTEXT_KEY
from deerflow.runtime.user_context import resolve_runtime_user_id

logger = logging.getLogger(__name__)


class McpAgentAuthorizationError(ToolException):
    """An agent's administrator grant is absent, revoked or replaced."""


class AgentCredentialReference(BaseModel):
    """Nonsecret identity retained by a durable task."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)
    version: Literal[1] = 1
    server: str
    binding: BindingId
    agent: str
    definition_digest: DefinitionDigest
    credential_digest: DefinitionDigest
    destination_digest: DefinitionDigest


@dataclass(frozen=True)
class AgentMcpAuthority:
    user_id: str
    references: tuple[AgentCredentialReference, ...]
    definition_json: str | None = None
    soul: str = ""

    def agent_config(self) -> AgentConfig | None:
        return AgentConfig.model_validate_json(self.definition_json) if self.definition_json is not None else None


_task_authority: ContextVar[AgentMcpAuthority | None] = ContextVar("deerflow_mcp_task_agent_authority", default=None)
_reference_list = TypeAdapter(list[AgentCredentialReference])
_token_managers: OrderedDict[tuple[str, str, str], OAuthTokenManager] = OrderedDict()
_token_managers_lock = threading.Lock()


def agent_definition_digest(config: AgentConfig, soul: str | None) -> str:
    """Hash the stored agent settings and SOUL text that admission will pin."""
    return canonical_hash({"version": 1, "config": config.model_dump(mode="json"), "soul": soul or ""})


def grant_subject(app_config: Any, binding: McpAgentCredentialBinding) -> McpAgentGrantSubject | None:
    """What a runtime grant for ``binding`` is approved for under the current configuration."""
    server = app_config.extensions.mcp_servers.get(binding.server)
    if server is None:
        return None
    return McpAgentGrantSubject(agent=binding.agent, server=binding.server, destination_digest=_destination_digest(server), credential_digest=_credential_digest(binding))


def runtime_grant_in_force(app_config: Any, binding_id: str, binding: McpAgentCredentialBinding, grant: StoredMcpAgentGrant | None) -> tuple[frozenset[str], frozenset[str]]:
    """Owners and digests of a stored runtime grant, or none when it no longer applies.

    An approval covers the agent, server, destination and OAuth client it was
    given for. Pointing the binding at another agent, server or client, or the
    server at another destination, leaves the grant stored but in force for
    nobody until an administrator approves it again.
    """
    if grant is None:
        return frozenset(), frozenset()
    if grant.approved_for != grant_subject(app_config, binding):
        logger.warning("MCP agent grant for binding=%s was approved for a different agent, server, destination or OAuth client; it admits nobody until approved again", binding_id)
        return frozenset(), frozenset()
    return frozenset(grant.owners), frozenset(grant.definition_digests)


def binding_grant(app_config: Any, binding_id: str, binding: McpAgentCredentialBinding) -> tuple[frozenset[str], frozenset[str]]:
    """Return the owners and approved digests in force for one binding.

    ``grants: runtime`` bindings read the administrator's grant from the
    database (or file store) on each call, so a change applies without a
    restart. A binding without a stored grant, or whose grant was approved for
    another agent, server, destination or OAuth client, admits nobody.
    """
    if binding.grants == "config":
        return frozenset(binding.owners), frozenset(binding.definition_digests)
    from deerflow.persistence.mcp_agent_grants import make_mcp_agent_grant_store

    try:
        grant = make_mcp_agent_grant_store(app_config).get(binding_id)
    except Exception:
        logger.warning("MCP agent grant store unavailable for binding=%s", binding_id, exc_info=True)
        raise ToolException("MCP agent credential policy is unavailable") from None
    return runtime_grant_in_force(app_config, binding_id, binding, grant)


def _credential_digest(binding: McpAgentCredentialBinding) -> str:
    # Rotating a secret preserves the account. Replacing the endpoint, client,
    # scope or other request settings requires a new admission.
    return canonical_hash(binding.oauth.model_dump(mode="json", exclude={"client_secret", "refresh_token", "refresh_skew_seconds"}))


def _destination_digest(server: McpServerConfig) -> str:
    return canonical_hash({"transport": server.type, "url": server.url})


def _current_server(server_name: str) -> McpServerConfig | None:
    from deerflow.config.app_config import get_app_config, peek_loaded_app_config

    try:
        # Standalone MCP clients need only extensions_config.json. A Gateway
        # also applies its operator-owned YAML overrides, never a run snapshot.
        config = get_app_config(use_runtime_override=False).extensions if peek_loaded_app_config(use_runtime_override=False) is not None else get_extensions_config()
        return config.mcp_servers.get(server_name)
    except Exception:
        raise ToolException("MCP agent credential policy is unavailable") from None


def capture_agent_authority(app_config: Any, *, user_id: str, agent_config: AgentConfig | None) -> AgentMcpAuthority | None:
    """Admit a host-loaded definition once, before an agent run is assembled."""
    if agent_config is None:
        return None
    matches = []
    for binding_id, binding in app_config.mcp_agent_auth.items():
        server = app_config.extensions.mcp_servers.get(binding.server)
        if not (binding.enabled and binding.agent == agent_config.name and server is not None and server.enabled and server.agent_auth):
            continue
        try:
            owners, digests = binding_grant(app_config, binding_id, binding)
        except ToolException as exc:
            raise McpAgentAuthorizationError(str(exc)) from None
        if user_id in owners:
            matches.append((binding_id, binding, digests))
    if not matches:
        return None
    if len({binding.server for _, binding, _ in matches}) != len(matches):
        # Config validation rejects overlaps, and the admin API rejects them on
        # write; two concurrent runtime writes could still race. Fail closed.
        raise McpAgentAuthorizationError(f"MCP agent bindings overlap for agent '{agent_config.name}'")
    soul = load_agent_soul(agent_config.name, user_id=user_id) or ""
    digest = agent_definition_digest(agent_config, soul)
    references = []
    for binding_id, binding, digests in matches:
        if digest not in digests:
            raise McpAgentAuthorizationError(f"Agent definition is not approved for MCP binding '{binding_id}'")
        references.append(
            AgentCredentialReference(
                server=binding.server,
                binding=binding_id,
                agent=binding.agent,
                definition_digest=digest,
                credential_digest=_credential_digest(binding),
                destination_digest=_destination_digest(app_config.extensions.mcp_servers[binding.server]),
            )
        )
    return AgentMcpAuthority(user_id, tuple(references), canonical_json(agent_config.model_dump(mode="json")), soul)


def runtime_agent_authority(runtime: Any) -> AgentMcpAuthority | None:
    context = getattr(runtime, "context", None)
    authority = context.get(AGENT_AUTH_CONTEXT_KEY) if isinstance(context, Mapping) else None
    if isinstance(authority, AgentMcpAuthority) and authority.user_id == resolve_runtime_user_id(runtime):
        return authority
    return None


def export_agent_authority(authority: AgentMcpAuthority | None) -> list[dict[str, Any]] | None:
    """Persist references captured by the host, without definitions or credentials."""
    if not isinstance(authority, AgentMcpAuthority):
        return None
    return [reference.model_dump(mode="json") for reference in authority.references]


def restore_agent_authority(user_id: str, references: Any) -> AgentMcpAuthority | None:
    """Restore references from host-owned durable rows; each use rechecks the grant."""
    if references is None:
        return None
    try:
        parsed = _reference_list.validate_python(references)
    except ValidationError:
        raise McpAgentAuthorizationError("Invalid persisted MCP agent identity") from None
    if not parsed or len({ref.server for ref in parsed}) != len(parsed) or len({ref.agent for ref in parsed}) != 1:
        raise McpAgentAuthorizationError("Invalid persisted MCP agent identity")
    return AgentMcpAuthority(user_id, tuple(parsed))


def task_agent_reference(runtime: Any, server_name: str, *, required: bool) -> dict[str, Any] | None:
    authority = runtime_agent_authority(runtime)
    if authority is not None:
        for reference in authority.references:
            if reference.server == server_name:
                return reference.model_dump(mode="json")
    if required:
        raise McpAgentAuthorizationError(f"No admitted agent credential for MCP server '{server_name}'")
    return None


def _current_binding(reference: AgentCredentialReference, user_id: str) -> McpAgentCredentialBinding:
    from deerflow.config.app_config import get_app_config

    try:
        config = get_app_config(use_runtime_override=False)
    except Exception:
        raise ToolException("MCP agent credential policy is unavailable") from None
    binding = config.mcp_agent_auth.get(reference.binding)
    server = config.extensions.mcp_servers.get(reference.server)
    if (
        binding is None
        or not binding.enabled
        or user_id not in binding_grant(config, reference.binding, binding)[0]
        or binding.server != reference.server
        or binding.agent != reference.agent
        or server is None
        or not server.enabled
        or not server.agent_auth
        or _destination_digest(server) != reference.destination_digest
        or _credential_digest(binding) != reference.credential_digest
    ):
        raise McpAgentAuthorizationError(f"MCP agent credential binding '{reference.binding}' is unavailable or revoked")
    # Definition rollout changes admission for new runs. Existing calls and
    # durable tasks retain the definition version recorded at their admission.
    return binding


def _token_manager(reference: AgentCredentialReference, binding: McpAgentCredentialBinding) -> OAuthTokenManager:
    key = (reference.server, reference.binding, canonical_hash(binding.oauth.model_dump(mode="json")))
    with _token_managers_lock:
        manager = _token_managers.get(key)
        if manager is None:
            manager = OAuthTokenManager({reference.server: binding.oauth})
            _token_managers[key] = manager
        _token_managers.move_to_end(key)
        if len(_token_managers) > 128:
            _token_managers.popitem(last=False)
        return manager


@contextmanager
def bind_task_agent_authority(authority: AgentMcpAuthority | None) -> Iterator[None]:
    token = _task_authority.set(authority)
    try:
        yield
    finally:
        _task_authority.reset(token)


async def validate_task_agent_reference(user_id: str, server_name: str, reference: Any) -> AgentMcpAuthority | None:
    authority = restore_agent_authority(user_id, [reference]) if reference is not None else None
    if authority is not None:
        admitted = authority.references[0]
        if admitted.server != server_name:
            raise McpAgentAuthorizationError("MCP task credential belongs to a different server")
        await asyncio.to_thread(_current_binding, admitted, user_id)
    return authority


def build_agent_auth_interceptor(extensions_config: ExtensionsConfig) -> Any | None:
    servers = {name: server for name, server in extensions_config.get_enabled_mcp_servers().items() if server.type in ("http", "sse")}
    if not servers:
        return None

    async def agent_auth_interceptor(request: Any, handler: Any) -> Any:
        server = servers.get(request.server_name)
        if server is None:
            return await handler(request)
        if not server.agent_auth:
            current = await asyncio.to_thread(_current_server, request.server_name)
            try:
                deployed = await asyncio.to_thread(get_extensions_config)
            except Exception:
                raise ToolException("MCP credential policy is unavailable") from None
            browser_server = deployed.mcp_servers.get(request.server_name)
            if browser_server is not None and browser_server.uses_browser_oauth:
                raise ToolException(f"MCP server '{request.server_name}' now requires a browser connection. Start a new run to reload its tools.")
            if current is not None and current.agent_auth:
                # The old chain may still contain user/context auth writers.
                # Require rediscovery instead of injecting into that chain.
                raise McpAgentAuthorizationError(f"MCP server '{request.server_name}' now requires agent credentials; start a new run to reload its tools")
            return await handler(request)
        runtime = getattr(request, "runtime", None)
        authority = runtime_agent_authority(runtime) if runtime is not None else _task_authority.get()
        reference = next((ref for ref in authority.references if ref.server == request.server_name), None) if authority is not None else None
        if reference is None:
            raise McpAgentAuthorizationError(f"No admitted agent credential for MCP server '{request.server_name}'")
        if _destination_digest(server) != reference.destination_digest:
            raise McpAgentAuthorizationError(f"MCP destination no longer matches binding '{reference.binding}'")
        binding = await asyncio.to_thread(_current_binding, reference, authority.user_id)
        manager = _token_manager(reference, binding)
        try:
            authorization = await manager.get_authorization_header(reference.server)
        except Exception:
            raise ToolException(f"Could not acquire the agent credential for MCP server '{reference.server}'") from None
        if not authorization:
            raise ToolException(f"Missing agent credential for MCP server '{reference.server}'")
        # Token acquisition may await an external identity provider.
        await asyncio.to_thread(_current_binding, reference, authority.user_id)
        logger.info("MCP agent credential selected for server=%s agent=%s owner=%s binding=%s", reference.server, reference.agent, authority.user_id, reference.binding)
        headers = apply_header_overrides(request.headers, {"Authorization": authorization}, spellings=header_spellings(server.headers))
        return await handler(request.override(headers=headers))

    return agent_auth_interceptor
