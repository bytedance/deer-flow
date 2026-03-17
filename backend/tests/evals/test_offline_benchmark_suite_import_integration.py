"""Integration tests for layered offline benchmark suite import/eval loop."""

from __future__ import annotations

from src.evals.academic import (
    TARGET_HARD_NEGATIVE_FAILURE_MODES,
    evaluate_dataset,
    evaluate_failure_mode_library,
    import_accept_reject_payload,
    write_offline_benchmark_layers,
)


def test_offline_core_layer_import_supports_auc_ece_brier(tmp_path):
    written = write_offline_benchmark_layers(tmp_path, overwrite=True)
    core_raw = written["core"]
    imported = import_accept_reject_payload(
        raw_payload=load_raw_payload(core_raw),
        source_path_label=str(core_raw),
        dataset_name="offline_core",
        dataset_version="2026_03",
        benchmark_split="offline_core",
        source_name="offline-suite-integration",
        anonymize=False,
        strict=True,
    )

    cases = load_eval_cases_payload(imported["dataset_payload"])
    summary = evaluate_dataset(cases)
    assert summary.accepted_case_count > 0
    assert summary.rejected_case_count > 0
    assert 0.0 <= summary.auc_accept_reject <= 1.0
    assert 0.0 <= summary.ece <= 1.0
    assert summary.brier_score >= 0.0


def test_offline_failure_mode_layer_import_supports_redteam_gate(tmp_path):
    written = write_offline_benchmark_layers(tmp_path, overwrite=True)
    failure_raw = written["failure_mode"]
    imported = import_accept_reject_payload(
        raw_payload=load_raw_payload(failure_raw),
        source_path_label=str(failure_raw),
        dataset_name="offline_failure_mode",
        dataset_version="2026_03",
        benchmark_split="offline_failure_mode",
        source_name="offline-suite-integration",
        anonymize=False,
        strict=True,
    )

    cases = load_eval_cases_payload(imported["dataset_payload"])
    report = evaluate_failure_mode_library(cases)
    assert report["status"] == "pass"
    assert report["targeted_case_count"] >= len(TARGET_HARD_NEGATIVE_FAILURE_MODES)
    assert all(case.failure_modes for case in cases)


def test_offline_domain_split_layers_keep_expected_domain_labels(tmp_path):
    written = write_offline_benchmark_layers(tmp_path, overwrite=True)
    expected = {
        "domain_ai_cs": "ai_cs",
        "domain_biomed": "biomed",
        "domain_cross_discipline": "cross_discipline",
    }
    for layer_key, expected_domain in expected.items():
        path = written[layer_key]
        imported = import_accept_reject_payload(
            raw_payload=load_raw_payload(path),
            source_path_label=str(path),
            dataset_name=f"offline_{layer_key}",
            dataset_version="2026_03",
            benchmark_split=layer_key,
            source_name="offline-suite-integration",
            anonymize=False,
            strict=True,
        )
        cases = load_eval_cases_payload(imported["dataset_payload"])
        assert cases
        assert all(case.domain == expected_domain for case in cases)


def load_raw_payload(path):
    import json

    return json.loads(path.read_text(encoding="utf-8"))


def load_eval_cases_payload(payload):
    from src.evals.academic.schemas import AcademicEvalCase

    return [AcademicEvalCase.model_validate(item) for item in payload["cases"]]

