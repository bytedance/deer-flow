"""Evaluation core helpers for DeerFlow eval suites."""

from deerflow.evaluation.checks import run_check, run_checks
from deerflow.evaluation.loader import LoadedSuite, load_eval_suite, normalize_suite_snapshot, suite_digest
from deerflow.evaluation.metrics import (
    EvaluationMetricsSummary,
    PairedComparison,
    VariantMetricSummary,
    build_metrics_summary,
    compare_paired_variants,
)
from deerflow.evaluation.reports import EvaluationReport, build_evaluation_report, render_markdown_report, report_to_json
from deerflow.evaluation.results import AttemptResult, CheckResult, CostSummary, normalize_attempt_result
from deerflow.evaluation.schema import EvalSuite
from deerflow.evaluation.workspace_seed import WorkspaceRef, materialize_workspace_seed

__all__ = [
    "AttemptResult",
    "CheckResult",
    "CostSummary",
    "EvalSuite",
    "EvaluationMetricsSummary",
    "EvaluationReport",
    "LoadedSuite",
    "PairedComparison",
    "VariantMetricSummary",
    "WorkspaceRef",
    "build_evaluation_report",
    "build_metrics_summary",
    "compare_paired_variants",
    "load_eval_suite",
    "materialize_workspace_seed",
    "normalize_attempt_result",
    "normalize_suite_snapshot",
    "render_markdown_report",
    "report_to_json",
    "run_check",
    "run_checks",
    "suite_digest",
]
