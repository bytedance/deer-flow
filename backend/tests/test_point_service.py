"""Tests for PointServiceClient with mocked RpcClient."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from deerflow.config.rpc_config import load_rpc_config_from_dict
from deerflow.rpc.point_service import PointServiceClient


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


def test_get_point_info_under_component_ids():
    client = PointServiceClient()
    mock_raw = AsyncMock()
    mock_raw.return_value = {
        "code": 0,
        "msg": "success",
        "data": {
            "1781744317660112": [
                {"id": 9001, "name": "振动测点", "parentId": 1781744317660112},
            ],
        },
    }

    with patch.object(client._rpc, "call_raw", mock_raw):
        result = asyncio.run(
            client.get_point_info_under_component_ids(["1781744317660112"], hidden_if_valid=True)
        )
        assert result["1781744317660112"][0]["name"] == "振动测点"
        call_args = mock_raw.call_args
        assert call_args.args[0] == "ins-bus-rpc"
        assert call_args.args[1] == "/ins-bus-rpc/pointModel/getPointInfoUnderComponentIds"
        assert call_args.args[2] == "GET"
        assert call_args.args[3]["componentIds"] == "1781744317660112"
        assert call_args.args[3]["hiddenIfValid"] is True
