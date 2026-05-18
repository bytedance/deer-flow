"""Tests for skills/custom/data-analyst/scripts/query_diagnosis.py.

The script is loaded by file path because it lives in the runtime sandbox
skills tree, not on the package import path.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "skills" / "custom" / "data-analyst" / "scripts" / "query_diagnosis.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("query_diagnosis", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def query_diagnosis(tmp_path, monkeypatch):
    monkeypatch.setenv("DIAGNOSIS_OUTPUT_DIR", str(tmp_path))
    # Ensure InS toolchain is "absent" so build_result takes demo_fallback path
    monkeypatch.setenv("INS_SKILL_ROOT", str(tmp_path / "no_skills"))
    monkeypatch.setenv("FEATURES_TOOL_ROOT", str(tmp_path / "no_features"))
    return _load_module()


# --- Contract / shape ---


def test_demo_fallback_payload_contract(query_diagnosis):
    """Demo fallback must satisfy design doc §7.1 shape."""
    payload = query_diagnosis.build_result(
        kind="centrifugal_pump",
        equipment_ids=["PUMP-A-001"],
        start="2026-05-12T00:00:00",
        end="2026-05-13T00:00:00",
        mode="oneoff",
        compare="previous_period",
    )
    assert payload["kind"] == "centrifugal_pump"
    assert payload["equipment_ids"] == ["PUMP-A-001"]
    assert payload["data_source"] == "demo_fallback"
    assert payload["mode"] == "oneoff"
    assert payload["time_window"] == {"start": "2026-05-12T00:00:00", "end": "2026-05-13T00:00:00"}
    assert payload["compare_window"] is not None
    assert payload["compare"] is not None
    assert payload["points"], "demo block must have points"
    point = payload["points"][0]
    for key in ("equipment_id", "point_id", "point_name", "point_type", "default_features", "trend_summary"):
        assert key in point
    assert "anomaly_time_ms" in point["trend_summary"]
    assert "discharge_pressure" in payload["process_signals"]


def test_compare_none_yields_null_compare(query_diagnosis):
    payload = query_diagnosis.build_result(
        kind="centrifugal_pump",
        equipment_ids=["PUMP-A-001"],
        start="2026-05-12T00:00:00",
        end="2026-05-13T00:00:00",
        mode="oneoff",
        compare="none",
    )
    assert payload["compare"] is None
    assert payload["compare_window"] is None


def test_compare_previous_period_window_arithmetic(query_diagnosis):
    payload = query_diagnosis.build_result(
        kind="steam_turbine",
        equipment_ids=["ST-101"],
        start="2026-05-12T00:00:00",
        end="2026-05-13T00:00:00",
        mode="oneoff",
        compare="previous_period",
    )
    cw = payload["compare_window"]
    # Previous period mirrors the same span ending at the current start
    expected_prev_end = "2026-05-12T00:00:00"
    expected_prev_start = "2026-05-11T00:00:00"
    assert cw["end"] == expected_prev_end
    assert cw["start"] == expected_prev_start


def test_screening_mode_uses_reduced_feature_set(query_diagnosis):
    payload = query_diagnosis.build_result(
        kind="centrifugal_pump",
        equipment_ids=["PUMP-A-001"],
        start="2026-05-12T00:00:00",
        end="2026-05-13T00:00:00",
        mode="screening",
        compare="none",
    )
    feats = payload["points"][0]["default_features"]
    # Screening defaults to 3-feature set
    assert set(feats) == set(query_diagnosis.SCREENING_FEATURES)


def test_reciprocating_kind_includes_crank_features(query_diagnosis):
    payload = query_diagnosis.build_result(
        kind="reciprocating_compressor",
        equipment_ids=["RC-201"],
        start="2026-05-12T00:00:00",
        end="2026-05-13T00:00:00",
        mode="oneoff",
        compare="none",
    )
    feats = payload["points"][0]["default_features"]
    assert "crank_angle" in feats
    assert "cylinder_pressure" in feats
    # Process signals should match the reciprocating channel set
    assert "crank_angle" in payload["process_signals"]
    assert "unloader_state" in payload["process_signals"]


def test_pump_process_channels_match_design(query_diagnosis):
    payload = query_diagnosis.build_result(
        kind="centrifugal_pump",
        equipment_ids=["PUMP-A-001"],
        start="2026-05-12T00:00:00",
        end="2026-05-13T00:00:00",
        mode="oneoff",
        compare="none",
    )
    proc = payload["process_signals"]
    assert {"discharge_pressure", "suction_pressure", "flow_rate", "motor_current"}.issubset(proc.keys())
    assert proc["flow_rate"]["unit"] == "m3/h"


# --- CLI / validation ---


def test_main_demo_path_writes_output(query_diagnosis, monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "query_diagnosis.py",
            "--kind",
            "centrifugal_pump",
            "--equipment",
            "PUMP-A-001,PUMP-A-002",
            "--start",
            "2026-05-12T00:00:00",
            "--end",
            "2026-05-13T00:00:00",
            "--mode",
            "oneoff",
            "--compare",
            "previous_period",
        ],
    )
    assert query_diagnosis.main() == 0
    out = json.loads(capsys.readouterr().out)
    assert out["kind"] == "centrifugal_pump"
    assert out["data_source"] == "demo_fallback"
    assert out["equipment_count"] == 2
    written = json.loads((tmp_path / "query_diagnosis.json").read_text(encoding="utf-8"))
    assert written["equipment_ids"] == ["PUMP-A-001", "PUMP-A-002"]


def test_main_rejects_invalid_kind(query_diagnosis, monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "query_diagnosis.py",
            "--kind",
            "not_a_real_kind",
            "--equipment",
            "PUMP-A-001",
            "--start",
            "2026-05-12T00:00:00",
            "--end",
            "2026-05-13T00:00:00",
        ],
    )
    # argparse choices not used (we do manual validation), so main returns 0 with structured error
    code = query_diagnosis.main()
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert "error" in out
    assert "--kind" in out["error"]


def test_main_rejects_invalid_equipment_id(query_diagnosis, monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "query_diagnosis.py",
            "--kind",
            "centrifugal_pump",
            "--equipment",
            "PUMP-A-001,$(touch pwned)",
            "--start",
            "2026-05-12T00:00:00",
            "--end",
            "2026-05-13T00:00:00",
        ],
    )
    assert query_diagnosis.main() == 0
    out = json.loads(capsys.readouterr().out)
    assert out["error"] == "--equipment contains invalid equipment id(s): $(touch pwned)"


def test_main_rejects_empty_equipment(query_diagnosis, monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "query_diagnosis.py",
            "--kind",
            "centrifugal_pump",
            "--equipment",
            "",
            "--start",
            "2026-05-12T00:00:00",
            "--end",
            "2026-05-13T00:00:00",
        ],
    )
    assert query_diagnosis.main() == 0
    out = json.loads(capsys.readouterr().out)
    assert out["error"] == "--equipment must be a non-empty CSV"


def test_main_rejects_window_too_long(query_diagnosis, monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "query_diagnosis.py",
            "--kind",
            "centrifugal_pump",
            "--equipment",
            "PUMP-A-001",
            "--start",
            "2026-04-01T00:00:00",
            "--end",
            "2026-05-13T00:00:00",
        ],
    )
    assert query_diagnosis.main() == 0
    out = json.loads(capsys.readouterr().out)
    assert "diagnosis window must not exceed 30 days" in out["error"]


def test_main_rejects_end_before_start(query_diagnosis, monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "query_diagnosis.py",
            "--kind",
            "centrifugal_pump",
            "--equipment",
            "PUMP-A-001",
            "--start",
            "2026-05-13T00:00:00",
            "--end",
            "2026-05-12T00:00:00",
        ],
    )
    assert query_diagnosis.main() == 0
    out = json.loads(capsys.readouterr().out)
    assert "--end must be strictly after --start" in out["error"]


def test_main_rejects_bad_iso_format(query_diagnosis, monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "query_diagnosis.py",
            "--kind",
            "centrifugal_pump",
            "--equipment",
            "PUMP-A-001",
            "--start",
            "2026/05/12 00:00:00",
            "--end",
            "2026-05-13T00:00:00",
        ],
    )
    assert query_diagnosis.main() == 0
    out = json.loads(capsys.readouterr().out)
    assert "ISO datetime" in out["error"]


def test_main_dedupes_equipment_ids(query_diagnosis, monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "query_diagnosis.py",
            "--kind",
            "centrifugal_pump",
            "--equipment",
            "PUMP-A-001,PUMP-A-002,PUMP-A-001",
            "--start",
            "2026-05-12T00:00:00",
            "--end",
            "2026-05-13T00:00:00",
        ],
    )
    assert query_diagnosis.main() == 0
    written = json.loads((tmp_path / "query_diagnosis.json").read_text(encoding="utf-8"))
    assert written["equipment_ids"] == ["PUMP-A-001", "PUMP-A-002"]


def test_main_no_stack_trace_on_unexpected_exception(query_diagnosis, monkeypatch, capsys):
    """Even unexpected exceptions are converted to structured JSON error."""
    def _boom(*_args, **_kwargs):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(query_diagnosis, "build_result", _boom)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "query_diagnosis.py",
            "--kind",
            "centrifugal_pump",
            "--equipment",
            "PUMP-A-001",
            "--start",
            "2026-05-12T00:00:00",
            "--end",
            "2026-05-13T00:00:00",
        ],
    )
    assert query_diagnosis.main() == 0
    out = json.loads(capsys.readouterr().out)
    assert out["error"] == "RuntimeError: unexpected"


# --- InS toolchain integration (mocked) ---


def test_fetch_block_uses_ins_when_toolchain_present(query_diagnosis, monkeypatch, tmp_path):
    """When run.sh + features-tool both exist, build_result calls _call_ins_extract_trend."""
    # Fake skill root with run.sh and a fake features-tool root
    skill_root = tmp_path / "skills"
    (skill_root / "ins-extract-trend-features" / "scripts").mkdir(parents=True)
    (skill_root / "ins-extract-trend-features" / "scripts" / "run.sh").write_text("#!/bin/sh\n")
    features_root = tmp_path / "features-tool"
    features_root.mkdir()
    monkeypatch.setenv("INS_SKILL_ROOT", str(skill_root))
    monkeypatch.setenv("FEATURES_TOOL_ROOT", str(features_root))

    captured: dict = {}

    def fake_call(component_features, start, end, timeout_seconds=30.0):
        captured["component_features"] = component_features
        captured["start"] = start
        captured["end"] = end
        return {
            "point_results": {
                pid: {
                    "summary": f"ins summary for {pid}",
                    "notable_points": [],
                    "anomaly_time_ms": [1747000000000],
                }
                for pid in component_features
            }
        }

    monkeypatch.setattr(query_diagnosis, "_call_ins_extract_trend", fake_call)

    point_specs = {
        "PUMP-A-001": [
            {"point_id": "1801", "point_name": "驱动端 X 轴振", "point_type": 83},
            {"point_id": "1802", "point_name": "轴位移", "point_type": 82},
        ]
    }
    block, source = query_diagnosis.fetch_block(
        kind="centrifugal_pump",
        equipment_ids=["PUMP-A-001"],
        window={"start": "2026-05-12T00:00:00", "end": "2026-05-13T00:00:00"},
        mode="oneoff",
        warnings=[],
        point_specs_by_equipment=point_specs,
    )
    assert source == "ins"
    assert captured["start"] == "2026-05-12T00:00:00"
    # Type 83 → vibration features; type 82 → ["value"]
    assert captured["component_features"]["1801"] == query_diagnosis.ROTATING_AND_PUMP_FEATURES
    assert captured["component_features"]["1802"] == ["value"]
    assert all(p["trend_summary"]["summary"].startswith("ins summary") for p in block["points"])


def test_fetch_block_falls_back_when_ins_call_fails(query_diagnosis, monkeypatch, tmp_path):
    """If InS toolchain is reachable but the call fails twice, fall back + record warning."""
    skill_root = tmp_path / "skills"
    (skill_root / "ins-extract-trend-features" / "scripts").mkdir(parents=True)
    (skill_root / "ins-extract-trend-features" / "scripts" / "run.sh").write_text("#!/bin/sh\n")
    features_root = tmp_path / "features-tool"
    features_root.mkdir()
    monkeypatch.setenv("INS_SKILL_ROOT", str(skill_root))
    monkeypatch.setenv("FEATURES_TOOL_ROOT", str(features_root))

    def always_fail(*_args, **_kwargs):
        raise subprocess.CalledProcessError(returncode=1, cmd=["bash"], output="", stderr="err")

    monkeypatch.setattr(query_diagnosis, "_call_ins_extract_trend", always_fail)

    point_specs = {
        "PUMP-A-001": [
            {"point_id": "1801", "point_name": "驱动端 X 轴振", "point_type": 83},
        ]
    }
    warnings: list = []
    block, source = query_diagnosis.fetch_block(
        kind="centrifugal_pump",
        equipment_ids=["PUMP-A-001"],
        window={"start": "2026-05-12T00:00:00", "end": "2026-05-13T00:00:00"},
        mode="oneoff",
        warnings=warnings,
        point_specs_by_equipment=point_specs,
    )
    assert source == "demo_fallback"
    assert any("ins-extract-trend-features failed twice" in w for w in warnings)
    assert block["points"], "demo fallback block must still contain points"


def test_build_component_features_skips_waveform_points(query_diagnosis):
    """Type 83 with '波形' in name must be excluded (per ins SKILL default mapping)."""
    specs = [
        {"point_id": "1801", "point_name": "驱动端 X 轴振", "point_type": 83},
        {"point_id": "1899", "point_name": "驱动端 X 波形", "point_type": 83},
        {"point_id": "1701", "point_name": "转速", "point_type": 81},
        {"point_id": "1601", "point_name": "轴承温度", "point_type": 82},
    ]
    cf = query_diagnosis._build_component_features(specs, mode="oneoff")
    assert "1801" in cf
    assert "1899" not in cf  # waveform excluded
    assert cf["1701"] == ["speed"]
    assert cf["1601"] == ["value"]


def test_build_component_features_screening_mode(query_diagnosis):
    specs = [{"point_id": "1801", "point_name": "驱动端 X 轴振", "point_type": 83}]
    cf = query_diagnosis._build_component_features(specs, mode="screening")
    assert cf["1801"] == query_diagnosis.SCREENING_FEATURES
