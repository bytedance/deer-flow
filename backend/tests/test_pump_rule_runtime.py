"""Tests for managed pump rule runtime and payload mapping."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
FEATURES_TOOL_DIR = REPO_ROOT / "docker" / "sandbox" / "features-tool"
SCRIPT_DIR = REPO_ROOT / "skills" / "custom" / "pump-fault-diagnosis" / "scripts"
FIXTURE_DIR = REPO_ROOT / "backend" / "tests" / "fixtures" / "pump_rule"


def _load_script(filename: str, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, SCRIPT_DIR / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_builds_target_context_from_point_configs():
    from pump_rule.context import build_target_context_from_point_configs

    context = build_target_context_from_point_configs(
        "PUMP1",
        "BRG1",
        {
            "vibPointConfig": [
                {
                    "posId": "VIB27",
                    "posName": "驱动端_水平",
                    "componentId": "BRG1",
                    "type": 27,
                    "position": "P-101A/驱动端",
                    "config": "{\"vRmsCValue\":4.5,\"cValue\":4.5}",
                },
                {
                    "posId": "PROCESS",
                    "posName": "非振动量",
                    "componentId": "BRG1",
                    "type": 99,
                    "config": "{}",
                },
            ],
            "staPointConfig": [
                {
                    "posId": "TEMP1",
                    "posName": "驱动端_温度",
                    "componentId": "BRG1",
                    "type": 28,
                    "position": "P-101A/驱动端",
                    "config": "{\"tempH\":75,\"tempHH\":80}",
                }
            ],
        },
    )

    assert context.target_name == "驱动端"
    assert [point.point_id for point in context.points] == ["VIB27", "TEMP1"]
    assert context.points[0].point_kind == "vibration"
    assert context.points[0].thresholds["rms_c"] == 4.5
    assert context.points[1].point_kind == "temperature"
    assert context.points[1].thresholds["temp_h"] == 75


def test_point_config_context_falls_back_to_machine_points():
    from pump_rule.context import build_target_context_from_point_configs

    context = build_target_context_from_point_configs(
        "PUMP1",
        "PUMP_STAGE",
        {
            "vibPointConfig": [
                {
                    "posId": "VIB1",
                    "posName": "电机联端_水平",
                    "componentId": "LOWER_POSITION",
                    "type": 27,
                    "position": "P-101A/电机/电机联端",
                    "config": "{\"vRmsCValue\":4.5}",
                }
            ],
            "staPointConfig": [],
        },
        component_name="泵体",
    )

    assert [point.point_id for point in context.points] == ["VIB1"]
    assert any("已回退使用整台机泵测点" in warning for warning in context.warnings)


def test_component_tree_context_expands_pump_subdevice_children():
    from pump_rule.context import build_target_context_from_component_tree

    context = build_target_context_from_component_tree(
        "230110150247014",
        "550472292971315200",
        [
            {
                "id": "230110150247014",
                "name": "歧化进料泵3500-P-101A",
                "type": 4,
                "children": [
                    {
                        "id": "550472292971315200",
                        "type": 50,
                        "name": "泵",
                        "children": [
                            {
                                "id": "448840838189940736",
                                "type": 40,
                                "name": "泵联端",
                                "children": [
                                    {
                                        "unitType": 3,
                                        "machineId": "230110150247014",
                                        "id": "2301101502470140001",
                                        "type": 23,
                                        "name": "泵联端_H",
                                        "configInfo": {"vRmsCValue": 4.5, "tempH": 75},
                                    },
                                    {
                                        "unitType": 3,
                                        "machineId": "230110150247014",
                                        "id": "2301101502470140004",
                                        "type": 22,
                                        "name": "泵联端_T",
                                        "configInfo": {"tempH": 75, "tempHH": 80},
                                    },
                                ],
                                "unitType": 2,
                            }
                        ],
                        "unitType": 2,
                    }
                ],
                "unitType": 1,
            }
        ],
    )

    assert context.target_name == "泵"
    assert [point.point_id for point in context.points] == ["2301101502470140001", "2301101502470140004"]
    assert context.points[0].point_kind == "vibration"
    assert context.points[1].point_kind == "temperature"


@pytest.fixture(autouse=True)
def _path(monkeypatch):
    monkeypatch.setenv("FEATURES_TOOL_ROOT", str(FEATURES_TOOL_DIR))
    if str(FEATURES_TOOL_DIR) not in sys.path:
        sys.path.insert(0, str(FEATURES_TOOL_DIR))


@pytest.mark.asyncio
async def test_pump_rule_runtime_detects_unbalance(monkeypatch, tmp_path):
    monkeypatch.setenv("DIAGNOSIS_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("PUMP_RULE_FIXTURE", str(FIXTURE_DIR / "unbalance.json"))

    from pump_rule import close_all_clients, run_diagnosis

    try:
        result = await run_diagnosis("PUMP1", "BRG1", "2026-02-19T08:00:00")
    finally:
        await close_all_clients()

    payload = result.model_dump()
    assert payload["machine_id"] == "PUMP1"
    assert payload["component_id"] == "BRG1"
    assert payload["target_info"]["target_kind"] == "bearing"
    assert payload["base_freq"] == pytest.approx(25.0, abs=0.5)
    assert any(item["type"] == "unbalance" for item in payload["malfunction_findings"])
    assert payload["evidence"]
    assert (tmp_path / "pump_rule_cache").exists()


@pytest.mark.asyncio
async def test_pump_rule_comparison_unbalance_detailed(monkeypatch, tmp_path):
    """Task 6.3: compare unbalance fixture output against reference /malfunction behavior.

    Verifies fault type, probability range, evidence point IDs, and base frequency.
    """
    monkeypatch.setenv("DIAGNOSIS_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("PUMP_RULE_FIXTURE", str(FIXTURE_DIR / "unbalance.json"))

    from pump_rule import close_all_clients, run_diagnosis

    try:
        result = await run_diagnosis("PUMP1", "BRG1", "2026-02-19T08:00:00")
    finally:
        await close_all_clients()

    payload = result.model_dump()

    # --- base frequency: waveform is 25 Hz pure sine at 200 Hz sampling ---
    assert payload["base_freq"] == pytest.approx(25.0, abs=0.5)

    # --- malfunction findings: fault type & probability range ---
    malfunctions = payload["malfunction_findings"]
    unbalance_items = [item for item in malfunctions if item["type"] == "unbalance"]
    assert len(unbalance_items) == 1, f"Expected exactly 1 unbalance finding, got {unbalance_items}"
    unbalance = unbalance_items[0]
    assert unbalance["name"] == "不平衡或刚性不足"
    # unbalance probability capped at 0.85 by _clip_probability(max_probability, 0.85)
    assert 0.5 <= unbalance["probability"] <= 0.88, (
        f"Unbalance probability {unbalance['probability']} out of expected [0.5, 0.88]"
    )

    # --- evidence: VIB1 must appear as evidence point ---
    for evidence_item in payload["evidence"]:
        if evidence_item.get("category") == "rule":
            point_str = str(evidence_item.get("point") or "")
            assert "VIB1" in point_str, (
                f"Evidence point {point_str!r} does not reference VIB1"
            )

    # --- health findings: v_rms > D threshold (7.0) should trigger D zone ---
    health_statuses = {item["status"] for item in payload["health_findings"]}
    assert ("D" in health_statuses or "C" in health_statuses), (
        f"Expected C/D-zone health finding (v_rms > 4.0), got statuses: {health_statuses}"
    )
    # C_His verifies 12h window check is active
    assert "C_His" in health_statuses, (
        f"Expected 12h-in-C-zone finding, got statuses: {health_statuses}"
    )

    # --- evidence spectrum row: 1X energy ratio should be high for unbalance ---
    spectrum_rows = [item for item in payload["evidence"] if item.get("category") == "spectrum"]
    one_x_rows = [item for item in spectrum_rows if "1X" in str(item.get("feature") or "")]
    assert one_x_rows, "Expected 1X energy ratio evidence row"
    for row in one_x_rows:
        energy = float(row.get("value") or 0)
        assert energy >= 0.5, f"1X energy ratio {energy} should be >= 0.5 for unbalance"


@pytest.mark.asyncio
async def test_pump_rule_comparison_no_findings_detailed(monkeypatch, tmp_path):
    """Task 6.3: compare no_findings fixture output against reference /malfunction behavior.

    Verifies clean output: no malfunctions, no health findings, base frequency still detectable.
    """
    monkeypatch.setenv("DIAGNOSIS_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("PUMP_RULE_FIXTURE", str(FIXTURE_DIR / "no_findings.json"))

    from pump_rule import close_all_clients, run_diagnosis

    try:
        result = await run_diagnosis("PUMP1", "BRG1", "2026-02-19T08:00:00")
    finally:
        await close_all_clients()

    payload = result.model_dump()

    # --- base frequency: waveform still has 25 Hz component ---
    assert payload["base_freq"] is not None, "Base frequency should be detectable even without faults"
    assert payload["base_freq"] == pytest.approx(25.0, abs=1.0)

    # --- malfunction findings: must be empty (v_rms=1.0 < c_threshold=4.0) ---
    assert payload["malfunction_findings"] == [], (
        f"Expected no malfunction findings, got: {payload['malfunction_findings']}"
    )

    # --- health findings: v_rms=1.0 < B=3.0 so no vibration health findings ---
    # Temperature trend may trigger due to slow rise in fixture, but no vibration issues
    vibration_health = [
        item for item in payload["health_findings"]
        if "Rms" in str(item.get("status") or "") or "Acc" in str(item.get("status") or "")
        or item.get("status") in ("C", "D", "C_His")
    ]
    assert not vibration_health, (
        f"Expected no vibration health findings (v_rms=1.0 < B=3.0), got: {vibration_health}"
    )

    # --- warnings: should not contain base frequency failure ---
    base_freq_warnings = [w for w in payload["warnings"] if "基频" in str(w)]
    assert not base_freq_warnings, (
        f"Unexpected base frequency warnings: {base_freq_warnings}"
    )

    # --- target info: same bearing target ---
    assert payload["target_info"]["target_kind"] == "bearing"


@pytest.mark.asyncio
async def test_pump_rule_runtime_allows_no_findings(monkeypatch, tmp_path):
    monkeypatch.setenv("DIAGNOSIS_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("PUMP_RULE_FIXTURE", str(FIXTURE_DIR / "no_findings.json"))

    from pump_rule import close_all_clients, run_diagnosis

    try:
        result = await run_diagnosis("PUMP1", "BRG1", "2026-02-19T08:00:00")
    finally:
        await close_all_clients()

    payload = result.model_dump()
    assert payload["malfunction_findings"] == []


def test_pump_rule_cli_writes_result(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("DIAGNOSIS_OUTPUT_DIR", str(tmp_path))
    module = _load_script("run_pump_rule_diagnosis.py", "run_pump_rule_diagnosis_test")
    output = tmp_path / "pump_rule_result.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_pump_rule_diagnosis.py",
            "--machine-id",
            "PUMP1",
            "--component-id",
            "BRG1",
            "--diagnosis-time",
            "2026-02-19T08:00:00",
            "--fixture",
            str(FIXTURE_DIR / "unbalance.json"),
            "--output",
            str(output),
        ],
    )

    assert module.main() == 0
    stdout = json.loads(capsys.readouterr().out)
    assert stdout["ok"] is True
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["ok"] is True
    assert any(item["type"] == "unbalance" for item in payload["malfunction_findings"])


def test_build_pump_report_payload(monkeypatch, tmp_path):
    monkeypatch.setenv("DIAGNOSIS_OUTPUT_DIR", str(tmp_path))
    run_module = _load_script("run_pump_rule_diagnosis.py", "run_pump_rule_for_payload")
    result_path = tmp_path / "pump_rule_result.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_pump_rule_diagnosis.py",
            "--machine-id",
            "PUMP1",
            "--component-id",
            "BRG1",
            "--diagnosis-time",
            "2026-02-19T08:00:00",
            "--fixture",
            str(FIXTURE_DIR / "unbalance.json"),
            "--output",
            str(result_path),
        ],
    )
    assert run_module.main() == 0

    build_module = _load_script("build_pump_report_payload.py", "build_pump_report_payload_test")
    report_payload = build_module.build_payload(json.loads(result_path.read_text(encoding="utf-8")))
    assert report_payload["report_meta"]["data_source"] == "pump_rule_runtime"
    assert report_payload["report_meta"]["rules_skill"] == "pump-fault-diagnosis"
    assert report_payload["rule_matches"][0]["fault_family"] == "unbalance"
    assert report_payload["equipment_summary"][0]["component_id"] == "BRG1"


def test_pump_rule_path_does_not_import_start_stop_modules():
    for path in (FEATURES_TOOL_DIR / "pump_rule").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "stop.CheckStop" not in text
        assert "StopValue" not in text
