"""Catalog and administrator CRUD API for subagent definitions."""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError

from app.gateway.deps import is_admin_user, require_admin_user
from deerflow.config.app_config import get_app_config
from deerflow.persistence.managed_subagents import (
    ManagedSubagentDefinition,
    ManagedSubagentExistsError,
    get_managed_subagent_store,
)
from deerflow.persistence.managed_subagents.base import (
    MANAGED_SUBAGENT_NAME_PATTERN,
    normalize_managed_subagent_name,
)
from deerflow.subagents.builtins import BUILTIN_SUBAGENTS

router = APIRouter(prefix="/api/subagents", tags=["subagents"])
_ADMIN_REQUIRED_DETAIL = "Admin privileges are required to manage subagents."


class SubagentResponse(BaseModel):
    name: str
    display_name: str | None = None
    description: str
    system_prompt: str | None = None
    tools: list[str] | None = None
    disallowed_tools: list[str] | None = None
    skills: list[str] | None = None
    model: str = "inherit"
    max_turns: int = 50
    timeout_seconds: int = 900
    enabled: bool = True
    source: Literal["builtin", "config", "managed"]
    editable: bool = False
    conflict: bool = False
    config_overrides: dict[str, Any] = Field(default_factory=dict)


class SubagentsListResponse(BaseModel):
    subagents: list[SubagentResponse]


class ManagedSubagentCreateRequest(BaseModel):
    name: str = Field(pattern=MANAGED_SUBAGENT_NAME_PATTERN.pattern)
    display_name: str | None = None
    description: str = Field(min_length=1)
    system_prompt: str = Field(min_length=1)
    tools: list[str] | None = None
    disallowed_tools: list[str] | None = None
    skills: list[str] | None = None
    model: str = "inherit"
    max_turns: int = Field(default=50, ge=1)
    timeout_seconds: int = Field(default=900, ge=1)
    enabled: bool = True


class ManagedSubagentUpdateRequest(BaseModel):
    display_name: str | None = None
    description: str | None = Field(default=None, min_length=1)
    system_prompt: str | None = Field(default=None, min_length=1)
    tools: list[str] | None = None
    disallowed_tools: list[str] | None = None
    skills: list[str] | None = None
    model: str | None = None
    max_turns: int | None = Field(default=None, ge=1)
    timeout_seconds: int | None = Field(default=None, ge=1)
    enabled: bool | None = None


def _validate_model(model: str, app_config) -> None:
    if model == "inherit":
        return
    if app_config.get_model_config(model) is None:
        raise HTTPException(status_code=422, detail=f"Unknown model '{model}'. Use 'inherit' or a configured model name.")


def _validate_path_name(name: str) -> str:
    try:
        return normalize_managed_subagent_name(name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _explicit_overrides(name: str, app_config) -> dict[str, Any]:
    override = app_config.subagents.agents.get(name)
    if override is None:
        return {}
    result: dict[str, Any] = {}
    for field in ("timeout_seconds", "max_turns", "model", "skills"):
        if field not in override.model_fields_set:
            continue
        value = getattr(override, field)
        if value is not None:
            result[field] = value
    return result


def _catalog(include_system_prompt: bool) -> SubagentsListResponse:
    app_config = get_app_config()
    config_names = set(app_config.subagents.custom_agents)
    reserved_names = set(BUILTIN_SUBAGENTS) | config_names
    items: list[SubagentResponse] = []

    for name, definition in BUILTIN_SUBAGENTS.items():
        items.append(
            SubagentResponse(
                name=name,
                description=definition.description,
                system_prompt=definition.system_prompt if include_system_prompt else None,
                tools=definition.tools,
                disallowed_tools=definition.disallowed_tools,
                skills=definition.skills,
                model=definition.model,
                max_turns=definition.max_turns,
                timeout_seconds=definition.timeout_seconds,
                source="builtin",
                config_overrides=_explicit_overrides(name, app_config),
            )
        )

    for name, definition in app_config.subagents.custom_agents.items():
        items.append(
            SubagentResponse(
                name=name,
                description=definition.description,
                system_prompt=definition.system_prompt if include_system_prompt else None,
                tools=definition.tools,
                disallowed_tools=definition.disallowed_tools,
                skills=definition.skills,
                model=definition.model,
                max_turns=definition.max_turns,
                timeout_seconds=definition.timeout_seconds,
                source="config",
                conflict=name in BUILTIN_SUBAGENTS,
                config_overrides=_explicit_overrides(name, app_config),
            )
        )

    store = get_managed_subagent_store(app_config)
    for definition in store.list():
        items.append(
            SubagentResponse(
                **definition.model_dump(exclude={"system_prompt"}),
                system_prompt=definition.system_prompt if include_system_prompt else None,
                source="managed",
                editable=True,
                conflict=definition.name in reserved_names,
                config_overrides=_explicit_overrides(definition.name, app_config),
            )
        )
    source_order = {"builtin": 0, "config": 1, "managed": 2}
    items.sort(key=lambda item: (item.name, source_order[item.source]))
    return SubagentsListResponse(subagents=items)


@router.get("", response_model=SubagentsListResponse, summary="List Subagents")
async def list_subagents(request: Request) -> SubagentsListResponse:
    """List the runtime catalog; prompts remain visible only to admins."""
    include_system_prompt = await is_admin_user(request)
    return await asyncio.to_thread(_catalog, include_system_prompt)


@router.post("", response_model=SubagentResponse, status_code=201, summary="Create Managed Subagent")
async def create_managed_subagent(request: Request, body: ManagedSubagentCreateRequest) -> SubagentResponse:
    await require_admin_user(request, detail=_ADMIN_REQUIRED_DETAIL)
    try:
        definition = ManagedSubagentDefinition(**body.model_dump(exclude_none=True))
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc
    app_config = await asyncio.to_thread(get_app_config)
    _validate_model(definition.model, app_config)
    if definition.name in BUILTIN_SUBAGENTS or definition.name in app_config.subagents.custom_agents:
        raise HTTPException(status_code=409, detail=f"Subagent name '{definition.name}' is reserved by a built-in or config.yaml definition.")
    store = get_managed_subagent_store(app_config)
    try:
        await asyncio.to_thread(store.create, definition)
    except ManagedSubagentExistsError:
        raise HTTPException(status_code=409, detail=f"Managed subagent '{definition.name}' already exists")
    return SubagentResponse(
        **definition.model_dump(exclude={"system_prompt"}),
        system_prompt=definition.system_prompt,
        source="managed",
        editable=True,
        config_overrides=_explicit_overrides(definition.name, app_config),
    )


@router.put("/{name}", response_model=SubagentResponse, summary="Update Managed Subagent")
async def update_managed_subagent(name: str, request: Request, body: ManagedSubagentUpdateRequest) -> SubagentResponse:
    await require_admin_user(request, detail=_ADMIN_REQUIRED_DETAIL)
    name = _validate_path_name(name)
    app_config = await asyncio.to_thread(get_app_config)
    store = get_managed_subagent_store(app_config)
    try:
        existing = await asyncio.to_thread(store.get, name)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Managed subagent '{name}' not found")
    changes = body.model_dump(exclude_unset=True)
    updated = existing.model_copy(update=changes)
    # model_copy does not re-run validation, so round-trip through the model.
    try:
        updated = ManagedSubagentDefinition.model_validate(updated.model_dump())
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc
    _validate_model(updated.model, app_config)
    try:
        await asyncio.to_thread(store.update, updated)
    except FileNotFoundError:
        # The definition may be deleted by another administrator after the
        # read above. Preserve the endpoint's not-found contract instead of
        # leaking that race as a 500.
        raise HTTPException(status_code=404, detail=f"Managed subagent '{name}' not found")
    conflict = updated.name in BUILTIN_SUBAGENTS or updated.name in app_config.subagents.custom_agents
    return SubagentResponse(
        **updated.model_dump(exclude={"system_prompt"}),
        system_prompt=updated.system_prompt,
        source="managed",
        editable=True,
        conflict=conflict,
        config_overrides=_explicit_overrides(updated.name, app_config),
    )


@router.delete("/{name}", status_code=204, summary="Delete Managed Subagent")
async def delete_managed_subagent(name: str, request: Request) -> None:
    await require_admin_user(request, detail=_ADMIN_REQUIRED_DETAIL)
    name = _validate_path_name(name)
    app_config = await asyncio.to_thread(get_app_config)
    store = get_managed_subagent_store(app_config)
    if not await asyncio.to_thread(store.delete, name):
        raise HTTPException(status_code=404, detail=f"Managed subagent '{name}' not found")
