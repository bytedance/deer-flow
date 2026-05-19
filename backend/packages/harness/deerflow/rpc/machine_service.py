"""Python client for Java MachineService (设备服务) FeignClient.

Corresponds to com.ins.datainput.feign.ins.bus.MachineService.
"""

import logging
from typing import Any

from deerflow.rpc.rpc_client import RpcClient, get_rpc_client

logger = logging.getLogger(__name__)

SERVICE_NAME = "ins-bus-rpc"
PATH_PREFIX = "/ins-bus-rpc/machineModel"


class MachineServiceClient:
    """Python client for Java MachineService FeignClient.

    Usage:
        client = MachineServiceClient()
        machines = await client.get_machine_info_by_ids([1, 2, 3])
    """

    def __init__(self, rpc_client: RpcClient | None = None):
        self._rpc = rpc_client or get_rpc_client()
        if self._rpc is None:
            raise RuntimeError("RPC client is not configured")

    async def get_machine_info_by_ids(self, machine_ids: list[int]) -> list[dict]:
        """通过设备ID批量查询设备信息。

        Args:
            machine_ids: 设备ID列表。

        Returns:
            list[dict]: MachineInfo 列表。
        """
        result = await self._rpc.call_raw(
            SERVICE_NAME,
            f"{PATH_PREFIX}/getMachineInfoByIds",
            "GET",
            {"machineIds": ",".join(str(i) for i in machine_ids)},
        )
        return self._unwrap_result(result)

    async def get_devices_ids_by_mac_ids(self, mac_ids: list[int]) -> dict[int, list[str]]:
        """通过macId获取设备id。

        Args:
            mac_ids: MAC ID 列表。

        Returns:
            dict: {macId: [deviceId, ...]}。
        """
        result = await self._rpc.call_raw(
            SERVICE_NAME,
            f"{PATH_PREFIX}/getDevicesIdsByMacIds",
            "GET",
            {"macIds": ",".join(str(i) for i in mac_ids)},
        )
        return self._unwrap_result(result)

    async def get_all_machine_id_by_type(self, machine_type: int | None = None) -> list[int]:
        """获取平台所有机组/机泵的id。

        Args:
            machine_type: 设备类型（1：机组 4：机泵，None = 查询全部设备）。

        Returns:
            list[int]: 设备ID列表。
        """
        params = {}
        if machine_type is not None:
            params["machineType"] = machine_type
        result = await self._rpc.call_raw(
            SERVICE_NAME,
            f"{PATH_PREFIX}/getAllMachineIdByType",
            "GET",
            params,
        )
        return self._unwrap_result(result)

    async def get_machine_detail_info(
        self,
        *,
        user_id: int,
        org_id: int,
        machine_name: str = "",
        device_name: str = "",
        no_page: int = 0,
        current_page: int = 1,
        page_size: int = 10,
        mac_status: str = "",
        alarm_status: str = "",
        type_id: str = "",
        producer: str = "",
    ) -> dict[str, Any]:
        """获取设备详细信息（分页）。

        Args:
            user_id: 用户ID。
            org_id: 组织ID。
            machine_name: 设备名称（模糊查询）。
            device_name: 装置名称（模糊查询）。
            no_page: 是否分页（0：分页 1：不分页）。
            current_page: 当前页码。
            page_size: 每页条数。
            mac_status: 设备状态。
            alarm_status: 报警状态。
            type_id: 设备类型ID。
            producer: 厂商。

        Returns:
            dict: 分页查询结果。
        """
        params = {
            "userId": user_id,
            "orgId": org_id,
            "machineName": machine_name,
            "deviceName": device_name,
            "noPage": no_page,
            "currentPage": current_page,
            "pageSize": page_size,
            "macStatus": mac_status,
            "alarmStatus": alarm_status,
            "typeId": type_id,
            "producer": producer,
        }
        result = await self._rpc.call_raw(
            SERVICE_NAME,
            f"{PATH_PREFIX}/getMachineDetailInfo",
            "GET",
            params,
        )
        return self._unwrap_ajax_result(result)

    async def get_component_info_by_machine_id(
        self,
        machine_id: int,
        hidden_if_valid: bool = False,
    ) -> list[dict]:
        """通过设备id获取部件信息。

        Args:
            machine_id: 设备ID。
            hidden_if_valid: 隐藏设置是否有效。

        Returns:
            list[dict]: ComponentInfo 列表。
        """
        params: dict = {"machineId": machine_id}
        if hidden_if_valid:
            params["hiddenIfValid"] = True
        result = await self._rpc.call_raw(
            SERVICE_NAME,
            f"{PATH_PREFIX}/getComponentInfoByMachineId",
            "GET",
            params,
        )
        return self._unwrap_ajax_result(result)

    @staticmethod
    def _unwrap_result(result: Any) -> Any:
        """Extract data from ResultT wrapper {code, message, data, success}."""
        if isinstance(result, dict):
            return result.get("data", result)
        return result

    @staticmethod
    def _unwrap_ajax_result(result: Any) -> Any:
        """Extract data from AjaxResult wrapper {code, msg, data}."""
        if isinstance(result, dict):
            return result.get("data", result)
        return result
