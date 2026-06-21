"""Component API router — proxies component context queries to ins-bus-rpc."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query, Request

from deerflow.rpc.machine_service import MachineServiceClient
from deerflow.rpc.organize_service import OrganizeServiceClient
from deerflow.rpc.point_service import PointServiceClient
from deerflow.tools.industrial_asset_tools import resolve_component_context_data

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/component", tags=["component"])

_machine_client: MachineServiceClient | None = None
_organize_client: OrganizeServiceClient | None = None
_point_client: PointServiceClient | None = None


def _get_machine_client() -> MachineServiceClient:
    global _machine_client
    if _machine_client is None:
        _machine_client = MachineServiceClient()
    return _machine_client


def _get_organize_client() -> OrganizeServiceClient:
    global _organize_client
    if _organize_client is None:
        _organize_client = OrganizeServiceClient()
    return _organize_client


def _get_point_client() -> PointServiceClient:
    global _point_client
    if _point_client is None:
        _point_client = PointServiceClient()
    return _point_client


def _resolve_access_token(request: Request) -> str | None:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        if token:
            return token
    cookie_token = request.cookies.get("access_token", "").strip()
    return cookie_token or None


@router.get("/info")
async def get_component_info(
    component_ids: str = Query(..., alias="componentIds", description="部件/子设备ID，多个以逗号分隔"),
) -> list:
    """通过 componentId 查询部件/子设备详情。"""
    try:
        ids = [item.strip() for item in component_ids.split(",") if item.strip()]
        if not ids:
            return []
        return await _get_machine_client().get_component_info_by_ids(ids)
    except Exception as e:
        logger.exception("Failed to fetch component info")
        raise HTTPException(status_code=502, detail=f"Component service unavailable: {e}")


@router.get("/path")
async def get_component_path(
    component_id: str = Query(..., alias="componentId", description="部件/子设备ID"),
) -> dict:
    """通过 componentId 查询设备到部件/子设备的路径。"""
    try:
        return await _get_organize_client().get_component_path(component_id)
    except Exception as e:
        logger.exception("Failed to fetch component path")
        raise HTTPException(status_code=502, detail=f"Organize service unavailable: {e}")


@router.get("/points")
async def get_component_points(
    component_ids: str = Query(..., alias="componentIds", description="部件/子设备ID，多个以逗号分隔"),
    include_children: bool = Query(True, alias="includeChildren", description="是否包含下级部件测点"),
    hidden_if_valid: bool = Query(False, alias="hiddenIfValid", description="隐藏设置是否有效"),
) -> dict:
    """通过 componentId 查询部件/子设备相关测点。"""
    try:
        ids = [item.strip() for item in component_ids.split(",") if item.strip()]
        if not ids:
            return {}
        client = _get_point_client()
        if include_children:
            return await client.get_point_info_under_component_ids(ids, hidden_if_valid=hidden_if_valid)
        return await client.get_point_info_by_component_ids(ids)
    except Exception as e:
        logger.exception("Failed to fetch component points")
        raise HTTPException(status_code=502, detail=f"Point service unavailable: {e}")


@router.get("/context")
async def get_component_context(
    request: Request,
    component_id: str | None = Query(None, alias="componentId", description="InS 部件/子设备ID"),
    equipment_id: str | None = Query(None, alias="equipmentId", description="EHM 平台设备ID"),
    include_points: bool = Query(True, alias="includePoints", description="是否包含测点"),
    include_children: bool = Query(True, alias="includeChildren", description="是否包含下级部件测点"),
    hidden_if_valid: bool = Query(False, alias="hiddenIfValid", description="隐藏设置是否有效"),
    max_points: int = Query(50, alias="maxPoints", ge=0, le=200, description="最多返回测点数量"),
) -> dict:
    """通过 componentId 或 EHM equipmentId 聚合设备、部件路径和测点上下文。"""
    try:
        return await resolve_component_context_data(
            component_id,
            equipment_id=equipment_id,
            access_token=_resolve_access_token(request),
            include_points=include_points,
            include_children=include_children,
            hidden_if_valid=hidden_if_valid,
            max_points=max_points,
        )
    except Exception as e:
        logger.exception("Failed to resolve component context")
        raise HTTPException(status_code=502, detail=f"Component context unavailable: {e}")
