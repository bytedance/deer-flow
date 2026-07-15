"""JSON and Markdown report builders for evaluation runs."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from deerflow.evaluation.metrics import EvaluationMetricsSummary, build_metrics_summary
from deerflow.evaluation.results import AttemptResult, selected_attempts
from deerflow.evaluation.schema import EvalSuite

REPORT_SCHEMA_VERSION = "deerflow.evaluation.report.v1"
RENDERED_EXPECTED_KEYS = (
    "benchmark_source",
    "professional_relevance",
    "complexity",
    "deterministic_oracle",
    "report_interpretation",
    "expected_failure_types",
    "capability_mapping",
)


class ReportSummary(BaseModel):
    total_attempts: int = 0
    passed_attempts: int = 0
    pass_rate: float | None = None
    status_counts: dict[str, int] = Field(default_factory=dict)
    conclusion_label: str | None = None


class ReportItem(BaseModel):
    suite_item_id: str
    variant_id: str
    sample_index: int
    attempt_index: int
    status: str
    failure_kind: str | None = None
    thread_id: str | None = None
    run_id: str | None = None
    workspace_path: str | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    check_results: list[dict[str, Any]] = Field(default_factory=list)
    run_event_summary: dict[str, Any] | None = None
    trace: dict[str, Any] = Field(default_factory=dict)
    expected: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class EvaluationReport(BaseModel):
    schema_version: str = REPORT_SCHEMA_VERSION
    eval_run_id: str | None = None
    generated_at: str
    suite: dict[str, Any]
    dataset_digest: str | None = None
    variants: list[dict[str, Any]] = Field(default_factory=list)
    summary: ReportSummary
    effect_summary: dict[str, Any] = Field(default_factory=dict)
    items: list[ReportItem] = Field(default_factory=list)


def build_evaluation_report(
    suite: EvalSuite,
    attempts: Iterable[AttemptResult],
    *,
    eval_run_id: str | None = None,
    dataset_digest: str | None = None,
    generated_at: datetime | None = None,
    metrics_summary: EvaluationMetricsSummary | None = None,
) -> EvaluationReport:
    selected = selected_attempts(list(attempts))
    metrics = metrics_summary or build_metrics_summary(suite, selected)
    status_counts = dict(Counter(attempt.status for attempt in selected))
    pass_rate = status_counts.get("passed", 0) / len(selected) if selected else None
    conclusion = metrics.comparison.conclusion_label if metrics.comparison is not None else None
    generated = generated_at or datetime.now(UTC)
    items_by_id = {item.id: item for item in suite.items}

    return EvaluationReport(
        eval_run_id=eval_run_id,
        generated_at=generated.isoformat(),
        suite={
            "name": suite.name,
            "version": suite.version,
            "item_count": len(suite.items),
        },
        dataset_digest=dataset_digest,
        variants=[variant.model_dump(mode="json", exclude_none=True) for variant in suite.variants],
        summary=ReportSummary(
            total_attempts=len(selected),
            passed_attempts=status_counts.get("passed", 0),
            pass_rate=pass_rate,
            status_counts=status_counts,
            conclusion_label=conclusion,
        ),
        effect_summary=metrics.model_dump(mode="json", exclude_none=True),
        items=[
            ReportItem(
                suite_item_id=attempt.suite_item_id,
                variant_id=attempt.variant_id,
                sample_index=attempt.sample_index,
                attempt_index=attempt.attempt_index,
                status=attempt.status,
                failure_kind=attempt.failure_kind,
                thread_id=attempt.thread_id,
                run_id=attempt.run_id,
                workspace_path=attempt.workspace_path,
                metrics=attempt.metrics,
                check_results=[check.model_dump(mode="json", exclude_none=True) for check in attempt.check_results],
                run_event_summary=attempt.run_event_summary,
                trace=_trace_ref(attempt.thread_id, attempt.run_id, attempt.run_event_summary),
                expected=items_by_id.get(attempt.suite_item_id).expected if attempt.suite_item_id in items_by_id else {},
                error=str(attempt.error) if attempt.error is not None else None,
            )
            for attempt in sorted(selected, key=lambda item: (item.suite_item_id, item.variant_id, item.sample_index))
        ],
    )


def report_to_json(report: EvaluationReport, *, indent: int = 2) -> str:
    return report.model_dump_json(indent=indent, exclude_none=True)


def render_markdown_report(report: EvaluationReport) -> str:
    suite = report.suite
    lines = [
        f"# DeerFlow Evaluation Report: {_md(str(suite['name']))}",
        "",
        f"- Schema: `{report.schema_version}`",
        f"- Generated at: `{report.generated_at}`",
        f"- Eval run: `{report.eval_run_id or 'n/a'}`",
        f"- Dataset digest: `{report.dataset_digest or 'n/a'}`",
        f"- Suite version: `{suite.get('version') or 'n/a'}`",
        "",
        "## Summary",
        "",
        f"- Attempts: `{report.summary.total_attempts}`",
        f"- Passed: `{report.summary.passed_attempts}`",
        f"- Pass rate: `{_format_rate(report.summary.pass_rate)}`",
        f"- Conclusion: `{report.summary.conclusion_label or 'n/a'}`",
        "",
    ]

    comparison = report.effect_summary.get("comparison")
    if comparison:
        lines.extend(
            [
                "## Comparison",
                "",
                f"- Baseline: `{comparison.get('baseline')}`",
                f"- Candidate: `{comparison.get('candidate')}`",
                f"- Status: `{comparison.get('status')}`",
                f"- Paired count: `{comparison.get('paired_count', 0)}`",
                f"- Conclusion: `{comparison.get('conclusion_label')}`",
                "",
            ]
        )
        deltas = comparison.get("deltas") or {}
        if deltas:
            lines.extend(["| Metric | Delta |", "| --- | ---: |"])
            for name, value in sorted(deltas.items()):
                lines.append(f"| `{_md(str(name))}` | `{value:.4f}` |")
            lines.append("")
        cost_delta = comparison.get("cost_delta") or {}
        if any(value is not None for value in cost_delta.values()):
            lines.extend(["Cost delta:", "", "| Metric | Delta ratio |", "| --- | ---: |"])
            for name, value in sorted(cost_delta.items()):
                rendered = "n/a" if value is None else f"{value:.4f}"
                lines.append(f"| `{_md(str(name))}` | `{rendered}` |")
            lines.append("")
        if comparison.get("missing_pairs"):
            lines.append("Missing pairs:")
            for missing in comparison["missing_pairs"]:
                lines.append(f"- `{_md(str(missing.get('suite_item_id')))}` sample `{missing.get('sample_index')}` missing `{', '.join(missing.get('missing_variants') or [])}`")
            lines.append("")

    if any(item.trace or item.run_event_summary for item in report.items):
        lines.extend(["## Trace", "", "| Item | Variant | Thread | Run | Events | Raw Trace | API |", "| --- | --- | --- | --- | --- | --- | --- |"])
        for item in report.items:
            trace = item.trace or {}
            event_types = trace.get("event_types") or (item.run_event_summary or {}).get("event_types") or {}
            events = ", ".join(f"{name}:{count}" for name, count in sorted(event_types.items())) or "n/a"
            raw_path = trace.get("local_jsonl_path")
            raw_link = f"[jsonl](file://{_md(str(raw_path))})" if raw_path else "n/a"
            api_path = trace.get("events_api_path")
            api_link = f"`{_md(str(api_path))}`" if api_path else "n/a"
            lines.append(f"| `{_md(item.suite_item_id)}` | `{_md(item.variant_id)}` | `{_md(item.thread_id or 'n/a')}` | `{_md(item.run_id or 'n/a')}` | `{_md(events)}` | {raw_link} | {api_link} |")
        lines.append("")

    item_contexts = _unique_item_contexts(report.items)
    if item_contexts:
        lines.extend(["## Item Context", ""])
        for suite_item_id, expected in item_contexts:
            lines.append(f"### `{_md(suite_item_id)}`")
            for key in (
                "benchmark_source",
                "professional_relevance",
                "complexity",
                "deterministic_oracle",
                "report_interpretation",
            ):
                value = expected.get(key)
                if value:
                    lines.append(f"- {_md(key.replace('_', ' ').title())}: {_md(str(value))}")
            expected_failure_types = expected.get("expected_failure_types") or []
            if expected_failure_types:
                lines.append(f"- Expected Failure Types: {_md(', '.join(str(item) for item in expected_failure_types))}")
            capabilities = expected.get("capability_mapping") or []
            if capabilities:
                lines.append(f"- Capability Mapping: {_md(', '.join(str(item) for item in capabilities))}")
            lines.append("")

    lines.extend(["## Items", "", "| Item | Variant | Sample | Status | Failure | Checks |", "| --- | --- | ---: | --- | --- | ---: |"])
    for item in report.items:
        failed_checks = sum(1 for check in item.check_results if not check.get("passed", False))
        lines.append(f"| `{_md(item.suite_item_id)}` | `{_md(item.variant_id)}` | `{item.sample_index}` | `{item.status}` | `{item.failure_kind or ''}` | `{failed_checks}/{len(item.check_results)}` |")

    return "\n".join(lines).rstrip() + "\n"


def _unique_item_contexts(items: list[ReportItem]) -> list[tuple[str, dict[str, Any]]]:
    seen: set[str] = set()
    contexts: list[tuple[str, dict[str, Any]]] = []
    for item in sorted(items, key=lambda value: value.suite_item_id):
        if item.suite_item_id in seen or not _has_renderable_context(item.expected):
            continue
        seen.add(item.suite_item_id)
        contexts.append((item.suite_item_id, item.expected))
    return contexts


def _has_renderable_context(expected: dict[str, Any]) -> bool:
    return any(expected.get(key) for key in RENDERED_EXPECTED_KEYS)


def _trace_ref(thread_id: str | None, run_id: str | None, run_event_summary: dict[str, Any] | None) -> dict[str, Any]:
    if not thread_id or not run_id:
        return {}
    trace: dict[str, Any] = {
        "thread_id": thread_id,
        "run_id": run_id,
        "events_api_path": f"/api/threads/{thread_id}/runs/{run_id}/events",
    }
    if isinstance(run_event_summary, dict):
        trace["event_count"] = run_event_summary.get("event_count", 0)
        trace["event_types"] = run_event_summary.get("event_types") or {}
    try:
        from deerflow.config.paths import get_paths

        trace["local_jsonl_path"] = str(get_paths().base_dir / "threads" / thread_id / "runs" / f"{run_id}.jsonl")
    except Exception:
        pass
    return trace


def _format_rate(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2%}"


def _md(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
