"""Global Variables API router for managing project-level and thread-level variables."""

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from deerflow.config.global_variables_config import get_global_variables_config
from deerflow.global_variables.prompt_injector import get_merged_variables
from deerflow.global_variables.storage import get_storage, utc_now_iso_z

router = APIRouter(prefix="/api/global-variables", tags=["global-variables"])


class VariableItem(BaseModel):
    value: str = Field(..., description="Variable value")
    description: str = Field(default="", description="Variable description")


class VariableResponse(BaseModel):
    key: str = Field(..., description="Variable key")
    value: str = Field(..., description="Variable value")
    description: str = Field(default="", description="Variable description")
    is_system: bool = Field(default=False, description="Whether this is a system variable (read-only)")
    llm_editable: bool = Field(default=True, description="Whether LLM can modify this variable")
    updated_at: str = Field(default="", description="Last update timestamp")
    updated_by: str = Field(default="", description="Who last updated the variable")


class VariablesListResponse(BaseModel):
    variables: list[VariableResponse] = Field(default_factory=list)
    lastUpdated: str = Field(default="", description="Last update timestamp")


class VariableSetRequest(BaseModel):
    value: str = Field(..., description="Variable value")
    description: str = Field(default="", description="Variable description")
    llm_editable: bool = Field(default=True, description="Whether LLM can modify this variable")
    is_system: bool = Field(default=False, description="Whether this is a system variable")


@router.get(
    "/project",
    response_model=VariablesListResponse,
    summary="Get Project-Level Variables",
    description="Retrieve all project-level global variables.",
)
async def get_project_variables() -> VariablesListResponse:
    data = get_storage().load("project")
    return _build_variables_response(data)


@router.get(
    "/threads/{thread_id}",
    response_model=VariablesListResponse,
    summary="Get Thread-Level Variables",
    description="Retrieve all thread-level global variables for a specific thread.",
)
async def get_thread_variables(thread_id: str) -> VariablesListResponse:
    data = get_storage().load("thread", thread_id=thread_id)
    return _build_variables_response(data)


@router.get(
    "/merged",
    response_model=VariablesListResponse,
    summary="Get Merged Variables",
    description="Get merged variables (thread overrides project).",
)
async def get_merged_variables_endpoint(thread_id: str | None = None) -> VariablesListResponse:
    merged = get_merged_variables(thread_id=thread_id)
    lines = []
    for key, var in merged.items():
        if isinstance(var, dict):
            lines.append(
                VariableResponse(
                    key=key,
                    value=str(var.get("value", "")),
                    description=var.get("description", ""),
                    is_system=var.get("is_system", False),
                    llm_editable=var.get("llm_editable", True),
                    updated_at=var.get("updated_at", ""),
                    updated_by=var.get("updated_by", ""),
                )
            )
        else:
            lines.append(VariableResponse(key=key, value=str(var)))
    return VariablesListResponse(variables=lines)


@router.put(
    "/project/{key}",
    response_model=VariablesListResponse,
    summary="Set Project-Level Variable",
    description="Set or update a project-level global variable.",
)
async def set_project_variable(key: str, request: VariableSetRequest) -> VariablesListResponse:
    return _set_variable(key, request, scope="project")


@router.put(
    "/threads/{thread_id}/{key}",
    response_model=VariablesListResponse,
    summary="Set Thread-Level Variable",
    description="Set or update a thread-level global variable.",
)
async def set_thread_variable(thread_id: str, key: str, request: VariableSetRequest) -> VariablesListResponse:
    return _set_variable(key, request, scope="thread", thread_id=thread_id)


@router.delete(
    "/project/{key}",
    response_model=VariablesListResponse,
    summary="Delete Project-Level Variable",
    description="Delete a project-level global variable.",
)
async def delete_project_variable(key: str) -> VariablesListResponse:
    return _delete_variable(key, scope="project")


@router.delete(
    "/threads/{thread_id}/{key}",
    response_model=VariablesListResponse,
    summary="Delete Thread-Level Variable",
    description="Delete a thread-level global variable.",
)
async def delete_thread_variable(thread_id: str, key: str) -> VariablesListResponse:
    return _delete_variable(key, scope="thread", thread_id=thread_id)


@router.get(
    "/config",
    summary="Get Global Variables Configuration",
    description="Retrieve the current global variables system configuration.",
)
async def get_config() -> dict[str, Any]:
    config = get_global_variables_config()
    return {
        "enabled": config.enabled,
        "injection_enabled": config.injection_enabled,
        "max_variables_per_scope": config.max_variables_per_scope,
        "max_value_length": config.max_value_length,
        "max_total_prompt_length": config.max_total_prompt_length,
    }


def _build_variables_response(data: dict[str, Any]) -> VariablesListResponse:
    variables = data.get("variables", {})
    lines = []
    for key, var in variables.items():
        if isinstance(var, dict):
            lines.append(
                VariableResponse(
                    key=key,
                    value=str(var.get("value", "")),
                    description=var.get("description", ""),
                    is_system=var.get("is_system", False),
                    llm_editable=var.get("llm_editable", True),
                    updated_at=var.get("updated_at", ""),
                    updated_by=var.get("updated_by", ""),
                )
            )
        else:
            lines.append(VariableResponse(key=key, value=str(var)))
    return VariablesListResponse(
        variables=lines,
        lastUpdated=data.get("lastUpdated", ""),
    )


def _check_system_variable(key: str, variables: dict[str, Any]) -> None:
    """Check if variable is a system variable and raise if so."""
    existing = variables.get(key, {})
    if isinstance(existing, dict) and existing.get("is_system"):
        raise HTTPException(status_code=403, detail=f"Variable '{key}' is a system variable and cannot be modified")


def _set_variable(key: str, request: VariableSetRequest, scope: str, thread_id: str | None = None) -> VariablesListResponse:
    config = get_global_variables_config()
    if not config.enabled:
        raise HTTPException(status_code=400, detail="Global variables system is disabled")

    if not key or len(key) > 100:
        raise HTTPException(status_code=400, detail="Variable key must be a non-empty string (max 100 chars)")

    if len(request.value) > config.max_value_length:
        raise HTTPException(status_code=400, detail=f"Variable value exceeds maximum length of {config.max_value_length} characters")

    data = get_storage().load(scope, thread_id=thread_id)
    variables = data.get("variables", {})

    _check_system_variable(key, variables)

    if key not in variables and len(variables) >= config.max_variables_per_scope:
        raise HTTPException(
            status_code=400,
            detail=f"{scope} scope has reached maximum variables limit ({config.max_variables_per_scope})",
        )

    variables[key] = {
        "value": request.value,
        "description": request.description,
        "llm_editable": request.llm_editable,
        "is_system": request.is_system,
        "updated_at": utc_now_iso_z(),
        "updated_by": "api",
    }
    data["variables"] = variables
    get_storage().save(data, scope, thread_id=thread_id)

    return _build_variables_response(data)


def _delete_variable(key: str, scope: str, thread_id: str | None = None) -> VariablesListResponse:
    data = get_storage().load(scope, thread_id=thread_id)
    variables = data.get("variables", {})

    _check_system_variable(key, variables)

    if key not in variables:
        raise HTTPException(status_code=404, detail=f"Variable '{key}' not found in {scope} scope")

    del variables[key]
    data["variables"] = variables
    get_storage().save(data, scope, thread_id=thread_id)

    return _build_variables_response(data)
