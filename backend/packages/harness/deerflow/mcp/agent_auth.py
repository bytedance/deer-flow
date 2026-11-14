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
from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.config.mcp_agent_auth_config import BindingId, DefinitionDigest, McpAgentCredentialBinding
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


def _credential_digest(binding: McpAgentCredentialBinding) -> str:
    # Rotating a secret preserves the account. Replacing the endpoint, client,
    # scope or other request settings requires a new admission.
    return canonical_hash(binding.oauth.model_dump(mode="json", exclude={"client_secret", "refresh_token", "refresh_skew_seconds"}))


def capture_agent_authority(app_config: Any, *, user_id: str, agent_config: AgentConfig | None) -> AgentMcpAuthority | None:
    """Admit a host-loaded definition once, before an agent run is assembled."""
    if agent_config is None:
        return None
    matches = []
    for binding_id, binding in app_config.mcp_agent_auth.items():
        server = app_config.extensions.mcp_servers.get(binding.server)
        if binding.enabled and binding.agent == agent_config.name and user_id in binding.owners and server is not None and server.enabled and server.agent_auth:
            matches.append((binding_id, binding))
    if not matches:
        return None
    soul = load_agent_soul(agent_config.name, user_id=user_id) or ""
    digest = agent_definition_digest(agent_config, soul)
    references = []
    for binding_id, binding in matches:
        if digest not in binding.definition_digests:
            raise McpAgentAuthorizationError(f"Agent definition is not approved for MCP binding '{binding_id}'")
        references.append(AgentCredentialReference(server=binding.server, binding=binding_id, agent=binding.agent, definition_digest=digest, credential_digest=_credential_digest(binding)))
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
        or user_id not in binding.owners
        or binding.server != reference.server
        or binding.agent != reference.agent
        or server is None
        or not server.enabled
        or not server.agent_auth
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
    servers = {name: server for name, server in extensions_config.get_enabled_mcp_servers().items() if server.agent_auth}
    if not servers:
        return None

    async def agent_auth_interceptor(request: Any, handler: Any) -> Any:
        server = servers.get(request.server_name)
        if server is None:
            return await handler(request)
        runtime = getattr(request, "runtime", None)
        authority = runtime_agent_authority(runtime) if runtime is not None else _task_authority.get()
        reference = next((ref for ref in authority.references if ref.server == request.server_name), None) if authority is not None else None
        if reference is None:
            raise McpAgentAuthorizationError(f"No admitted agent credential for MCP server '{request.server_name}'")
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
