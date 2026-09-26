"""Tests for scripts/eval_memory_prescreen.py.

The script is the pre-``enforce`` evidence for the memory pre-screen, so its
arithmetic has to stay honest when the record set is thin or contradictory: a
cache hit and a local fallback must never vote on the model's accuracy, a skip
whose outcome is unknown must be censored rather than counted as saved, and the
miss-rate bound must be the exact Clopper-Pearson interval it claims to be.

Only the pure analysis logic is covered here — population classification, the
saved/miss arithmetic, the no-network baseline comparison, the confidence bound
and the gate outcomes. The JSONL loading and the report printing are plumbing.
"""

from __future__ import annotations

import argparse
import importlib.util
import math
import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "eval_memory_prescreen.py"

spec = importlib.util.spec_from_file_location("deerflow_eval_memory_prescreen", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
eval_script = importlib.util.module_from_spec(spec)
# dataclasses resolve ``cls.__module__`` through sys.modules, so register first.
sys.modules[spec.name] = eval_script
spec.loader.exec_module(eval_script)


def _payload(**overrides: Any) -> dict[str, Any]:
    """A shadow record shaped exactly like the DeerMem ``extraction_callback`` payload."""
    payload: dict[str, Any] = {
        "thread_id": "thread-1",
        "success": True,
        "token_usage": {"input_tokens": 100, "output_tokens": 20},
        "mutations_accepted": 0,
        "prescreen": {
            "mode": "shadow",
            "verdict": "skip",
            "probability": 0.05,
            "skip_threshold": 0.2,
            "model": "jev-latest",
            "cached": False,
            "digest": "digest-0",
            "signals": [],
            "message_count": 4,
            "batch_chars": 400,
            "duration_ms": 40.0,
            "fallback_reason": None,
        },
    }
    prescreen_override = overrides.pop("prescreen", "absent")
    if prescreen_override != "absent":
        if prescreen_override is None:
            del payload["prescreen"]
        else:
            payload["prescreen"].update(prescreen_override)
    for key, value in overrides.items():
        if value is None:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


def _record(**overrides: Any):
    return eval_script.parse_record(1, _payload(**overrides))


def _fallback(reason: str):
    return _record(prescreen={"verdict": None, "cached": None, "fallback_reason": reason}, mutations_accepted=None, success=True)


def _population(records, name: str) -> dict[str, Any]:
    return eval_script.summarize_population(records, name)


# --- classification -------------------------------------------------------


def test_classify_population_is_mutually_exclusive_across_the_design_populations():
    assert eval_script.classify_population(_payload()) == eval_script.NETWORK
    assert eval_script.classify_population(_payload(prescreen={"cached": True})) == eval_script.CACHE_HIT
    assert eval_script.classify_population(_payload(prescreen={"verdict": None, "cached": None, "fallback_reason": "over_limit"})) == eval_script.LOCAL_FALLBACK
    assert eval_script.classify_population(_payload(prescreen={"verdict": None, "cached": None, "fallback_reason": "deterministic_signals"})) == eval_script.LOCAL_FALLBACK
    assert eval_script.classify_population(_payload(prescreen=None)) == eval_script.UNJUDGED
    assert eval_script.classify_population({"success": True}) == eval_script.UNJUDGED
    for name in (eval_script.NETWORK, eval_script.CACHE_HIT, eval_script.LOCAL_FALLBACK, eval_script.UNJUDGED):
        assert name in eval_script.POPULATIONS


def test_local_fallback_reasons_map_to_their_design_locks():
    records = [_fallback("deterministic_signals"), _fallback("over_limit"), _fallback("emergency_flush"), _fallback("shutdown_drain"), _fallback("staleness_or_consolidation"), _fallback("no_verdict")]
    summary = _population(records, eval_script.LOCAL_FALLBACK)
    assert summary["records"] == 6
    assert summary["verdicts"] == {"skip": 0, "extract": 0, "none": 6}
    assert summary["fallback_reasons"]["deterministic_signals"] == 1
    assert summary["fallback_locks"] == {"L3": 1, "L4": 1, "L5": 1, "L7": 1, "L8": 1, "failure": 1}


def test_local_fallbacks_and_cache_hits_stay_out_of_the_classifier_rates():
    records = [
        _record(mutations_accepted=0),
        _record(prescreen={"verdict": "extract"}, mutations_accepted=3),
        _record(prescreen={"cached": True}, mutations_accepted=5),
        _fallback("over_limit"),
    ]
    network = _population(records, eval_script.NETWORK)
    assert network["records"] == 2
    assert network["verdicts"] == {"skip": 1, "extract": 1, "none": 0}
    assert network["scored_skips"] == 1
    assert network["misses"] == 0
    assert network["miss_rate"] == 0.0
    assert _population(records, eval_script.CACHE_HIT)["misses"] == 1
    assert _population(records, eval_script.LOCAL_FALLBACK)["scored_skips"] == 0


def test_sensitive_labels_are_read_from_stratum_and_labels_and_normalised():
    record = eval_script.parse_record(1, _payload(stratum="Preference", labels=["identity", "chatter", 7]))
    assert record.sensitive_labels == {"preference", "identity"}
    assert record.sensitive is True
    assert eval_script.parse_record(1, _payload(stratum="chatter")).sensitive is False


# --- saved / miss arithmetic ---------------------------------------------


def test_saved_and_miss_rates_are_complementary_over_scored_skips():
    records = [_record(mutations_accepted=0), _record(mutations_accepted=0), _record(mutations_accepted=0), _record(mutations_accepted=2), _record(prescreen={"verdict": "extract"}, mutations_accepted=1)]
    summary = _population(records, eval_script.NETWORK)
    assert summary["skip_rate"] == 4 / 5
    assert summary["scored_skips"] == 4
    assert summary["saved_calls"] == 3
    assert summary["saved_call_rate"] == 0.75
    assert summary["misses"] == 1
    assert summary["miss_rate"] == 0.25
    assert summary["saved_call_rate"] + summary["miss_rate"] == 1.0
    assert summary["saved_call_rate_over_all_verdicts"] == 3 / 5


def test_a_skip_without_an_outcome_is_censored_not_counted_as_saved():
    censored_skip = _record(mutations_accepted=None)
    failed_extract = _record(prescreen={"verdict": "extract"}, mutations_accepted=None, success=False)
    scored_skip = _record(mutations_accepted=0)
    records = [censored_skip, failed_extract, scored_skip]
    summary = _population(records, eval_script.NETWORK)
    assert censored_skip.censored is True
    assert censored_skip.censored_reason == eval_script.CENSORED_OUTCOME_NOT_RECORDED
    assert failed_extract.censored is True
    assert failed_extract.censored_reason == eval_script.CENSORED_EXTRACTION_FAILED
    assert scored_skip.censored is False
    assert summary["censored"] == 2
    assert summary["censored_reasons"] == {eval_script.CENSORED_OUTCOME_NOT_RECORDED: 1, eval_script.CENSORED_EXTRACTION_FAILED: 1}
    assert summary["scored_skips"] == 1
    assert summary["saved_call_rate"] == 1.0


def test_a_manual_review_is_a_second_ground_truth_witness_for_a_skip():
    reviewed_saved = _record(mutations_accepted=None, reviewed=True, review_outcome="none_worth_remembering")
    reviewed_missed = _record(mutations_accepted=0, reviewed=True, review_outcome="worth_remembering")
    contradicted = _record(mutations_accepted=2, reviewed=True, review_outcome="none_worth_remembering")
    summary = _population([reviewed_saved, reviewed_missed, contradicted], eval_script.NETWORK)
    assert reviewed_saved.censored is False and reviewed_saved.miss is False
    assert reviewed_missed.miss is True
    assert contradicted.miss is True, "a review saying not-worth never clears a counter that says otherwise"
    assert summary["scored_skips"] == 3
    assert summary["saved_calls"] == 1
    assert summary["misses"] == 2


def test_missed_digests_are_reported_for_audit():
    records = [_record(prescreen={"digest": "lost-1"}, mutations_accepted=1), _record(prescreen={"digest": "kept-0"}, mutations_accepted=0)]
    summary = _population(records, eval_script.NETWORK)
    assert summary["missed_digests"] == ["lost-1"]


# --- heuristic baseline ---------------------------------------------------


def test_baseline_comparison_scores_both_policies_on_the_same_records():
    records = [
        _record(trivial_only=True, mutations_accepted=0),  # baseline skip, saved
        _record(trivial_only=True, mutations_accepted=1),  # baseline skip, missed
        _record(trivial_only=False, mutations_accepted=0),  # baseline extracts
        _record(prescreen={"signals": ["preference"]}, trivial_only=True, mutations_accepted=0),  # a signal blocks the baseline
    ]
    baseline = eval_script.baseline_summary(records)
    assert baseline["evaluated_verdicts"] == 4
    assert baseline["computable"] == 4
    assert baseline["coverage"] == 1.0
    assert baseline["skips"] == 2
    assert baseline["saved_calls"] == 1
    assert baseline["misses"] == 1
    assert baseline["saved_call_rate"] == 0.5
    assert baseline["miss_rate"] == 0.5
    model = baseline["model"]
    assert model["skips"] == 4 and model["saved_calls"] == 3 and model["misses"] == 1
    assert model["saved_call_rate"] == 0.75
    assert baseline["incremental_saved_calls"] == 2
    assert baseline["incremental_saved_call_rate"] == 2 / 4, "incremental saving is measured over the shared scored set"


def test_incremental_saving_uses_the_shared_denominator_not_the_conditional_rates():
    """Different skip rates: subtracting conditional rates hides real call savings.

    Both policies saved every batch they skipped, so both conditional rates are
    1.0 and their difference is 0 — yet the model skipped 70 more batches. The
    incremental rate must be (model_saved - baseline_saved) / scored.
    """
    records = (
        [_record(trivial_only=True, mutations_accepted=0) for _ in range(10)]  # both skip, harmless
        + [_record(trivial_only=False, mutations_accepted=0) for _ in range(70)]  # model-only skip, harmless
        + [_record(trivial_only=False, prescreen={"verdict": "extract"}, mutations_accepted=1) for _ in range(20)]  # neither skips
    )
    baseline = eval_script.baseline_summary(records)

    assert baseline["scored"] == 100
    assert baseline["saved_calls"] == 10
    assert baseline["model"]["saved_calls"] == 80
    assert baseline["saved_call_rate"] == 1.0 and baseline["model"]["saved_call_rate"] == 1.0, "the conditional rates stay in the report"
    assert baseline["incremental_saved_calls"] == 70
    assert baseline["incremental_saved_call_rate"] == 70 / 100, "70 extra saved calls over 100 scored records"


def test_baseline_reports_coverage_instead_of_shrinking_the_denominator():
    records = [
        _record(mutations_accepted=0),
        _record(trivial_only=True, mutations_accepted=0),
        _record(prescreen={"signals": "unreadable"}, trivial_only=True),
    ]
    baseline = eval_script.baseline_summary(records)
    assert baseline["evaluated_verdicts"] == 3
    assert baseline["computable"] == 1
    assert baseline["coverage"] == 1 / 3
    assert baseline["trivial_only_missing"] == 1
    assert baseline["signals_missing"] == 1
    assert baseline["skips"] == 1
    assert baseline["incremental_saved_calls"] == 0

    empty = eval_script.baseline_summary([_record()])
    assert empty["computable"] == 0
    assert empty["coverage"] == 0.0
    assert empty["saved_call_rate"] is None and empty["miss_rate"] is None


# --- confidence bound -----------------------------------------------------


def test_clopper_pearson_upper_matches_known_reference_values():
    # Zero misses: the bound is 1 - alpha ** (1 / n) exactly.
    assert math.isclose(eval_script.clopper_pearson_upper(0, 10), 1 - 0.05**0.1, rel_tol=1e-9)
    assert math.isclose(eval_script.clopper_pearson_upper(0, 10), 0.25887, abs_tol=1e-4)
    # Published table value: the two-sided 95% upper limit of 0/20 is 0.16843.
    assert math.isclose(eval_script.clopper_pearson_upper(0, 20, confidence=0.975), 0.16843, abs_tol=1e-4)
    assert eval_script.clopper_pearson_upper(0, 0) is None
    assert eval_script.clopper_pearson_upper(4, 4) == 1.0


def test_clopper_pearson_upper_satisfies_its_defining_equation():
    alpha = 1 - eval_script.DEFAULT_CONFIDENCE
    for misses, skips in ((0, 200), (1, 200), (3, 50), (7, 30), (2, 3)):
        bound = eval_script.clopper_pearson_upper(misses, skips)
        solved = eval_script._regularized_incomplete_beta(skips - misses, misses + 1, 1 - bound)
        assert math.isclose(solved, alpha, rel_tol=1e-6), (misses, skips, solved)


def test_clopper_pearson_upper_is_monotone_in_samples_and_in_misses():
    assert eval_script.clopper_pearson_upper(0, 10) > eval_script.clopper_pearson_upper(0, 200)
    assert eval_script.clopper_pearson_upper(0, 200) > eval_script.clopper_pearson_upper(0, 2000)
    assert eval_script.clopper_pearson_upper(1, 200) > eval_script.clopper_pearson_upper(0, 200)
    assert eval_script.clopper_pearson_upper(5, 200) > eval_script.clopper_pearson_upper(1, 200)
    for misses, skips in ((0, 1), (1, 10), (9, 10), (0, 200)):
        bound = eval_script.clopper_pearson_upper(misses, skips)
        assert misses / skips <= bound <= 1.0


def test_clopper_pearson_upper_rejects_an_impossible_confidence():
    with pytest.raises(ValueError):
        eval_script.clopper_pearson_upper(0, 10, confidence=1.0)


# --- gates ----------------------------------------------------------------


def _gates(evidence, coverage) -> dict[str, str]:
    return {gate.gate_id: gate.status for gate in eval_script.evaluate_gates(evidence, coverage)}


def _evidence(**overrides: Any):
    base = {
        "scored_skips": 250,
        "misses": 0,
        "saved_calls": 250,
        "sensitive_scored_skips": {"identity": 2, "preference": 2, "correction": 1},
        "sensitive_misses": {"identity": 0, "preference": 0, "correction": 0},
        "reviewed_skips": 200,
        "reviewed_scored_skips": 200,
        "reviewed_missed": 0,
        "saved_skips_with_tokens": 250,
        "latency_samples": 250,
        "baseline_computable": 250,
    }
    base.update(overrides)
    return eval_script.Evidence(**base)


_CLEAN_COVERAGE = eval_script.Coverage(records=260, censored=10, malformed_lines=0)


def test_every_gate_passes_on_a_clean_run():
    assert _gates(_evidence(), _CLEAN_COVERAGE) == {
        "network_miss_rate": eval_script.PASS,
        "sensitive_stratum_zero_misses": eval_script.PASS,
        "reviewed_skips_confirm_no_loss": eval_script.PASS,
        "censoring_disclosed": eval_script.PASS,
        "savings_recorded": eval_script.PASS,
    }


@pytest.mark.parametrize(
    ("overrides", "coverage", "expected"),
    [
        ({"misses": 3, "saved_calls": 247}, None, "network_miss_rate"),
        ({"sensitive_misses": {"identity": 1}}, None, "sensitive_stratum_zero_misses"),
        ({"reviewed_skips": 199}, None, "reviewed_skips_confirm_no_loss"),
        ({"reviewed_missed": 1}, None, "reviewed_skips_confirm_no_loss"),
        ({}, eval_script.Coverage(records=260, censored=10, malformed_lines=2), "censoring_disclosed"),
        ({"saved_calls": 0, "misses": 250}, None, "savings_recorded"),
    ],
)
def test_a_failing_gate_is_reported_as_fail(overrides, coverage, expected):
    statuses = _gates(_evidence(**overrides), coverage or _CLEAN_COVERAGE)
    assert statuses[expected] == eval_script.FAIL


def test_gates_report_insufficient_instead_of_passing_vacuously():
    empty = eval_script.Evidence(
        scored_skips=0, misses=0, saved_calls=0, sensitive_scored_skips={}, sensitive_misses={}, reviewed_skips=0, reviewed_scored_skips=0, reviewed_missed=0, saved_skips_with_tokens=0, latency_samples=0, baseline_computable=0
    )
    statuses = _gates(empty, eval_script.Coverage(records=0, censored=0, malformed_lines=0))
    assert set(statuses.values()) == {eval_script.INSUFFICIENT}
    assert statuses["network_miss_rate"] == eval_script.INSUFFICIENT

    thin = eval_script.Evidence(
        scored_skips=2, misses=0, saved_calls=2, sensitive_scored_skips={}, sensitive_misses={}, reviewed_skips=0, reviewed_scored_skips=0, reviewed_missed=0, saved_skips_with_tokens=2, latency_samples=2, baseline_computable=2
    )
    statuses = _gates(thin, eval_script.Coverage(records=2, censored=0, malformed_lines=0))
    assert statuses["network_miss_rate"] == eval_script.PASS
    assert statuses["sensitive_stratum_zero_misses"] == eval_script.INSUFFICIENT
    assert statuses["reviewed_skips_confirm_no_loss"] == eval_script.INSUFFICIENT


def test_the_review_gate_needs_a_confirmed_review_not_only_a_count():
    """Design §5 gate 3: ≥200 reviewed skips *confirming* none was worth remembering."""
    gate_id = "reviewed_skips_confirm_no_loss"
    assert _gates(_evidence(reviewed_missed=1), _CLEAN_COVERAGE)[gate_id] == eval_script.FAIL
    assert _gates(_evidence(reviewed_scored_skips=199), _CLEAN_COVERAGE)[gate_id] == eval_script.INSUFFICIENT, "a reviewed skip with no outcome confirms nothing"


def test_the_savings_gate_needs_tokens_latency_and_the_baseline():
    """Design §5 gate 4: recorded calls are not the whole evidence, so missing pieces are INSUFFICIENT."""
    for overrides in ({"saved_skips_with_tokens": 0}, {"latency_samples": 0}, {"baseline_computable": 0}):
        statuses = _gates(_evidence(**overrides), _CLEAN_COVERAGE)
        assert statuses["savings_recorded"] == eval_script.INSUFFICIENT, overrides
    assert _gates(_evidence(), _CLEAN_COVERAGE)["savings_recorded"] == eval_script.PASS


def test_the_sensitive_gate_needs_evidence_for_each_stratum_not_a_pooled_sample():
    """A pooled identity/preference/correction sample hides a stratum with no evidence.

    An identity-only run with zero misses must not pass the advertised zero-miss
    check across all three strata; the uncovered strata make it INSUFFICIENT.
    """
    identity_only = _evidence(sensitive_scored_skips={"identity": 5}, sensitive_misses={"identity": 0})
    assert _gates(identity_only, _CLEAN_COVERAGE)["sensitive_stratum_zero_misses"] == eval_script.INSUFFICIENT

    all_covered = _evidence(sensitive_scored_skips={"identity": 5, "preference": 5, "correction": 5}, sensitive_misses={"identity": 0, "preference": 0, "correction": 0})
    assert _gates(all_covered, _CLEAN_COVERAGE)["sensitive_stratum_zero_misses"] == eval_script.PASS

    one_miss = _evidence(sensitive_scored_skips={"identity": 5, "preference": 5}, sensitive_misses={"preference": 1})
    assert _gates(one_miss, _CLEAN_COVERAGE)["sensitive_stratum_zero_misses"] == eval_script.FAIL, "a recorded miss outranks missing strata"


def test_miss_rate_gate_reports_the_exact_bound_and_the_sample_size():
    gate = next(gate for gate in eval_script.evaluate_gates(_evidence(misses=1, saved_calls=249), _CLEAN_COVERAGE) if gate.gate_id == "network_miss_rate")
    assert gate.status == eval_script.PASS
    assert "n=250" in gate.detail
    assert f"{eval_script.clopper_pearson_upper(1, 250):.4f}" in gate.detail
    assert "exceeds the target" in gate.detail


# --- report assembly ------------------------------------------------------


def test_build_report_carries_the_gates_the_evidence_and_the_censoring():
    records = [
        _record(prescreen={"digest": "saved-1"}, mutations_accepted=0, trivial_only=True),
        _record(prescreen={"digest": "lost-1"}, mutations_accepted=2, trivial_only=True),
        _record(prescreen={"digest": "lost-2"}, mutations_accepted=1, stratum="preference"),
        _record(prescreen={"verdict": "extract"}, mutations_accepted=0),
        _record(mutations_accepted=None),
        _record(prescreen=None, mutations_accepted=None),
    ]
    report = eval_script.build_report(records, source="test.jsonl", malformed_lines=1, filtered_out=0)
    assert report["populations"][eval_script.NETWORK]["records"] == 5
    assert report["populations"][eval_script.UNJUDGED]["records"] == 1
    assert report["model"]["scored_skips"] == 3
    assert report["model"]["misses"] == 2
    assert report["model"]["miss_rate"] == pytest.approx(2 / 3)
    assert report["model"]["missed_digests"] == ["lost-1", "lost-2"]
    assert report["sensitive_stratum"]["by_label"]["preference"] == {"scored_skips": 1, "misses": 1}
    assert report["censoring"]["censored"] == 1
    statuses = {gate["id"]: gate["status"] for gate in report["gates"]}
    assert statuses["network_miss_rate"] == eval_script.FAIL
    assert statuses["sensitive_stratum_zero_misses"] == eval_script.FAIL
    assert statuses["censoring_disclosed"] == eval_script.FAIL
    assert report["gate_summary"]["enable_recommended"] is False
    assert report["baseline_heuristic"]["computable"] == 2


def test_build_report_refuses_enforce_when_a_review_contradicts_a_skip():
    """The reviewer's counterexample: 200 reviewed skips with one worth remembering must not enable."""
    records = [_record(prescreen={"digest": f"d{i}"}, mutations_accepted=0, trivial_only=True, reviewed=True, review_outcome="none_worth_remembering", stratum="identity" if i < 5 else None) for i in range(199)]
    records.append(_record(prescreen={"digest": "lost"}, mutations_accepted=0, trivial_only=True, reviewed=True, review_outcome="worth_remembering"))
    report = eval_script.build_report(records, source="review.jsonl")

    assert report["review"]["reviewed_skips"] == 200
    assert report["review"]["reviewed_missed"] == 1
    gates = {gate["id"]: gate["status"] for gate in report["gates"]}
    assert gates["reviewed_skips_confirm_no_loss"] == eval_script.FAIL
    assert report["gate_summary"]["enable_recommended"] is False


def test_build_report_treats_a_record_set_without_savings_evidence_as_insufficient():
    """The reviewer's counterexample: 250 saved calls with no tokens, latency or baseline must not enable."""
    records = [_record(prescreen={"digest": f"d{i}", "duration_ms": None}, token_usage=None, trivial_only=None, mutations_accepted=0) for i in range(250)]
    report = eval_script.build_report(records, source="thin.jsonl")

    assert report["model"]["saved_calls"] == 250
    assert report["baseline_heuristic"]["computable"] == 0
    gates = {gate["id"]: gate["status"] for gate in report["gates"]}
    assert gates["savings_recorded"] == eval_script.INSUFFICIENT
    assert report["gate_summary"]["enable_recommended"] is False


def test_build_report_enables_when_every_gate_passes():
    strata = ("identity", "preference", "correction")
    records = [_record(prescreen={"digest": f"d{i}"}, mutations_accepted=0, trivial_only=True, reviewed=True, review_outcome="none_worth_remembering", stratum=strata[i] if i < 3 else None) for i in range(250)]
    report = eval_script.build_report(records, source="clean.jsonl")
    assert report["model"]["scored_skips"] == 250
    assert report["model"]["misses"] == 0
    assert report["gate_summary"]["enable_recommended"] is True
    assert report["model"]["saved_call_rate_over_all_verdicts"] == 1.0


# --- label filtering ------------------------------------------------------


def test_label_filter_matches_dotted_paths_and_typed_values():
    record = _payload(stratum="preference")
    assert eval_script.record_matches(record, [("prescreen.mode", "shadow")]) is True
    assert eval_script.record_matches(record, [("prescreen.mode", "enforce")]) is False
    assert eval_script.record_matches(record, [("prescreen.cached", "false")]) is True
    assert eval_script.record_matches(record, [("success", "true")]) is True
    assert eval_script.record_matches(record, [("mutations_accepted", "0")]) is True
    assert eval_script.record_matches(record, [("prescreen.mode", "shadow"), ("stratum", "preference")]) is True
    assert eval_script.record_matches(record, [("prescreen.mode", "shadow"), ("stratum", "identity")]) is False
    assert eval_script.record_matches(record, [("prescreen.missing", "shadow")]) is False
    assert eval_script.record_matches(record, [("prescreen.mode", "not json")]) is False


def test_label_filter_rejects_a_missing_equals_sign():
    assert eval_script.parse_label_filter("prescreen.mode=shadow") == ("prescreen.mode", "shadow")
    assert eval_script.parse_label_filter("stratum=") == ("stratum", "")
    with pytest.raises(argparse.ArgumentTypeError):
        eval_script.parse_label_filter("prescreen.mode")


def test_percentile_uses_the_nearest_rank():
    assert eval_script._percentile([], 0.95) is None
    assert eval_script._percentile([5.0], 0.95) == 5.0
    assert eval_script._percentile([1.0, 2.0, 3.0, 4.0], 0.95) == 4.0
    assert eval_script._percentile(list(range(1, 101)), 0.95) == 95
