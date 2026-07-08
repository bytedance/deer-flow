"""Data quality scoring for local DuckDB tables."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from database import get_repository


@dataclass
class QualityIssue:
    """One data quality issue."""

    severity: str
    category: str
    title: str
    description: str
    columns: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)
    recommendation: str = ""


@dataclass
class QualityReport:
    """Complete table quality report."""

    table: str
    row_count: int
    column_count: int
    score: int
    grade: str
    generated_at: str
    issues: list[QualityIssue] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["issues"] = [asdict(issue) for issue in self.issues]
        return data


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _grade(score: int) -> str:
    if score >= 90:
        return "A"
    if score >= 75:
        return "B"
    if score >= 60:
        return "C"
    return "D"


def _issue_penalty(issue: QualityIssue) -> int:
    if issue.severity == "critical":
        return 18
    if issue.severity == "high":
        return 10
    if issue.severity == "medium":
        return 5
    return 2


def _column_expr(columns: list[str]) -> str:
    return ", ".join(_quote(col) for col in columns)


def analyze_table_quality(table: str, db_path: str = "workspace.duckdb") -> QualityReport:
    """Analyze a DuckDB table and return a quality score/report."""
    repo = get_repository(db_path)

    row_result = repo.execute_query(f"SELECT COUNT(*) AS cnt FROM {_quote(table)}")
    row_count = int(row_result[0]["cnt"]) if row_result else 0
    cols_info = repo.execute_query(f"DESCRIBE {_quote(table)}")
    columns = [row["column_name"] for row in cols_info]
    column_count = len(columns)
    issues: list[QualityIssue] = []
    metrics: dict[str, Any] = {
        "row_count": row_count,
        "column_count": column_count,
        "columns": {},
    }

    if row_count == 0:
        issues.append(QualityIssue(
            severity="critical",
            category="volume",
            title="表为空",
            description=f"表 `{table}` 没有任何数据行，无法支撑分析结论。",
            recommendation="先导入有效数据后再生成报告或 Dashboard。",
        ))
        return QualityReport(
            table=table,
            row_count=row_count,
            column_count=column_count,
            score=0,
            grade="D",
            generated_at=datetime.now().isoformat(timespec="seconds"),
            issues=issues,
            metrics=metrics,
        )

    for column in columns:
        safe_col = _quote(column)
        stats = repo.execute_query(
            f"""
            SELECT
                COUNT({safe_col}) AS non_null,
                COUNT(DISTINCT {safe_col}) AS unique_count
            FROM {_quote(table)}
            """
        )[0]
        non_null = int(stats["non_null"] or 0)
        unique_count = int(stats["unique_count"] or 0)
        null_count = row_count - non_null
        null_pct = round(null_count / max(row_count, 1) * 100, 2)
        unique_pct = round(unique_count / max(row_count, 1) * 100, 2)
        metrics["columns"][column] = {
            "non_null": non_null,
            "null_count": null_count,
            "null_pct": null_pct,
            "unique_count": unique_count,
            "unique_pct": unique_pct,
        }

        if null_pct >= 80:
            issues.append(QualityIssue(
                severity="critical",
                category="completeness",
                title=f"{column} 缺失率极高",
                description=f"`{column}` 缺失率为 {null_pct}%，基本不能作为可靠分析字段。",
                columns=[column],
                evidence={"null_pct": null_pct, "null_count": null_count},
                recommendation="确认字段来源；如非必要，从主要分析口径中排除。",
            ))
        elif null_pct >= 40:
            issues.append(QualityIssue(
                severity="high",
                category="completeness",
                title=f"{column} 缺失率较高",
                description=f"`{column}` 缺失率为 {null_pct}%，会影响分组、趋势或归因判断。",
                columns=[column],
                evidence={"null_pct": null_pct, "null_count": null_count},
                recommendation="补齐字段或在报告中明确样本限制。",
            ))
        elif null_pct >= 15:
            issues.append(QualityIssue(
                severity="medium",
                category="completeness",
                title=f"{column} 存在明显缺失",
                description=f"`{column}` 缺失率为 {null_pct}%，分析时需要说明口径限制。",
                columns=[column],
                evidence={"null_pct": null_pct, "null_count": null_count},
                recommendation="在统计口径说明中注明缺失处理方式。",
            ))

        if unique_count == 1 and non_null > 0:
            issues.append(QualityIssue(
                severity="low",
                category="variance",
                title=f"{column} 为常量列",
                description=f"`{column}` 只有 1 个非空取值，对分组分析贡献有限。",
                columns=[column],
                evidence={"unique_count": unique_count},
                recommendation="除非它代表固定过滤条件，否则不要作为分析维度。",
            ))

        if unique_pct >= 95 and row_count >= 20:
            issues.append(QualityIssue(
                severity="low",
                category="identity",
                title=f"{column} 可能是标识符",
                description=f"`{column}` 唯一率为 {unique_pct}%，更像 ID 字段，不适合直接聚合求和或作为普通维度。",
                columns=[column],
                evidence={"unique_pct": unique_pct, "unique_count": unique_count},
                recommendation="可作为去重键或关联键，不建议当作业务分类维度。",
            ))

    duplicate_count = 0
    if columns:
        distinct_rows = repo.execute_query(
            f"SELECT COUNT(*) AS cnt FROM (SELECT DISTINCT {_column_expr(columns)} FROM {_quote(table)})"
        )
        distinct_count = int(distinct_rows[0]["cnt"]) if distinct_rows else row_count
        duplicate_count = max(row_count - distinct_count, 0)
        duplicate_pct = round(duplicate_count / max(row_count, 1) * 100, 2)
        metrics["duplicate_rows"] = duplicate_count
        metrics["duplicate_pct"] = duplicate_pct

        if duplicate_pct >= 20:
            issues.append(QualityIssue(
                severity="high",
                category="duplicate",
                title="重复行比例较高",
                description=f"完全重复行占 {duplicate_pct}%，可能夸大总量类指标。",
                evidence={"duplicate_count": duplicate_count, "duplicate_pct": duplicate_pct},
                recommendation="确认主键或唯一键，分析前先去重或说明重复口径。",
            ))
        elif duplicate_pct >= 5:
            issues.append(QualityIssue(
                severity="medium",
                category="duplicate",
                title="存在重复行",
                description=f"完全重复行占 {duplicate_pct}%，可能影响计数和汇总。",
                evidence={"duplicate_count": duplicate_count, "duplicate_pct": duplicate_pct},
                recommendation="检查是否为重复导入或业务上允许的一单多行。",
            ))

    score = max(0, 100 - sum(_issue_penalty(issue) for issue in issues))
    return QualityReport(
        table=table,
        row_count=row_count,
        column_count=column_count,
        score=score,
        grade=_grade(score),
        generated_at=datetime.now().isoformat(timespec="seconds"),
        issues=issues,
        metrics=metrics,
    )


def render_quality_markdown(report: QualityReport) -> str:
    """Render a data quality report as Markdown."""
    lines = [
        "# 数据质量报告",
        "",
        f"- 表名: `{report.table}`",
        f"- 行数: {report.row_count}",
        f"- 字段数: {report.column_count}",
        f"- 质量分: {report.score} / 100",
        f"- 等级: {report.grade}",
        f"- 生成时间: {report.generated_at}",
        "",
        "## 问题概览",
        "",
    ]
    if not report.issues:
        lines.append("未发现明显数据质量问题。")
        lines.append("")
        return "\n".join(lines)

    lines.append("| 严重级别 | 类型 | 问题 | 字段 | 建议 |")
    lines.append("|---|---|---|---|---|")
    for issue in report.issues:
        lines.append(
            f"| {issue.severity} | {issue.category} | {issue.title}: {issue.description} | "
            f"{', '.join(issue.columns)} | {issue.recommendation} |"
        )
    lines.append("")
    return "\n".join(lines)


def write_quality_report(report: QualityReport, output_path: str = "", output_format: str = "markdown") -> Path:
    """Write a quality report to disk."""
    if output_path:
        path = Path(output_path)
    else:
        out_dir = PROJECT_ROOT / "outputs" / "quality"
        out_dir.mkdir(parents=True, exist_ok=True)
        suffix = "json" if output_format == "json" else "md"
        path = out_dir / f"{report.table}_quality_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{suffix}"
    path.parent.mkdir(parents=True, exist_ok=True)
    if output_format == "json":
        path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        path.write_text(render_quality_markdown(report), encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 DuckDB 表的数据质量评分")
    parser.add_argument("table", help="表名")
    parser.add_argument("--db", default="workspace.duckdb", help="DuckDB 数据库路径")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown", help="输出格式")
    parser.add_argument("--output", help="输出路径")
    parser.add_argument("--print", action="store_true", help="同时打印报告")
    args = parser.parse_args()

    report = analyze_table_quality(args.table, args.db)
    path = write_quality_report(report, args.output or "", args.format)
    if args.print:
        if args.format == "json":
            print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(render_quality_markdown(report))
    print(f"✅ 数据质量报告已生成: {path}")


if __name__ == "__main__":  # pragma: no cover
    main()
