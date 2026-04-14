from __future__ import annotations

import json
from dataclasses import asdict

from deerflow.agents.memory.eval.comparator import compute_summary
from deerflow.agents.memory.eval.types import ComparisonResult, OutputFormatter

try:
    from rich.console import Console
    from rich.table import Table

    HAS_RICH = True
except ImportError:
    HAS_RICH = False


def _format_number(value: float) -> str:
    text = f"{value:.4f}"
    text = text.rstrip("0").rstrip(".")
    return text if text else "0"


def _direction(delta: float) -> str:
    if delta > 0:
        return "↑"
    if delta < 0:
        return "↓"
    return "→"


class TerminalFormatter(OutputFormatter):
    def format(self, results: list[ComparisonResult]) -> str:
        if not results:
            return "No comparison results."

        if HAS_RICH:
            console = Console(record=True, color_system=None, force_terminal=False, width=120)
            for result in results:
                table = Table(title=f"Trace {result.trace_id}")
                table.add_column("Metric Name")
                table.add_column("Baseline Value", justify="right")
                table.add_column("Comparison Value", justify="right")
                table.add_column("Delta", justify="right")
                table.add_column("Direction")
                for metric in sorted(set(result.baseline_metrics) | set(result.comparison_metrics) | set(result.deltas)):
                    baseline = result.baseline_metrics.get(metric, 0.0)
                    comparison = result.comparison_metrics.get(metric, 0.0)
                    delta = result.deltas.get(metric, comparison - baseline)
                    table.add_row(metric, _format_number(baseline), _format_number(comparison), _format_number(delta), _direction(delta))
                console.print(table)
                console.print()

            summary = Table(title="Average Across All Traces")
            summary.add_column("Metric Name")
            summary.add_column("Average Delta", justify="right")
            summary.add_column("Direction")
            for metric, delta in compute_summary(results).items():
                summary.add_row(metric, _format_number(delta), _direction(delta))
            console.print(summary)
            return console.export_text()

        lines: list[str] = []
        for result in results:
            metrics = sorted(set(result.baseline_metrics) | set(result.comparison_metrics) | set(result.deltas))
            rows = [
                (
                    metric,
                    _format_number(result.baseline_metrics.get(metric, 0.0)),
                    _format_number(result.comparison_metrics.get(metric, 0.0)),
                    _format_number(result.deltas.get(metric, result.comparison_metrics.get(metric, 0.0) - result.baseline_metrics.get(metric, 0.0))),
                    _direction(result.deltas.get(metric, result.comparison_metrics.get(metric, 0.0) - result.baseline_metrics.get(metric, 0.0))),
                )
                for metric in metrics
            ]
            headers = ["Metric Name", "Baseline Value", "Comparison Value", "Delta", "Direction"]
            widths = [len(h) for h in headers]
            for row in rows:
                for idx, cell in enumerate(row):
                    widths[idx] = max(widths[idx], len(cell))
            lines.append(f"Trace {result.trace_id}")
            lines.append(" | ".join(headers[i].ljust(widths[i]) if i == 0 else headers[i].rjust(widths[i]) for i in range(len(headers))))
            lines.append("-+-".join("-" * width for width in widths))
            for row in rows:
                lines.append(" | ".join(row[i].ljust(widths[i]) if i == 0 else row[i].rjust(widths[i]) for i in range(len(row))))
            lines.append("")

        summary = compute_summary(results)
        lines.append("Average Across All Traces")
        if summary:
            headers = ["Metric Name", "Average Delta", "Direction"]
            rows = [(metric, _format_number(delta), _direction(delta)) for metric, delta in summary.items()]
            widths = [len(h) for h in headers]
            for row in rows:
                for idx, cell in enumerate(row):
                    widths[idx] = max(widths[idx], len(cell))
            lines.append(" | ".join(headers[i].ljust(widths[i]) if i == 0 else headers[i].rjust(widths[i]) for i in range(len(headers))))
            lines.append("-+-".join("-" * width for width in widths))
            for row in rows:
                lines.append(" | ".join(row[i].ljust(widths[i]) if i == 0 else row[i].rjust(widths[i]) for i in range(len(row))))
        return "\n".join(lines).rstrip()


class JsonFormatter(OutputFormatter):
    def format(self, results: list[ComparisonResult]) -> str:
        payload = {
            "comparisons": [asdict(result) for result in results],
            "summary": {"avg_deltas": compute_summary(results)},
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)


class MarkdownFormatter(OutputFormatter):
    def format(self, results: list[ComparisonResult]) -> str:
        lines = ["# Evaluation Report", ""]
        lines.append("## Summary")
        summary = compute_summary(results)
        if summary:
            lines.extend(["| Metric | Average Delta |", "| --- | ---: |"])
            for metric, delta in summary.items():
                lines.append(f"| {metric} | {_format_number(delta)} |")
        else:
            lines.append("No comparison results.")

        lines.extend(["", "## Per-Trace Results", ""])
        if not results:
            lines.append("No comparison results.")
            return "\n".join(lines)

        for result in results:
            lines.append(f"### Trace {result.trace_id}")
            lines.append(f"- Baseline Strategy: {result.baseline_strategy}")
            lines.append(f"- Comparison Strategy: {result.comparison_strategy}")
            lines.append("")
            lines.extend(["| Metric | Baseline | Comparison | Delta |", "| --- | ---: | ---: | ---: |"])
            for metric in sorted(set(result.baseline_metrics) | set(result.comparison_metrics) | set(result.deltas)):
                baseline = result.baseline_metrics.get(metric, 0.0)
                comparison = result.comparison_metrics.get(metric, 0.0)
                delta = result.deltas.get(metric, comparison - baseline)
                lines.append(f"| {metric} | {_format_number(baseline)} | {_format_number(comparison)} | {_format_number(delta)} |")
            lines.append("")
        return "\n".join(lines).rstrip()


def get_formatter(name: str) -> OutputFormatter:
    formatters = {
        "terminal": TerminalFormatter,
        "json": JsonFormatter,
        "md": MarkdownFormatter,
        "markdown": MarkdownFormatter,
    }
    cls = formatters.get(name)
    if cls is None:
        raise ValueError(f"Unknown format: {name!r}. Choose from: {', '.join(formatters)}")
    return cls()
