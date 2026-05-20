from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = REPO_ROOT / "skills" / "custom" / "data-analyst" / "scripts"
FEATURES_TOOL_ROOT = REPO_ROOT / "docker" / "sandbox" / "features-tool"

_SCRIPT_MODULES = (
    "query_daily",
    "query_weekly",
    "query_monthly",
    "daily_kpi",
    "weekly_kpi",
    "monthly_kpi",
    "export_report",
    "_data_providers",
    "_data_provider_impls",
    "_ins_provider",
    "_data_banner",
)


def clear_script_modules() -> None:
    for name in _SCRIPT_MODULES:
        sys.modules.pop(name, None)


def load_script(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, SCRIPT_DIR / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_features_ins() -> Any:
    root = str(FEATURES_TOOL_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
    import ins

    return ins


def configure_report_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    provider_mode: str | None = None,
    factory_id: str | None = None,
) -> None:
    monkeypatch.setenv("DAILY_REPORT_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("WEEKLY_REPORT_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("MONTHLY_REPORT_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("FEATURES_TOOL_ROOT", str(FEATURES_TOOL_ROOT))
    monkeypatch.delenv("DATA_PLATFORM_URL", raising=False)
    monkeypatch.delenv("DATA_API_URL", raising=False)
    if provider_mode is None:
        monkeypatch.delenv("DEER_FLOW_DATA_PROVIDER", raising=False)
    else:
        monkeypatch.setenv("DEER_FLOW_DATA_PROVIDER", provider_mode)
    if factory_id is None:
        monkeypatch.delenv("INS_FACTORY_ID", raising=False)
    else:
        monkeypatch.setenv("INS_FACTORY_ID", factory_id)


def load_ins_provider(monkeypatch: pytest.MonkeyPatch, *, factory_id: str | None = None) -> Any:
    if factory_id is None:
        monkeypatch.delenv("INS_FACTORY_ID", raising=False)
    else:
        monkeypatch.setenv("INS_FACTORY_ID", factory_id)
    load_script("_data_providers")
    return load_script("_ins_provider")


class FakeClient:
    def __init__(
        self,
        components: dict[str, list[dict[str, Any]]],
        trend_table: dict[tuple[str, str], Any],
        *,
        parse_raw_rows: bool = True,
    ) -> None:
        self._components = components
        self._trend_table = trend_table
        self._parse_raw_rows = parse_raw_rows
        self.trend_calls: list[dict[str, Any]] = []
        self.closed = False

    async def get_slim_components(self, equipment_id: str) -> list[dict[str, Any]]:
        rows = self._components.get(equipment_id, [])
        if isinstance(rows, Exception):
            raise rows
        return rows

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
        rows = self._trend_table.get((component_id, kwargs.get("endpoint_series")), [])
        if isinstance(rows, Exception):
            raise rows
        result = list(rows)
        if not self._parse_raw_rows:
            return result
        return load_features_ins().parse_trend_response(result, kwargs.get("endpoint_series", "8k"))

    async def close(self) -> None:
        self.closed = True


def patch_ins_provider(
    monkeypatch: pytest.MonkeyPatch,
    *,
    fake_client: FakeClient | None = None,
    features_available: bool = True,
    factory_id: str | None = None,
) -> Any:
    provider = load_ins_provider(monkeypatch, factory_id=factory_id)
    monkeypatch.setattr(provider, "_FEATURES_TOOL_AVAILABLE", features_available)
    monkeypatch.setattr(provider, "load_ins_settings", lambda: object())
    if fake_client is not None:
        monkeypatch.setattr(provider, "InsApiClient", lambda settings: fake_client)
    return provider


def machine_2k() -> list[dict[str, Any]]:
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
                }
            ],
        }
    ]


def machine_8k() -> list[dict[str, Any]]:
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
                }
            ],
        }
    ]


def machine_6k() -> list[dict[str, Any]]:
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
                }
            ],
        }
    ]


def machine_mixed() -> list[dict[str, Any]]:
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
                    "alarm_thresholds": {"v_rms": {"B": 1.0, "C": 2.0, "D": 4.0}},
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


def raw_rows_2k(*values: tuple[float, float], start_ms: int = 1700000000000) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, (v_rms, a_peak) in enumerate(values):
        rows.append(
            {
                "datatime": str(start_ms + index * 60_000),
                "value": [
                    {"name": "速度有效值", "value": str(v_rms)},
                    {"name": "加速度峰值", "value": str(a_peak)},
                ],
            }
        )
    return rows


def raw_rows_2k_velocity_only(values: list[float], start_ms: int = 1700000000000) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, v_rms in enumerate(values):
        rows.append(
            {
                "datatime": str(start_ms + index * 60_000),
                "value": [{"name": "速度有效值", "value": str(v_rms)}],
            }
        )
    return rows


def raw_rows_6k(*pairs: tuple[float | None, float], start_ms: int = 1700000000000) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, (corrosion_rate, thickness) in enumerate(pairs):
        rows.append(
            {
                "datatime": str(start_ms + index * 86_400_000),
                "value": [
                    {"key": "corrosionRate", "value": "" if corrosion_rate is None else str(corrosion_rate)},
                    {"key": "thickness", "value": str(thickness)},
                ],
            }
        )
    return rows


def raw_rows_8k_pressures(values: list[float], start_ms: int = 1700000000000) -> list[dict[str, Any]]:
    return [
        {
            "component_id": "P_8K_1",
            "time_ms": str(start_ms + index * 60_000),
            "time": "t",
            "values": {"pressure": value},
        }
        for index, value in enumerate(values)
    ]


def assert_fallback_note(notes: list[str], expected_fragment: str) -> None:
    assert notes
    assert expected_fragment in notes[0] or any(expected_fragment in note for note in notes)
