"""Tests for MachineServiceClient with mocked RpcClient."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from deerflow.config.rpc_config import load_rpc_config_from_dict
from deerflow.rpc.machine_service import MachineServiceClient


@pytest.fixture(autouse=True)
def setup_rpc_config():
    load_rpc_config_from_dict({
        "default_timeout": 30.0,
        "services": [
            {"name": "ins-bus-rpc", "base_url": "http://localhost:8080"},
        ],
    })
    yield
    load_rpc_config_from_dict(None)


class TestMachineServiceClient:
    def test_get_machine_info_by_ids(self):
        client = MachineServiceClient()
        mock_raw = AsyncMock()
        mock_raw.return_value = {"code": 200, "message": "success", "data": [{"id": 1, "name": "pump-01"}]}

        with patch.object(client._rpc, "call_raw", mock_raw):
            result = asyncio.run(client.get_machine_info_by_ids([1, 2, 3]))
            assert result == [{"id": 1, "name": "pump-01"}]
            call_args = mock_raw.call_args
            assert call_args.args[0] == "ins-bus-rpc"
            assert call_args.args[1] == "/ins-bus-rpc/machineModel/getMachineInfoByIds"
            assert call_args.args[2] == "GET"
            assert call_args.args[3]["machineIds"] == "1,2,3"

    def test_get_devices_ids_by_mac_ids(self):
        client = MachineServiceClient()
        mock_raw = AsyncMock()
        mock_raw.return_value = {"code": 200, "message": "success", "data": {1: ["dev-1", "dev-2"]}}

        with patch.object(client._rpc, "call_raw", mock_raw):
            result = asyncio.run(client.get_devices_ids_by_mac_ids([100, 200]))
            assert result == {1: ["dev-1", "dev-2"]}
            assert mock_raw.call_args.args[3]["macIds"] == "100,200"

    def test_get_all_machine_id_by_type_with_type(self):
        client = MachineServiceClient()
        mock_raw = AsyncMock()
        mock_raw.return_value = {"code": 200, "message": "success", "data": [1, 2, 3]}

        with patch.object(client._rpc, "call_raw", mock_raw):
            result = asyncio.run(client.get_all_machine_id_by_type(1))
            assert result == [1, 2, 3]
            assert mock_raw.call_args.args[3]["machineType"] == 1

    def test_get_all_machine_id_by_type_without_type(self):
        client = MachineServiceClient()
        mock_raw = AsyncMock()
        mock_raw.return_value = {"code": 200, "message": "success", "data": [1, 2, 3, 4]}

        with patch.object(client._rpc, "call_raw", mock_raw):
            result = asyncio.run(client.get_all_machine_id_by_type())
            assert result == [1, 2, 3, 4]
            assert "machineType" not in mock_raw.call_args.args[3]

    def test_get_machine_detail_info(self):
        client = MachineServiceClient()
        mock_raw = AsyncMock()
        mock_raw.return_value = {"code": 0, "msg": "success", "data": {"total": 100, "rows": []}}

        with patch.object(client._rpc, "call_raw", mock_raw):
            result = asyncio.run(client.get_machine_detail_info(
                user_id=1, org_id=10, machine_name="pump", current_page=1, page_size=20,
            ))
            assert result == {"total": 100, "rows": []}
            params = mock_raw.call_args.args[3]
            assert params["userId"] == 1
            assert params["orgId"] == 10
            assert params["machineName"] == "pump"
            assert params["pageSize"] == 20

    def test_empty_result_unwrap(self):
        client = MachineServiceClient()
        mock_raw = AsyncMock()
        mock_raw.return_value = None

        with patch.object(client._rpc, "call_raw", mock_raw):
            result = asyncio.run(client.get_machine_info_by_ids([99]))
            assert result is None

    def test_get_component_info_by_machine_id(self):
        client = MachineServiceClient()
        mock_raw = AsyncMock()
        mock_raw.return_value = {
            "code": 0, "msg": "success",
            "data": [{"id": 101, "type": 80, "name": "测点-A", "machineId": 12345}],
        }

        with patch.object(client._rpc, "call_raw", mock_raw):
            result = asyncio.run(client.get_component_info_by_machine_id(12345))
            assert result == [{"id": 101, "type": 80, "name": "测点-A", "machineId": 12345}]
            call_args = mock_raw.call_args
            assert call_args.args[0] == "ins-bus-rpc"
            assert call_args.args[1] == "/ins-bus-rpc/machineModel/getComponentInfoByMachineId"
            assert call_args.args[2] == "GET"
            assert call_args.args[3]["machineId"] == 12345
            assert "hiddenIfValid" not in call_args.args[3]

    def test_get_component_info_by_machine_id_with_hidden(self):
        client = MachineServiceClient()
        mock_raw = AsyncMock()
        mock_raw.return_value = {"code": 0, "msg": "success", "data": []}

        with patch.object(client._rpc, "call_raw", mock_raw):
            result = asyncio.run(client.get_component_info_by_machine_id(12345, hidden_if_valid=True))
            assert result == []
            assert mock_raw.call_args.args[3]["hiddenIfValid"] is True

    def test_get_component_info_by_machine_id_empty(self):
        client = MachineServiceClient()
        mock_raw = AsyncMock()
        mock_raw.return_value = {"code": 0, "msg": "success", "data": []}

        with patch.object(client._rpc, "call_raw", mock_raw):
            result = asyncio.run(client.get_component_info_by_machine_id(99999))
            assert result == []
