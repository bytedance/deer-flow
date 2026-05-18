"""Python client for Java OrganizeService (组织服务) FeignClient.

Corresponds to ins-bus-rpc /organize endpoints.
"""

import logging
from typing import Any

from deerflow.rpc.rpc_client import RpcClient, get_rpc_client

logger = logging.getLogger(__name__)

SERVICE_NAME = "ins-bus-rpc"
PATH_PREFIX = "/ins-bus-rpc/organize"


class OrganizeServiceClient:
    """Python client for Java OrganizeService FeignClient.

    Usage:
        client = OrganizeServiceClient()
        tree = await client.get_org_tree_by_user_id_and_org_id(user_id=1, org_id=0, tree_type=1)
    """

    def __init__(self, rpc_client: RpcClient | None = None):
        self._rpc = rpc_client or get_rpc_client()
        if self._rpc is None:
            raise RuntimeError("RPC client is not configured")

    async def get_org_tree_by_user_id_and_org_id(
        self,
        user_id: int,
        org_id: int,
        tree_type: int,
        *,
        content: str | None = None,
        hidden_if_valid: bool | None = None,
        if_add_overview_count: bool | None = None,
        view_id: int | None = None,
        type_id: int | None = None,
    ) -> list[dict]:
        """获取用户权限下某一组织的结构树。

        Args:
            user_id: 用户id。
            org_id: 组织id。
            tree_type: 结构类型（0：结构树 1：设备树）。
            content: 搜索内容（可选）。
            hidden_if_valid: 隐藏设置是否有效（可选）。
            if_add_overview_count: 是否添加概览数量（可选）。
            view_id: 视图id（可选）。
            type_id: 设备类型（可选）。

        Returns:
            list[dict]: 组织树节点列表。
        """
        params: dict[str, Any] = {
            "userId": user_id,
            "orgId": org_id,
            "treeType": tree_type,
        }
        if content is not None:
            params["content"] = content
        if hidden_if_valid is not None:
            params["hiddenIfValid"] = hidden_if_valid
        if if_add_overview_count is not None:
            params["ifAddOverviewCount"] = if_add_overview_count
        if view_id is not None:
            params["viewId"] = view_id
        if type_id is not None:
            params["typeId"] = type_id

        result = await self._rpc.call_raw(
            SERVICE_NAME,
            f"{PATH_PREFIX}/getOrgTreeByUserIdAndOrgId",
            "GET",
            params,
        )
        return self._unwrap_ajax_result(result)

    @staticmethod
    def _unwrap_ajax_result(result: Any) -> Any:
        """Extract data from AjaxResult wrapper {code, msg, data}."""
        if isinstance(result, dict):
            return result.get("data", result)
        return result
