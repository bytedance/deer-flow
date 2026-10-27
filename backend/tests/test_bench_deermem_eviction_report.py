from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.benchmark.deermem_eviction.config import load_evaluation_config
from scripts.benchmark.deermem_eviction.policy import PolicyResult
from scripts.benchmark.deermem_eviction.pool import PreparedCase
from scripts.benchmark.deermem_eviction.report import AnswerRowIntegrityError, collect_answer_rows, compute_qa_statistics, grade_answer_rows, summarize_qa_rows, write_qa_report
from scripts.benchmark.deermem_eviction.runner import response_path
from scripts.benchmark.deermem_eviction.stats import exact_mcnemar, paired_bootstrap_difference

EVAL_ROOT = Path(__file__).parents[1] / "scripts" / "benchmark" / "deermem_eviction"


def _load_config():
    return load_evaluation_config(EVAL_ROOT / "configs" / "pr4789-reproduction-v1.yaml")


def _case(case_id: str, *, source: str, scenario: str, answer: str) -> PreparedCase:
    config = _load_config()
    facts = [{"id": f"{case_id}-fact", "content": "Secret memory content.", "category": "context", "confidence": 0.9, "createdAt": "2026-02-14T00:00:00Z", "source": "synthetic"}]
    return PreparedCase(
        case_id=case_id,
        source=source,  # type: ignore[arg-type]
        scenario=scenario,  # type: ignore[arg-type]
        question_type="synthetic-shape",
        question="Secret question text?",
        answer=answer,
        question_date=None,
        evaluation_time=config.evaluation_time,
        facts=facts,
        usage={},
        support_fact_ids=(f"{case_id}-fact",),
    )


def _policy_result(case: PreparedCase, policy: str) -> PolicyResult:
    return PolicyResult(
        case_id=case.case_id,
        source=case.source,
        scenario=case.scenario,
        question_type=case.question_type,
        policy=policy,  # type: ignore[arg-type]
        capacity=7,
        support_fact_ids=case.support_fact_ids,
        kept_fact_ids=case.support_fact_ids,
        evicted=(),
        scores={},
        support_all_retained=True,
        support_recall=1.0,
        reserved_correction_slots=0,
    )


def _write_response(output_dir: Path, case: PreparedCase, policy: str, prediction: str, *, capacity: int = 7) -> None:
    row_id = f"{case.case_id}__{policy}"
    path = response_path(output_dir, row_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "schema_version": 1,
        "row_id": row_id,
        "case_id": case.case_id,
        "source": case.source,
        "scenario": case.scenario,
        "policy": policy,
        "capacity": capacity,
        "kept_fact_ids": list(case.support_fact_ids),
        "prediction": prediction,
        "attempts": 1,
        "request_fingerprint": "f" * 64,
        "response_model": "deepseek-v4-flash",
        "usage": {"prompt_tokens": 10, "completion_tokens": 2},
        "created_at": "2026-08-17T00:00:00Z",
    }
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")


def _setup(tmp_path: Path):
    official = _case("case-off", source="longmemeval", scenario="access_help", answer="Lyon-Reference-Secret")
    synthetic = _case("case-syn", source="synthetic", scenario="correction_reserve", answer="NO")
    cases = [official, synthetic]
    _write_response(tmp_path, official, "confidence", "Paris")
    _write_response(tmp_path, official, "hybrid-v1", "Lyon-Reference-Secret")
    _write_response(tmp_path, synthetic, "confidence", "NO")
    _write_response(tmp_path, synthetic, "hybrid-v1", "NO")
    results = {f"{case.case_id}__{policy}": _policy_result(case, policy) for case in cases for policy in ("confidence", "hybrid-v1")}
    fingerprints = {row_id: "f" * 64 for row_id in results}
    return cases, results, fingerprints


def test_exact_mcnemar_matches_the_two_sided_exact_binomial() -> None:
    concordant = exact_mcnemar([(True, True), (False, False)])
    assert concordant.p_value == 1.0
    one_sided_shift = exact_mcnemar([(False, True)] * 5)
    assert one_sided_shift.only_second_correct == 5
    assert one_sided_shift.p_value == pytest.approx(2 * 0.5**5)
    mixed = exact_mcnemar([(False, True)] * 8 + [(True, False)] + [(True, True)] * 3)
    assert (mixed.only_first_correct, mixed.only_second_correct, mixed.both_correct) == (1, 8, 3)
    assert mixed.p_value == pytest.approx(2 * (0.5**9) * (1 + 9), rel=1e-12)


def test_paired_bootstrap_is_seed_deterministic_and_signed_second_minus_first() -> None:
    config = _load_config()
    pairs = [(False, True)] * 4 + [(True, True)] * 4
    first = paired_bootstrap_difference(pairs, seed=config.statistics.bootstrap_seed, iterations=1000, alpha=config.statistics.alpha)
    second = paired_bootstrap_difference(pairs, seed=config.statistics.bootstrap_seed, iterations=1000, alpha=config.statistics.alpha)
    assert first == second
    assert first.mean_difference == pytest.approx(0.5)
    degenerate = paired_bootstrap_difference([(False, True)] * 3, seed=1, iterations=100, alpha=0.05)
    assert (degenerate.mean_difference, degenerate.lower, degenerate.upper) == (1.0, 1.0, 1.0)


def test_grading_is_blind_and_joined_by_row_id(tmp_path: Path) -> None:
    cases, results, fingerprints = _setup(tmp_path)
    rows = collect_answer_rows(tmp_path, cases)
    graded = grade_answer_rows(cases, results, rows, expected_fingerprints=fingerprints)
    by_row = {row["row_id"]: row for row in graded}
    assert not by_row["case-off__confidence"]["grade_correct"]
    assert by_row["case-off__hybrid-v1"]["grade_correct"]
    assert by_row["case-syn__confidence"]["grade_correct"]
    assert by_row["case-syn__hybrid-v1"]["grade_correct"]
    assert all(row["grader_version"] == "deterministic-overlap-v1" for row in graded)


def test_collect_and_integrity_checks_reject_incomplete_or_tampered_rows(tmp_path: Path) -> None:
    cases, results, fingerprints = _setup(tmp_path)
    response_path(tmp_path, "case-syn__hybrid-v1").unlink()
    with pytest.raises(AnswerRowIntegrityError, match="case-syn__hybrid-v1"):
        collect_answer_rows(tmp_path, cases)

    _write_response(tmp_path, cases[1], "hybrid-v1", "NO", capacity=5)
    rows = collect_answer_rows(tmp_path, cases)
    with pytest.raises(AnswerRowIntegrityError, match="capacity/policy"):
        grade_answer_rows(cases, results, rows, expected_fingerprints=fingerprints)

    _write_response(tmp_path, cases[1], "hybrid-v1", "NO")
    rows = collect_answer_rows(tmp_path, cases)
    tampered = dict(results)
    tampered["case-syn__hybrid-v1"] = _policy_result(_case("case-syn", source="synthetic", scenario="correction_reserve", answer="NO"), "hybrid-v1")
    object.__setattr__(tampered["case-syn__hybrid-v1"], "kept_fact_ids", ("other-fact",))
    with pytest.raises(AnswerRowIntegrityError, match="kept facts"):
        grade_answer_rows(cases, tampered, rows, expected_fingerprints=fingerprints)

    stale = dict(fingerprints)
    stale["case-syn__hybrid-v1"] = "0" * 64
    with pytest.raises(AnswerRowIntegrityError, match="request fingerprint"):
        grade_answer_rows(cases, results, rows, expected_fingerprints=stale)


def test_grading_rejects_a_row_reassigned_to_another_valid_case(tmp_path: Path) -> None:
    cases, results, fingerprints = _setup(tmp_path)
    path = response_path(tmp_path, "case-off__hybrid-v1")
    original = json.loads(path.read_text(encoding="utf-8"))
    for field, value in (("case_id", "case-syn"), ("source", "synthetic"), ("scenario", "correction_reserve"), ("row_id", "case-syn__hybrid-v1")):
        path.write_text(json.dumps(dict(original, **{field: value})) + "\n", encoding="utf-8")
        rows = collect_answer_rows(tmp_path, cases)
        with pytest.raises(AnswerRowIntegrityError, match="case-off__hybrid-v1.*case identity"):
            grade_answer_rows(cases, results, rows, expected_fingerprints=fingerprints)


def test_summary_and_statistics_keep_suites_separate(tmp_path: Path) -> None:
    cases, results, fingerprints = _setup(tmp_path)
    config = _load_config()
    graded = grade_answer_rows(cases, results, collect_answer_rows(tmp_path, cases), expected_fingerprints=fingerprints)
    summary = summarize_qa_rows(graded)
    assert {(group["source"], group["scenario"], group["policy"]): group["accuracy"] for group in summary} == {
        ("longmemeval", "access_help", "confidence"): 0.0,
        ("longmemeval", "access_help", "hybrid-v1"): 1.0,
        ("synthetic", "correction_reserve", "confidence"): 1.0,
        ("synthetic", "correction_reserve", "hybrid-v1"): 1.0,
    }
    statistics = compute_qa_statistics(graded, config)
    assert statistics["suites"]["official"]["cases"] == 1
    assert statistics["suites"]["synthetic"]["cases"] == 1
    assert statistics["suites"]["overall"]["cases"] == 2
    assert statistics["suites"]["official"]["mcnemar"]["only_second_correct"] == 1
    assert statistics["suites"]["official"]["bootstrap"]["seed"] == config.statistics.bootstrap_seed


def test_written_report_redacts_dataset_text_and_refuses_overwrite(tmp_path: Path) -> None:
    cases, results, fingerprints = _setup(tmp_path)
    config = _load_config()
    graded = grade_answer_rows(cases, results, collect_answer_rows(tmp_path, cases), expected_fingerprints=fingerprints)
    write_qa_report(tmp_path, graded=graded, summary=summarize_qa_rows(graded), statistics=compute_qa_statistics(graded, config), config=config)
    rows_text = (tmp_path / "qa.rows.jsonl").read_text(encoding="utf-8")
    assert "Secret question text" not in rows_text
    assert "Secret memory content" not in rows_text
    confidence_official = json.loads(next(line for line in rows_text.splitlines() if '"case-off__confidence"' in line))
    assert "Lyon-Reference-Secret" not in json.dumps(confidence_official)
    assert (tmp_path / "qa.summary.json").exists()
    assert (tmp_path / "qa.stats.json").exists()
    with pytest.raises(FileExistsError):
        write_qa_report(tmp_path, graded=graded, summary=summarize_qa_rows(graded), statistics=compute_qa_statistics(graded, config), config=config)
