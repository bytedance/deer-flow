"""Python client for Java PointService (测点服务) FeignClient.

Corresponds to com.ins.datainput.feign.ins.bus.PointService.
"""

import logging
from typing import Any

from deerflow.rpc.rpc_client import RpcClient, get_rpc_client

logger = logging.getLogger(__name__)

SERVICE_NAME = "ins-bus-rpc"
PATH_PREFIX = "/ins-bus-rpc/pointModel"


class PointServiceClient:
    """Python client for Java PointService FeignClient.

    Usage:
        client = PointServiceClient()
        points = await client.get_point_list_by_machine_ids([1, 2, 3])
    """

    def __init__(self, rpc_client: RpcClient | None = None):
        self._rpc = rpc_client or get_rpc_client()
        if self._rpc is None:
            raise RuntimeError("RPC client is not configured")

    async def get_point_list_by_machine_ids(self, machine_ids: list[int]) -> list[dict]:
        """通过设备ID批量查询测点列表。

        Args:
            machine_ids: 设备ID列表。

        Returns:
            list[dict]: PointInfo 列表，每个对象包含：
                id, name, machineId, parentId, craftBit, type, moniType,
                iotDeviceId, iotChannelId, iotChannelType, iotDeviceCode,
                delFlag, displayOrder, shaftId, configInfo, conntype,
                machineName, lastUploadTime, componentName, sampleName,
                samplingPointName, corrosionFlag, syncSourceId.
        """
        result = await self._rpc.call_raw(
            SERVICE_NAME,
            f"{PATH_PREFIX}/getPointListByMachineIds",
            "GET",
            {"machineIds": ",".join(str(i) for i in machine_ids)},
        )
        return self._unwrap_ajax_result(result)

    async def get_point_info_by_component_ids(self, component_ids: list[int | str]) -> dict[str, list[dict]]:
        """获取多个部件/子设备直属测点信息。

        Args:
            component_ids: 部件/子设备ID列表。

        Returns:
            dict[str, list[dict]]: 以 componentId 分组的测点列表。
        """
        result = await self._rpc.call_raw(
            SERVICE_NAME,
            f"{PATH_PREFIX}/getPointInfoByComponentIds",
            "GET",
            {"componentIds": ",".join(str(i) for i in component_ids)},
        )
        data = self._unwrap_any_ajax_result(result)
        return data if isinstance(data, dict) else {}

    async def get_point_info_list_by_component_ids(self, component_ids: list[int | str]) -> list[dict]:
        """获取多个部件/子设备直属测点信息，返回扁平列表。"""
        result = await self._rpc.call_raw(
            SERVICE_NAME,
            f"{PATH_PREFIX}/getPointInfoListByComponentIds",
            "GET",
            {"componentIds": ",".join(str(i) for i in component_ids)},
        )
        data = self._unwrap_any_ajax_result(result)
        return data if isinstance(data, list) else []

    async def get_point_info_under_component_ids(
        self,
        component_ids: list[int | str],
        hidden_if_valid: bool = False,
    ) -> dict[str, list[dict]]:
        """获取部件/子设备及其下级部件下的测点信息。

        Args:
            component_ids: 部件/子设备ID列表。
            hidden_if_valid: 隐藏设置是否有效。

        Returns:
            dict[str, list[dict]]: 以原始 componentId 分组的测点列表。
        """
        params: dict[str, Any] = {"componentIds": ",".join(str(i) for i in component_ids)}
        if hidden_if_valid:
            params["hiddenIfValid"] = True
        result = await self._rpc.call_raw(
            SERVICE_NAME,
            f"{PATH_PREFIX}/getPointInfoUnderComponentIds",
            "GET",
            params,
        )
        data = self._unwrap_any_ajax_result(result)
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _unwrap_ajax_result(result) -> list[dict]:
        """Extract data from AjaxResult wrapper {code, msg, data}."""
        if isinstance(result, dict):
            data = result.get("data", result)
            return data if isinstance(data, list) else []
        return []

    @staticmethod
    def _unwrap_any_ajax_result(result: Any) -> Any:
        """Extract data from AjaxResult wrapper without forcing a concrete type."""
        if isinstance(result, dict):
            return result.get("data", result)
        return result
