"""Blind grading of completed answer rows and public QA reporting.

Grading is join-free by construction: every prediction is graded through
``grade_answer(prediction, reference)`` — two strings, no policy identity —
and only afterwards joined back to its policy through the stable row ID.
Published rows carry predictions, grades, and non-secret metadata; they never
contain questions, reference answers, or memory content. The per-scenario
summary keeps the official and synthetic sources separate; the statistics
report the ``official`` and ``synthetic`` suites separately and additionally
an explicitly labeled combined ``overall`` suite.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .config import EvaluationConfig
from .grading import GRADER_VERSION, grade_answer
from .policy import PolicyResult
from .pool import PreparedCase
from .results import _atomic_write_text
from .runner import load_completed_row, response_path
from .stats import exact_mcnemar, paired_bootstrap_difference

POLICY_ORDER = ("confidence", "hybrid-v1")


class AnswerRowIntegrityError(RuntimeError):
    pass


def collect_answer_rows(output_dir: Path, cases: list[PreparedCase]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    for case in cases:
        for policy in POLICY_ORDER:
            row_id = f"{case.case_id}__{policy}"
            row = load_completed_row(response_path(output_dir, row_id))
            if row is None:
                missing.append(row_id)
            else:
                rows[row_id] = row
    if missing:
        raise AnswerRowIntegrityError(f"missing or invalid answer rows: {', '.join(sorted(missing))}")
    return rows


def grade_answer_rows(cases: list[PreparedCase], results_by_row: dict[str, PolicyResult], rows: dict[str, dict[str, Any]], *, expected_fingerprints: dict[str, str]) -> list[dict[str, Any]]:
    cases_by_id = {case.case_id: case for case in cases}
    graded: list[dict[str, Any]] = []
    for row_id in sorted(rows):
        row = rows[row_id]
        result = results_by_row[row_id]
        # The recomputed task is authoritative: the reference case is derived from it,
        # never from the stored row, and every persisted identity field must match it.
        case = cases_by_id[result.case_id]
        if row.get("row_id") != row_id or row.get("case_id") != result.case_id or row.get("source") != result.source or row.get("scenario") != result.scenario:
            raise AnswerRowIntegrityError(f"row {row_id} case identity does not match the expected task")
        if tuple(row.get("kept_fact_ids", ())) != result.kept_fact_ids:
            raise AnswerRowIntegrityError(f"row {row_id} kept facts do not match the deterministic selector output")
        if row.get("capacity") != result.capacity or row.get("policy") != result.policy:
            raise AnswerRowIntegrityError(f"row {row_id} capacity/policy does not match the protocol")
        if row.get("request_fingerprint") != expected_fingerprints.get(row_id):
            raise AnswerRowIntegrityError(f"row {row_id} request fingerprint does not match the task recomputed from the current protocol")
        prediction = str(row["prediction"])
        grade = grade_answer(prediction, case.answer)
        graded.append(
            {
                "schema_version": 1,
                "row_id": row_id,
                "case_id": case.case_id,
                "source": case.source,
                "scenario": case.scenario,
                "question_type": case.question_type,
                "policy": result.policy,
                "capacity": result.capacity,
                "kept_fact_ids": list(result.kept_fact_ids),
                "support_all_retained": result.support_all_retained,
                "support_recall": result.support_recall,
                "prediction": prediction,
                "grade_correct": grade.correct,
                "grade_rule": grade.rule,
                "grader_version": GRADER_VERSION,
                "attempts": row.get("attempts"),
                "request_fingerprint": row.get("request_fingerprint"),
                "response_model": row.get("response_model"),
                "usage": row.get("usage"),
            }
        )
    return graded


def summarize_qa_rows(graded: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in graded:
        groups[(row["source"], row["scenario"], row["policy"])].append(row)
    summary: list[dict[str, Any]] = []
    for (source, scenario, policy), rows in sorted(groups.items()):
        correct = sum(1 for row in rows if row["grade_correct"])
        summary.append({"source": source, "scenario": scenario, "policy": policy, "cases": len(rows), "correct": correct, "accuracy": correct / len(rows)})
    return summary


def _paired_grades(graded: list[dict[str, Any]]) -> dict[str, tuple[bool, bool]]:
    by_case: dict[str, dict[str, bool]] = defaultdict(dict)
    for row in graded:
        by_case[row["case_id"]][row["policy"]] = bool(row["grade_correct"])
    pairs: dict[str, tuple[bool, bool]] = {}
    for case_id, grades in by_case.items():
        if set(grades) != set(POLICY_ORDER):
            raise AnswerRowIntegrityError(f"case {case_id} is missing one policy row")
        pairs[case_id] = (grades[POLICY_ORDER[0]], grades[POLICY_ORDER[1]])
    return pairs


def compute_qa_statistics(graded: list[dict[str, Any]], config: EvaluationConfig) -> dict[str, Any]:
    pairs_by_case = _paired_grades(graded)
    sources_by_case = {row["case_id"]: row["source"] for row in graded}
    suites = {
        "official": [pairs_by_case[case_id] for case_id in sorted(pairs_by_case) if sources_by_case[case_id] == "longmemeval"],
        "synthetic": [pairs_by_case[case_id] for case_id in sorted(pairs_by_case) if sources_by_case[case_id] == "synthetic"],
        "overall": [pairs_by_case[case_id] for case_id in sorted(pairs_by_case)],
    }
    statistics: dict[str, Any] = {"schema_version": 1, "protocol_id": config.protocol_id, "grader_version": GRADER_VERSION, "policies": list(POLICY_ORDER), "suites": {}}
    for suite, pairs in suites.items():
        mcnemar = exact_mcnemar(pairs)
        bootstrap = paired_bootstrap_difference(pairs, seed=config.statistics.bootstrap_seed, iterations=config.statistics.bootstrap_iterations, alpha=config.statistics.alpha)
        statistics["suites"][suite] = {"cases": len(pairs), "mcnemar": asdict(mcnemar), "bootstrap": asdict(bootstrap)}
    return statistics


def write_qa_report(output_dir: Path, *, graded: list[dict[str, Any]], summary: list[dict[str, Any]], statistics: dict[str, Any], config: EvaluationConfig) -> None:
    targets = [output_dir / "qa.rows.jsonl", output_dir / "qa.summary.json", output_dir / "qa.stats.json"]
    existing = [path for path in targets if path.exists()]
    if existing:
        raise FileExistsError(f"refusing to overwrite existing result files: {', '.join(str(path) for path in existing)}")
    rows_lines = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in graded)
    summary_document = {"schema_version": 1, "protocol_id": config.protocol_id, "grader_version": GRADER_VERSION, "qa_capacity": config.pool.qa_capacity, "groups": summary}
    _atomic_write_text(output_dir / "qa.rows.jsonl", rows_lines)
    _atomic_write_text(output_dir / "qa.summary.json", json.dumps(summary_document, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    _atomic_write_text(output_dir / "qa.stats.json", json.dumps(statistics, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
