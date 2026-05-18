"""Organize tree API router — proxies organize tree queries to ins-bus-rpc."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query

from deerflow.rpc.organize_service import OrganizeServiceClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/organize", tags=["organize"])

_client: OrganizeServiceClient | None = None


def _get_client() -> OrganizeServiceClient:
    global _client
    if _client is None:
        _client = OrganizeServiceClient()
    return _client


@router.get("/tree")
async def get_org_tree(
    user_id: int = Query(1, alias="userId", description="用户id"),
    org_id: int = Query(0, alias="orgId", description="组织id"),
    tree_type: int = Query(1, alias="treeType", description="结构类型（0：结构树 1：设备树）"),
    content: str | None = Query(None, description="搜索内容"),
    hidden_if_valid: bool | None = Query(None, alias="hiddenIfValid", description="隐藏设置是否有效"),
    if_add_overview_count: bool | None = Query(None, alias="ifAddOverviewCount", description="是否添加概览数量"),
    view_id: int | None = Query(None, alias="viewId", description="视图id"),
    type_id: int | None = Query(None, alias="typeId", description="设备类型"),
) -> list:
    """获取用户权限下某一组织的结构树。

    Proxies to ins-bus-rpc /organize/getOrgTreeByUserIdAndOrgId.
    """
    try:
        client = _get_client()
        return await client.get_org_tree_by_user_id_and_org_id(
            user_id=user_id,
            org_id=org_id,
            tree_type=tree_type,
            content=content,
            hidden_if_valid=hidden_if_valid,
            if_add_overview_count=if_add_overview_count,
            view_id=view_id,
            type_id=type_id,
        )
    except Exception as e:
        logger.exception("Failed to fetch organize tree")
        raise HTTPException(status_code=502, detail=f"Organize service unavailable: {e}")
