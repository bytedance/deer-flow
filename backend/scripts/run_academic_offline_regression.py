#!/usr/bin/env python3
"""Run layered offline benchmark regression with quality gates."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate layered offline benchmark suite and emit gate reports.",
    )
    parser.add_argument(
        "--input-dir",
        default="src/evals/academic/templates/offline_benchmark_suite",
        help="Directory containing layered raw suite files.",
    )
    parser.add_argument(
        "--output-dir",
        default="src/evals/academic/datasets/offline_regression",
        help="Directory for regression report artifacts.",
    )
    parser.add_argument(
        "--dataset-version",
        default="v1",
        help="Dataset version label written into import/eval flow.",
    )
    parser.add_argument(
        "--core-min-auc",
        type=float,
        default=0.9,
        help="Gate: core layer minimum AUC.",
    )
    parser.add_argument(
        "--core-max-ece",
        type=float,
        default=0.25,
        help="Gate: core layer maximum ECE.",
    )
    parser.add_argument(
        "--core-max-brier",
        type=float,
        default=0.1,
        help="Gate: core layer maximum Brier score.",
    )
    parser.add_argument(
        "--domain-min-gap",
        type=float,
        default=0.1,
        help="Gate: domain-split minimum accept/reject score gap.",
    )
    parser.add_argument(
        "--failure-mode-min-targeted",
        type=int,
        default=5,
        help="Gate: failure-mode layer minimum targeted hard negatives.",
    )
    parser.add_argument(
        "--baseline-report",
        default="",
        help="Optional baseline offline report JSON for drift comparison.",
    )
    parser.add_argument(
        "--drift-report-json",
        default="offline-benchmark-drift.json",
        help="Drift report JSON file name (or absolute path).",
    )
    parser.add_argument(
        "--drift-report-markdown",
        default="offline-benchmark-drift.md",
        help="Drift report markdown file name (or absolute path).",
    )
    parser.add_argument(
        "--max-hallucination-rate-increase",
        type=float,
        default=0.0,
        help="Drift gate: maximum allowed citation-hallucination-rate increase.",
    )
    parser.add_argument(
        "--max-ece-increase",
        type=float,
        default=0.0,
        help="Drift gate: maximum allowed ECE increase.",
    )
    parser.add_argument(
        "--max-brier-increase",
        type=float,
        default=0.0,
        help="Drift gate: maximum allowed Brier score increase.",
    )
    parser.add_argument(
        "--max-auc-drop",
        type=float,
        default=1.0,
        help="Drift gate: maximum allowed AUC drop.",
    )
    parser.add_argument(
        "--strict-gate",
        action="store_true",
        default=False,
        help="Exit non-zero when any regression gate fails.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        default=False,
        help="Allow overwriting existing report files.",
    )
    return parser


def _write_text(path: Path, payload: str, *, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(f"Refusing to overwrite existing file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")


def _write_json(path: Path, payload: dict, *, overwrite: bool) -> None:
    _write_text(path, json.dumps(payload, indent=2, ensure_ascii=False), overwrite=overwrite)


def main() -> int:
    from src.evals.academic.offline_regression import (
        OfflineRegressionDriftThresholds,
        OfflineRegressionThresholds,
        build_offline_regression_drift_report,
        evaluate_offline_regression_layers,
        load_offline_layer_payloads,
        render_offline_regression_drift_markdown,
        render_offline_regression_markdown,
    )
    from src.research_writing.prompt_pack import get_prompt_pack_metadata

    args = build_parser().parse_args()
    input_dir = Path(args.input_dir).expanduser()
    if not input_dir.is_absolute():
        input_dir = (Path.cwd() / input_dir).resolve()
    output_dir = Path(args.output_dir).expanduser()
    if not output_dir.is_absolute():
        output_dir = (Path.cwd() / output_dir).resolve()

    layers = load_offline_layer_payloads(input_dir)
    thresholds = OfflineRegressionThresholds(
        core_min_auc=args.core_min_auc,
        core_max_ece=args.core_max_ece,
        core_max_brier=args.core_max_brier,
        domain_min_accept_reject_gap=args.domain_min_gap,
        failure_mode_min_targeted_case_count=args.failure_mode_min_targeted,
    )
    report = evaluate_offline_regression_layers(
        layers,
        dataset_version=args.dataset_version,
        thresholds=thresholds,
    )
    prompt_pack = get_prompt_pack_metadata()
    report["prompt_pack_id"] = str(prompt_pack.get("prompt_pack_id") or "")
    report["prompt_pack_hash"] = str(prompt_pack.get("prompt_pack_hash") or "")
    prompt_layer_signatures = prompt_pack.get("prompt_layer_signatures")
    report["prompt_layer_signatures"] = prompt_layer_signatures if isinstance(prompt_layer_signatures, dict) else {}
    report["generated_at"] = datetime.now(UTC).isoformat()
    report["input_dir"] = str(input_dir)
    report["dataset_version"] = args.dataset_version

    json_path = output_dir / "offline-benchmark-regression.json"
    md_path = output_dir / "offline-benchmark-regression.md"
    _write_json(json_path, report, overwrite=args.overwrite)
    _write_text(md_path, render_offline_regression_markdown(report), overwrite=args.overwrite)

    drift_status = "not_run"
    drift_json_path: Path | None = None
    drift_md_path: Path | None = None
    if str(args.baseline_report or "").strip():
        baseline_path = Path(args.baseline_report).expanduser()
        if not baseline_path.is_absolute():
            baseline_path = (Path.cwd() / baseline_path).resolve()
        baseline_payload: dict | None = None
        if baseline_path.exists():
            loaded = json.loads(baseline_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                baseline_payload = loaded
        drift_thresholds = OfflineRegressionDriftThresholds(
            max_hallucination_rate_increase=args.max_hallucination_rate_increase,
            max_ece_increase=args.max_ece_increase,
            max_brier_increase=args.max_brier_increase,
            max_auc_drop=args.max_auc_drop,
        )
        drift_report = build_offline_regression_drift_report(
            current_report=report,
            baseline_report=baseline_payload,
            thresholds=drift_thresholds,
        )
        drift_report["generated_at"] = datetime.now(UTC).isoformat()
        drift_report["baseline_report_path"] = str(baseline_path)
        drift_status = str(drift_report.get("status") or "unknown")

        drift_json_path = Path(args.drift_report_json).expanduser()
        if not drift_json_path.is_absolute():
            drift_json_path = (output_dir / drift_json_path).resolve()
        drift_md_path = Path(args.drift_report_markdown).expanduser()
        if not drift_md_path.is_absolute():
            drift_md_path = (output_dir / drift_md_path).resolve()
        _write_json(drift_json_path, drift_report, overwrite=args.overwrite)
        _write_text(drift_md_path, render_offline_regression_drift_markdown(drift_report), overwrite=args.overwrite)

    print(
        json.dumps(
            {
                "ok": True,
                "status": report.get("status", "unknown"),
                "json_report": str(json_path),
                "markdown_report": str(md_path),
                "drift_status": drift_status,
                "drift_json_report": str(drift_json_path) if drift_json_path else None,
                "drift_markdown_report": str(drift_md_path) if drift_md_path else None,
                "strict_gate": args.strict_gate,
            },
            ensure_ascii=False,
        )
    )
    gate_failed = report.get("status") != "pass" or drift_status == "has_alerts"
    if args.strict_gate and gate_failed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

