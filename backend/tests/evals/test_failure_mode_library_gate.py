"""Regression gates for failure-mode red-team library."""

from __future__ import annotations

import json
from unittest.mock import patch

from src.config.failure_mode_gate_config import FailureModeGateConfig, get_failure_mode_gate_config, set_failure_mode_gate_config
from src.config.paths import Paths
from src.evals.academic import evaluate_failure_mode_library, load_builtin_eval_cases
from src.research_writing.runtime_service import evaluate_academic_and_persist


def test_failure_mode_library_builtin_gate_pass():
    cases = load_builtin_eval_cases("failure_mode_library_v1")
    report = evaluate_failure_mode_library(cases)

    assert report["status"] == "pass"
    assert report["case_count"] >= 9
    assert report["targeted_case_count"] >= 7
    assert report["control_case_count"] >= 2
    assert report["failed_modes"] == []


def test_failure_mode_library_mode_level_recall_and_false_positive():
    cases = load_builtin_eval_cases("failure_mode_library_v1")
    report = evaluate_failure_mode_library(cases)
    by_mode = report["by_mode"]

    expected_modes = {
        "citation_hallucination",
        "overclaim",
        "numeric_drift",
        "evidence_chain_break",
        "style_mismatch",
        "superficial_rebuttal",
        "ethics_gap",
    }
    assert expected_modes.issubset(set(by_mode))
    for mode in expected_modes:
        row = by_mode[mode]
        assert row["targeted_case_count"] >= 1
        assert row["target_recall"] >= 0.95
        assert row["control_false_positive_rate"] <= 0.2
        assert row["status"] == "pass"


def test_evaluate_academic_persists_failure_mode_gate_artifact(tmp_path):
    paths = Paths(base_dir=tmp_path)
    cases = load_builtin_eval_cases("failure_mode_library_v1")

    with patch("src.research_writing.runtime_service.get_paths", return_value=paths):
        payload = evaluate_academic_and_persist(
            "thread-failure-mode",
            cases=cases,
            name="failure-mode-regression",
            dataset_name="failure_mode_library_v1",
        )

    assert payload["failure_mode_gate_status"] == "pass"
    assert payload["failure_mode_gate_schema_version"] == "deerflow.failure_mode_gates.v1"
    assert payload["failure_mode_gate_artifact_path"].startswith("/mnt/user-data/outputs/research-writing/evals/")

    gate_path = paths.resolve_virtual_path("thread-failure-mode", payload["failure_mode_gate_artifact_path"])
    gate_payload = json.loads(gate_path.read_text(encoding="utf-8"))
    assert gate_payload["schema_version"] == "deerflow.failure_mode_gates.v1"
    assert gate_payload["status"] == "pass"


def test_evaluate_academic_uses_configured_failure_mode_gate_thresholds(tmp_path):
    previous = get_failure_mode_gate_config().model_copy(deep=True)
    paths = Paths(base_dir=tmp_path)
    cases = load_builtin_eval_cases("failure_mode_library_v1")
    try:
        set_failure_mode_gate_config(
            FailureModeGateConfig(
                citation_fidelity_max=0.71,
                overclaim_claim_grounding_max=0.61,
                numeric_drift_abstract_body_max=0.79,
                evidence_chain_claim_grounding_max=0.51,
                style_mismatch_venue_fit_max=0.69,
                superficial_rebuttal_completeness_max=0.67,
                min_target_recall=0.96,
                max_control_false_positive_rate=0.12,
            )
        )
        with patch("src.research_writing.runtime_service.get_paths", return_value=paths):
            payload = evaluate_academic_and_persist(
                "thread-failure-mode-thresholds",
                cases=cases,
                name="failure-mode-thresholds",
                dataset_name="failure_mode_library_v1",
            )
        gate_path = paths.resolve_virtual_path("thread-failure-mode-thresholds", payload["failure_mode_gate_artifact_path"])
        gate_payload = json.loads(gate_path.read_text(encoding="utf-8"))
        thresholds = gate_payload["thresholds"]
        assert thresholds["citation_fidelity_max"] == 0.71
        assert thresholds["overclaim_claim_grounding_max"] == 0.61
        assert thresholds["numeric_drift_abstract_body_max"] == 0.79
        assert thresholds["evidence_chain_claim_grounding_max"] == 0.51
        assert thresholds["style_mismatch_venue_fit_max"] == 0.69
        assert thresholds["superficial_rebuttal_completeness_max"] == 0.67
        assert thresholds["min_target_recall"] == 0.96
        assert thresholds["max_control_false_positive_rate"] == 0.12
    finally:
        set_failure_mode_gate_config(previous)

