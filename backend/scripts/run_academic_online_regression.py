#!/usr/bin/env python3
"""Run automated online regression (commit/week drift) for academic eval."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _default_branch() -> str:
    return (
        os.getenv("GITHUB_REF_NAME")
        or os.getenv("CI_COMMIT_REF_NAME")
        or os.getenv("BRANCH_NAME")
        or "local"
    )


def _default_commit() -> str:
    return (
        os.getenv("GITHUB_SHA")
        or os.getenv("CI_COMMIT_SHA")
        or os.getenv("COMMIT_SHA")
        or "local"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run online regression drift on evaluate_academic_and_persist outputs.",
    )
    parser.add_argument(
        "--run-mode",
        choices=("smoke", "full"),
        default="smoke",
        help="Preset dataset mode for CI workflows.",
    )
    parser.add_argument(
        "--dataset-name",
        action="append",
        default=None,
        help="Builtin dataset name under src/evals/academic/datasets (repeatable).",
    )
    parser.add_argument(
        "--dataset-path",
        action="append",
        default=None,
        help="Path to dataset JSON file (repeatable; absolute or backend-relative).",
    )
    parser.add_argument(
        "--thread-id",
        default="ci-online-regression",
        help="Thread id used by evaluate_academic_and_persist persistence.",
    )
    parser.add_argument(
        "--artifact-name",
        default="academic-online-regression",
        help="Artifact basename passed to evaluate_academic_and_persist.",
    )
    parser.add_argument(
        "--model-label",
        default="deerflow-ci",
        help="Model label for leaderboard merge rows.",
    )
    parser.add_argument(
        "--output-dir",
        default="src/evals/academic/datasets/online_regression",
        help="Output directory for online regression artifacts.",
    )
    parser.add_argument(
        "--history-file",
        default="online-regression-history.json",
        help="History file name (or absolute path).",
    )
    parser.add_argument(
        "--dataset-version",
        default="v1",
        help="Dataset version label for this run.",
    )
    parser.add_argument(
        "--branch",
        default=_default_branch(),
        help="Branch name for run metadata.",
    )
    parser.add_argument(
        "--commit-sha",
        default=_default_commit(),
        help="Commit SHA for run metadata.",
    )
    parser.add_argument(
        "--run-label",
        default="online-regression",
        help="Run label prefix.",
    )
    parser.add_argument(
        "--max-auc-drop",
        type=float,
        default=1.0,
        help="Alert when AUC decreases more than this value.",
    )
    parser.add_argument(
        "--max-claim-grounding-drop",
        type=float,
        default=0.0,
        help="Alert when average_claim_grounding decreases more than this value.",
    )
    parser.add_argument(
        "--max-citation-fidelity-drop",
        type=float,
        default=0.0,
        help="Alert when average_citation_fidelity decreases more than this value.",
    )
    parser.add_argument(
        "--max-ece-increase",
        type=float,
        default=0.0,
        help="Alert when ECE increases more than this value.",
    )
    parser.add_argument(
        "--max-safety-valve-rate-increase",
        type=float,
        default=0.0,
        help="Alert when safety_valve_triggered_rate increases more than this value.",
    )
    parser.add_argument(
        "--allow-safety-valve-increase",
        action="store_true",
        default=False,
        help="Allow safety_valve_triggered increase (for intentional conservative changes).",
    )
    parser.add_argument(
        "--max-brier-increase",
        type=float,
        default=1.0,
        help="Alert when Brier score increases more than this value.",
    )
    parser.add_argument(
        "--max-score-gap-drop",
        type=float,
        default=1.0,
        help="Alert when accept/reject score gap decreases more than this value.",
    )
    parser.add_argument(
        "--max-overall-drop",
        type=float,
        default=1.0,
        help="Alert when average overall score decreases more than this value.",
    )
    parser.add_argument(
        "--strict-gate",
        action="store_true",
        default=False,
        help="Exit with non-zero status when drift alerts are present.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        default=False,
        help="Allow overwriting current/drift report files.",
    )
    return parser


def _write_json(path: Path, payload: dict, *, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(f"Refusing to overwrite existing file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _write_text(path: Path, payload: str, *, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(f"Refusing to overwrite existing file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")


def _resolve_history_path(history_arg: str, *, output_dir: Path) -> Path:
    candidate = Path(history_arg).expanduser()
    if candidate.is_absolute():
        return candidate
    # If user passes a relative path with directories, respect it from cwd.
    if candidate.parent != Path("."):
        return (Path.cwd() / candidate).resolve()
    # Bare filename defaults to output directory.
    return (output_dir / candidate).resolve()


def _default_dataset_names(run_mode: str) -> list[str]:
    if run_mode == "full":
        return ["top_tier_accept_reject_v1", "failure_mode_library_v1"]
    return ["online_regression_smoke_v1"]


def _load_cases(dataset_names: list[str], dataset_paths: list[str]) -> tuple[list[object], list[str]]:
    from src.evals.academic.loader import load_builtin_eval_cases, load_eval_cases

    cases: list[object] = []
    labels: list[str] = []
    for name in dataset_names:
        loaded = load_builtin_eval_cases(name)
        cases.extend(loaded)
        labels.append(f"builtin:{name}({len(loaded)})")
    for path_token in dataset_paths:
        path = Path(path_token).expanduser()
        if not path.is_absolute():
            path = (Path.cwd() / path).resolve()
        loaded = load_eval_cases(path)
        cases.extend(loaded)
        labels.append(f"path:{path}({len(loaded)})")
    return cases, labels


def main() -> int:
    from src.evals.academic.online_regression import (
        OnlineDriftThresholds,
        append_online_run,
        build_online_drift_report,
        build_online_run_from_eval_summary,
        dump_online_regression_history,
        find_previous_commit_run,
        find_previous_week_run,
        load_online_regression_history,
        render_online_drift_markdown,
    )
    from src.research_writing.runtime_service import evaluate_academic_and_persist

    args = build_parser().parse_args()
    output_dir = Path(args.output_dir).expanduser()
    if not output_dir.is_absolute():
        output_dir = (Path.cwd() / output_dir).resolve()
    history_path = _resolve_history_path(args.history_file, output_dir=output_dir)

    dataset_names = list(args.dataset_name or _default_dataset_names(args.run_mode))
    dataset_paths = list(args.dataset_path or [])
    cases, source_labels = _load_cases(dataset_names, dataset_paths)
    if not cases:
        raise ValueError("No eval cases resolved from dataset_name/dataset_path.")

    eval_summary = evaluate_academic_and_persist(
        args.thread_id,
        cases=cases,
        name=args.artifact_name,
        model_label=args.model_label,
        dataset_name="+".join(dataset_names) if dataset_names else None,
    )
    current_run = build_online_run_from_eval_summary(
        eval_summary=eval_summary,
        branch=args.branch,
        commit_sha=args.commit_sha,
        run_label=args.run_label,
    )
    history = load_online_regression_history(history_path)
    previous_commit = find_previous_commit_run(history, current_run)
    previous_week = find_previous_week_run(history, current_run)

    thresholds = OnlineDriftThresholds(
        max_claim_grounding_drop=args.max_claim_grounding_drop,
        max_citation_fidelity_drop=args.max_citation_fidelity_drop,
        max_auc_drop=args.max_auc_drop,
        max_ece_increase=args.max_ece_increase,
        max_brier_increase=args.max_brier_increase,
        max_safety_valve_rate_increase=args.max_safety_valve_rate_increase,
        allow_safety_valve_increase=args.allow_safety_valve_increase,
        max_score_gap_drop=args.max_score_gap_drop,
        max_overall_drop=args.max_overall_drop,
    )
    drift_report = build_online_drift_report(
        current=current_run,
        previous_commit=previous_commit,
        previous_week=previous_week,
        thresholds=thresholds,
    )

    current_report = {
        "schema_version": drift_report["schema_version"],
        "generated_at": datetime.now(UTC).isoformat(),
        "run_mode": args.run_mode,
        "thread_id": args.thread_id,
        "dataset_names": dataset_names,
        "dataset_sources": source_labels,
        "eval_summary": eval_summary,
        "current_run": current_run.model_dump(),
    }
    current_path = output_dir / "online-regression-current.json"
    drift_json_path = output_dir / "online-regression-drift.json"
    drift_md_path = output_dir / "online-regression-drift.md"
    _write_json(current_path, current_report, overwrite=args.overwrite)
    _write_json(drift_json_path, drift_report, overwrite=args.overwrite)
    _write_text(drift_md_path, render_online_drift_markdown(drift_report), overwrite=args.overwrite)

    updated = append_online_run(history, current_run)
    dump_online_regression_history(history_path, updated, overwrite=True)

    has_alerts = drift_report.get("status") == "has_alerts"
    print(
        json.dumps(
            {
                "ok": True,
                "status": drift_report.get("status", "unknown"),
                "alert_count": int(drift_report.get("alert_count") or 0),
                "current_report": str(current_path),
                "drift_report": str(drift_json_path),
                "drift_markdown": str(drift_md_path),
                "history_file": str(history_path),
                "previous_commit_run_id": (previous_commit.run_id if previous_commit else None),
                "previous_week_run_id": (previous_week.run_id if previous_week else None),
                "leaderboard_artifact_path": str(eval_summary.get("leaderboard_artifact_path") or ""),
                "eval_artifact_path": str(eval_summary.get("artifact_path") or ""),
                "strict_gate": args.strict_gate,
            },
            ensure_ascii=False,
        )
    )
    if args.strict_gate and has_alerts:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

