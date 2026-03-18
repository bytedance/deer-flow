from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml

from src.research_writing.prompt_optimizer import run_prompt_optimizer


def _write_json(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_yaml(path, payload):
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _base_prompt_layers():
    return {
        "schema_version": "deerflow.prompt_asset_bundle.v1",
        "layers": {
            "L1": {
                "default_version": "v1",
                "rollback_version": "v0",
                "versions": {
                    "v0": "legacy protocol",
                    "v1": "strict runtime protocol",
                },
            },
            "L4": {
                "default_version": "v2",
                "rollback_version": "v0",
                "versions": {
                    "v0": "legacy style adapter",
                    "v2": "dynamic style adapter",
                    "ieee.v1": "IEEE profile base",
                },
            },
            "L5": {
                "default_version": "v2",
                "rollback_version": "v0",
                "versions": {
                    "v0": "legacy reasoning",
                    "v2": "hardened reasoning",
                },
            },
        },
        "venue_layer_overrides": {
            "ieee": {
                "L4": "ieee.v1",
            }
        },
    }


def test_run_prompt_optimizer_generates_candidate_versions_from_signals(tmp_path):
    prompt_layers_path = tmp_path / "prompt_layers.yaml"
    compile_metrics_path = tmp_path / "compile-gates.json"
    offline_report_path = tmp_path / "offline-regression.json"
    output_dir = tmp_path / "optimizer-output"

    _write_yaml(prompt_layers_path, _base_prompt_layers())
    _write_json(
        compile_metrics_path,
        {
            "safety_valve_reason_distribution": {
                "Hard grounding check detected conclusion sentences without [citation:*] binding.": 4,
                "Experimental details are under-specified; disclose n/sample size, random seed, and protocol details.": 3,
                "Failure-mode gate detected runtime risk: overclaim.": 2,
            }
        },
    )
    _write_json(
        offline_report_path,
        {
            "status": "fail",
            "failed_checks": [
                {"layer": "core", "name": "core_ece"},
                {"layer": "failure_mode", "name": "failure_mode_gate_status"},
            ],
        },
    )

    payload = run_prompt_optimizer(
        thread_id="thread-opt",
        compile_metrics_path=compile_metrics_path,
        offline_regression_report_path=offline_report_path,
        prompt_layers_path=prompt_layers_path,
        output_dir=output_dir,
        apply_prompt_patch=False,
        run_offline_validation=False,
    )

    assert payload["status"] == "candidate_generated"
    assert payload["optimizer_mode_used"] == "rules"
    assert payload["change_count"] == 3
    assert {item["layer_id"] for item in payload["changes"]} == {"L1", "L4", "L5"}

    candidate_path = output_dir / Path(payload["candidate_prompt_layers_path"]).name
    candidate = yaml.safe_load(candidate_path.read_text(encoding="utf-8"))
    assert candidate["layers"]["L1"]["default_version"] == "v2"
    assert "v2" in candidate["layers"]["L1"]["versions"]
    assert any("Reflection carry-over is mandatory" in line for line in candidate["layers"]["L1"]["versions"]["v2"].splitlines())
    assert candidate["venue_layer_overrides"]["ieee"]["L4"].startswith("ieee.v")
    assert candidate["venue_layer_overrides"]["ieee"]["L4"] != "ieee.v1"
    new_ieee_version = candidate["venue_layer_overrides"]["ieee"]["L4"]
    assert "Methods completeness gate" in candidate["layers"]["L4"]["versions"][new_ieee_version]
    assert candidate["layers"]["L5"]["default_version"] == "v3"
    assert "Causal-overclaim guard" in candidate["layers"]["L5"]["versions"]["v3"]


def test_run_prompt_optimizer_applies_patch_when_requested(tmp_path):
    prompt_layers_path = tmp_path / "prompt_layers.yaml"
    compile_metrics_path = tmp_path / "compile-gates.json"
    offline_report_path = tmp_path / "offline-regression.json"

    _write_yaml(prompt_layers_path, _base_prompt_layers())
    _write_json(
        compile_metrics_path,
        {
            "safety_valve_reason_distribution": {
                "Detected 1 unknown [citation:*] binding(s) not present in citation registry.": 1,
            }
        },
    )
    _write_json(offline_report_path, {"status": "pass", "failed_checks": []})

    payload = run_prompt_optimizer(
        thread_id="thread-opt-apply",
        compile_metrics_path=compile_metrics_path,
        offline_regression_report_path=offline_report_path,
        prompt_layers_path=prompt_layers_path,
        output_dir=tmp_path / "optimizer-output",
        apply_prompt_patch=True,
        run_offline_validation=False,
    )

    assert payload["applied_prompt_patch"] is True
    assert payload["status"] == "applied"
    patched = yaml.safe_load(prompt_layers_path.read_text(encoding="utf-8"))
    assert patched["layers"]["L1"]["default_version"] == "v2"
    assert "Fail-close gate" in patched["layers"]["L1"]["versions"]["v2"]


def test_run_prompt_optimizer_uses_llm_structured_patch_when_valid(tmp_path):
    prompt_layers_path = tmp_path / "prompt_layers.yaml"
    compile_metrics_path = tmp_path / "compile-gates.json"
    offline_report_path = tmp_path / "offline-regression.json"
    output_dir = tmp_path / "optimizer-output"

    _write_yaml(prompt_layers_path, _base_prompt_layers())
    _write_json(
        compile_metrics_path,
        {
            "safety_valve_reason_distribution": {
                "Hard grounding check detected conclusion sentences without [citation:*] binding.": 2,
            }
        },
    )
    _write_json(offline_report_path, {"status": "pass", "failed_checks": []})

    model = MagicMock()
    model.model = "optimizer-llm"
    model.invoke.return_value = MagicMock(
        content=json.dumps(
            {
                "optimizer_mode": "llm_structured_patch",
                "summary": "Tighten L1 fail-close protocol.",
                "patches": [
                    {
                        "layer_id": "L1",
                        "base_version": "v1",
                        "new_version": "v2",
                        "instructions_added": [
                            "- Fail-close gate: reject placeholder bindings before prose is accepted.",
                            "- Carry forward reflection diagnostics into the next rewrite prompt.",
                        ],
                        "instructions_removed": [],
                        "rationale": "Tighten the fail-close contract for repeated binding regressions.",
                    }
                ],
            }
        )
    )

    with patch("src.research_writing.prompt_optimizer.create_chat_model", return_value=model):
        payload = run_prompt_optimizer(
            thread_id="thread-opt-llm",
            compile_metrics_path=compile_metrics_path,
            offline_regression_report_path=offline_report_path,
            prompt_layers_path=prompt_layers_path,
            output_dir=output_dir,
            apply_prompt_patch=False,
            run_offline_validation=False,
            optimizer_config={
                "optimizer_mode": "llm_structured_patch",
                "model_name": "optimizer-llm",
            },
        )

    assert payload["status"] == "candidate_generated"
    assert payload["optimizer_mode_requested"] == "llm_structured_patch"
    assert payload["optimizer_mode_used"] == "llm_structured_patch"
    assert payload["fallback_reason"] is None
    assert payload["change_count"] == 1
    assert payload["candidate_prompt_patch_path"] is not None
    assert payload["optimizer_config"]["model_name"] == "optimizer-llm"
    assert payload["llm_candidate"]["llm_model_name"] == "optimizer-llm"
    assert payload["changes"][0]["instructions_added"][0].startswith("- Fail-close gate")

    candidate_path = output_dir / Path(payload["candidate_prompt_layers_path"]).name
    candidate = yaml.safe_load(candidate_path.read_text(encoding="utf-8"))
    assert candidate["layers"]["L1"]["default_version"] == "v2"
    assert "Carry forward reflection diagnostics" in candidate["layers"]["L1"]["versions"]["v2"]


def test_run_prompt_optimizer_falls_back_to_rules_when_llm_patch_invalid(tmp_path):
    prompt_layers_path = tmp_path / "prompt_layers.yaml"
    compile_metrics_path = tmp_path / "compile-gates.json"
    offline_report_path = tmp_path / "offline-regression.json"
    output_dir = tmp_path / "optimizer-output"

    _write_yaml(prompt_layers_path, _base_prompt_layers())
    _write_json(
        compile_metrics_path,
        {
            "safety_valve_reason_distribution": {
                "Hard grounding check detected conclusion sentences without [citation:*] binding.": 2,
            }
        },
    )
    _write_json(offline_report_path, {"status": "pass", "failed_checks": []})

    model = MagicMock()
    model.model = "optimizer-llm"
    model.invoke.return_value = MagicMock(
        content=json.dumps(
            {
                "optimizer_mode": "llm_structured_patch",
                "summary": "Invalid patch should be rejected.",
                "patches": [
                    {
                        "layer_id": "L2",
                        "base_version": "v1",
                        "new_version": "v2",
                        "instructions_added": ["- Invalid layer patch."],
                        "instructions_removed": [],
                        "rationale": "This should be rejected because L2 is not allowed.",
                    }
                ],
            }
        )
    )

    with patch("src.research_writing.prompt_optimizer.create_chat_model", return_value=model):
        payload = run_prompt_optimizer(
            thread_id="thread-opt-llm-fallback",
            compile_metrics_path=compile_metrics_path,
            offline_regression_report_path=offline_report_path,
            prompt_layers_path=prompt_layers_path,
            output_dir=output_dir,
            apply_prompt_patch=False,
            run_offline_validation=False,
            optimizer_config={
                "optimizer_mode": "llm_structured_patch",
                "model_name": "optimizer-llm",
            },
        )

    assert payload["status"] == "candidate_generated"
    assert payload["optimizer_mode_requested"] == "llm_structured_patch"
    assert payload["optimizer_mode_used"] == "rules"
    assert payload["fallback_reason"] == "llm_structured_patch_validation_failed"
    assert payload["change_count"] == 1
    assert payload["validation_issues"]
    assert payload["candidate_prompt_patch_path"] is not None

    candidate_path = output_dir / Path(payload["candidate_prompt_layers_path"]).name
    candidate = yaml.safe_load(candidate_path.read_text(encoding="utf-8"))
    assert candidate["layers"]["L1"]["default_version"] == "v2"
    assert "Fail-close gate" in candidate["layers"]["L1"]["versions"]["v2"]


def test_run_prompt_optimizer_passes_explicit_optimizer_config_to_model_factory(tmp_path):
    prompt_layers_path = tmp_path / "prompt_layers.yaml"
    compile_metrics_path = tmp_path / "compile-gates.json"
    offline_report_path = tmp_path / "offline-regression.json"
    output_dir = tmp_path / "optimizer-output"

    _write_yaml(prompt_layers_path, _base_prompt_layers())
    _write_json(
        compile_metrics_path,
        {
            "safety_valve_reason_distribution": {
                "Hard grounding check detected conclusion sentences without [citation:*] binding.": 1,
            }
        },
    )
    _write_json(offline_report_path, {"status": "pass", "failed_checks": []})

    model = MagicMock()
    model.model = "optimizer-llm"
    model.invoke.return_value = MagicMock(
        content=json.dumps(
            {
                "optimizer_mode": "llm_structured_patch",
                "summary": "Tighten L1 fail-close protocol.",
                "patches": [
                    {
                        "layer_id": "L1",
                        "base_version": "v1",
                        "new_version": "v2",
                        "instructions_added": ["- Fail-close gate: reject placeholder bindings before prose is accepted."],
                        "instructions_removed": [],
                        "rationale": "Tighten fail-close behavior.",
                    }
                ],
            }
        )
    )

    with patch("src.research_writing.prompt_optimizer.create_chat_model", return_value=model) as create_model_mock:
        payload = run_prompt_optimizer(
            thread_id="thread-opt-config",
            compile_metrics_path=compile_metrics_path,
            offline_regression_report_path=offline_report_path,
            prompt_layers_path=prompt_layers_path,
            output_dir=output_dir,
            apply_prompt_patch=False,
            run_offline_validation=False,
            optimizer_config={
                "enabled": True,
                "optimizer_mode": "llm_structured_patch",
                "model_name": "optimizer-llm",
                "thinking_enabled": True,
                "temperature": 0.3,
                "max_candidate_count": 2,
                "fallback_to_rules": True,
            },
        )

    create_model_mock.assert_called_once_with(
        name="optimizer-llm",
        thinking_enabled=True,
        temperature=0.3,
    )
    assert payload["optimizer_config"]["max_candidate_count"] == 2
    assert payload["optimizer_config"]["thinking_enabled"] is True
