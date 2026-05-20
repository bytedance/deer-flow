"""Smoke tests for the 9 multi-series wrapper tools.

Each get_trend_data_*k wrapper: mock InsApiClient.get_trend_data and assert
endpoint_series passthrough + output shape.

Each device_analysis_*k wrapper: feed a mixed-series component tree and assert
only the targeted series survives.

Each extract_trend_features_*k wrapper: assert it composes the trend pipeline
and produces the unified TrendAnalysisResult shape.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any
from unittest.mock import patch

import pytest

from tools import device_analysis_2k_tool as da_2k
from tools import device_analysis_6k_tool as da_6k
from tools import device_analysis_9k_tool as da_9k
from tools import extract_trend_features_2k_tool as ef_2k
from tools import extract_trend_features_6k_tool as ef_6k
from tools import extract_trend_features_9k_tool as ef_9k
from tools import get_trend_data_2k_tool as gtd_2k
from tools import get_trend_data_6k_tool as gtd_6k
from tools import get_trend_data_9k_tool as gtd_9k


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ---------- get_trend_data_*_tool ----------

def test_get_trend_data_2k_passes_series():
    captured: list[dict[str, Any]] = []

    async def fake_get_trend_data(component_id, start_ms, end_ms, features, **kwargs):
        captured.append({"component_id": component_id, **kwargs})
        return [
            {"datatime": "2025-01-01 00:00:00", "v_rms": 1.5, "a_peak": 2.5},
        ]

    with patch.object(gtd_2k.ins_client, "get_trend_data", side_effect=fake_get_trend_data):
        result = _run(
            gtd_2k._get_trend_data_impl(
                {"p1": ["v_rms", "a_peak"]}, "2025-01-01 00:00:00", "2025-01-02 00:00:00"
            )
        )
    assert all(call["endpoint_series"] == "2k" for call in captured)
    assert result["endpoint_series"] == "2k"
    assert "p1" in result["data"]
    assert result["data"]["p1"][0]["values"]["v_rms"] == 1.5


def test_get_trend_data_6k_default_features_when_empty():
    captured: list[dict[str, Any]] = []

    async def fake_get_trend_data(component_id, start_ms, end_ms, features, **kwargs):
        captured.append({"features": list(features), **kwargs})
        return [{"datatime": "2025-01-01 00:00:00", "corrosionRate": 0.1, "thickness": 12.3}]

    with patch.object(gtd_6k.ins_client, "get_trend_data", side_effect=fake_get_trend_data):
        result = _run(
            gtd_6k._get_trend_data_impl(
                {"p6k": []}, "2025-01-01 00:00:00", "2025-01-02 00:00:00"
            )
        )
    assert captured[0]["endpoint_series"] == "6k"
    assert captured[0]["features"] == ["corrosionRate", "thinningRate", "thickness", "temperature"]
    assert result["data"]["p6k"][0]["values"]["corrosionRate"] == 0.1


def test_get_trend_data_9k_passes_series():
    captured: list[dict[str, Any]] = []

    async def fake_get_trend_data(component_id, start_ms, end_ms, features, **kwargs):
        captured.append({**kwargs})
        # parse_trend_response_multi shape from 9k path
        return [
            {"component_id": "p9k", "time_ms": "1700000000000", "time": "t", "values": {"rms": 0.4}}
        ]

    with patch.object(gtd_9k.ins_client, "get_trend_data", side_effect=fake_get_trend_data):
        result = _run(
            gtd_9k._get_trend_data_impl(
                {"p9k": ["rms"]}, "2025-01-01 00:00:00", "2025-01-02 00:00:00"
            )
        )
    assert captured[0]["endpoint_series"] == "9k"
    assert result["endpoint_series"] == "9k"


# ---------- device_analysis_*_tool: mixed-series filtering ----------

_MIXED_SLIM_TREE = [
    {
        "id": "M1",
        "name": "P-3101A",
        "unit_type": 1,
        "type_num": 4,
        "points": [
            {"id": "p2k", "name": "泵前轴承", "unit_type": 3, "endpoint_series": "2k"},
            {"id": "p6k", "name": "出口_TH", "unit_type": 3, "endpoint_series": "6k"},
            {"id": "p8k", "name": "8k点", "unit_type": 3, "endpoint_series": "8k"},
            {"id": "p9k", "name": "9k点", "unit_type": 3, "endpoint_series": "9k"},
        ],
    }
]


def _patched_components(monkey_target):
    async def fake_get_slim_components(device_id):
        return _MIXED_SLIM_TREE

    monkey_target.INS_SETTINGS = replace(monkey_target.INS_SETTINGS, username="u", password="p")
    return patch.object(monkey_target.ins_client, "get_slim_components", side_effect=fake_get_slim_components)


def test_device_analysis_2k_filters_to_2k_points():
    with _patched_components(da_2k):
        result = _run(da_2k.get_device_children_2k("M1"))
    machines = result["child_device_list"]
    assert len(machines) == 1
    assert [p["id"] for p in machines[0]["points"]] == ["p2k"]


def test_device_analysis_6k_filters_to_6k_points():
    with _patched_components(da_6k):
        result = _run(da_6k.get_device_children_6k("M1"))
    assert [p["id"] for p in result["child_device_list"][0]["points"]] == ["p6k"]


def test_device_analysis_9k_filters_to_9k_points():
    with _patched_components(da_9k):
        result = _run(da_9k.get_device_children_9k("M1"))
    assert [p["id"] for p in result["child_device_list"][0]["points"]] == ["p9k"]


# ---------- extract_trend_features_*_tool: smoke ----------

def _fake_2k_rows():
    return [
        {"datatime": f"2025-01-01 00:{m:02d}:00", "v_rms": 1.0 + m * 0.01, "a_peak": 2.0 + m * 0.02}
        for m in range(20)
    ]


def _fake_6k_rows():
    return [
        {"datatime": f"2025-01-{1+d:02d} 00:00:00", "corrosionRate": 0.1 + d * 0.001, "thickness": 12.0 - d * 0.001}
        for d in range(20)
    ]


def _fake_9k_unified():
    return [
        {"component_id": "p9k", "time_ms": str(1700000000000 + i * 60000), "time": "t", "values": {"rms": 0.5 + i * 0.001}}
        for i in range(20)
    ]


def test_extract_trend_features_2k_runs_pipeline():
    async def fake(component_id, start_ms, end_ms, features, **kwargs):
        assert kwargs["endpoint_series"] == "2k"
        return _fake_2k_rows()

    with patch.object(gtd_2k.ins_client, "get_trend_data", side_effect=fake):
        result = _run(
            ef_2k.extract_trend_features_2k_tool(
                {"p2k": ["v_rms", "a_peak"]}, "2025-01-01 00:00:00", "2025-01-01 01:00:00"
            )
        )
    assert result["component_ids"] == ["p2k"]
    point = result["point_results"][0]
    assert "v_rms" in point["feature_stats"]
    assert "a_peak" in point["feature_stats"]


def test_extract_trend_features_6k_runs_pipeline():
    async def fake(component_id, start_ms, end_ms, features, **kwargs):
        assert kwargs["endpoint_series"] == "6k"
        return _fake_6k_rows()

    with patch.object(gtd_6k.ins_client, "get_trend_data", side_effect=fake):
        result = _run(
            ef_6k.extract_trend_features_6k_tool(
                {"p6k": ["corrosionRate", "thickness"]}, "2025-01-01 00:00:00", "2025-01-20 00:00:00"
            )
        )
    point = result["point_results"][0]
    assert "corrosionRate" in point["feature_stats"]
    assert "thickness" in point["feature_stats"]


def test_extract_trend_features_9k_runs_pipeline():
    async def fake(component_id, start_ms, end_ms, features, **kwargs):
        assert kwargs["endpoint_series"] == "9k"
        return _fake_9k_unified()

    with patch.object(gtd_9k.ins_client, "get_trend_data", side_effect=fake):
        result = _run(
            ef_9k.extract_trend_features_9k_tool(
                {"p9k": ["rms"]}, "2025-01-01 00:00:00", "2025-01-01 01:00:00"
            )
        )
    point = result["point_results"][0]
    assert "rms" in point["feature_stats"]
