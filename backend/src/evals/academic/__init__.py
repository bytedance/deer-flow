"""Academic evaluation framework."""

from .evaluator import evaluate_case, evaluate_dataset
from .failure_modes import (
    FAILURE_MODE_GATES_SCHEMA_VERSION,
    FailureModeThresholds,
    evaluate_failure_mode_library,
)
from .importer import import_accept_reject_dataset, import_accept_reject_payload
from .leaderboard import (
    LEADERBOARD_SCHEMA_VERSION,
    LeaderboardBucket,
    LeaderboardEntry,
    WeeklyLeaderboard,
    build_weekly_entries,
    merge_weekly_leaderboard,
)
from .loader import load_builtin_eval_cases, load_eval_cases
from .offline_benchmark_suite import (
    OFFLINE_BENCHMARK_SUITE_VERSION,
    REQUIRED_RAW_RECORD_FIELDS,
    TARGET_HARD_NEGATIVE_FAILURE_MODES,
    build_offline_benchmark_layers,
    write_offline_benchmark_layers,
)
from .offline_regression import (
    OfflineRegressionDriftThresholds,
    OfflineRegressionThresholds,
    build_offline_regression_drift_report,
    evaluate_offline_regression_layers,
    load_offline_layer_payloads,
    render_offline_regression_drift_markdown,
    render_offline_regression_markdown,
)
from .openreview_importer import build_openreview_raw_payload, build_openreview_raw_records
from .online_regression import (
    ONLINE_REGRESSION_SCHEMA_VERSION,
    OnlineDriftThresholds,
    OnlineRegressionHistory,
    OnlineRegressionRun,
    append_online_run,
    build_online_drift_report,
    build_online_run_from_eval_summary,
    build_online_run_from_offline_report,
    compare_online_runs,
    dump_online_regression_history,
    find_previous_commit_run,
    find_previous_week_run,
    load_online_regression_history,
    render_online_drift_markdown,
)
from .preprocessor import (
    preprocess_accept_reject_dataset,
    preprocess_accept_reject_payload,
    render_autofix_report_markdown,
)
from .schemas import AcademicEvalCase, AcademicEvalResult, AcademicEvalSummary
from .validator import (
    render_validation_report_markdown,
    validate_accept_reject_dataset,
    validate_accept_reject_payload,
)

__all__ = [
    "AcademicEvalCase",
    "AcademicEvalResult",
    "AcademicEvalSummary",
    "evaluate_case",
    "evaluate_dataset",
    "evaluate_failure_mode_library",
    "FailureModeThresholds",
    "FAILURE_MODE_GATES_SCHEMA_VERSION",
    "load_eval_cases",
    "load_builtin_eval_cases",
    "import_accept_reject_dataset",
    "import_accept_reject_payload",
    "LEADERBOARD_SCHEMA_VERSION",
    "LeaderboardEntry",
    "LeaderboardBucket",
    "WeeklyLeaderboard",
    "build_weekly_entries",
    "merge_weekly_leaderboard",
    "validate_accept_reject_dataset",
    "validate_accept_reject_payload",
    "render_validation_report_markdown",
    "preprocess_accept_reject_dataset",
    "preprocess_accept_reject_payload",
    "render_autofix_report_markdown",
    "OFFLINE_BENCHMARK_SUITE_VERSION",
    "REQUIRED_RAW_RECORD_FIELDS",
    "TARGET_HARD_NEGATIVE_FAILURE_MODES",
    "build_offline_benchmark_layers",
    "write_offline_benchmark_layers",
    "OfflineRegressionDriftThresholds",
    "OfflineRegressionThresholds",
    "build_offline_regression_drift_report",
    "evaluate_offline_regression_layers",
    "load_offline_layer_payloads",
    "render_offline_regression_drift_markdown",
    "render_offline_regression_markdown",
    "build_openreview_raw_records",
    "build_openreview_raw_payload",
    "ONLINE_REGRESSION_SCHEMA_VERSION",
    "OnlineDriftThresholds",
    "OnlineRegressionRun",
    "OnlineRegressionHistory",
    "build_online_run_from_eval_summary",
    "build_online_run_from_offline_report",
    "append_online_run",
    "load_online_regression_history",
    "dump_online_regression_history",
    "find_previous_commit_run",
    "find_previous_week_run",
    "compare_online_runs",
    "build_online_drift_report",
    "render_online_drift_markdown",
]
