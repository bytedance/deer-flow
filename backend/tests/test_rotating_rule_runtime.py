"""Tests for rotating rule runtime wrappers and report payload mapping."""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = REPO_ROOT / "skills" / "custom" / "rotating-fault-diagnosis" / "scripts"
FEATURES_TOOL_DIR = REPO_ROOT / "docker" / "sandbox" / "features-tool"
FEATURES_TOOL_TOOLS_DIR = FEATURES_TOOL_DIR / "tools"
FEATURES_TOOL_RULE_DIR = FEATURES_TOOL_DIR / "diagnosis_rule"


def _load_module(filename: str, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, SCRIPT_DIR / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_local_module(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_cache(tmp_path: Path) -> None:
    cache_dir = tmp_path / "rotating_rule_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    (cache_dir / "trend_MAC-1.json").write_text(
        json.dumps(
            {
                "component_ids": ["P-101"],
                "start_time": "1747728000000",
                "end_time": "1747731600000",
                "data": {
                    "P-101": [
                        {"time_ms": "1747728000000", "values": {"pp_value": 18.5, "rms": 6.2}},
                        {"time_ms": "1747731600000", "values": {"pp_value": 28.5, "rms": 8.4}},
                    ]
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (cache_dir / "trend_features_MAC-1.json").write_text(
        json.dumps(
            {
                "point_results": [
                    {
                        "component_id": "P-101",
                        "feature_stats": {
                            "pp_value": {"current": 28.5, "mean": 20.0, "std": 2.0},
                            "rms": {"current": 8.4, "mean": 7.5, "std": 0.4},
                        },
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (cache_dir / "waveform_P-101_1747731600000.json").write_text(
        json.dumps(
            {
                "component_id": "P-101",
                "time_ms": "1747731600000",
                "data": {
                    "spec_x": [10.0, 20.0, 30.0],
                    "spec_y": [1.0, 2.5, 1.8],
                    "wave_x": [0.0, 1.0, 2.0],
                    "wave_y": [0.2, 0.4, 0.1],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (cache_dir / "waveform_features_P-101_1747731600000.json").write_text(
        json.dumps(
            {
                "component_id": "P-101",
                "feature_details": {
                    "amp_1x_ratio": 0.71,
                    "amp_2x_to_1x_ratio": 0.16,
                    "crest_factor": 3.8,
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (cache_dir / "orbit_BRG-1_1747731600000.json").write_text(
        json.dumps(
            {
                "bearing_id": "BRG-1",
                "data": {
                    "points": [[0.0, 0.1], [0.2, 0.3], [0.4, 0.15], [0.0, 0.1]]
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (cache_dir / "orbit_features_BRG-1_1747731600000.json").write_text(
        json.dumps(
            {
                "bearing_id": "BRG-1",
                "feature_details": {
                    "first_cycle_axis_ratio": 1.62,
                    "raw_repetition_score": 0.88,
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _result_payload(tmp_path: Path) -> dict:
    return {
        "ok": True,
        "device_id": "MAC-1",
        "sub_device_id": "BRG-1",
        "diagnosis_time": "2026-05-20T08:00:00",
        "runtime": {"entrypoint": "diagnosis_rule.run_diagnosis"},
        "artifacts": {"cache_dir": str(tmp_path / "rotating_rule_cache")},
        "warnings": ["waveform case count limited to 1"],
        "result": {
            "stage": "running",
            "fault_type": "unbalance",
            "fault_subtype": "",
            "confidence": "high",
            "score": 0.91,
            "running_actions": ["减载观察振动变化"],
            "maintenance_actions": ["停机后执行动平衡"],
            "rule_optimization_conclusion": ["复核转子支撑与轴承状态"],
            "evidence_summary": ["1X 占优", "轨迹重复性较好"],
            "primary_rule_detail": {
                "rule_id": "rule-unbalance",
                "fault_type": "unbalance",
                "fault_subtype": "",
                "score": 0.91,
                "matched_conditions": ["1X 占优", "轨迹重复性较好"],
                "missing_evidence": [],
                "contradictions": [],
            },
            "alternative_faults": [
                {
                    "rule_id": "rule-misalignment",
                    "fault_type": "misalignment",
                    "fault_subtype": "",
                    "score": 0.52,
                    "matched_conditions": ["存在一定 2X 成分"],
                    "missing_evidence": ["更多轴向证据"],
                    "contradictions": [],
                }
            ],
            "debug": {
                "reasoning_summary": [
                    "device_type=离心压缩机",
                    "target_device_type=离心压缩机",
                ]
            },
        },
    }


def test_build_rotating_report_payload_reads_cache_only(tmp_path, monkeypatch):
    monkeypatch.setenv("DIAGNOSIS_OUTPUT_DIR", str(tmp_path))
    _write_cache(tmp_path)
    module = _load_module("build_rotating_report_payload.py", "build_rotating_report_payload")

    payload = module.build_payload(_result_payload(tmp_path))

    assert payload["report_meta"]["data_source"] == "rotating_rule_runtime"
    assert payload["report_meta"]["rules_skill"] == "vibration-fault-diagnosis"
    assert payload["trend_chart"]["series"]
    assert len(payload["spectrum_charts"]) == 1
    assert len(payload["orbit_charts"]) == 1
    assert payload["rule_matches"][0]["fault_family"] == "unbalance"
    assert payload["rule_matches"][1]["fault_family"] == "misalignment"
    assert payload["recommendations"] == [
        "减载观察振动变化",
        "停机后执行动平衡",
        "复核转子支撑与轴承状态",
    ]
    assert "waveform case count limited to 1" in payload["warnings"]


def test_build_rotating_report_payload_cli_writes_output(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DIAGNOSIS_OUTPUT_DIR", str(tmp_path))
    _write_cache(tmp_path)
    result_path = tmp_path / "rotating_rule_result.json"
    result_path.write_text(json.dumps(_result_payload(tmp_path), ensure_ascii=False), encoding="utf-8")
    module = _load_module("build_rotating_report_payload.py", "build_rotating_report_payload_cli")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "build_rotating_report_payload.py",
            "--input",
            str(result_path),
            "--output",
            str(tmp_path / "diagnosis_features.json"),
        ],
    )

    assert module.main() == 0
    stdout = json.loads(capsys.readouterr().out)
    assert stdout["output"] == str(tmp_path / "diagnosis_features.json")
    assert stdout["rule_matches_count"] == 2


def test_build_rotating_report_payload_keeps_engine_fallback_semantics(tmp_path, monkeypatch):
    monkeypatch.setenv("DIAGNOSIS_OUTPUT_DIR", str(tmp_path))
    _write_cache(tmp_path)
    module = _load_module("build_rotating_report_payload.py", "build_rotating_report_payload_fallback")

    payload = _result_payload(tmp_path)
    payload["result"]["fault_type"] = "no_specific_fault"
    payload["result"]["confidence"] = "low"
    payload["result"]["score"] = 0.12
    payload["result"]["primary_rule_detail"] = None
    payload["result"]["alternative_faults"] = []

    built = module.build_payload(payload)

    assert len(built["rule_matches"]) == 1
    assert built["rule_matches"][0]["fault_family"] == "no_specific_fault"
    assert built["rule_matches"][0]["confidence"] == "low"


def test_build_device_context_artifact_contains_target_info(monkeypatch):
    monkeypatch.syspath_prepend(str(FEATURES_TOOL_DIR))

    from diagnosis.device_context_artifact import build_device_context_artifact
    from diagnosis_rule.config import load_config

    analysis = {
        "device_id": "MAC-1",
        "child_device_list": [
            {
                "id": "ROT-1",
                "name": "离心压缩机转子",
                "unit_type": 2,
                "type_num": 80,
                "children": [
                    {
                        "id": "BRG-1",
                        "name": "联端轴承",
                        "unit_type": 2,
                        "type_num": 70,
                        "children": [
                            {
                                "id": "P-101",
                                "name": "联端X轴振",
                                "unit_type": 3,
                                "type_num": 83,
                                "h_alarm": 20,
                                "hh_alarm": 30,
                                "belongShaftId": "S-1",
                            },
                            {
                                "id": "P-102",
                                "name": "联端Y轴振",
                                "unit_type": 3,
                                "type_num": 83,
                                "h_alarm": 20,
                                "hh_alarm": 30,
                                "belongShaftId": "S-1",
                            },
                        ],
                    },
                    {
                        "id": "PT-1",
                        "name": "入口流量",
                        "unit_type": 3,
                        "type_num": 82,
                    },
                ],
            }
        ],
    }

    artifact = build_device_context_artifact(analysis, load_config(), sub_device_id="P-101")

    assert artifact["device_type"]["value"] == "离心式&轴流式压缩机"
    assert artifact["process_type"]["value"] == "压缩机工艺"
    assert artifact["target_info"]["target_kind"] == "probe"
    assert artifact["target_info"]["probe_ids"] == ["P-101", "P-102"]
    assert artifact["target_info"]["bearing_ids"] == ["BRG-1"]
    assert artifact["target_info"]["target_device_type"] == "离心式&轴流式压缩机"
    assert artifact["resolved_context"]["rotor_device_ids"] == ["ROT-1"]


def test_collect_orbit_results_prefers_device_context_probe_mapping(monkeypatch):
    monkeypatch.syspath_prepend(str(FEATURES_TOOL_DIR))

    from diagnosis_rule import workflow as module
    from models import BearingRef, DeviceContext, ProbeRef

    context = DeviceContext(device_id="MAC-1", device_type="离心式&轴流式压缩机")
    context.bearing_probe_map["BRG-1"] = ["P-101", "P-102"]
    context.probe_index["P-101"] = ProbeRef(point_id="P-101", point_name="联端X轴振", point_type="轴振", bearing_id="BRG-1")
    context.probe_index["P-102"] = ProbeRef(point_id="P-102", point_name="联端Y轴振", point_type="轴振", bearing_id="BRG-1")
    context.bearing_index["BRG-1"] = BearingRef(bearing_id="BRG-1", bearing_name="联端轴承")

    captured: list[tuple[str, str, str, list[str] | None]] = []

    async def _fake_cached_extract_orbit(root_device_id: str, bearing_id: str, time_ms: str, probe_ids: list[str] | None = None):
        captured.append((root_device_id, bearing_id, time_ms, probe_ids))
        return {"bearing_id": bearing_id, "time_ms": time_ms, "probe_ids": probe_ids or []}

    monkeypatch.setattr(module, "cached_extract_orbit", _fake_cached_extract_orbit)

    results, failures = asyncio.run(
        module._collect_orbit_results(
            "MAC-1",
            context,
            {"bearing_ids": ["BRG-1"]},
            ["1747731600000"],
            {"max_orbit_points": 2},
        )
    )

    assert not failures
    assert len(results) == 1
    assert captured == [("MAC-1", "BRG-1", "1747731600000", ["P-101", "P-102"])]


def test_device_analysis_script_returns_raw_tree_only(monkeypatch):
    monkeypatch.syspath_prepend(str(FEATURES_TOOL_DIR))

    module = _load_local_module(FEATURES_TOOL_TOOLS_DIR / "device_analysis.py", "device_analysis_script")

    async def _fake_tree(_device_id: str):
        return {
            "device_id": "MAC-1",
            "child_device_list": [
                {
                    "id": "ROT-1",
                    "name": "离心压缩机转子",
                    "unit_type": 2,
                    "type_num": 80,
                    "children": [
                        {
                            "id": "BRG-1",
                            "name": "联端轴承",
                            "unit_type": 2,
                            "type_num": 70,
                            "children": [
                                {
                                    "id": "P-101",
                                    "name": "联端X轴振",
                                    "unit_type": 3,
                                    "type_num": 83,
                                    "h_alarm": 20,
                                    "hh_alarm": 30,
                                    "belongShaftId": "S-1",
                                }
                            ],
                        }
                    ],
                }
            ],
        }

    monkeypatch.setattr(module, "get_device_children", _fake_tree)

    parsed = asyncio.run(module.analyze_device("MAC-1"))

    assert parsed["device_id"] == "MAC-1"
    assert "child_device_list" in parsed
    assert "device_type" not in parsed
    assert parsed["child_device_list"][0]["id"] == "ROT-1"


def test_rule_context_reuses_existing_device_context_artifact(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(FEATURES_TOOL_DIR))
    monkeypatch.setenv("DIAGNOSIS_OUTPUT_DIR", str(tmp_path))

    sys.modules.pop("diagnosis_rule.context", None)
    module = importlib.import_module("diagnosis_rule.context")
    artifact_path = tmp_path / "device_context.json"
    artifact_path.write_text(
        json.dumps(
            {
                "device_id": "MAC-1",
                "child_device_summary": ["离心压缩机转子下挂联端轴承与轴振测点"],
                "device_type": {"value": "离心式&轴流式压缩机", "confidence": "high", "reason": "名称匹配"},
                "process_type": {"value": "压缩机工艺", "confidence": "medium", "reason": "工艺测点"},
                "device_structure": {"value": "单转子-多轴承支撑结构", "confidence": "medium", "reason": "层级完整"},
                "child_device_list": [
                    {
                        "id": "ROT-1",
                        "name": "离心压缩机转子",
                        "unit_type": 2,
                        "type_num": 80,
                        "type": "离心式&轴流式压缩机",
                        "children": [
                            {
                                "id": "BRG-1",
                                "name": "联端轴承",
                                "unit_type": 2,
                                "type_num": 70,
                                "direction": "联端",
                                "bearing_type": ["支撑轴承"],
                                "children": [
                                    {
                                        "id": "P-101",
                                        "name": "联端X轴振",
                                        "unit_type": 3,
                                        "type_num": 83,
                                        "type": "轴振",
                                        "h_alarm": 20,
                                        "hh_alarm": 30,
                                        "belongShaftId": "S-1",
                                    }
                                ],
                            }
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    context = asyncio.run(module.build_rule_device_context("MAC-1", sub_device_id="P-101"))
    assert context.device_id == "MAC-1"
    assert "P-101" in context.probe_index


def test_rule_context_requires_agent_written_device_context(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(FEATURES_TOOL_DIR))
    monkeypatch.setenv("DIAGNOSIS_OUTPUT_DIR", str(tmp_path))

    sys.modules.pop("diagnosis_rule.context", None)
    module = importlib.import_module("diagnosis_rule.context")

    with pytest.raises(FileNotFoundError) as exc_info:
        asyncio.run(module.build_rule_device_context("MAC-1", sub_device_id="P-101"))

    assert "device_context.json not found" in str(exc_info.value)


def test_run_rotating_rule_diagnosis_main_records_device_context_artifact(tmp_path, monkeypatch):
    monkeypatch.setenv("DIAGNOSIS_OUTPUT_DIR", str(tmp_path))
    module = _load_module("run_rotating_rule_diagnosis.py", "run_rotating_rule_diagnosis_success")

    device_context_path = tmp_path / "device_context.json"
    device_context_path.write_text("{}", encoding="utf-8")

    def _ok(_coro):
        _coro.close()
        return {
            "ok": True,
            "device_id": "MAC-1",
            "sub_device_id": "BRG-1",
            "diagnosis_time": "2026-05-20T08:00:00",
            "runtime": {"entrypoint": "diagnosis_rule.run_diagnosis"},
            "artifacts": {
                "cache_dir": str(tmp_path / "rotating_rule_cache"),
                "cache_files": [],
                "device_context_path": str(device_context_path),
            },
            "warnings": [],
            "result": {"fault_type": "unbalance"},
        }

    monkeypatch.setattr(module.asyncio, "run", _ok)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_rotating_rule_diagnosis.py",
            "--device-id",
            "MAC-1",
            "--sub-device-id",
            "BRG-1",
            "--diagnosis-time",
            "2026-05-20T08:00:00",
            "--output",
            str(tmp_path / "rotating_rule_result.json"),
        ],
    )

    assert module.main() == 0
    written = json.loads((tmp_path / "rotating_rule_result.json").read_text(encoding="utf-8"))
    assert written["artifacts"]["device_context_path"] == str(device_context_path)


def test_run_rotating_rule_diagnosis_main_serializes_error(tmp_path, monkeypatch):
    monkeypatch.setenv("DIAGNOSIS_OUTPUT_DIR", str(tmp_path))
    module = _load_module("run_rotating_rule_diagnosis.py", "run_rotating_rule_diagnosis")

    def _boom(_coro):
        _coro.close()
        raise FileNotFoundError("features-tool missing")

    monkeypatch.setattr(module.asyncio, "run", _boom)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_rotating_rule_diagnosis.py",
            "--device-id",
            "MAC-1",
            "--sub-device-id",
            "BRG-1",
            "--diagnosis-time",
            "2026-05-20T08:00:00",
            "--output",
            str(tmp_path / "rotating_rule_result.json"),
        ],
    )

    assert module.main() == 0
    written = json.loads((tmp_path / "rotating_rule_result.json").read_text(encoding="utf-8"))
    assert written["ok"] is False
    assert written["error"]["type"] == "FileNotFoundError"
