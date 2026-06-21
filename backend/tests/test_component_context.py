"""Tests for component context aggregation used by defect workflow agents."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx

from deerflow.tools.industrial_asset_tools import resolve_component_context
from deerflow.tools.industrial_asset_tools import resolve_component_context_data
from deerflow.tools.industrial_asset_tools import resolve_machine_context


def _runtime(context: dict | None = None):
    return SimpleNamespace(context=context or {})


def test_resolve_component_context_aggregates_component_machine_path_and_points():
    with (
        patch("deerflow.tools.industrial_asset_tools.MachineServiceClient") as machine_cls,
        patch("deerflow.tools.industrial_asset_tools.OrganizeServiceClient") as organize_cls,
        patch("deerflow.tools.industrial_asset_tools.PointServiceClient") as point_cls,
    ):
        machine = machine_cls.return_value
        machine.get_component_info_by_ids = AsyncMock(return_value=[
            {
                "id": 1781744317660112,
                "name": "测试子设备",
                "machineId": 2067266200919998465,
                "craftBit": "COMP-01",
            }
        ])
        machine.get_machine_info_by_ids = AsyncMock(return_value=[
            {"id": 2067266200919998465, "name": "测试ehm设备01", "code": "TEST-E-01"}
        ])
        organize = organize_cls.return_value
        organize.get_component_path = AsyncMock(return_value={"path": "测试ehm设备01/测试子设备"})
        point = point_cls.return_value
        point.get_point_info_under_component_ids = AsyncMock(return_value={
            "1781744317660112": [{"id": 9001, "name": "振动测点"}]
        })

        payload = json.loads(resolve_component_context.func(
            runtime=_runtime(),
            component_id="1781744317660112",
            include_points=True,
            include_children=True,
        ))

    assert payload["status"] == "ok"
    assert payload["component_id"] == "1781744317660112"
    assert payload["machine_id"] == "2067266200919998465"
    assert payload["machine"]["name"] == "测试ehm设备01"
    assert payload["component_path"] == "测试ehm设备01/测试子设备"
    assert payload["points"][0]["name"] == "振动测点"
    assert "测试子设备" in payload["summary"]


def test_resolve_component_context_returns_not_found_when_component_missing():
    with patch("deerflow.tools.industrial_asset_tools.MachineServiceClient") as machine_cls:
        machine = machine_cls.return_value
        machine.get_component_info_by_ids = AsyncMock(return_value=[])

        payload = json.loads(resolve_component_context.func(
            component_id="missing-component",
            include_points=False,
        ))

    assert payload["status"] == "not_found"
    assert payload["component_id"] == "missing-component"


def test_resolve_component_context_uses_ehm_equipment_source_data_id(monkeypatch):
    calls: list[dict] = []

    class FakeAsyncClient:
        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url, **kwargs):
            calls.append({"url": url, **kwargs})
            return httpx.Response(
                200,
                json={
                    "equipmentId": "1781744317660112",
                    "name": "EHM设备",
                    "sourceDataId": "903277040369664000",
                },
                request=httpx.Request("GET", url),
            )

    monkeypatch.setenv("EHM_SERVER_BASE_URL", "http://ehm.local/ehm-server")
    monkeypatch.setattr("deerflow.tools.industrial_asset_tools.httpx.AsyncClient", FakeAsyncClient)

    with (
        patch("deerflow.tools.industrial_asset_tools.MachineServiceClient") as machine_cls,
        patch("deerflow.tools.industrial_asset_tools.OrganizeServiceClient") as organize_cls,
        patch("deerflow.tools.industrial_asset_tools.PointServiceClient") as point_cls,
    ):
        machine = machine_cls.return_value
        machine.get_component_info_by_ids = AsyncMock(return_value=[
            {"id": "903277040369664000", "name": "测试压缩机", "machineId": "260617151001913"}
        ])
        machine.get_machine_info_by_ids = AsyncMock(return_value=[
            {"id": "260617151001913", "name": "测试机泵"}
        ])
        organize_cls.return_value.get_component_path = AsyncMock(return_value={"path": "测试机泵/测试压缩机"})
        point_cls.return_value.get_point_info_under_component_ids = AsyncMock(return_value={})

        payload = asyncio.run(
            resolve_component_context_data(
                "",
                equipment_id="1781744317660112",
                access_token="user-token",
                include_points=False,
            )
        )

    assert payload["status"] == "ok"
    assert payload["equipment_id"] == "1781744317660112"
    assert payload["component_id"] == "903277040369664000"
    assert payload["machine_id"] == "260617151001913"
    assert calls[0]["url"] == "http://ehm.local/ehm-server/api/v1/equipments/1781744317660112"
    assert calls[0]["headers"]["Authorization"] == "Bearer user-token"


def test_resolve_machine_context_aggregates_machine_components_and_points():
    with (
        patch("deerflow.tools.industrial_asset_tools.MachineServiceClient") as machine_cls,
        patch("deerflow.tools.industrial_asset_tools.PointServiceClient") as point_cls,
    ):
        machine = machine_cls.return_value
        machine.get_machine_info_by_ids = AsyncMock(return_value=[
            {
                "id": 260617151001913,
                "name": "测试机泵",
                "machineCode": "M-001",
                "typeId": 4,
            }
        ])
        machine.get_component_info_by_machine_id = AsyncMock(return_value=[
            {"id": 903277040369664000, "name": "测试压缩机", "machineId": 260617151001913}
        ])
        point = point_cls.return_value
        point.get_point_list_by_machine_ids = AsyncMock(return_value=[
            {"id": 1001, "name": "测试压缩机_SX", "machineId": 260617151001913, "type": 23},
            {"id": 1002, "name": "测试压缩机_SY", "machineId": 260617151001913, "type": 24},
        ])

        payload = json.loads(resolve_machine_context.func(
            machine_id="260617151001913",
            include_components=True,
            include_points=True,
            max_components=10,
            max_points=1,
        ))

    assert payload["status"] == "ok"
    assert payload["machine_id"] == "260617151001913"
    assert payload["machine"]["name"] == "测试机泵"
    assert payload["component_count"] == 1
    assert payload["components"][0]["name"] == "测试压缩机"
    assert payload["point_count"] == 2
    assert payload["points_truncated"] is True
    assert payload["points"][0]["name"] == "测试压缩机_SX"
    assert "设备 测试机泵" in payload["summary"]


def test_resolve_machine_context_accepts_ehm_equipment_id(monkeypatch):
    calls: list[dict] = []

    class FakeAsyncClient:
        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url, **kwargs):
            calls.append({"url": url, **kwargs})
            return httpx.Response(
                200,
                json={"id": "2067266200919998465", "name": "测试ehm设备01", "sourceDataId": "903277040369664000"},
                request=httpx.Request("GET", url),
            )

    monkeypatch.setenv("EHM_SERVER_BASE_URL", "http://ehm.local/ehm-server")
    monkeypatch.setattr("deerflow.tools.industrial_asset_tools.httpx.AsyncClient", FakeAsyncClient)

    with (
        patch("deerflow.tools.industrial_asset_tools.MachineServiceClient") as machine_cls,
        patch("deerflow.tools.industrial_asset_tools.OrganizeServiceClient") as organize_cls,
        patch("deerflow.tools.industrial_asset_tools.PointServiceClient") as point_cls,
    ):
        machine = machine_cls.return_value
        machine.get_component_info_by_ids = AsyncMock(return_value=[
            {"id": "903277040369664000", "name": "测试压缩机", "machineId": "260617151001913"}
        ])
        machine.get_machine_info_by_ids = AsyncMock(return_value=[
            {"id": "260617151001913", "name": "测试机泵"}
        ])
        machine.get_component_info_by_machine_id = AsyncMock(return_value=[
            {"id": "903277040369664000", "name": "测试压缩机", "machineId": "260617151001913"}
        ])
        organize_cls.return_value.get_component_path = AsyncMock(return_value={"path": "测试机泵/测试压缩机"})
        point_cls.return_value.get_point_list_by_machine_ids = AsyncMock(return_value=[
            {"id": 1001, "name": "测试压缩机_SX", "machineId": 260617151001913}
        ])

        payload = json.loads(resolve_machine_context.func(
            equipment_id="2067266200919998465",
            config={"context": {"access_token": "user-token"}},
        ))

    assert payload["status"] == "ok"
    assert payload["resolved_from"] == "equipment_id"
    assert payload["equipment_id"] == "2067266200919998465"
    assert payload["component_id"] == "903277040369664000"
    assert payload["machine_id"] == "260617151001913"
    assert payload["machine"]["name"] == "测试机泵"
    assert payload["component_count"] == 1
    assert payload["point_count"] == 1
    assert calls[0]["headers"]["Authorization"] == "Bearer user-token"


def test_resolve_machine_context_falls_back_when_machine_id_is_ehm_equipment_id(monkeypatch):
    class FakeAsyncClient:
        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url, **kwargs):
            return httpx.Response(
                200,
                json={"id": "2067266200919998465", "name": "测试ehm设备01", "sourceDataId": "903277040369664000"},
                request=httpx.Request("GET", url),
            )

    monkeypatch.setenv("EHM_SERVER_BASE_URL", "http://ehm.local/ehm-server")
    monkeypatch.setattr("deerflow.tools.industrial_asset_tools.httpx.AsyncClient", FakeAsyncClient)

    with (
        patch("deerflow.tools.industrial_asset_tools.MachineServiceClient") as machine_cls,
        patch("deerflow.tools.industrial_asset_tools.OrganizeServiceClient") as organize_cls,
        patch("deerflow.tools.industrial_asset_tools.PointServiceClient") as point_cls,
    ):
        machine = machine_cls.return_value
        machine.get_machine_info_by_ids = AsyncMock(side_effect=[
            [],
            [{"id": "260617151001913", "name": "测试机泵"}],
        ])
        machine.get_component_info_by_ids = AsyncMock(return_value=[
            {"id": "903277040369664000", "name": "测试压缩机", "machineId": "260617151001913"}
        ])
        machine.get_component_info_by_machine_id = AsyncMock(return_value=[])
        organize_cls.return_value.get_component_path = AsyncMock(return_value={"path": "测试机泵/测试压缩机"})
        point_cls.return_value.get_point_list_by_machine_ids = AsyncMock(return_value=[])

        payload = json.loads(resolve_machine_context.func(
            machine_id="2067266200919998465",
            config={"context": {"access_token": "user-token"}},
        ))

    assert payload["status"] == "ok"
    assert payload["resolved_from"] == "machine_id_fallback_equipment_id"
    assert payload["input_machine_id"] == "2067266200919998465"
    assert payload["equipment_id"] == "2067266200919998465"
    assert payload["component_id"] == "903277040369664000"
    assert payload["machine_id"] == "260617151001913"
