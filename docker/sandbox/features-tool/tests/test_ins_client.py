"""Unit tests for ins.client routing, slim_component, and parse_trend_response."""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

import pytest

from ins.client import (
    InsApiClient,
    parse_trend_response,
    slim_component,
)
from ins.config import InsSettings


def _settings() -> InsSettings:
    return InsSettings(
        base_url="https://example.invalid",
        username="u",
        password="p",
        rsa_public_key="-----BEGIN PUBLIC KEY-----\nAAAA\n-----END PUBLIC KEY-----\n",
    )


def _make_client() -> InsApiClient:
    client = InsApiClient(_settings())
    client.token = "fake-token"
    return client


def _ok_body(data: Any) -> dict[str, Any]:
    return {"code": 200, "msg": "ok", "data": data}


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ---------------- parse_trend_response ----------------

def test_parse_trend_response_2k_translates_chinese_names():
    rows = [
        {
            "datatime": "2025-01-01 00:00:00",
            "value": [
                {"name": "速度有效值", "unit": "mm/s", "value": "1.23"},
                {"name": "加速度峰值", "unit": "g", "value": "2.50"},
                {"name": "未知指标", "unit": "?", "value": "9.9"},
            ],
        }
    ]
    out = parse_trend_response(rows, "2k")
    assert len(out) == 1
    row = out[0]
    assert row["datatime"] == "2025-01-01 00:00:00"
    assert row["v_rms"] == 1.23
    assert row["a_peak"] == 2.5
    # unknown name preserved as key (no exception)
    assert row["未知指标"] == 9.9


def test_parse_trend_response_2k_empty_string_to_none():
    rows = [
        {
            "datatime": "t",
            "value": [{"name": "速度有效值", "unit": "", "value": ""}],
        }
    ]
    out = parse_trend_response(rows, "2k")
    assert out[0]["v_rms"] is None


def test_parse_trend_response_6k_flattens_by_key():
    rows = [
        {
            "datatime": "2025-01-01 00:00:00",
            "value": [
                {"key": "corrosionRate", "name": "腐蚀速率", "unit": "mm/y", "value": "0.12"},
                {"key": "thinningRate", "name": "减薄率", "unit": "mm/y", "value": "0.05"},
                {"key": "thickness", "name": "壁厚", "unit": "mm", "value": "12.34"},
                {"key": "temperature", "name": "温度", "unit": "C", "value": ""},
            ],
        }
    ]
    out = parse_trend_response(rows, "6k")
    assert out[0]["corrosionRate"] == 0.12
    assert out[0]["thinningRate"] == 0.05
    assert out[0]["thickness"] == 12.34
    assert out[0]["temperature"] is None


def test_parse_trend_response_8k_passes_through():
    rows = [{"datatime": "t", "pp_value": 1.0, "speed": 100.0}]
    out = parse_trend_response(rows, "8k")
    assert out == rows


def test_parse_trend_response_9k_passes_through():
    rows = [{"datatime": "t", "rms": 0.5}]
    out = parse_trend_response(rows, "9k")
    assert out == rows


def test_get_trend_data_unwraps_live_6k_envelope():
    """Live InS 6k responses nest sample rows inside data[0].value[]."""
    client = _make_client()
    body = _ok_body([
        {
            "posName": "弯头_TH",
            "positionType": 62,
            "gpid": "2309140102562780001",
            "value": [
                {
                    "datatime": 1779000700073,
                    "value": [
                        {"key": "corrosionRate", "value": "0.0"},
                        {"key": "thinningRate", "value": "0.0"},
                        {"key": "thickness", "value": "17.16"},
                        {"key": "temperature", "value": "166.77"},
                    ],
                },
                {
                    "datatime": 1779029593477,
                    "value": [
                        {"key": "corrosionRate", "value": "0.1"},
                        {"key": "thinningRate", "value": ""},
                        {"key": "thickness", "value": "17.14"},
                        {"key": "temperature", "value": "166.92"},
                    ],
                },
            ],
        }
    ])
    p, captured = _patch_get_json(client, body)
    with p:
        rows = _run(
            client.get_trend_data(
                "2309140102562780001",
                "0",
                "1",
                ["corrosionRate", "thinningRate", "thickness", "temperature"],
                endpoint_series="6k",
            )
        )
    assert len(rows) == 2
    assert rows[0]["corrosionRate"] == 0.0
    assert rows[0]["thickness"] == 17.16
    assert rows[1]["temperature"] == 166.92
    assert rows[1]["thinningRate"] is None


def test_parse_trend_response_skips_non_list_value():
    rows = [{"datatime": "t", "value": "scalar"}, {"datatime": "t2", "value": [{"key": "x", "value": "1"}]}]
    out = parse_trend_response(rows, "6k")
    assert len(out) == 1
    assert out[0]["x"] == 1.0


# ---------------- slim_component ----------------

def test_slim_component_2k_point_with_alarm_thresholds():
    node = {
        "id": "p2k",
        "name": "泵前轴承_A",
        "unitType": 3,
        "type": 23,
        "positionType": 23,
        "configInfo": {
            "vRmsBValue": 4.5,
            "vRmsCValue": 7.1,
            "vRmsDValue": 11.2,
            "aPeakBValue": 5.0,
            "aPeakCValue": 8.0,
            "aPeakDValue": 16.0,
            "kurtosisBValue": 3.5,
            "kurtosisCValue": 5.0,
            "kurtosisDValue": 8.0,
            "h_alarm": 7.1,
            "hh_alarm": 11.2,
        },
    }
    result = slim_component(node, parent_machine_type=4)
    assert result["endpoint_series"] == "2k"
    thresholds = result["alarm_thresholds"]
    assert thresholds["v_rms"] == {"B": 4.5, "C": 7.1, "D": 11.2}
    assert thresholds["a_peak"] == {"B": 5.0, "C": 8.0, "D": 16.0}
    assert thresholds["kurtosis"] == {"B": 3.5, "C": 5.0, "D": 8.0}


def test_slim_component_6k_point_via_position_type():
    node = {
        "id": "p6k",
        "name": "出口_TH",
        "unitType": 3,
        "positionType": 62,
        "configInfo": {},
    }
    result = slim_component(node, parent_machine_type=6)
    assert result["endpoint_series"] == "6k"
    assert "alarm_thresholds" not in result


def test_slim_component_8k_point_via_position_type():
    node = {
        "id": "p8k",
        "name": "轴承振动",
        "unitType": 3,
        "positionType": 83,
        "configInfo": {"h_alarm": 10.0, "hh_alarm": 15.0},
    }
    result = slim_component(node)
    assert result["endpoint_series"] == "8k"


def test_slim_component_9k_point_via_position_type():
    node = {
        "id": "p9k",
        "name": "轴瓦振动",
        "unitType": 3,
        "type": 9,
        "positionType": 93,
        "configInfo": {},
    }
    result = slim_component(node, parent_machine_type=9)
    assert result["endpoint_series"] == "9k"
    assert result["type_num"] == 9
    assert result["position_type"] == 93


def test_slim_component_machine_type_fallback_when_no_position_type():
    node = {
        "id": "px",
        "name": "未识别测点",
        "unitType": 3,
        "configInfo": {},
    }
    # parent machine is RC (9) → 9k fallback
    assert slim_component(node, parent_machine_type=9)["endpoint_series"] == "9k"
    # no parent → 8k catch-all
    assert slim_component(node, parent_machine_type=None)["endpoint_series"] == "8k"


def test_slim_component_machine_node_propagates_type_to_children():
    machine = {
        "id": "M1",
        "name": "P-3101A",
        "unitType": 1,
        "type": 4,  # PUMP
        "configInfo": {},
        "points": [
            {
                "id": "p1",
                "name": "泵前轴承_A",
                "unitType": 3,
                "configInfo": {},
            }
        ],
    }
    result = slim_component(machine)
    assert result["points"][0]["endpoint_series"] == "2k"


# ---------------- get_trend_data routing ----------------

def _patch_get_json(client: InsApiClient, body: dict[str, Any]):
    captured: dict[str, Any] = {}

    async def fake(path: str, params: dict[str, str]) -> dict[str, Any]:
        captured["path"] = path
        captured["params"] = params
        return body

    return patch.object(client, "_get_json", side_effect=fake), captured


def test_get_trend_data_routes_2k():
    client = _make_client()
    body = _ok_body([
        {"datatime": "t", "value": [{"name": "速度有效值", "value": "1.0"}]}
    ])
    p, captured = _patch_get_json(client, body)
    with p:
        rows = _run(
            client.get_trend_data("c1", "0", "1", ["v_rms"], endpoint_series="2k")
        )
    assert captured["path"] == "ins-os-view/data/getTrendDataHis"
    assert captured["params"]["density"] == "1"
    assert "factoryId" not in captured["params"]
    assert "includeFilter" not in captured["params"]
    assert rows[0]["v_rms"] == 1.0


def test_get_trend_data_routes_6k():
    client = _make_client()
    body = _ok_body([
        {"datatime": "t", "value": [{"key": "corrosionRate", "value": "0.1"}]}
    ])
    p, captured = _patch_get_json(client, body)
    with p:
        rows = _run(
            client.get_trend_data("c1", "0", "1", ["corrosionRate"], endpoint_series="6k")
        )
    assert captured["path"] == "ins-os-view/sg6kData/getTrendDataHis"
    assert captured["params"]["density"] == "1"
    assert rows[0]["corrosionRate"] == 0.1


def test_get_trend_data_routes_8k_default():
    client = _make_client()
    body = _ok_body([{"gpid": "c1", "trendData": [{"datatime": "1700000000000", "pp_value": 1.0}]}])
    p, captured = _patch_get_json(client, body)
    with p:
        rows = _run(client.get_trend_data("c1", "0", "1", ["pp_value"]))
    assert captured["path"] == "ins-os-view/sg8kData/getTrendDataHis"
    # 8k MUST preserve legacy params verbatim
    assert captured["params"]["density"] == "high"
    assert captured["params"]["includeFilter"] == "history,startstop,blackbox,alarm"
    assert captured["params"]["typeList"] == "pp_value"
    assert "factoryId" not in captured["params"]
    assert rows  # parse_trend_response_multi handled it


def test_get_trend_data_routes_9k_with_density_high():
    client = _make_client()
    body = _ok_body([{"gpid": "c1", "trendData": [{"datatime": "1700000000000", "rms": 0.5}]}])
    p, captured = _patch_get_json(client, body)
    with p:
        _run(client.get_trend_data("c1", "0", "1", ["rms"], endpoint_series="9k"))
    assert captured["path"] == "ins-os-view/sg9kData/getTrendDataHis"
    assert captured["params"]["density"] == "high"
    assert captured["params"]["includeFilter"] == "history"
    assert captured["params"]["typeList"] == "rms"


def test_get_trend_data_factory_id_passthrough():
    client = _make_client()
    body = _ok_body([])
    p, captured = _patch_get_json(client, body)
    with p:
        _run(
            client.get_trend_data(
                "c1", "0", "1", ["v_rms"], endpoint_series="2k", factory_id="F1"
            )
        )
    assert captured["params"]["factoryId"] == "F1"


def test_get_trend_data_factory_id_omitted_when_none():
    client = _make_client()
    body = _ok_body([])
    p, captured = _patch_get_json(client, body)
    with p:
        _run(client.get_trend_data("c1", "0", "1", ["v_rms"], endpoint_series="2k"))
    assert "factoryId" not in captured["params"]


def test_get_trend_data_invalid_series_raises():
    client = _make_client()
    with pytest.raises(ValueError):
        _run(client.get_trend_data("c1", "0", "1", [], endpoint_series="bogus"))
