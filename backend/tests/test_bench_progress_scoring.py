"""Offline regression checks for the #2805 trace replay benchmark."""

import json
import os
from pathlib import Path

import pytest

from scripts.benchmark.progress_scoring.benchmark import CONFIG_PATH, FIXTURES_PATH, HERE, load_inputs, summarize, text_sha256, validate_checkout
from scripts.benchmark.progress_scoring.worker import expand_case, replay


def test_fixture_contract_and_deterministic_expansion():
    config, cases = load_inputs(CONFIG_PATH, FIXTURES_PATH)
    assert {case["scenario"] for case in cases} >= {"identical_calls", "failed_varied_calls", "cross_tool_identical", "distinct_stagnation", "legitimate_long"}
    assert len({case["id"] for case in cases}) == len(cases)
    for case in cases:
        assert expand_case(case) == expand_case(case)
        assert len(expand_case(case)) == case["steps"]
    assert config["candidate_revision"] == "974f8fc6a5edce3b1ee5aa478351b6f3cc572ea9"


@pytest.mark.parametrize("field,value", [("steps", True), ("steps", 0), ("stalled", "yes"), ("evaluation", {"task_progress": 4, "tool_usefulness": 0})])
def test_invalid_fixture_rejected(tmp_path, field, value):
    payload = json.loads(FIXTURES_PATH.read_text(encoding="utf-8"))
    payload["cases"][0][field] = value
    fixture = tmp_path / "fixtures.json"
    fixture.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError):
        load_inputs(CONFIG_PATH, fixture)


def test_loop_warns_and_stops_identical_calls():
    config, cases = load_inputs(CONFIG_PATH, FIXTURES_PATH)
    row = replay("loop_detection", cases[0], config["policies"]["loop_detection"])
    assert row["first_intervention_step"] == 3
    assert row["first_hard_stop_step"] == 5
    assert row["score_output_bytes"] == 0


def test_tool_progress_warns_recoverable_failure_without_blocking():
    config, cases = load_inputs(CONFIG_PATH, FIXTURES_PATH)
    case = next(case for case in cases if case["id"] == "varied_no_results")
    row = replay("tool_progress", case, config["policies"]["tool_progress"])
    assert row["first_intervention_step"] == 3
    assert row["first_hard_stop_step"] is None


def test_long_distinct_outputs_expose_raw_frequency_stop():
    config, cases = load_inputs(CONFIG_PATH, FIXTURES_PATH)
    case = next(case for case in cases if case["id"] == "long_bash_artifacts")
    loop = replay("loop_detection", case, config["policies"]["loop_detection"])
    progress = replay("tool_progress", case, config["policies"]["tool_progress"])
    assert loop["first_intervention_step"] == 30
    assert loop["first_hard_stop_step"] == 50
    assert progress["first_intervention_step"] is None


def test_confusion_matrix_excludes_noncompliance_and_has_explicit_denominators():
    rows = [
        {"policy": "p", "stalled": True, "first_intervention_step": 3, "first_hard_stop_step": None},
        {"policy": "p", "stalled": True, "first_intervention_step": None, "first_hard_stop_step": None, "events": [{"action": "eval_noncompliance"}]},
        {"policy": "p", "stalled": False, "first_intervention_step": 30, "first_hard_stop_step": 50},
        {"policy": "p", "stalled": False, "first_intervention_step": None, "first_hard_stop_step": None},
    ]
    summary = summarize(rows)["p"]
    assert summary == {"tp": 1, "fn": 1, "fp": 1, "tn": 1, "stalled_cases": 2, "legitimate_cases": 2, "tpr": 0.5, "fpr": 0.5, "hard_stops": 1}


def test_source_pin_rejects_modified_checkout(tmp_path):
    config, _ = load_inputs(CONFIG_PATH, FIXTURES_PATH)
    relative = next(iter(config["source_hashes"]["baseline"]))
    source = tmp_path / relative
    source.parent.mkdir(parents=True)
    source.write_text("modified", encoding="utf-8")
    with pytest.raises(ValueError, match="Source pin mismatch"):
        validate_checkout(tmp_path, config["source_hashes"]["baseline"])


def test_source_pins_match_baseline_checkout():
    config, _ = load_inputs(CONFIG_PATH, FIXTURES_PATH)
    validate_checkout(Path(__file__).resolve().parents[2], config["source_hashes"]["baseline"])


def test_source_pins_ignore_checkout_newline_style(tmp_path):
    import hashlib

    source = tmp_path / "policy.py"
    source.write_bytes(b"# policy\r\nvalue = 1\r\n")
    expected = hashlib.sha256(b"# policy\nvalue = 1\n").hexdigest()
    validate_checkout(tmp_path, {"policy.py": expected})


def test_tokenizer_rejects_unverified_vocabulary_before_loading(tmp_path):
    from scripts.benchmark.progress_scoring.worker import local_encoding

    vocabulary = tmp_path / "bad.tiktoken"
    vocabulary.write_bytes(b"not the pinned vocabulary")
    with pytest.raises(ValueError, match="Tokenizer SHA-256 mismatch"):
        local_encoding(vocabulary, "0" * 64)


def test_committed_report_matches_inputs_sources_and_recomputed_metrics():
    import hashlib

    report = json.loads((HERE / "results/report.json").read_text(encoding="utf-8"))
    manifest = json.loads((HERE / "results/sources.json").read_text(encoding="utf-8"))
    assert report["config_sha256"] == text_sha256(CONFIG_PATH)
    assert report["fixtures_sha256"] == text_sha256(FIXTURES_PATH)
    assert report["benchmark_sources"] == {path.name: text_sha256(path) for path in sorted(HERE.glob("*.py"))}
    assert report["summary"] == summarize(report["rows"])
    assert report["loaded_source_manifest_sha256"] == hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()


@pytest.mark.skipif(not os.environ.get("PROGRESS_BENCH_CANDIDATE_ROOT"), reason="optional local checkout of pinned PR #5851")
def test_candidate_semantic_veto_and_protocol_noncompliance():
    from scripts.benchmark.progress_scoring.benchmark import run_worker

    config, cases = load_inputs(CONFIG_PATH, FIXTURES_PATH)
    root = Path(os.environ["PROGRESS_BENCH_CANDIDATE_ROOT"])
    validate_checkout(root, config["source_hashes"]["candidate"])
    selected = [case for case in cases if case["id"] in {"distinct_stagnation", "cross_tool_identical", "missing_evaluations"}]
    rows = run_worker(root, "progress_scoring", selected, config)
    assert rows == run_worker(root, "progress_scoring", selected, config)
    by_id = {row["case_id"]: row for row in rows}
    assert by_id["distinct_stagnation"]["first_intervention_step"] is None
    assert by_id["cross_tool_identical"]["first_intervention_step"] == 3
    assert by_id["missing_evaluations"]["first_intervention_step"] is None
    assert any(event["action"] == "eval_noncompliance" for event in by_id["missing_evaluations"]["events"])
    assert by_id["cross_tool_identical"]["protocol_input_bytes"] > 0
    assert by_id["cross_tool_identical"]["score_output_bytes"] > 0
    assert by_id["cross_tool_identical"]["protocol_model_calls"] == by_id["cross_tool_identical"]["steps"] + 1
