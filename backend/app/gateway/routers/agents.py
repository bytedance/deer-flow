"""CRUD API for custom agents."""

import asyncio
import logging
import re
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from deerflow.config.agents_api_config import get_agents_api_config
from deerflow.config.agents_config import (
    AgentConfig,
    AgentModelSettings,
    list_custom_agents,
    load_agent_config,
    load_agent_soul,
    preserve_non_managed_fields,
)
from deerflow.config.app_config import get_app_config
from deerflow.config.paths import get_paths
from deerflow.persistence.agents import AgentExistsError, get_agent_store
from deerflow.runtime.user_context import get_effective_user_id

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["agents"])

AGENT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9-]+$")

ReasoningEffort = Literal["low", "medium", "high"]

# Fields carrying a custom agent's per-agent model behavior (issue #4336),
# shared by the create/update request bodies and the response so the three
# stay in lockstep. ``model`` picks the profile; the rest layer on top of it.
_MODEL_BEHAVIOR_FIELDS = ("model", "model_settings", "thinking_enabled", "reasoning_effort")


class AgentResponse(BaseModel):
    """Response model for a custom agent."""

    name: str = Field(..., description="Agent name (hyphen-case)")
    description: str = Field(default="", description="Agent description")
    model: str | None = Field(default=None, description="Optional model override")
    tool_groups: list[str] | None = Field(default=None, description="Optional tool group whitelist")
    skills: list[str] | None = Field(default=None, description="Optional skill whitelist (None=all, []=none)")
    model_settings: AgentModelSettings | None = Field(default=None, description="Per-agent sampling overrides (temperature / max_tokens)")
    thinking_enabled: bool | None = Field(default=None, description="Per-agent thinking-mode default (None = runtime default)")
    reasoning_effort: ReasoningEffort | None = Field(default=None, description="Per-agent reasoning-effort default (None = runtime default)")
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
    model_settings: AgentModelSettings | None = Field(default=None, description="Per-agent sampling overrides (temperature / max_tokens)")
    thinking_enabled: bool | None = Field(default=None, description="Per-agent thinking-mode default (None = runtime default)")
    reasoning_effort: ReasoningEffort | None = Field(default=None, description="Per-agent reasoning-effort default (None = runtime default)")
    soul: str = Field(default="", description="SOUL.md content — agent personality and behavioral guardrails")


class AgentUpdateRequest(BaseModel):
    """Request body for updating a custom agent."""

    description: str | None = Field(default=None, description="Updated description")
    model: str | None = Field(default=None, description="Updated model override")
    tool_groups: list[str] | None = Field(default=None, description="Updated tool group whitelist")
    skills: list[str] | None = Field(default=None, description="Updated skill whitelist (None=all, []=none)")
    model_settings: AgentModelSettings | None = Field(default=None, description="Updated per-agent sampling overrides")
    thinking_enabled: bool | None = Field(default=None, description="Updated per-agent thinking-mode default")
    reasoning_effort: ReasoningEffort | None = Field(default=None, description="Updated per-agent reasoning-effort default")
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


def _validate_model_exists(model: str | None) -> None:
    """Reject an agent ``model`` that is not a configured profile.

    Mirrors the ``update_agent`` harness tool: without this, an unknown model
    silently falls back to the default at runtime and the user sees confusing
    repeated warnings on every later turn instead of an actionable error here.
    ``None``/empty means "use the global default" and is always allowed.

    Best-effort: if the app config cannot be loaded (e.g. no ``config.yaml`` on
    disk in a bare/test deployment), skip the check rather than failing the
    write — the runtime still falls back to the default for an unknown model.
    """
    if not model:
        return
    try:
        app_config = get_app_config()
    except Exception:
        logger.warning("Could not load app config to validate agent model %r; skipping model existence check.", model)
        return
    if app_config.get_model_config(model) is None:
        raise HTTPException(status_code=422, detail=f"Unknown model '{model}'. Use a model name defined under `models:` in config.yaml.")


def _merge_model_settings_update(value: AgentModelSettings, existing: AgentModelSettings | None) -> dict:
    """Merge an explicit ``model_settings`` update with existing sub-fields.

    The top-level ``model_settings`` key is optional in update requests:
    omitted means "preserve the current block", while explicit ``null`` means
    "clear the block". Inside the block, omitted sub-fields should behave the
    same way. This lets API callers update only ``temperature`` without
    accidentally clearing an existing ``max_tokens``.
    """
    merged = existing.model_dump(exclude_none=True) if existing is not None else {}
    for field in value.model_fields_set:
        field_value = getattr(value, field)
        if field_value is None:
            merged.pop(field, None)
        else:
            merged[field] = field_value
    return merged


def _apply_model_behavior(config_data: dict, source: BaseModel, existing: AgentConfig | None = None) -> None:
    """Write the model-behavior fields (issue #4336) onto ``config_data``.

    Only fields explicitly set on ``source`` (``model_fields_set``) are taken
    from it; the rest fall back to ``existing`` (on update) so an omitted field
    is preserved rather than cleared. A resulting ``None`` is dropped so the
    persisted YAML stays minimal and "unset" round-trips cleanly.
    """
    for field in _MODEL_BEHAVIOR_FIELDS:
        if field in source.model_fields_set:
            value = getattr(source, field)
        else:
            value = getattr(existing, field, None) if existing is not None else None
        if value is None:
            continue
        if field == "model_settings" and isinstance(value, AgentModelSettings):
            dumped_settings = _merge_model_settings_update(value, existing.model_settings if existing is not None else None)
            if dumped_settings:
                config_data[field] = dumped_settings
            continue
        config_data[field] = value.model_dump(exclude_none=True) if isinstance(value, BaseModel) else value


def _agent_config_to_response(agent_cfg: AgentConfig, include_soul: bool = False, *, user_id: str | None = None) -> AgentResponse:
    """Convert AgentConfig to AgentResponse."""
    soul: str | None = None
    if include_soul:
        soul = load_agent_soul(agent_cfg.name, user_id=user_id) or ""

    return AgentResponse(
        name=agent_cfg.name,
        description=agent_cfg.description,
        model=agent_cfg.model,
        tool_groups=agent_cfg.tool_groups,
        skills=agent_cfg.skills,
        model_settings=agent_cfg.model_settings,
        thinking_enabled=agent_cfg.thinking_enabled,
        reasoning_effort=agent_cfg.reasoning_effort,
        soul=soul,
    )


@router.get(
    "/agents",
    response_model=AgentsListResponse,
    summary="List Custom Agents",
    description="List all custom agents available in the agents directory, including their soul content.",
)
async def list_agents() -> AgentsListResponse:
    """List all custom agents.

    Returns:
        List of all custom agents with their metadata and soul content.
    """
    _require_agents_api_enabled()

    user_id = get_effective_user_id()

    def _list() -> AgentsListResponse:
        # Worker thread: the store read plus the per-agent SOUL read inside
        # _agent_config_to_response are filesystem IO (file backend) or DB round
        # trips (db backend) and must stay off the event loop.
        agents = list_custom_agents(user_id=user_id)
        return AgentsListResponse(agents=[_agent_config_to_response(a, include_soul=True, user_id=user_id) for a in agents])

    try:
        return await asyncio.to_thread(_list)
    except Exception as e:
        logger.error(f"Failed to list agents: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list agents: {str(e)}")


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
    # Availability is defined by the active backend and stays consistent with
    # create()'s conflict rule (file: per-user or legacy dir; db: a row). The
    # exists() probe is filesystem IO / a DB round trip, so keep it off the loop.
    exists = await asyncio.to_thread(get_agent_store().exists, normalized, user_id=user_id)
    return {"available": not exists, "name": normalized}


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

    def _get() -> AgentResponse:
        # Worker thread: config read + SOUL read must stay off the event loop.
        agent_cfg = load_agent_config(name, user_id=user_id)
        return _agent_config_to_response(agent_cfg, include_soul=True, user_id=user_id)

    try:
        return await asyncio.to_thread(_get)
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
    _validate_model_exists(request.model)
    normalized_name = _normalize_agent_name(request.name)
    user_id = get_effective_user_id()

    # Config document — only the fields the caller set, matching the historical
    # writer (an omitted field stays absent rather than being materialized).
    config_data: dict = {"name": normalized_name}
    if request.description:
        config_data["description"] = request.description
    if request.tool_groups is not None:
        config_data["tool_groups"] = request.tool_groups
    if request.skills is not None:
        config_data["skills"] = request.skills
    # model / model_settings / thinking_enabled / reasoning_effort (issue #4336).
    _apply_model_behavior(config_data, request)

    store = get_agent_store()

    def _create_agent() -> AgentResponse:
        # Worker thread: existence checks + persistence (file IO or a DB round
        # trip) must stay off the event loop.
        store.create(normalized_name, config_data, request.soul, user_id=user_id)
        logger.info("Created agent '%s'", normalized_name)
        agent_cfg = load_agent_config(normalized_name, user_id=user_id)
        return _agent_config_to_response(agent_cfg, include_soul=True, user_id=user_id)

    try:
        return await asyncio.to_thread(_create_agent)
    except AgentExistsError:
        raise HTTPException(status_code=409, detail=f"Agent '{normalized_name}' already exists")
    except Exception as e:
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
        agent_cfg = await asyncio.to_thread(load_agent_config, name, user_id=user_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")

    def _is_legacy_only_layout() -> bool:
        # Require config.yaml, not bare directory existence — a per-user agent
        # directory can exist containing only memory.json (written the first
        # time this user chats with a legacy shared agent, before this route
        # is ever called). Bare .exists() would miss that case and let this
        # fall through to a silent fork of a brand-new config.yaml/SOUL.md
        # into the memory-only directory instead of blocking (mirrors
        # resolve_agent_dir's guard, see #3390). The db backend has no legacy
        # shared layout, so this file-only guard is a no-op there. The .exists()
        # probes are filesystem IO, so they run off the event loop.
        paths = get_paths()
        agent_dir = paths.user_agent_dir(user_id, name)
        legacy_dir = paths.agent_dir(name)
        return not (agent_dir / "config.yaml").exists() and (legacy_dir / "config.yaml").exists()

    if await asyncio.to_thread(_is_legacy_only_layout):
        raise HTTPException(
            status_code=409,
            detail=(f"Agent '{name}' only exists in the legacy shared layout and is not scoped to a user. Run scripts/migrate_user_isolation.py to move legacy agents into the per-user layout before updating."),
        )

    if "model" in request.model_fields_set:
        _validate_model_exists(request.model)

    try:
        # Update config if any config fields changed
        # Use model_fields_set to distinguish "field omitted" from "explicitly set to null".
        # This is critical for skills where None means "inherit all" (not "don't change").
        fields_set = request.model_fields_set
        config_changed = bool(fields_set & ({"description", "tool_groups", "skills"} | set(_MODEL_BEHAVIOR_FIELDS)))

        updated: dict | None = None
        if config_changed:
            updated = {
                "name": agent_cfg.name,
                "description": request.description if "description" in fields_set else agent_cfg.description,
            }

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

            # model / model_settings / thinking_enabled / reasoning_effort:
            # take explicitly-set request fields, else preserve the existing
            # value (issue #4336).
            _apply_model_behavior(updated, request, existing=agent_cfg)

            # Carry forward every top-level AgentConfig field this route does
            # not manage (currently ``github:``, plus any future field added
            # to :class:`AgentConfig`). The harness ``update_agent`` tool uses
            # the same helper, so an operator editing the agent description
            # from the Web UI does not silently strip a hand-authored
            # ``github:`` binding — which would otherwise leave the next
            # webhook delivery unable to find the agent in the registry and
            # silently no-op.
            for key, value in preserve_non_managed_fields(agent_cfg).items():
                updated.setdefault(key, value)

        store = get_agent_store()
        # Persist config (when changed) and/or soul (when provided) off the
        # event loop. A no-change PATCH commits nothing and re-reads current state.
        if updated is not None or request.soul is not None:
            await asyncio.to_thread(store.update, name, updated, request.soul, user_id=user_id)

        logger.info(f"Updated agent '{name}'")

        def _refresh() -> AgentResponse:
            # Worker thread: re-read config + SOUL off the event loop.
            refreshed_cfg = load_agent_config(name, user_id=user_id)
            return _agent_config_to_response(refreshed_cfg, include_soul=True, user_id=user_id)

        return await asyncio.to_thread(_refresh)

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
    store = get_agent_store()

    try:
        # Off the event loop: file rmtree or a DB delete plus memory cleanup.
        outcome = await asyncio.to_thread(store.delete, name, user_id=user_id)
    except Exception as e:
        logger.error(f"Failed to delete agent '{name}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to delete agent: {str(e)}")

    if outcome == "legacy":
        raise HTTPException(
            status_code=409,
            detail=(f"Agent '{name}' only exists in the legacy shared layout and is not scoped to a user. Run scripts/migrate_user_isolation.py to move legacy agents into the per-user layout before deleting."),
        )
    if outcome == "missing":
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
    if outcome == "not-custom-agent":
        raise HTTPException(
            status_code=409,
            detail=(f"Directory for '{name}' contains memory data but is not a custom agent because config.yaml is missing; it was preserved."),
        )

    logger.info(f"Deleted agent '{name}'")
