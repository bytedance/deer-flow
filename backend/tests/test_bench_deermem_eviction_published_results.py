from __future__ import annotations

import json
from pathlib import Path

from scripts.benchmark.deermem_eviction.config import load_evaluation_config
from scripts.benchmark.deermem_eviction.grading import GRADER_VERSION
from scripts.benchmark.deermem_eviction.stats import exact_mcnemar, paired_bootstrap_difference

EVAL_ROOT = Path(__file__).parents[1] / "scripts" / "benchmark" / "deermem_eviction"
RESULTS_ROOT = EVAL_ROOT / "results" / "pr4789-reproduction-v1"

ALLOWED_ROW_KEYS = {
    "schema_version",
    "row_id",
    "case_id",
    "source",
    "scenario",
    "question_type",
    "policy",
    "capacity",
    "kept_fact_ids",
    "support_all_retained",
    "support_recall",
    "prediction",
    "grade_correct",
    "grade_rule",
    "grader_version",
    "attempts",
    "request_fingerprint",
    "response_model",
    "usage",
}


def _rows() -> list[dict]:
    return [json.loads(line) for line in (RESULTS_ROOT / "qa.rows.jsonl").read_text(encoding="utf-8").splitlines()]


def test_published_rows_contain_only_allowed_metadata() -> None:
    rows = _rows()
    config = load_evaluation_config(EVAL_ROOT / "configs" / "pr4789-reproduction-v1.yaml")
    assert len(rows) == 90
    assert {row["policy"] for row in rows} == {"confidence", "hybrid-v1"}
    for row in rows:
        assert set(row) == ALLOWED_ROW_KEYS
        assert row["capacity"] == config.pool.qa_capacity
        assert len(row["kept_fact_ids"]) == config.pool.qa_capacity
        assert row["grader_version"] == GRADER_VERSION
        assert isinstance(row["prediction"], str)


def test_published_statistics_are_recomputable_from_the_rows() -> None:
    rows = _rows()
    config = load_evaluation_config(EVAL_ROOT / "configs" / "pr4789-reproduction-v1.yaml")
    statistics = json.loads((RESULTS_ROOT / "qa.stats.json").read_text(encoding="utf-8"))
    grades: dict[str, dict[str, bool]] = {}
    sources: dict[str, str] = {}
    for row in rows:
        grades.setdefault(row["case_id"], {})[row["policy"]] = row["grade_correct"]
        sources[row["case_id"]] = row["source"]
    suites = {
        "official": [case_id for case_id in sorted(grades) if sources[case_id] == "longmemeval"],
        "synthetic": [case_id for case_id in sorted(grades) if sources[case_id] == "synthetic"],
        "overall": sorted(grades),
    }
    for suite, case_ids in suites.items():
        pairs = [(grades[case_id]["confidence"], grades[case_id]["hybrid-v1"]) for case_id in case_ids]
        expected = exact_mcnemar(pairs)
        published = statistics["suites"][suite]["mcnemar"]
        assert published["p_value"] == expected.p_value
        assert published["only_first_correct"] == expected.only_first_correct
        assert published["only_second_correct"] == expected.only_second_correct
        assert statistics["suites"][suite]["cases"] == len(pairs)
        expected_bootstrap = paired_bootstrap_difference(pairs, seed=config.statistics.bootstrap_seed, iterations=config.statistics.bootstrap_iterations, alpha=config.statistics.alpha)
        published_bootstrap = statistics["suites"][suite]["bootstrap"]
        assert published_bootstrap["mean_difference"] == expected_bootstrap.mean_difference
        assert published_bootstrap["lower"] == expected_bootstrap.lower
        assert published_bootstrap["upper"] == expected_bootstrap.upper
        assert (published_bootstrap["seed"], published_bootstrap["iterations"], published_bootstrap["alpha"]) == (expected_bootstrap.seed, expected_bootstrap.iterations, expected_bootstrap.alpha)


def test_published_summary_matches_the_rows_and_run_provenance_is_secret_free() -> None:
    rows = _rows()
    summary = json.loads((RESULTS_ROOT / "qa.summary.json").read_text(encoding="utf-8"))
    for group in summary["groups"]:
        matching = [row for row in rows if (row["source"], row["scenario"], row["policy"]) == (group["source"], group["scenario"], group["policy"])]
        assert len(matching) == group["cases"]
        assert sum(1 for row in matching if row["grade_correct"]) == group["correct"]
    run = json.loads((RESULTS_ROOT / "qa_run.json").read_text(encoding="utf-8"))
    serialized = json.dumps(run)
    assert "sk-" not in serialized
    assert run["qa"]["api_key_env"] == "DEERMEM_EVAL_ANSWER_API_KEY"
    assert run["dataset"]["sha256"] == load_evaluation_config(EVAL_ROOT / "configs" / "pr4789-reproduction-v1.yaml").dataset.sha256
