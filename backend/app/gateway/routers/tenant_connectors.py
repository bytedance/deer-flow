"""CRUD API for tenant-level HTTP connector configurations (admin only)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from deerflow.persistence.agent.auth import is_tenant_admin
from deerflow.runtime.user_context import get_effective_user_id

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/tenants/{tenant_id}/connectors", tags=["tenant-connectors"])


class ConnectorCreateRequest(BaseModel):
    connector_name: str = Field(..., description="Unique connector name within the tenant")
    display_name: str | None = Field(default=None)
    description: str | None = Field(default=None)
    url: str = Field(..., description="Target URL")
    method: str = Field(default="GET", description="HTTP method: GET | POST | PUT")
    headers: dict[str, str] = Field(default_factory=dict)
    auth_type: str = Field(default="none", description="none | bearer | api_key")
    auth_token_env: str | None = Field(default=None)
    auth_header: str = Field(default="Authorization")
    timeout_seconds: float = Field(default=30.0, ge=1, le=300)
    max_response_bytes: int = Field(default=524288)
    max_retries: int = Field(default=1, ge=0, le=5)
    retry_on_status: list[int] = Field(default_factory=lambda: [502, 503, 504])
    cache_ttl_seconds: int | None = Field(default=None)
    enabled: bool = Field(default=True)


class ConnectorUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None)
    description: str | None = Field(default=None)
    url: str | None = Field(default=None)
    method: str | None = Field(default=None)
    headers: dict[str, str] | None = Field(default=None)
    auth_type: str | None = Field(default=None)
    auth_token_env: str | None = Field(default=None)
    auth_header: str | None = Field(default=None)
    timeout_seconds: float | None = Field(default=None, ge=1, le=300)
    max_response_bytes: int | None = Field(default=None)
    max_retries: int | None = Field(default=None, ge=0, le=5)
    retry_on_status: list[int] | None = Field(default=None)
    cache_ttl_seconds: int | None = Field(default=None)
    enabled: bool | None = Field(default=None)


class EnableRequest(BaseModel):
    enabled: bool


VALID_METHODS = {"GET", "POST", "PUT"}
VALID_AUTH_TYPES = {"none", "bearer", "api_key"}


def _get_current_user_role(request: Request) -> str:
    user = getattr(request.state, "user", None)
    if user is None:
        return "user"
    return getattr(user, "system_role", "user") or "user"


def _get_current_user_tenant(request: Request) -> str:
    user = getattr(request.state, "user", None)
    if user is None:
        return "default"
    return getattr(user, "tenant_id", "default") or "default"


def _require_tenant_admin(request: Request, tenant_id: str) -> None:
    role = _get_current_user_role(request)
    if not is_tenant_admin(role):
        raise HTTPException(status_code=403, detail="Tenant admin privileges required")
    user_tenant = _get_current_user_tenant(request)
    if role == "tenant_admin" and user_tenant != tenant_id:
        raise HTTPException(status_code=403, detail="Cannot manage connectors for a different tenant")


def _validate_connector_fields(method: str | None = None, auth_type: str | None = None) -> None:
    if method is not None and method.upper() not in VALID_METHODS:
        raise HTTPException(status_code=422, detail=f"method must be one of: {', '.join(VALID_METHODS)}")
    if auth_type is not None and auth_type not in VALID_AUTH_TYPES:
        raise HTTPException(status_code=422, detail=f"auth_type must be one of: {', '.join(VALID_AUTH_TYPES)}")


def _get_repo(request: Request):
    return request.app.state.http_connector_repo


@router.post("", summary="Create Tenant HTTP Connector")
async def create_connector(tenant_id: str, body: ConnectorCreateRequest, request: Request):
    _require_tenant_admin(request, tenant_id)
    _validate_connector_fields(body.method, body.auth_type)

    repo = _get_repo(request)
    existing = await repo.get_by_name(tenant_id, body.connector_name)
    if existing:
        raise HTTPException(status_code=409, detail=f"Connector '{body.connector_name}' already exists")

    user_id = get_effective_user_id()
    result = await repo.create(
        tenant_id=tenant_id,
        connector_name=body.connector_name,
        url=body.url,
        method=body.method.upper(),
        created_by=user_id,
        display_name=body.display_name,
        description=body.description,
        headers=body.headers,
        auth_type=body.auth_type,
        auth_token_env=body.auth_token_env,
        auth_header=body.auth_header,
        timeout_seconds=body.timeout_seconds,
        max_response_bytes=body.max_response_bytes,
        max_retries=body.max_retries,
        retry_on_status=body.retry_on_status,
        cache_ttl_seconds=body.cache_ttl_seconds,
        enabled=body.enabled,
    )
    return result


@router.get("", summary="List Tenant HTTP Connectors")
async def list_connectors(tenant_id: str, request: Request):
    _require_tenant_admin(request, tenant_id)
    repo = _get_repo(request)
    connectors = await repo.list_by_tenant(tenant_id, include_disabled=True)
    return {"connectors": connectors, "count": len(connectors)}


@router.get("/{connector_name}", summary="Get Tenant HTTP Connector")
async def get_connector(tenant_id: str, connector_name: str, request: Request):
    _require_tenant_admin(request, tenant_id)
    repo = _get_repo(request)
    connector = await repo.get_by_name(tenant_id, connector_name)
    if not connector:
        raise HTTPException(status_code=404, detail=f"Connector '{connector_name}' not found")
    return connector


@router.put("/{connector_name}", summary="Update Tenant HTTP Connector")
async def update_connector(tenant_id: str, connector_name: str, body: ConnectorUpdateRequest, request: Request):
    _require_tenant_admin(request, tenant_id)
    _validate_connector_fields(body.method, body.auth_type)

    repo = _get_repo(request)
    existing = await repo.get_by_name(tenant_id, connector_name)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Connector '{connector_name}' not found")

    fields = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    if "method" in fields:
        fields["method"] = fields["method"].upper()
    if not fields:
        return existing

    result = await repo.update(tenant_id, connector_name, **fields)
    return result


@router.delete("/{connector_name}", summary="Delete Tenant HTTP Connector")
async def delete_connector(tenant_id: str, connector_name: str, request: Request):
    _require_tenant_admin(request, tenant_id)
    repo = _get_repo(request)
    deleted = await repo.delete(tenant_id, connector_name)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Connector '{connector_name}' not found")
    return {"deleted": True}


@router.put("/{connector_name}/enabled", summary="Enable/Disable Tenant HTTP Connector")
async def set_connector_enabled(tenant_id: str, connector_name: str, body: EnableRequest, request: Request):
    _require_tenant_admin(request, tenant_id)
    repo = _get_repo(request)
    result = await repo.set_enabled(tenant_id, connector_name, body.enabled)
    if not result:
        raise HTTPException(status_code=404, detail=f"Connector '{connector_name}' not found")
    return result
