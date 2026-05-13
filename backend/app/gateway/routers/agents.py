"""CRUD API for custom agents."""

import logging
import re
import shutil

import yaml
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from deerflow.config.agents_api_config import get_agents_api_config
from deerflow.config.agents_config import AgentConfig, list_custom_agents, load_agent_config, load_agent_soul, load_builtin_agent_soul, load_tenant_agent_soul, scan_builtin_agents, scan_tenant_agents
from deerflow.config.paths import get_paths
from deerflow.config.tenant import get_current_tenant_id
from deerflow.runtime.user_context import get_effective_user_id

from app.gateway.deps import get_agent_usage_repo

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["agents"])

AGENT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9-]+$")


class AgentResponse(BaseModel):
    """Response model for a custom agent."""

    name: str = Field(..., description="Agent name (hyphen-case)")
    description: str = Field(default="", description="Agent description")
    display_name: str | None = Field(default=None, description="Human-readable display name")
    icon: str | None = Field(default=None, description="Icon identifier")
    model: str | None = Field(default=None, description="Optional model override")
    tool_groups: list[str] | None = Field(default=None, description="Optional tool group whitelist")
    skills: list[str] | None = Field(default=None, description="Optional skill whitelist (None=all, []=none)")
    mcp_servers: list[str] | None = Field(default=None, description="Optional MCP server whitelist")
    tags: list[str] | None = Field(default=None, description="Agent tags for filtering")
    source: str = Field(default="user", description="Agent source: builtin | tenant | user")
    editable: bool = Field(default=True, description="Whether the current user can edit this agent")
    enabled: bool = Field(default=True, description="Whether the agent is enabled")
    type: str | None = Field(default=None, description="Agent type: null/agent (normal) or group (parent agent)")
    parent: str | None = Field(default=None, description="Parent agent name for child agents")
    order: int | None = Field(default=None, description="Display order for child agents within a group")
    soul: str | None = Field(default=None, description="SOUL.md content")


class AgentsListResponse(BaseModel):
    """Response model for listing all custom agents."""

    agents: list[AgentResponse]


class AgentCreateRequest(BaseModel):
    """Request body for creating a custom agent."""

    name: str = Field(..., description="Agent name (must match ^[A-Za-z0-9-]+$, stored as lowercase)")
    description: str = Field(default="", description="Agent description")
    model: str | None = Field(default=None, description="Optional model override")
    tool_groups: list[str] | None = Field(default=None, description="Optional tool group whitelist")
    skills: list[str] | None = Field(default=None, description="Optional skill whitelist (None=all enabled, []=none)")
    soul: str = Field(default="", description="SOUL.md content — agent personality and behavioral guardrails")


class AgentUpdateRequest(BaseModel):
    """Request body for updating a custom agent."""

    description: str | None = Field(default=None, description="Updated description")
    model: str | None = Field(default=None, description="Updated model override")
    tool_groups: list[str] | None = Field(default=None, description="Updated tool group whitelist")
    skills: list[str] | None = Field(default=None, description="Updated skill whitelist (None=all, []=none)")
    soul: str | None = Field(default=None, description="Updated SOUL.md content")


def _validate_agent_name(name: str) -> None:
    """Validate agent name against allowed pattern.

    Args:
        name: The agent name to validate.

    Raises:
        HTTPException: 422 if the name is invalid.
    """
    if not AGENT_NAME_PATTERN.match(name):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid agent name '{name}'. Must match ^[A-Za-z0-9-]+$ (letters, digits, and hyphens only).",
        )


def _normalize_agent_name(name: str) -> str:
    """Normalize agent name to lowercase for filesystem storage."""
    return name.lower()


def _require_agents_api_enabled() -> None:
    """Reject access unless the custom-agent management API is explicitly enabled."""
    if not get_agents_api_config().enabled:
        raise HTTPException(
            status_code=403,
            detail=("Custom-agent management API is disabled. Set agents_api.enabled=true to expose agent and user-profile routes over HTTP."),
        )


def _agent_config_to_response(agent_cfg: AgentConfig, include_soul: bool = False, *, user_id: str | None = None, source: str = "user", editable: bool = True, tenant_id: str | None = None) -> AgentResponse:
    """Convert AgentConfig to AgentResponse."""
    soul: str | None = None
    if include_soul:
        if source == "builtin":
            soul = load_builtin_agent_soul(agent_cfg.name) or ""
        elif source == "tenant" and tenant_id:
            soul = load_tenant_agent_soul(tenant_id, agent_cfg.name) or ""
        else:
            soul = load_agent_soul(agent_cfg.name, user_id=user_id) or ""

    return AgentResponse(
        name=agent_cfg.name,
        description=agent_cfg.description,
        display_name=agent_cfg.display_name,
        icon=agent_cfg.icon,
        model=agent_cfg.model,
        tool_groups=agent_cfg.tool_groups,
        skills=agent_cfg.skills,
        mcp_servers=agent_cfg.mcp_servers,
        tags=agent_cfg.tags,
        source=source,
        editable=editable,
        type=agent_cfg.type,
        parent=agent_cfg.parent,
        order=agent_cfg.order,
        soul=soul,
    )


@router.get(
    "/agents",
    response_model=AgentsListResponse,
    summary="List Available Agents",
    description="List all available agents (builtin + user), with optional tag and enabled filtering.",
)
async def list_agents(tags: str | None = None, enabled: bool | None = None) -> AgentsListResponse:
    """List all available agents, merging builtin and user agents.

    User agents override builtin agents with the same name.

    Args:
        tags: Comma-separated tag filter (e.g. "research,writing").
        enabled: Filter by enabled status.

    Returns:
        Merged list of agents with source metadata.
    """
    _require_agents_api_enabled()

    user_id = get_effective_user_id()
    tenant_id = get_current_tenant_id()
    try:
        disabled_agents = _load_disabled_agents(user_id)
        merged: dict[str, AgentResponse] = {}

        # 3. Builtin agents (lowest priority — added first, overridden by higher)
        for agent_cfg in scan_builtin_agents():
            resp = _agent_config_to_response(agent_cfg, include_soul=True, source="builtin", editable=False)
            resp.enabled = resp.name not in disabled_agents
            merged[agent_cfg.name] = resp

        # 2. Tenant agents (middle priority)
        if tenant_id:
            for agent_cfg in scan_tenant_agents(tenant_id):
                resp = _agent_config_to_response(agent_cfg, include_soul=True, source="tenant", editable=False, tenant_id=tenant_id)
                resp.enabled = resp.name not in disabled_agents
                merged[agent_cfg.name] = resp

        # 1. User agents (highest priority — overrides all)
        for agent_cfg in list_custom_agents(user_id=user_id):
            resp = _agent_config_to_response(agent_cfg, include_soul=True, user_id=user_id, source="user", editable=True)
            resp.enabled = resp.name not in disabled_agents
            merged[agent_cfg.name] = resp

        result = sorted(merged.values(), key=lambda a: a.display_name or a.name)

        if tags:
            tag_set = {t.strip() for t in tags.split(",")}
            result = [a for a in result if a.tags and tag_set.intersection(a.tags)]

        if enabled is not None:
            result = [a for a in result if a.enabled == enabled]

        return AgentsListResponse(agents=result)
    except Exception as e:
        logger.error(f"Failed to list agents: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list agents: {str(e)}")


@router.get(
    "/agents/mine",
    response_model=AgentsListResponse,
    summary="List My Agents",
    description="List only the current user's own custom agents (excludes builtin and tenant agents).",
)
async def list_my_agents() -> AgentsListResponse:
    """List only the current user's own custom agents.

    Returns:
        List of user-owned agents sorted by name.
    """
    _require_agents_api_enabled()

    user_id = get_effective_user_id()
    try:
        agents = [
            _agent_config_to_response(cfg, include_soul=True, user_id=user_id, source="user", editable=True)
            for cfg in list_custom_agents(user_id=user_id)
        ]
        return AgentsListResponse(agents=agents)
    except Exception as e:
        logger.error(f"Failed to list user agents: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list user agents: {str(e)}")


@router.get(
    "/agents/check",
    summary="Check Agent Name",
    description="Validate an agent name and check if it is available (case-insensitive).",
)
async def check_agent_name(name: str) -> dict:
    """Check whether an agent name is valid and not yet taken.

    Args:
        name: The agent name to check.

    Returns:
        ``{"available": true/false, "name": "<normalized>"}``

    Raises:
        HTTPException: 422 if the name is invalid.
    """
    _require_agents_api_enabled()
    _validate_agent_name(name)
    normalized = _normalize_agent_name(name)
    user_id = get_effective_user_id()
    paths = get_paths()
    # Treat the name as taken if either the per-user path or the legacy shared
    # path holds an agent — picking a name that collides with an unmigrated
    # legacy agent would shadow the legacy entry once migration runs.
    available = not paths.user_agent_dir(user_id, normalized).exists() and not paths.agent_dir(normalized).exists()
    return {"available": available, "name": normalized}


@router.get(
    "/agents/{name}",
    response_model=AgentResponse,
    summary="Get Custom Agent",
    description="Retrieve details and SOUL.md content for a specific custom agent.",
)
async def get_agent(name: str) -> AgentResponse:
    """Get a specific custom agent by name.

    Args:
        name: The agent name.

    Returns:
        Agent details including SOUL.md content.

    Raises:
        HTTPException: 404 if agent not found.
    """
    _require_agents_api_enabled()
    _validate_agent_name(name)
    name = _normalize_agent_name(name)
    user_id = get_effective_user_id()
    tenant_id = get_current_tenant_id()

    try:
        agent_cfg = load_agent_config(name, user_id=user_id, tenant_id=tenant_id)
        # Determine source based on where the agent was found
        source = "user"
        editable = True
        paths = get_paths()
        if not paths.user_agent_dir(user_id, name).exists() and not paths.agent_dir(name).exists():
            if tenant_id:
                tenant_dir = paths.base_dir / "tenants" / tenant_id / "agents" / name
                if tenant_dir.exists():
                    source = "tenant"
                    editable = False
                else:
                    source = "builtin"
                    editable = False
            else:
                source = "builtin"
                editable = False
        return _agent_config_to_response(agent_cfg, include_soul=True, user_id=user_id, source=source, editable=editable, tenant_id=tenant_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
    except Exception as e:
        logger.error(f"Failed to get agent '{name}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get agent: {str(e)}")


@router.post(
    "/agents",
    response_model=AgentResponse,
    status_code=201,
    summary="Create Custom Agent",
    description="Create a new custom agent with its config and SOUL.md.",
)
async def create_agent_endpoint(request: AgentCreateRequest) -> AgentResponse:
    """Create a new custom agent.

    Args:
        request: The agent creation request.

    Returns:
        The created agent details.

    Raises:
        HTTPException: 409 if agent already exists, 422 if name is invalid.
    """
    _require_agents_api_enabled()
    _validate_agent_name(request.name)
    normalized_name = _normalize_agent_name(request.name)
    user_id = get_effective_user_id()
    paths = get_paths()

    agent_dir = paths.user_agent_dir(user_id, normalized_name)
    legacy_dir = paths.agent_dir(normalized_name)

    if agent_dir.exists() or legacy_dir.exists():
        raise HTTPException(status_code=409, detail=f"Agent '{normalized_name}' already exists")

    try:
        agent_dir.mkdir(parents=True, exist_ok=True)

        # Write config.yaml
        config_data: dict = {"name": normalized_name}
        if request.description:
            config_data["description"] = request.description
        if request.model is not None:
            config_data["model"] = request.model
        if request.tool_groups is not None:
            config_data["tool_groups"] = request.tool_groups
        if request.skills is not None:
            config_data["skills"] = request.skills

        config_file = agent_dir / "config.yaml"
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump(config_data, f, default_flow_style=False, allow_unicode=True)

        # Write SOUL.md
        soul_file = agent_dir / "SOUL.md"
        soul_file.write_text(request.soul, encoding="utf-8")

        logger.info(f"Created agent '{normalized_name}' at {agent_dir}")

        agent_cfg = load_agent_config(normalized_name, user_id=user_id)
        return _agent_config_to_response(agent_cfg, include_soul=True, user_id=user_id)

    except HTTPException:
        raise
    except Exception as e:
        # Clean up on failure
        if agent_dir.exists():
            shutil.rmtree(agent_dir)
        logger.error(f"Failed to create agent '{request.name}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to create agent: {str(e)}")


@router.put(
    "/agents/{name}",
    response_model=AgentResponse,
    summary="Update Custom Agent",
    description="Update an existing custom agent's config and/or SOUL.md.",
)
async def update_agent(name: str, request: AgentUpdateRequest) -> AgentResponse:
    """Update an existing custom agent.

    Args:
        name: The agent name.
        request: The update request (all fields optional).

    Returns:
        The updated agent details.

    Raises:
        HTTPException: 404 if agent not found.
    """
    _require_agents_api_enabled()
    _validate_agent_name(name)
    name = _normalize_agent_name(name)
    user_id = get_effective_user_id()

    try:
        agent_cfg = load_agent_config(name, user_id=user_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")

    paths = get_paths()
    agent_dir = paths.user_agent_dir(user_id, name)
    if not agent_dir.exists() and paths.agent_dir(name).exists():
        raise HTTPException(
            status_code=409,
            detail=(f"Agent '{name}' only exists in the legacy shared layout and is not scoped to a user. Run scripts/migrate_user_isolation.py to move legacy agents into the per-user layout before updating."),
        )

    try:
        # Update config if any config fields changed
        # Use model_fields_set to distinguish "field omitted" from "explicitly set to null".
        # This is critical for skills where None means "inherit all" (not "don't change").
        fields_set = request.model_fields_set
        config_changed = bool(fields_set & {"description", "model", "tool_groups", "skills"})

        if config_changed:
            updated: dict = {
                "name": agent_cfg.name,
                "description": request.description if "description" in fields_set else agent_cfg.description,
            }
            new_model = request.model if "model" in fields_set else agent_cfg.model
            if new_model is not None:
                updated["model"] = new_model

            new_tool_groups = request.tool_groups if "tool_groups" in fields_set else agent_cfg.tool_groups
            if new_tool_groups is not None:
                updated["tool_groups"] = new_tool_groups

            # skills: None = inherit all, [] = no skills, ["a","b"] = whitelist
            if "skills" in fields_set:
                new_skills = request.skills
            else:
                new_skills = agent_cfg.skills
            if new_skills is not None:
                updated["skills"] = new_skills

            config_file = agent_dir / "config.yaml"
            with open(config_file, "w", encoding="utf-8") as f:
                yaml.dump(updated, f, default_flow_style=False, allow_unicode=True)

        # Update SOUL.md if provided
        if request.soul is not None:
            soul_path = agent_dir / "SOUL.md"
            soul_path.write_text(request.soul, encoding="utf-8")

        logger.info(f"Updated agent '{name}'")

        refreshed_cfg = load_agent_config(name, user_id=user_id)
        return _agent_config_to_response(refreshed_cfg, include_soul=True, user_id=user_id)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update agent '{name}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update agent: {str(e)}")


class UserProfileResponse(BaseModel):
    """Response model for the global user profile (USER.md)."""

    content: str | None = Field(default=None, description="USER.md content, or null if not yet created")


class UserProfileUpdateRequest(BaseModel):
    """Request body for setting the global user profile."""

    content: str = Field(default="", description="USER.md content — describes the user's background and preferences")


@router.get(
    "/user-profile",
    response_model=UserProfileResponse,
    summary="Get User Profile",
    description="Read the global USER.md file that is injected into all custom agents.",
)
async def get_user_profile() -> UserProfileResponse:
    """Return the current USER.md content.

    Returns:
        UserProfileResponse with content=None if USER.md does not exist yet.
    """
    _require_agents_api_enabled()

    try:
        user_md_path = get_paths().user_md_file
        if not user_md_path.exists():
            return UserProfileResponse(content=None)
        raw = user_md_path.read_text(encoding="utf-8").strip()
        return UserProfileResponse(content=raw or None)
    except Exception as e:
        logger.error(f"Failed to read user profile: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to read user profile: {str(e)}")


@router.put(
    "/user-profile",
    response_model=UserProfileResponse,
    summary="Update User Profile",
    description="Write the global USER.md file that is injected into all custom agents.",
)
async def update_user_profile(request: UserProfileUpdateRequest) -> UserProfileResponse:
    """Create or overwrite the global USER.md.

    Args:
        request: The update request with the new USER.md content.

    Returns:
        UserProfileResponse with the saved content.
    """
    _require_agents_api_enabled()

    try:
        paths = get_paths()
        paths.base_dir.mkdir(parents=True, exist_ok=True)
        paths.user_md_file.write_text(request.content, encoding="utf-8")
        logger.info(f"Updated USER.md at {paths.user_md_file}")
        return UserProfileResponse(content=request.content or None)
    except Exception as e:
        logger.error(f"Failed to update user profile: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update user profile: {str(e)}")


@router.delete(
    "/agents/{name}",
    status_code=204,
    summary="Delete Custom Agent",
    description="Delete a custom agent and all its files (config, SOUL.md, memory).",
)
async def delete_agent(name: str) -> None:
    """Delete a custom agent.

    Args:
        name: The agent name.

    Raises:
        HTTPException: 404 if no per-user copy exists; 409 if only a legacy
            shared copy exists (suggesting the migration script).
    """
    _require_agents_api_enabled()
    _validate_agent_name(name)
    name = _normalize_agent_name(name)
    user_id = get_effective_user_id()
    paths = get_paths()
    agent_dir = paths.user_agent_dir(user_id, name)

    if not agent_dir.exists():
        if paths.agent_dir(name).exists():
            raise HTTPException(
                status_code=409,
                detail=(f"Agent '{name}' only exists in the legacy shared layout and is not scoped to a user. Run scripts/migrate_user_isolation.py to move legacy agents into the per-user layout before deleting."),
            )
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")

    try:
        shutil.rmtree(agent_dir)
        logger.info(f"Deleted agent '{name}' from {agent_dir}")
    except Exception as e:
        logger.error(f"Failed to delete agent '{name}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to delete agent: {str(e)}")


class AgentEnabledRequest(BaseModel):
    """Request body for enabling/disabling an agent."""

    enabled: bool = Field(..., description="Whether the agent should be enabled")


@router.put(
    "/agents/{name}/enabled",
    summary="Enable/Disable Agent",
    description="Enable or disable an agent for the current user. Works for builtin, tenant, and user agents.",
)
async def set_agent_enabled(name: str, body: AgentEnabledRequest) -> dict:
    """Enable or disable an agent for the current user.

    Disabled agents are excluded from the agent list and cannot be selected.
    The state is stored per-user in a JSON file.

    Args:
        name: The agent name.
        body: The enable/disable request.

    Returns:
        Updated enabled state.
    """
    _require_agents_api_enabled()
    _validate_agent_name(name)
    name = _normalize_agent_name(name)
    user_id = get_effective_user_id()

    disabled_agents = _load_disabled_agents(user_id)

    if body.enabled:
        disabled_agents.discard(name)
    else:
        disabled_agents.add(name)

    _save_disabled_agents(user_id, disabled_agents)
    return {"name": name, "enabled": body.enabled}


def _get_disabled_agents_path(user_id: str):
    """Return the path to the user's disabled agents JSON file."""
    paths = get_paths()
    return paths.base_dir / "users" / user_id / "disabled_agents.json"


def _load_disabled_agents(user_id: str) -> set[str]:
    """Load the set of disabled agent names for a user."""
    import json

    path = _get_disabled_agents_path(user_id)
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return set(data) if isinstance(data, list) else set()
    except Exception:
        return set()


def _save_disabled_agents(user_id: str, disabled: set[str]) -> None:
    """Persist the set of disabled agent names for a user."""
    import json

    path = _get_disabled_agents_path(user_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted(disabled)), encoding="utf-8")


@router.post(
    "/agents/fork/{name}",
    response_model=AgentResponse,
    status_code=201,
    summary="Fork Agent",
    description="Copy a builtin or tenant agent to the user's own agents directory for customization.",
)
async def fork_agent(name: str) -> AgentResponse:
    """Fork a builtin or tenant agent into the user's personal agents.

    Creates a copy of the agent's config and SOUL.md in the user's
    agent directory, allowing customization without affecting the original.

    Args:
        name: The agent name to fork.

    Returns:
        The forked agent details.

    Raises:
        HTTPException: 404 if source agent not found, 409 if user already has an agent with that name.
    """
    _require_agents_api_enabled()
    _validate_agent_name(name)
    name = _normalize_agent_name(name)
    user_id = get_effective_user_id()
    tenant_id = get_current_tenant_id()
    paths = get_paths()

    user_agent_dir = paths.user_agent_dir(user_id, name)
    if user_agent_dir.exists():
        raise HTTPException(status_code=409, detail=f"Agent '{name}' already exists in your agents. Delete it first to re-fork.")

    try:
        source_config = load_agent_config(name, user_id=user_id, tenant_id=tenant_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")

    # Load SOUL from the source
    from deerflow.config.agents_config import load_builtin_agent_soul, load_tenant_agent_soul

    soul: str = ""
    # Determine source: check tenant first, then builtin
    tenant_dir = paths.base_dir / "tenants" / (tenant_id or "") / "agents" / name
    if tenant_id and tenant_dir.exists():
        soul = load_tenant_agent_soul(tenant_id, name) or ""
    else:
        soul = load_builtin_agent_soul(name) or ""

    # Write forked agent to user directory
    user_agent_dir.mkdir(parents=True, exist_ok=True)

    config_data: dict = {"name": name}
    if source_config.description:
        config_data["description"] = source_config.description
    if source_config.display_name:
        config_data["display_name"] = source_config.display_name
    if source_config.icon:
        config_data["icon"] = source_config.icon
    if source_config.model:
        config_data["model"] = source_config.model
    if source_config.tool_groups:
        config_data["tool_groups"] = source_config.tool_groups
    if source_config.skills is not None:
        config_data["skills"] = source_config.skills
    if source_config.mcp_servers:
        config_data["mcp_servers"] = source_config.mcp_servers
    if source_config.tags:
        config_data["tags"] = source_config.tags

    config_file = user_agent_dir / "config.yaml"
    with open(config_file, "w", encoding="utf-8") as f:
        yaml.dump(config_data, f, default_flow_style=False, allow_unicode=True)

    soul_file = user_agent_dir / "SOUL.md"
    soul_file.write_text(soul, encoding="utf-8")

    logger.info(f"Forked agent '{name}' to user '{user_id}'")

    forked_config = load_agent_config(name, user_id=user_id)
    return _agent_config_to_response(forked_config, include_soul=True, user_id=user_id, source="user", editable=True)


@router.post(
    "/agents/{name}/usage",
    summary="Record Agent Usage (Deprecated)",
    description="Deprecated: usage is now auto-recorded on run end. Kept for backward compatibility.",
    deprecated=True,
)
async def record_agent_usage(
    name: str,
    request: Request,
    usage_repo=Depends(get_agent_usage_repo),
) -> dict:
    """Record an agent usage event (deprecated — auto-recorded on run end)."""
    if usage_repo is None:
        return {"recorded": False}
    user_id = get_effective_user_id()
    tenant_id = get_current_tenant_id() or "default"
    await usage_repo.record(tenant_id=tenant_id, agent_name=name, user_id=user_id)
    return {"recorded": True}


@router.get(
    "/agents/stats",
    summary="Get Agent Usage Stats",
    description="Get usage stats with token aggregation for all agents in the current tenant.",
)
async def get_agent_usage_stats(
    request: Request,
    period: int | None = None,
    usage_repo=Depends(get_agent_usage_repo),
) -> dict:
    """Return usage stats grouped by agent name with token totals."""
    if usage_repo is None:
        return {"stats": []}
    tenant_id = get_current_tenant_id() or "default"
    stats = await usage_repo.stats_by_tenant(tenant_id, period_days=period)
    return {"stats": stats}


@router.get(
    "/agents/stats/mine",
    summary="Get My Agent Usage Stats",
    description="Get usage stats with token aggregation for the current user.",
)
async def get_my_agent_usage_stats(
    request: Request,
    period: int | None = None,
    usage_repo=Depends(get_agent_usage_repo),
) -> dict:
    """Return usage stats for the current user with token totals."""
    if usage_repo is None:
        return {"stats": []}
    user_id = get_effective_user_id()
    stats = await usage_repo.stats_by_user(user_id, period_days=period)
    return {"stats": stats}


@router.get(
    "/agents/{name}/stats",
    summary="Get Single Agent Stats",
    description="Get detailed usage stats for a specific agent.",
)
async def get_single_agent_stats(
    name: str,
    request: Request,
    period: int | None = None,
    usage_repo=Depends(get_agent_usage_repo),
) -> dict:
    """Return detailed stats for a single agent."""
    if usage_repo is None:
        return {"stats": {}}
    tenant_id = get_current_tenant_id() or "default"
    stats = await usage_repo.stats_for_agent(tenant_id, name, period_days=period)
    return {"stats": stats}


@router.get(
    "/agents/stats/summary",
    summary="Get Agent Usage Summary",
    description="Get aggregated usage summary for a time period (default 7 days).",
)
async def get_agent_usage_summary(
    request: Request,
    period: int = 7,
    usage_repo=Depends(get_agent_usage_repo),
) -> dict:
    """Return time-bounded usage summary for the tenant."""
    if usage_repo is None:
        return {"stats": [], "period_days": period}
    tenant_id = get_current_tenant_id() or "default"
    stats = await usage_repo.stats_by_tenant(tenant_id, period_days=period)
    return {"stats": stats, "period_days": period}


@router.get(
    "/agents/recommend",
    summary="Recommend Agents",
    description="Recommend top-3 agents based on keyword matching against tags and descriptions.",
)
async def recommend_agents(q: str) -> dict:
    """Return top-3 agent recommendations based on keyword matching.

    Matches the query against agent names, descriptions, and tags.
    Returns enabled agents only, sorted by relevance score.

    Args:
        q: The user's input text to match against.

    Returns:
        List of up to 3 recommended agents with scores.
    """
    _require_agents_api_enabled()

    user_id = get_effective_user_id()
    tenant_id = get_current_tenant_id()

    from deerflow.config.agents_config import list_available_agents

    all_agents = list_available_agents(tenant_id=tenant_id, user_id=user_id)

    query_words = set(q.lower().split())
    if not query_words:
        return {"recommendations": []}

    scored: list[tuple[float, dict]] = []
    for agent in all_agents:
        if not agent.enabled:
            continue
        score = 0.0
        name_lower = agent.name.lower()
        desc_lower = (agent.description or "").lower()
        display_lower = (agent.display_name or "").lower()
        tags_lower = [t.lower() for t in (agent.tags or [])]

        for word in query_words:
            if word in name_lower or word in display_lower:
                score += 3.0
            if word in desc_lower:
                score += 1.0
            for tag in tags_lower:
                if word in tag:
                    score += 2.0

        if score > 0:
            scored.append((score, {"name": agent.name, "display_name": agent.display_name, "description": agent.description, "source": agent.source, "score": score}))

    scored.sort(key=lambda x: x[0], reverse=True)
    return {"recommendations": [item[1] for item in scored[:3]]}
