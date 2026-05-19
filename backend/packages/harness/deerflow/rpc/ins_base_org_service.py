"""Python client for ins-base-rpc organization service.

Corresponds to ins-base-rpc /org endpoints.
"""

import logging
from typing import Any, TypedDict

from deerflow.rpc.rpc_client import RpcClient, get_rpc_client

logger = logging.getLogger(__name__)

SERVICE_NAME = "ins-base-rpc"
PATH_PREFIX = "/ins-base-rpc"


class OrgData(TypedDict, total=False):
    """组织数据结构"""
    orgId: int
    parentId: int
    orgName: str
    ancestors: str
    orgType: int
    orderNum: int
    remark: str
    guid: str
    id: int
    path: str
    syncSourceId: int
    authFlag: bool


class InsBaseOrgServiceClient:
    """Python client for ins-base-rpc organization endpoints.

    Usage:
        client = InsBaseOrgServiceClient()
        orgs = await client.get_all_parent_org(org_id=5)
    """

    def __init__(self, rpc_client: RpcClient | None = None):
        self._rpc = rpc_client or get_rpc_client()
        if self._rpc is None:
            raise RuntimeError("RPC client is not configured")

    async def get_all_parent_org(self, org_id: int) -> list[dict[str, Any]]:
        """获取指定组织的所有父组织。

        Args:
            org_id: 组织ID。

        Returns:
            list[dict]: 父组织列表，每个元素包含 orgId, parentId, orgName, orgType 等字段。
        """
        result = await self._rpc.call_raw(
            SERVICE_NAME,
            f"{PATH_PREFIX}/org/getAllParentOrg",
            "GET",
            {"orgId": org_id},
        )
        return self._unwrap_ajax_result(result)

    @staticmethod
    def _unwrap_ajax_result(result: Any) -> Any:
        """从 AjaxResult 包装 {code, msg, data} 中提取 data 字段。"""
        if isinstance(result, dict):
            return result.get("data", result)
        return result
