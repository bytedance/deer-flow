"""Tests for OrganizeServiceClient with mocked RpcClient."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from deerflow.config.rpc_config import load_rpc_config_from_dict
from deerflow.rpc.organize_service import OrganizeServiceClient


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


class TestOrganizeServiceClient:
    def test_get_org_tree_basic(self):
        client = OrganizeServiceClient()
        mock_raw = AsyncMock()
        mock_raw.return_value = {
            "code": 200,
            "msg": "操作成功",
            "data": [
                {
                    "id": "1",
                    "label": "组织A",
                    "type": 10,
                    "path": "/组织A",
                    "parentId": "0",
                    "children": [
                        {"id": "2", "label": "设备1", "type": 4, "path": "/组织A/设备1", "parentId": "1"},
                    ],
                }
            ],
        }

        with patch.object(client._rpc, "call_raw", mock_raw):
            result = asyncio.run(client.get_org_tree_by_user_id_and_org_id(user_id=1, org_id=0, tree_type=1))
            assert len(result) == 1
            assert result[0]["label"] == "组织A"
            call_args = mock_raw.call_args
            assert call_args.args[0] == "ins-bus-rpc"
            assert call_args.args[1] == "/ins-bus-rpc/organize/getOrgTreeByUserIdAndOrgId"
            assert call_args.args[2] == "GET"
            assert call_args.args[3]["userId"] == 1
            assert call_args.args[3]["orgId"] == 0
            assert call_args.args[3]["treeType"] == 1

    def test_get_org_tree_with_optional_params(self):
        client = OrganizeServiceClient()
        mock_raw = AsyncMock()
        mock_raw.return_value = {"code": 200, "msg": "操作成功", "data": []}

        with patch.object(client._rpc, "call_raw", mock_raw):
            result = asyncio.run(client.get_org_tree_by_user_id_and_org_id(
                user_id=2,
                org_id=10,
                tree_type=0,
                content="搜索关键字",
                hidden_if_valid=True,
                if_add_overview_count=True,
                view_id=100,
                type_id=4,
            ))
            assert result == []
            params = mock_raw.call_args.args[3]
            assert params["userId"] == 2
            assert params["orgId"] == 10
            assert params["treeType"] == 0
            assert params["content"] == "搜索关键字"
            assert params["hiddenIfValid"] is True
            assert params["ifAddOverviewCount"] is True
            assert params["viewId"] == 100
            assert params["typeId"] == 4

    def test_get_org_tree_empty_response(self):
        client = OrganizeServiceClient()
        mock_raw = AsyncMock()
        mock_raw.return_value = {"code": 200, "msg": "操作成功", "data": []}

        with patch.object(client._rpc, "call_raw", mock_raw):
            result = asyncio.run(client.get_org_tree_by_user_id_and_org_id(user_id=1, org_id=0, tree_type=1))
            assert result == []

    def test_get_org_tree_raw_dict_response(self):
        """Fallback: if response is not a dict with data key, return raw value."""
        client = OrganizeServiceClient()
        mock_raw = AsyncMock()
        mock_raw.return_value = [{"id": "3", "label": "raw"}]

        with patch.object(client._rpc, "call_raw", mock_raw):
            result = asyncio.run(client.get_org_tree_by_user_id_and_org_id(user_id=1, org_id=0, tree_type=1))
            assert result == [{"id": "3", "label": "raw"}]

    def test_get_component_path(self):
        client = OrganizeServiceClient()
        mock_raw = AsyncMock()
        mock_raw.return_value = {"code": 0, "msg": "success", "data": {"path": "测试设备/测试子设备"}}

        with patch.object(client._rpc, "call_raw", mock_raw):
            result = asyncio.run(client.get_component_path("1781744317660112"))
            assert result == {"path": "测试设备/测试子设备"}
            call_args = mock_raw.call_args
            assert call_args.args[0] == "ins-bus-rpc"
            assert call_args.args[1] == "/ins-bus-rpc/organize/getComponentPath"
            assert call_args.args[2] == "GET"
            assert call_args.args[3]["componentId"] == "1781744317660112"
