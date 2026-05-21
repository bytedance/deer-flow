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
