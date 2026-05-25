"""Unit tests for ``skills/custom/data-analyst/scripts/_ins_provider.py``.

These cover the provider in isolation by mocking ``InsApiClient`` so the tests
do not require the docker sandbox, the features-tool source tree, or live InS
credentials. The provider module itself is loaded by file path because it
sits in the runtime sandbox skills tree, not on the package import path.

Coverage matches §1.8 of ``openspec/changes/wire-equipment-reports-real-data/tasks.md``:

- 2k KPI aggregation (after _TWO_K_NAME_KEY_MAP-style flattening).
- Rotating 8k KPI aggregation.
- 6k corrosion KPI aggregation, with ``None`` skipped (empty-string proxy).
- Mixed 2k + 6k + 8k KPI list issues 3 separate ``get_trend_data`` calls
  (one per ``(component_id, endpoint_series)`` bucket).
- 2k ``alarm_count`` for ``vibration_velocity_rms`` counts samples > C-tier
  (``vRmsCValue``), and switches to D-tier when the KPI is configured with
  ``alarm_tier="D"``.
- Unmappable KPI raises ``HttpProviderError`` with the offending key name.
- ``_FEATURES_TOOL_AVAILABLE=False`` raises ``HttpProviderError("features-tool not available...")``.
- ``INS_FACTORY_ID`` env set → ``factory_id=<value>`` is passed through to
  ``get_trend_data``.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PROVIDER_PATH = (
    REPO_ROOT
    / "skills"
    / "custom"
    / "data-analyst"
    / "scripts"
    / "_ins_provider.py"
)


# ---------------------------------------------------------------------------
# Module loader — fresh import per test so module-level env reads are honored
# ---------------------------------------------------------------------------


def _load_provider(monkeypatch: pytest.MonkeyPatch) -> Any:
    sys.modules.pop("_ins_provider", None)
    spec = importlib.util.spec_from_file_location("_ins_provider", PROVIDER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["_ins_provider"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def provider(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("INS_FACTORY_ID", raising=False)
    return _load_provider(monkeypatch)


# ---------------------------------------------------------------------------
# Slim component fixtures (mimic what InsApiClient.get_slim_components emits)
# ---------------------------------------------------------------------------


def _machine_2k() -> list[dict]:
    """Single 2k pump machine with one vibration point + alarm thresholds."""
    return [
        {
            "id": "M2K",
            "name": "P-3101A",
            "type_num": 4,
            "points": [
                {
                    "id": "P_2K_1",
                    "name": "泵前轴承_A",
                    "type_num": 23,
                    "endpoint_series": "2k",
                    "alarm_thresholds": {
                        "v_rms": {"B": 1.0, "C": 2.0, "D": 4.0},
                        "a_peak": {"B": 5.0, "C": 10.0, "D": 20.0},
                        "kurtosis": {"B": 3.0, "C": 4.5, "D": 6.0},
                    },
                },
            ],
        }
    ]


def _machine_8k() -> list[dict]:
    return [
        {
            "id": "M8K",
            "name": "C001",
            "type_num": 1,
            "points": [
                {
                    "id": "P_8K_1",
                    "name": "出口压力",
                    "type_num": 82,
                    "endpoint_series": "8k",
                    "h_alarm": 2.5,
                    "hh_alarm": 4.0,
                },
            ],
        }
    ]


def _machine_8k_bearing() -> list[dict]:
    return [
        {
            "id": "M8KBT",
            "name": "C001-bearing",
            "type_num": 1,
            "points": [
                {
                    "id": "P_8K_BT",
                    "name": "压缩机驱动端支撑轴承温度",
                    "type_num": 82,
                    "endpoint_series": "8k",
                    "h_alarm": 80.0,
                    "hh_alarm": 90.0,
                },
            ],
        }
    ]


def _machine_6k() -> list[dict]:
    return [
        {
            "id": "M6K",
            "name": "P-203A",
            "type_num": 6,
            "points": [
                {
                    "id": "P_6K_1",
                    "name": "出口_TH",
                    "type_num": 62,
                    "endpoint_series": "6k",
                },
            ],
        }
    ]


def _machine_mixed() -> list[dict]:
    """One device that hosts a 2k + a 6k + an 8k point (rare but possible)."""
    return [
        {
            "id": "MMIX",
            "name": "Mixed",
            "type_num": 1,
            "points": [
                {
                    "id": "PMX_2K",
                    "name": "泵前轴承",
                    "type_num": 23,
                    "endpoint_series": "2k",
                    "alarm_thresholds": {
                        "v_rms": {"B": 1.0, "C": 2.0, "D": 4.0},
                    },
                },
                {
                    "id": "PMX_6K",
                    "name": "出口_TH",
                    "type_num": 62,
                    "endpoint_series": "6k",
                },
                {
                    "id": "PMX_8K",
                    "name": "出口压力",
                    "type_num": 82,
                    "endpoint_series": "8k",
                    "h_alarm": 2.5,
                    "hh_alarm": 4.0,
                },
            ],
        }
    ]


# ---------------------------------------------------------------------------
# Fake InsApiClient — captures the calls and returns canned trend rows
# ---------------------------------------------------------------------------


class _FakeClient:
    def __init__(self, components: dict[str, list[dict]], trend_table: dict[tuple[str, str], list[dict]]):
        self._components = components
        self._trend_table = trend_table
        self.trend_calls: list[dict[str, Any]] = []
        self.machine_drops_calls: list[dict[str, Any]] = []
        self.closed = False
        # Per-machine drop events: dict[machine_id] → list[event_dict] or Exception
        self._machine_drops: dict[str, Any] = {}

    def set_machine_drops(self, events: dict[str, Any]) -> None:
        """Configure canned getMachineDrops responses keyed by machine_id."""
        self._machine_drops = events

    async def get_slim_components(self, equipment_id: str) -> list[dict]:
        return self._components.get(equipment_id, [])

    async def get_trend_data(self, component_id, start_ms, end_ms, features, **kwargs):
        self.trend_calls.append(
            {
                "component_id": component_id,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "features": list(features),
                "kwargs": dict(kwargs),
            }
        )
        return list(self._trend_table.get((component_id, kwargs.get("endpoint_series")), []))

    async def get_machine_drops(self, machine_id, start_ms, end_ms, event_types, endpoint_series="8k", factory_id=None):
        self.machine_drops_calls.append(
            {
                "machine_id": machine_id,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "event_types": list(event_types),
                "endpoint_series": endpoint_series,
                "factory_id": factory_id,
            }
        )
        result = self._machine_drops.get(machine_id, [])
        if isinstance(result, Exception):
            raise result
        return list(result)

    async def close(self) -> None:
        self.closed = True


def _patch_client(monkeypatch, provider, fake: _FakeClient) -> None:
    """Wire the provider's ``InsApiClient(...)`` constructor + ``load_ins_settings``
    so they hand back our fake without touching the env."""

    monkeypatch.setattr(provider, "_FEATURES_TOOL_AVAILABLE", True)
    monkeypatch.setattr(provider, "load_ins_settings", lambda: object())
    monkeypatch.setattr(provider, "InsApiClient", lambda settings: fake)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_2k_kpis_aggregate_to_expected_values(provider, monkeypatch):
    rows = [
        {"component_id": "P_2K_1", "time_ms": str(1700000000000 + i * 60_000), "time": "t",
         "values": {"v_rms": 1.0 + 0.5 * i, "a_peak": 8.0 + 0.5 * i}}
        for i in range(4)
    ]
    fake = _FakeClient(
        components={"M2K": _machine_2k()},
        trend_table={("P_2K_1", "2k"): rows},
    )
    _patch_client(monkeypatch, provider, fake)

    result = provider.fetch_daily_payload(
        date_str="2026-05-13",
        equipment_ids=["M2K"],
        kpi_keys=["vibration_velocity_rms", "vibration_acceleration_peak"],
    )

    # Expected values: mean of 1.0, 1.5, 2.0, 2.5 = 1.75; mean of 8.0..9.5 = 8.75
    assert result["kpis"]["vibration_velocity_rms"] == pytest.approx(1.75)
    assert result["kpis"]["vibration_acceleration_peak"] == pytest.approx(8.75)
    # One point, one bucket → exactly one trend call
    assert len(fake.trend_calls) == 1
    assert fake.trend_calls[0]["kwargs"]["endpoint_series"] == "2k"
    assert "v_rms" in fake.trend_calls[0]["features"]
    assert "a_peak" in fake.trend_calls[0]["features"]


def test_8k_rotating_kpis_aggregate_to_expected_values(provider, monkeypatch):
    rows = [
        {"component_id": "P_8K_1", "time_ms": str(1700000000000 + i * 60_000), "time": "t",
         "values": {"value": 1.0 + 0.25 * i}}
        for i in range(5)
    ]
    fake = _FakeClient(
        components={"M8K": _machine_8k()},
        trend_table={("P_8K_1", "8k"): rows},
    )
    _patch_client(monkeypatch, provider, fake)

    result = provider.fetch_daily_payload(
        date_str="2026-05-13",
        equipment_ids=["M8K"],
        kpi_keys=["outlet_pressure"],
    )

    # mean of 1.0, 1.25, 1.5, 1.75, 2.0 = 1.5
    assert result["kpis"]["outlet_pressure"] == pytest.approx(1.5)
    assert fake.trend_calls[0]["kwargs"]["endpoint_series"] == "8k"
    assert "value" in fake.trend_calls[0]["features"]


def test_8k_bearing_temp_uses_value_field_when_temperature_missing(provider, monkeypatch):
    rows = [
        {"component_id": "P_8K_BT", "time_ms": str(1700000000000 + i * 60_000), "time": "t",
         "values": {"value": v}}
        for i, v in enumerate([62.2, 62.0, 61.8, 62.4])
    ]
    fake = _FakeClient(
        components={"M8KBT": _machine_8k_bearing()},
        trend_table={("P_8K_BT", "8k"): rows},
    )
    _patch_client(monkeypatch, provider, fake)

    result = provider.fetch_daily_payload(
        date_str="2026-05-13",
        equipment_ids=["M8KBT"],
        kpi_keys=["bearing_temp"],
        eq_type="rotating_machinery",
    )

    assert result["kpis"]["bearing_temp"] == pytest.approx(0.621)
    requested = fake.trend_calls[0]["features"]
    assert "value" in requested
    assert "temperature" in requested


def test_6k_corrosion_kpis_skip_none_values(provider, monkeypatch):
    # Simulates parse_trend_response output for 6k with one empty/None reading
    # (proxy for what would be "" in raw response; client.py converts to None).
    rows = [
        {"component_id": "P_6K_1", "time_ms": "1700000000000", "time": "t",
         "values": {"corrosionRate": 0.10, "thickness": 12.0}},
        {"component_id": "P_6K_1", "time_ms": "1700086400000", "time": "t",
         "values": {"corrosionRate": None, "thickness": 11.9}},
        {"component_id": "P_6K_1", "time_ms": "1700172800000", "time": "t",
         "values": {"corrosionRate": 0.20, "thickness": 11.7}},
    ]
    fake = _FakeClient(
        components={"M6K": _machine_6k()},
        trend_table={("P_6K_1", "6k"): rows},
    )
    _patch_client(monkeypatch, provider, fake)

    result = provider.fetch_daily_payload(
        date_str="2026-05-13",
        equipment_ids=["M6K"],
        kpi_keys=["corrosion_rate", "thickness_loss"],
    )

    # mean skips None → mean(0.10, 0.20) = 0.15
    assert result["kpis"]["corrosion_rate"] == pytest.approx(0.15)
    # thickness_loss = first - last = 12.0 - 11.7 = 0.3
    assert result["kpis"]["thickness_loss"] == pytest.approx(0.3)


def test_mixed_kpi_list_issues_one_call_per_endpoint_series_bucket(provider, monkeypatch):
    rows_2k = [{"component_id": "PMX_2K", "time_ms": "1700000000000", "time": "t",
                "values": {"v_rms": 1.5}}]
    rows_6k = [{"component_id": "PMX_6K", "time_ms": "1700000000000", "time": "t",
                "values": {"corrosionRate": 0.1}}]
    rows_8k = [{"component_id": "PMX_8K", "time_ms": "1700000000000", "time": "t",
                "values": {"value": 2.0}}]
    fake = _FakeClient(
        components={"MMIX": _machine_mixed()},
        trend_table={
            ("PMX_2K", "2k"): rows_2k,
            ("PMX_6K", "6k"): rows_6k,
            ("PMX_8K", "8k"): rows_8k,
        },
    )
    _patch_client(monkeypatch, provider, fake)

    provider.fetch_daily_payload(
        date_str="2026-05-13",
        equipment_ids=["MMIX"],
        kpi_keys=["vibration_velocity_rms", "corrosion_rate", "outlet_pressure"],
    )

    series_per_call = sorted(call["kwargs"]["endpoint_series"] for call in fake.trend_calls)
    assert series_per_call == ["2k", "6k", "8k"]
    # Confirm one call per bucket (no duplication, no merging across series)
    assert len(fake.trend_calls) == 3


def test_2k_alarm_count_uses_c_tier_by_default(provider, monkeypatch):
    # vRmsCValue (C-tier) = 2.0 from _machine_2k()
    rows = [
        {"component_id": "P_2K_1", "time_ms": str(1700000000000 + i * 60_000), "time": "t",
         "values": {"v_rms": v}}
        for i, v in enumerate([1.0, 1.8, 2.0, 2.5, 3.5])
    ]
    fake = _FakeClient(
        components={"M2K": _machine_2k()},
        trend_table={("P_2K_1", "2k"): rows},
    )
    _patch_client(monkeypatch, provider, fake)

    # Override KPI map at runtime so vibration_velocity_rms uses alarm_count
    # against C-tier (default) — keeps the test self-contained.
    spec_c = dict(provider._KPI_FEATURE_MAP["vibration_velocity_rms"])
    spec_c["derivation"] = "alarm_count"
    monkeypatch.setitem(provider._KPI_FEATURE_MAP, "vibration_velocity_rms", spec_c)

    result = provider.fetch_daily_payload(
        date_str="2026-05-13",
        equipment_ids=["M2K"],
        kpi_keys=["vibration_velocity_rms"],
    )
    # Samples > 2.0: 2.5, 3.5 → count == 2
    assert result["kpis"]["vibration_velocity_rms"] == 2


def test_2k_alarm_count_d_tier_when_configured(provider, monkeypatch):
    # vRmsDValue = 4.0; samples chosen to make D-tier strictly fewer than C-tier
    rows = [
        {"component_id": "P_2K_1", "time_ms": str(1700000000000 + i * 60_000), "time": "t",
         "values": {"v_rms": v}}
        for i, v in enumerate([1.0, 1.8, 2.0, 2.5, 3.5, 5.0, 4.5])
    ]
    fake = _FakeClient(
        components={"M2K": _machine_2k()},
        trend_table={("P_2K_1", "2k"): rows},
    )
    _patch_client(monkeypatch, provider, fake)

    spec_d = dict(provider._KPI_FEATURE_MAP["vibration_velocity_rms"])
    spec_d["derivation"] = "alarm_count"
    spec_d["alarm_tier"] = "D"
    monkeypatch.setitem(provider._KPI_FEATURE_MAP, "vibration_velocity_rms", spec_d)

    result = provider.fetch_daily_payload(
        date_str="2026-05-13",
        equipment_ids=["M2K"],
        kpi_keys=["vibration_velocity_rms"],
    )
    # Samples > 4.0: 5.0, 4.5 → count == 2
    assert result["kpis"]["vibration_velocity_rms"] == 2


def test_unmappable_kpi_raises_http_provider_error(provider, monkeypatch):
    fake = _FakeClient(components={"M2K": _machine_2k()}, trend_table={})
    _patch_client(monkeypatch, provider, fake)

    with pytest.raises(provider.HttpProviderError) as excinfo:
        provider.fetch_daily_payload(
            date_str="2026-05-13",
            equipment_ids=["M2K"],
            kpi_keys=["totally_made_up_kpi_xyz"],
        )
    # The unmappable key name must appear in the error so logs are debuggable.
    assert "totally_made_up_kpi_xyz" in str(excinfo.value)


def test_features_tool_unavailable_raises(provider, monkeypatch):
    monkeypatch.setattr(provider, "_FEATURES_TOOL_AVAILABLE", False)
    monkeypatch.setattr(provider, "_FEATURES_TOOL_IMPORT_ERROR", "ModuleNotFoundError: ins")

    with pytest.raises(provider.HttpProviderError) as excinfo:
        provider.fetch_daily_payload(
            date_str="2026-05-13",
            equipment_ids=["M2K"],
            kpi_keys=["vibration_velocity_rms"],
        )
    msg = str(excinfo.value)
    assert "features-tool not available" in msg


def test_factory_id_env_threads_through_to_get_trend_data(monkeypatch):
    monkeypatch.setenv("INS_FACTORY_ID", "FACTORY_42")
    provider = _load_provider(monkeypatch)
    rows = [{"component_id": "P_8K_1", "time_ms": "1700000000000", "time": "t",
             "values": {"value": 2.0}}]
    fake = _FakeClient(
        components={"M8K": _machine_8k()},
        trend_table={("P_8K_1", "8k"): rows},
    )
    _patch_client(monkeypatch, provider, fake)

    provider.fetch_daily_payload(
        date_str="2026-05-13",
        equipment_ids=["M8K"],
        kpi_keys=["outlet_pressure"],
    )
    assert fake.trend_calls[0]["kwargs"].get("factory_id") == "FACTORY_42"


def test_factory_id_absent_when_env_unset(provider, monkeypatch):
    fake = _FakeClient(
        components={"M8K": _machine_8k()},
        trend_table={
            ("P_8K_1", "8k"): [{"component_id": "P_8K_1", "time_ms": "1700000000000", "time": "t",
                                "values": {"value": 2.0}}]
        },
    )
    _patch_client(monkeypatch, provider, fake)
    provider.fetch_daily_payload(
        date_str="2026-05-13",
        equipment_ids=["M8K"],
        kpi_keys=["outlet_pressure"],
    )
    assert "factory_id" not in fake.trend_calls[0]["kwargs"]


def test_close_clients_called(provider, monkeypatch):
    fake = _FakeClient(
        components={"M8K": _machine_8k()},
        trend_table={
            ("P_8K_1", "8k"): [{"component_id": "P_8K_1", "time_ms": "1700000000000", "time": "t",
                                "values": {"value": 2.0}}]
        },
    )
    _patch_client(monkeypatch, provider, fake)
    provider.fetch_daily_payload(
        date_str="2026-05-13",
        equipment_ids=["M8K"],
        kpi_keys=["outlet_pressure"],
    )
    assert fake.closed is True


def test_weekly_payload_shape_matches_daily(provider, monkeypatch):
    rows = [
        {"component_id": "P_8K_1", "time_ms": str(1700000000000 + i * 86_400_000), "time": "t",
         "values": {"value": 1.5 + 0.1 * i}}
        for i in range(7)
    ]
    fake = _FakeClient(
        components={"M8K": _machine_8k()},
        trend_table={("P_8K_1", "8k"): rows},
    )
    _patch_client(monkeypatch, provider, fake)

    result = provider.fetch_weekly_payload(
        week_start="2026-05-06",
        week_end="2026-05-12",
        equipment_ids=["M8K"],
        kpi_keys=["outlet_pressure"],
    )
    for required in ("kpis", "kpi_units", "hourly_runtime_rate", "alarms"):
        assert required in result
    assert isinstance(result["hourly_runtime_rate"], list)
    assert len(result["hourly_runtime_rate"]) == 24


def test_runtime_rate_derivation_from_speed(provider, monkeypatch):
    rows = [
        {"component_id": "P_8K_1", "time_ms": "1700000000000", "time": "t",
         "values": {"speed": s}}
        for s in [0.0, 100.0, 100.0, 100.0, 0.0]
    ]
    fake = _FakeClient(
        components={"M8K": _machine_8k()},
        trend_table={("P_8K_1", "8k"): rows},
    )
    _patch_client(monkeypatch, provider, fake)
    result = provider.fetch_daily_payload(
        date_str="2026-05-13",
        equipment_ids=["M8K"],
        kpi_keys=["runtime_rate"],
    )
    # 3 of 5 speed samples > 0 → 0.6
    assert result["kpis"]["runtime_rate"] == pytest.approx(0.6)


# ---------------------------------------------------------------------------
# Regression: _iter_points must yield nodes that ALREADY carry endpoint_series
# without descending into their children. A parent with endpoint_series set is
# a leaf point in the slim-component tree; descending would double-count.
# ---------------------------------------------------------------------------


def test_iter_points_yields_endpoint_series_node_and_skips_its_children(provider):
    """A node carrying ``endpoint_series`` is itself a measurement point and
    must be yielded as-is. Its ``children`` / ``points`` must NOT be visited
    (they belong to a different traversal layer)."""
    components = [
        {
            "id": "PARENT_AS_POINT",
            "endpoint_series": "8k",
            "type_num": 82,
            # If _iter_points wrongly recursed, this child would also yield.
            "children": [
                {"id": "DECOY_CHILD", "endpoint_series": "2k", "type_num": 23},
            ],
            "points": [
                {"id": "DECOY_POINT", "endpoint_series": "6k", "type_num": 62},
            ],
        }
    ]
    yielded = list(provider._iter_points(components))
    assert [n["id"] for n in yielded] == ["PARENT_AS_POINT"]


def test_iter_points_descends_into_children_when_endpoint_series_missing(provider):
    """When a node lacks ``endpoint_series``, _iter_points must walk into both
    ``children`` and ``points`` to find leaf points. Ordering is unspecified
    (stack-based), so compare as sets."""
    components = [
        {
            "id": "GROUP_A",
            "children": [
                {"id": "LEAF_1", "endpoint_series": "2k", "type_num": 23},
                {
                    "id": "GROUP_B",
                    "children": [
                        {"id": "LEAF_2", "endpoint_series": "6k", "type_num": 62},
                    ],
                },
            ],
            "points": [
                {"id": "LEAF_3", "endpoint_series": "8k", "type_num": 82},
            ],
        }
    ]
    yielded_ids = {n["id"] for n in provider._iter_points(components)}
    assert yielded_ids == {"LEAF_1", "LEAF_2", "LEAF_3"}


def test_iter_points_handles_non_dict_entries_gracefully(provider):
    """Non-dict entries in the input list or in ``children``/``points`` must be
    silently skipped instead of raising."""
    components = [
        None,  # ignored at top level
        "junk",  # ignored at top level
        {
            "id": "OK",
            "children": [None, {"id": "L1", "endpoint_series": "2k"}, "x"],
            "points": [{"id": "L2", "endpoint_series": "8k"}, 42],
        },
    ]
    yielded_ids = {n["id"] for n in provider._iter_points(components)}
    assert yielded_ids == {"L1", "L2"}


# ---------------------------------------------------------------------------
# 9k reciprocating-machine KPI regression — fixes the bug where
# vibration_level / runtime_rate / alarm_count / downtime_count silently
# returned None for any device whose points routed to the 9k endpoint
# (e.g. 循环氢压缩机 type_num=9, positionType 91..99). Root cause was
# expected_series being a hardcoded "8k" string in _KPI_FEATURE_MAP, while
# _select_points_for_kpi compared by strict equality.
# ---------------------------------------------------------------------------


def _machine_9k() -> list[dict]:
    """RC compressor (machineType=9, positionType 91..99) with a vibration point."""
    return [
        {
            "id": "M9K",
            "name": "循环氢压缩机1400-C-101",
            "type_num": 9,
            "points": [
                {
                    "id": "P_9K_1",
                    "name": "驱动端水平振动",
                    "type_num": 92,
                    "endpoint_series": "9k",
                    "h_alarm": 50.0,
                    "hh_alarm": 80.0,
                },
            ],
        }
    ]


def test_9k_vibration_level_aggregates(provider, monkeypatch):
    """vibration_level on a 9k RC device must aggregate, not return None.

    Regression: device 210623112850726 (循环氢压缩机1400-C-101) returned
    vibration_level=null even though data_source="ins" — because
    expected_series was the literal string "8k" and 9k points were filtered out.
    """
    rows = [
        {"component_id": "P_9K_1", "time_ms": str(1700000000000 + i * 60_000), "time": "t",
         "values": {"pp_value": v}}
        for i, v in enumerate([10.0, 12.0, 14.0, 16.0])
    ]
    fake = _FakeClient(
        components={"M9K": _machine_9k()},
        trend_table={("P_9K_1", "9k"): rows},
    )
    _patch_client(monkeypatch, provider, fake)

    result = provider.fetch_daily_payload(
        date_str="2026-05-13",
        equipment_ids=["M9K"],
        kpi_keys=["vibration_level"],
    )

    # mean of 10,12,14,16 = 13.0 — not None
    assert result["kpis"]["vibration_level"] == pytest.approx(13.0)
    # The endpoint call must use 9k, not 8k
    assert fake.trend_calls[0]["kwargs"]["endpoint_series"] == "9k"


def test_8k_and_9k_vibration_level_merge_across_series(provider, monkeypatch):
    """A device with both 8k and 9k vibration points must merge values from both."""
    components = {
        "MIX89": [
            {
                "id": "MIX89",
                "name": "Mixed-8k-9k",
                "type_num": 1,
                "points": [
                    {
                        "id": "P_8K_X",
                        "name": "驱动端振动",
                        "type_num": 82,
                        "endpoint_series": "8k",
                    },
                    {
                        "id": "P_9K_X",
                        "name": "驱动端振动",
                        "type_num": 92,
                        "endpoint_series": "9k",
                    },
                ],
            }
        ]
    }
    trend_table = {
        ("P_8K_X", "8k"): [
            {"component_id": "P_8K_X", "time_ms": "1700000000000", "time": "t",
             "values": {"pp_value": 10.0}},
        ],
        ("P_9K_X", "9k"): [
            {"component_id": "P_9K_X", "time_ms": "1700000000000", "time": "t",
             "values": {"pp_value": 20.0}},
        ],
    }
    fake = _FakeClient(components=components, trend_table=trend_table)
    _patch_client(monkeypatch, provider, fake)

    result = provider.fetch_daily_payload(
        date_str="2026-05-13",
        equipment_ids=["MIX89"],
        kpi_keys=["vibration_level"],
    )

    # Each point produces one mean (10.0 and 20.0 respectively).
    # The per-equipment reduce step averages them → 15.0.
    assert result["kpis"]["vibration_level"] == pytest.approx(15.0)
    series_calls = sorted(c["kwargs"]["endpoint_series"] for c in fake.trend_calls)
    assert series_calls == ["8k", "9k"]


def test_rotating_machinery_vibration_level_only_uses_8k(provider, monkeypatch):
    """Business split: rotating_machinery must narrow shared KPIs to 8k only."""
    components = {
        "MIX89": [
            {
                "id": "MIX89",
                "name": "Mixed-8k-9k",
                "type_num": 1,
                "points": [
                    {
                        "id": "P_8K_X",
                        "name": "驱动端振动",
                        "type_num": 82,
                        "endpoint_series": "8k",
                    },
                    {
                        "id": "P_9K_X",
                        "name": "驱动端振动",
                        "type_num": 92,
                        "endpoint_series": "9k",
                    },
                ],
            }
        ]
    }
    trend_table = {
        ("P_8K_X", "8k"): [
            {"component_id": "P_8K_X", "time_ms": "1700000000000", "time": "t",
             "values": {"pp_value": 10.0}},
        ],
        ("P_9K_X", "9k"): [
            {"component_id": "P_9K_X", "time_ms": "1700000000000", "time": "t",
             "values": {"pp_value": 20.0}},
        ],
    }
    fake = _FakeClient(components=components, trend_table=trend_table)
    _patch_client(monkeypatch, provider, fake)

    result = provider.fetch_daily_payload(
        date_str="2026-05-13",
        equipment_ids=["MIX89"],
        kpi_keys=["vibration_level"],
        eq_type="rotating_machinery",
    )

    assert result["kpis"]["vibration_level"] == pytest.approx(10.0)
    series_calls = [c["kwargs"]["endpoint_series"] for c in fake.trend_calls]
    assert series_calls == ["8k"]


def test_reciprocating_machinery_vibration_level_only_uses_9k(provider, monkeypatch):
    """Business split: reciprocating_machinery must narrow shared KPIs to 9k only."""
    components = {
        "MIX89": [
            {
                "id": "MIX89",
                "name": "Mixed-8k-9k",
                "type_num": 9,
                "points": [
                    {
                        "id": "P_8K_X",
                        "name": "驱动端振动",
                        "type_num": 82,
                        "endpoint_series": "8k",
                    },
                    {
                        "id": "P_9K_X",
                        "name": "驱动端振动",
                        "type_num": 92,
                        "endpoint_series": "9k",
                    },
                ],
            }
        ]
    }
    trend_table = {
        ("P_8K_X", "8k"): [
            {"component_id": "P_8K_X", "time_ms": "1700000000000", "time": "t",
             "values": {"pp_value": 10.0}},
        ],
        ("P_9K_X", "9k"): [
            {"component_id": "P_9K_X", "time_ms": "1700000000000", "time": "t",
             "values": {"pp_value": 20.0}},
        ],
    }
    fake = _FakeClient(components=components, trend_table=trend_table)
    _patch_client(monkeypatch, provider, fake)

    result = provider.fetch_daily_payload(
        date_str="2026-05-13",
        equipment_ids=["MIX89"],
        kpi_keys=["vibration_level"],
        eq_type="reciprocating_machinery",
    )

    assert result["kpis"]["vibration_level"] == pytest.approx(20.0)
    series_calls = [c["kwargs"]["endpoint_series"] for c in fake.trend_calls]
    assert series_calls == ["9k"]


def test_9k_runtime_rate_uses_9k_endpoint(provider, monkeypatch):
    """runtime_rate derives from ``speed`` and must also work on 9k devices."""
    rows = [
        {"component_id": "P_9K_1", "time_ms": str(1700000000000 + i * 60_000), "time": "t",
         "values": {"speed": v}}
        for i, v in enumerate([0.0, 1000.0, 1200.0, 0.0])
    ]
    fake = _FakeClient(
        components={"M9K": _machine_9k()},
        trend_table={("P_9K_1", "9k"): rows},
    )
    _patch_client(monkeypatch, provider, fake)

    result = provider.fetch_daily_payload(
        date_str="2026-05-13",
        equipment_ids=["M9K"],
        kpi_keys=["runtime_rate"],
    )

    # 2 of 4 samples have speed>0 → 0.5
    assert result["kpis"]["runtime_rate"] == pytest.approx(0.5)
    assert fake.trend_calls[0]["kwargs"]["endpoint_series"] == "9k"


# ---------------------------------------------------------------------------
# Machine drop events — _EVENT_TYPE_MAP, _fetch_machine_drops, graceful
# degradation, and report-scoped alarm injection.
# ---------------------------------------------------------------------------


def test_event_type_map_covers_all_18_types(provider):
    assert len(provider._EVENT_TYPE_MAP) == 18
    for t in range(1, 19):
        assert t in provider._EVENT_TYPE_MAP, f"type {t} missing from _EVENT_TYPE_MAP"
        label, level = provider._EVENT_TYPE_MAP[t]
        assert isinstance(label, str) and len(label) > 0
        assert level in {"high", "warning", "info"}


def test_event_type_map_critical_types_have_high_level(provider):
    # Main alarm (1) and deviation alarm (15) must be "high"
    assert provider._EVENT_TYPE_MAP[1][1] == "high"
    assert provider._EVENT_TYPE_MAP[15][1] == "high"


def test_event_type_map_warning_types_have_warning_level(provider):
    warning_types = [2, 6, 7, 8, 9, 10, 11, 12, 14]
    for t in warning_types:
        assert provider._EVENT_TYPE_MAP[t][1] == "warning", f"type {t} expected warning"


def test_event_types_8k_covers_1_to_18(provider):
    assert set(provider._EVENT_TYPES_8K) == set(range(1, 19))


def test_event_types_9k_is_restricted_subset(provider):
    assert set(provider._EVENT_TYPES_9K) == {1, 2, 3, 14, 15}


def test_event_series_for_eq_type_rotating(provider):
    assert provider._event_series_for_eq_type("rotating_machinery") == "8k"


def test_event_series_for_eq_type_reciprocating(provider):
    assert provider._event_series_for_eq_type("reciprocating_machinery") == "9k"


def test_event_series_for_eq_type_none_for_other(provider):
    assert provider._event_series_for_eq_type("pump") is None
    assert provider._event_series_for_eq_type("static_equipment") is None
    assert provider._event_series_for_eq_type("all") is None


def test_format_machine_drop_entry_maps_type_to_label_and_level(provider):
    entry = {
        "posId": "P001",
        "posName": "驱动端振动",
        "types": [1],
        "datatime": 1700000000000,
    }
    result = provider._format_machine_drop_entry(entry)
    assert result is not None
    assert result["level"] == "high"
    assert result["event_type"] == 1
    assert result["event_label"] == "主报警"
    assert "主报警" in result["message"]
    assert "驱动端振动" in result["message"]
    assert result["time"] is not None


def test_format_machine_drop_entry_uses_pos_id_fallback(provider):
    entry = {
        "posId": "P002",
        "types": [14],
        "datatime": 1700000000000,
    }
    result = provider._format_machine_drop_entry(entry)
    assert result is not None
    assert result["level"] == "warning"
    assert result["event_label"] == "预警"
    assert "P002" in result["message"]


def test_format_machine_drop_entry_returns_none_for_empty_types(provider):
    entry = {"posId": "P003", "posName": "x", "types": [], "datatime": 1700000000000}
    assert provider._format_machine_drop_entry(entry) is None


def test_rotating_machinery_report_includes_alarms(provider, monkeypatch):
    rows = [
        {"component_id": "P_8K_1", "time_ms": "1700000000000", "time": "t",
         "values": {"value": 2.0}}
    ]
    fake = _FakeClient(
        components={"M8K": _machine_8k()},
        trend_table={("P_8K_1", "8k"): rows},
    )
    fake.set_machine_drops({
        "M8K": [
            {
                "posId": "P_8K_1",
                "posName": "出口压力",
                "types": [1],
                "datatime": 1700000000000,
            },
            {
                "posId": "P_8K_1",
                "posName": "出口压力",
                "types": [14],
                "datatime": 1700000100000,
            },
        ],
    })
    _patch_client(monkeypatch, provider, fake)

    result = provider.fetch_daily_payload(
        date_str="2026-05-13",
        equipment_ids=["M8K"],
        kpi_keys=["outlet_pressure"],
        eq_type="rotating_machinery",
    )

    assert len(result["alarms"]) == 2
    assert result["alarms"][0]["level"] == "high"
    assert result["alarms"][0]["event_type"] == 1
    assert result["alarms"][1]["level"] == "warning"
    assert result["alarms"][1]["event_type"] == 14
    # Verify machine_drops was called with correct params
    assert len(fake.machine_drops_calls) == 1
    assert fake.machine_drops_calls[0]["endpoint_series"] == "8k"
    assert fake.machine_drops_calls[0]["machine_id"] == "M8K"


def test_reciprocating_machinery_report_includes_alarms(provider, monkeypatch):
    rows = [
        {"component_id": "P_9K_1", "time_ms": "1700000000000", "time": "t",
         "values": {"pp_value": 15.0}}
    ]
    fake = _FakeClient(
        components={"M9K": _machine_9k()},
        trend_table={("P_9K_1", "9k"): rows},
    )
    fake.set_machine_drops({
        "M9K": [
            {
                "posId": "P_9K_1",
                "posName": "驱动端水平振动",
                "types": [3],
                "datatime": 1700000000000,
            },
        ],
    })
    _patch_client(monkeypatch, provider, fake)

    result = provider.fetch_daily_payload(
        date_str="2026-05-13",
        equipment_ids=["M9K"],
        kpi_keys=["vibration_level"],
        eq_type="reciprocating_machinery",
    )

    assert len(result["alarms"]) == 1
    assert result["alarms"][0]["event_type"] == 3
    assert result["alarms"][0]["event_label"] == "启停机"
    assert fake.machine_drops_calls[0]["endpoint_series"] == "9k"
    # 9K only requests event types 1,2,3,14,15
    assert set(fake.machine_drops_calls[0]["event_types"]) == {1, 2, 3, 14, 15}


def test_pump_report_has_empty_alarms(provider, monkeypatch):
    rows = [
        {"component_id": "P_2K_1", "time_ms": "1700000000000", "time": "t",
         "values": {"v_rms": 1.5}}
    ]
    fake = _FakeClient(
        components={"M2K": _machine_2k()},
        trend_table={("P_2K_1", "2k"): rows},
    )
    _patch_client(monkeypatch, provider, fake)

    result = provider.fetch_daily_payload(
        date_str="2026-05-13",
        equipment_ids=["M2K"],
        kpi_keys=["vibration_velocity_rms"],
        eq_type="pump",
    )

    assert result["alarms"] == []
    assert len(fake.machine_drops_calls) == 0


def test_machine_drops_failure_degrades_gracefully(provider, monkeypatch):
    rows = [
        {"component_id": "P_8K_1", "time_ms": "1700000000000", "time": "t",
         "values": {"value": 2.0}}
    ]
    fake = _FakeClient(
        components={"M8K": _machine_8k()},
        trend_table={("P_8K_1", "8k"): rows},
    )
    fake.set_machine_drops({"M8K": RuntimeError("InS timeout")})
    _patch_client(monkeypatch, provider, fake)

    # Should NOT raise — event fetch failure is swallowed
    result = provider.fetch_daily_payload(
        date_str="2026-05-13",
        equipment_ids=["M8K"],
        kpi_keys=["outlet_pressure"],
        eq_type="rotating_machinery",
    )

    # KPI data is still returned
    assert result["kpis"]["outlet_pressure"] == pytest.approx(2.0)
    # Alarms degrade to empty list
    assert result["alarms"] == []


def test_daily_series_payload_scopes_events_per_day(provider, monkeypatch):
    components = {"M8K": _machine_8k()}
    # 3 days of trend data
    trend = {
        ("P_8K_1", "8k"): [
            {"component_id": "P_8K_1", "time_ms": str(1700000000000 + d * 86_400_000), "time": "t",
             "values": {"value": 2.0 + d * 0.1}}
            for d in range(3)
        ],
    }
    fake = _FakeClient(components=components, trend_table=trend)
    # Day 1 has events, day 2 has none, day 3 has events
    fake.set_machine_drops({
        "M8K": [
            {"posId": "P_8K_1", "posName": "出口压力", "types": [1], "datatime": 1700000000000},
            {"posId": "P_8K_1", "posName": "出口压力", "types": [2], "datatime": 1700086400000},
        ],
    })
    _patch_client(monkeypatch, provider, fake)

    result = provider.fetch_daily_series_payload(
        start_date="2026-05-13",
        day_count=3,
        equipment_ids=["M8K"],
        kpi_keys=["outlet_pressure"],
        eq_type="rotating_machinery",
    )

    assert len(result) == 3
    # Each day calls get_machine_drops (3 calls)
    assert len(fake.machine_drops_calls) == 3
    # Check day-level scoping
    for call in fake.machine_drops_calls:
        assert call["machine_id"] == "M8K"
        assert call["endpoint_series"] == "8k"
