"""Python client for Java PointService (测点服务) FeignClient.

Corresponds to com.ins.datainput.feign.ins.bus.PointService.
"""

import logging

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

    @staticmethod
    def _unwrap_ajax_result(result) -> list[dict]:
        """Extract data from AjaxResult wrapper {code, msg, data}."""
        if isinstance(result, dict):
            data = result.get("data", result)
            return data if isinstance(data, list) else []
        return []
