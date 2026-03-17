"""Tests for layered offline benchmark suite builder."""

from __future__ import annotations

import json
from pathlib import Path

from src.evals.academic import (
    REQUIRED_RAW_RECORD_FIELDS,
    TARGET_HARD_NEGATIVE_FAILURE_MODES,
    build_offline_benchmark_layers,
    load_builtin_eval_cases,
    write_offline_benchmark_layers,
)
from src.evals.academic.validator import validate_accept_reject_payload


def test_build_offline_benchmark_layers_contains_required_layers():
    core_cases = load_builtin_eval_cases("top_tier_accept_reject_v1")
    failure_cases = load_builtin_eval_cases("failure_mode_library_v1")

    layers = build_offline_benchmark_layers(core_cases, failure_cases)
    assert set(layers) == {"core", "failure_mode", "domain_ai_cs", "domain_biomed", "domain_cross_discipline"}
    assert layers["core"]["records"]
    assert layers["failure_mode"]["records"]
    assert layers["domain_ai_cs"]["records"]
    assert layers["domain_biomed"]["records"]
    assert layers["domain_cross_discipline"]["records"]
    assert all(record["domain"] == "ai_cs" for record in layers["domain_ai_cs"]["records"])
    assert all(record["domain"] == "biomed" for record in layers["domain_biomed"]["records"])
    assert all(record["domain"] == "cross_discipline" for record in layers["domain_cross_discipline"]["records"])


def test_offline_benchmark_layers_all_records_have_required_fields():
    core_cases = load_builtin_eval_cases("top_tier_accept_reject_v1")
    failure_cases = load_builtin_eval_cases("failure_mode_library_v1")
    layers = build_offline_benchmark_layers(core_cases, failure_cases)

    required = set(REQUIRED_RAW_RECORD_FIELDS)
    for payload in layers.values():
        records = payload["records"]
        for record in records:
            assert required.issubset(set(record.keys()))


def test_failure_mode_layer_contains_target_hard_negatives():
    core_cases = load_builtin_eval_cases("top_tier_accept_reject_v1")
    failure_cases = load_builtin_eval_cases("failure_mode_library_v1")
    layers = build_offline_benchmark_layers(core_cases, failure_cases)

    target_set = set(TARGET_HARD_NEGATIVE_FAILURE_MODES)
    covered: set[str] = set()
    for record in layers["failure_mode"]["records"]:
        covered.update(
            mode
            for mode in record.get("failure_modes", [])
            if isinstance(mode, str) and mode in target_set
        )
    assert target_set.issubset(covered)


def test_write_offline_benchmark_layers_outputs_importable_payloads(tmp_path: Path):
    written = write_offline_benchmark_layers(tmp_path, overwrite=True)
    assert set(written) == {"core", "failure_mode", "domain_ai_cs", "domain_biomed", "domain_cross_discipline"}
    for path in written.values():
        payload = json.loads(path.read_text(encoding="utf-8"))
        report = validate_accept_reject_payload(payload, source_path_label=str(path))
        assert report["error_count"] == 0

