"""
Report Engine — Automated Analysis Report Generation.

This module generates professional analysis reports from data insights,
supporting Markdown, HTML, and PDF output formats. It combines the Insight
Engine's structured findings with chart visualizations to produce
comprehensive, human-readable reports.

Architecture:
    Insights + Charts + Template → Structured Report → Multi-format Output

Usage:
    from scripts.report_engine import ReportEngine

    engine = ReportEngine("workspace.duckdb")
    report_path = engine.generate(
        table="sales",
        title="销售数据分析报告",
        output_format="html",
    )
"""

import json
import os
import sys
import html
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

import duckdb

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import get_repository
from logging_config import get_logger
from scripts.insight_engine import InsightEngine, Insight, InsightType, Severity, TableProfile

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Report data structures
# ---------------------------------------------------------------------------

@dataclass
class ReportSection:
    """A section within an analysis report."""
    heading: str
    level: int = 2  # Markdown heading level
    content: str = ""
    insights: list[Insight] = field(default_factory=list)
    subsections: list["ReportSection"] = field(default_factory=list)


@dataclass
class Report:
    """Complete analysis report."""
    title: str
    subtitle: str = ""
    generated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    sections: list[ReportSection] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


@dataclass
class ReportChart:
    """A single report chart generated from a Markdown chart recipe."""
    id: str
    title: str
    recipe_name: str
    recipe_context: str
    note: str
    option: dict
    appendix_id: str = ""


# ---------------------------------------------------------------------------
# Report Templates
# ---------------------------------------------------------------------------

REPORT_TEMPLATES = {
    "general": {
        "name": "通用数据分析报告",
        "description": "适用于各类数据表的通用分析报告模板",
        "sections": [
            {"heading": "报告摘要", "slug": "executive-summary"},
            {"heading": "数据概览", "slug": "data-overview"},
            {"heading": "关键指标分析", "slug": "key-metrics"},
            {"heading": "维度分析", "slug": "dimension-analysis"},
            {"heading": "趋势分析", "slug": "trend-analysis"},
            {"heading": "异常发现", "slug": "anomaly-findings"},
            {"heading": "相关性分析", "slug": "correlation-analysis"},
            {"heading": "建议与下一步", "slug": "recommendations"},
        ],
    },
    "sales": {
        "name": "销售分析报告",
        "description": "适用于销售数据的分析报告模板",
        "sections": [
            {"heading": "报告摘要", "slug": "executive-summary"},
            {"heading": "销售概况", "slug": "sales-overview"},
            {"heading": "产品销售分析", "slug": "product-analysis"},
            {"heading": "渠道与支付分析", "slug": "channel-analysis"},
            {"heading": "区域分析", "slug": "region-analysis"},
            {"heading": "趋势与预测", "slug": "trend-forecast"},
            {"heading": "问题与建议", "slug": "recommendations"},
        ],
    },
    "quick": {
        "name": "快速分析摘要",
        "description": "简洁的单页分析摘要，适合快速了解数据",
        "sections": [
            {"heading": "核心发现", "slug": "key-findings"},
            {"heading": "数据画像", "slug": "data-profile"},
            {"heading": "关键洞察", "slug": "key-insights"},
            {"heading": "行动建议", "slug": "actions"},
        ],
    },
}


# ---------------------------------------------------------------------------
# Report Engine
# ---------------------------------------------------------------------------

class ReportEngine:
    """Automated analysis report generator.

    This engine combines the Insight Engine's pattern discovery with
    professional report templates to produce comprehensive analysis
    reports in multiple formats.

    Attributes:
        db_path: Path to the DuckDB database file.
        insight_engine: InsightEngine instance for analysis.
        output_dir: Directory for generated reports.
    """

    def __init__(
        self,
        db_path: str = "workspace.duckdb",
        output_dir: str = "outputs/reports",
    ):
        """Initialize the report engine.

        Args:
            db_path: Path to the DuckDB database file.
            output_dir: Directory for generated reports.
        """
        self.db_path = db_path
        self.insight_engine = InsightEngine(db_path)
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(
        self,
        table: str,
        title: Optional[str] = None,
        template: str = "general",
        output_format: str = "markdown",
        output_path: Optional[str] = None,
        sections: Optional[list[str]] = None,
        include_charts: bool = True,
        **analysis_kwargs,
    ) -> str:
        """Generate a full analysis report.

        Args:
            table: Name of the table to analyze.
            title: Report title (auto-generated if None).
            template: Report template name ("general", "sales", "quick").
            output_format: Output format ("markdown", "html", "json").
            output_path: Output file path (auto-generated if None).
            sections: Specific sections to include (all if None).
            include_charts: Whether to include chart suggestions in the report.
            **analysis_kwargs: Additional args passed to InsightEngine.analyze().

        Returns:
            Path to the generated report file.
        """
        logger.info("开始生成报告", table=table, template=template)

        # Step 1: Profile & analyze
        profile = self.insight_engine.profile_table(table)
        if profile is None:
            raise ValueError(f"表 '{table}' 不存在或无法读取")

        insights = self.insight_engine.analyze(table, **analysis_kwargs)

        # Step 2: Build report structure from template
        template_config = REPORT_TEMPLATES.get(template, REPORT_TEMPLATES["general"])
        if title is None:
            title = f"{table} — {template_config['name']}"

        report = Report(
            title=title,
            subtitle=f"基于 {profile.row_count} 条数据的自动分析",
            metadata={
                "table_name": table,
                "row_count": profile.row_count,
                "column_count": profile.column_count,
                "template": template,
            },
        )

        # Step 3: Fill sections
        section_slugs = sections or [s["slug"] for s in template_config["sections"]]

        for section_config in template_config["sections"]:
            if section_config["slug"] not in section_slugs:
                continue

            section = self._build_section(
                section_config["slug"],
                section_config["heading"],
                profile,
                insights,
                include_charts,
            )
            if section:
                report.sections.append(section)

        # Step 4: Generate output
        if output_path is None:
            safe_table = table.replace("/", "_").replace(" ", "_")
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            ext = {"markdown": ".md", "html": ".html", "json": ".json"}[output_format]
            output_path = os.path.join(
                self.output_dir, f"{safe_table}_{template}_{timestamp}{ext}"
            )

        if output_format == "markdown":
            self._write_markdown(report, output_path, include_charts)
        elif output_format == "html":
            self._write_html(report, output_path, include_charts)
        elif output_format == "json":
            self._write_json(report, insights, output_path)

        logger.info("报告生成完成", path=output_path)
        return output_path

    def quick_report(
        self,
        table: str,
        output_format: str = "markdown",
    ) -> str:
        """Generate a quick summary report (fast mode).

        Args:
            table: Name of the table to analyze.
            output_format: Output format.

        Returns:
            Path to the generated report file.
        """
        return self.generate(
            table=table,
            template="quick",
            output_format=output_format,
            top_n=3,
            include_summary=True,
        )

    # ------------------------------------------------------------------
    # Section Builders
    # ------------------------------------------------------------------

    def _build_section(
        self,
        slug: str,
        heading: str,
        profile: TableProfile,
        insights: list[Insight],
        include_charts: bool,
    ) -> Optional[ReportSection]:
        """Build a report section from insights matching the slug."""

        # Route to specific builders
        builders = {
            "executive-summary": self._build_executive_summary,
            "data-overview": self._build_data_overview,
            "key-metrics": self._build_key_metrics,
            "dimension-analysis": self._build_dimension_analysis,
            "trend-analysis": self._build_trend_analysis,
            "anomaly-findings": self._build_anomaly_findings,
            "correlation-analysis": self._build_correlation_analysis,
            "recommendations": self._build_recommendations,
            # Sales template
            "sales-overview": self._build_data_overview,
            "product-analysis": self._build_dimension_analysis,
            "channel-analysis": self._build_dimension_analysis,
            "region-analysis": self._build_dimension_analysis,
            "trend-forecast": self._build_trend_analysis,
            # Quick template
            "key-findings": self._build_executive_summary,
            "data-profile": self._build_data_overview,
            "key-insights": self._build_dimension_analysis,
            "actions": self._build_recommendations,
        }

        builder = builders.get(slug)
        if builder:
            return builder(heading, profile, insights, include_charts)

        # Generic: collect matching insights
        return self._build_generic_section(heading, insights, include_charts)

    def _build_executive_summary(
        self,
        heading: str,
        profile: TableProfile,
        insights: list[Insight],
        include_charts: bool,
    ) -> ReportSection:
        """Build the executive summary section."""
        section = ReportSection(heading=heading, level=2)

        # Pick the most important insights
        high_severity = [
            i for i in insights
            if i.severity in (Severity.CRITICAL, Severity.HIGH)
        ][:3]

        summary_points = [self._stat_scope_note(profile, "summary")]
        # Key facts from profile
        summary_points.append(
            f"本报告基于 **{profile.table_name}** 表的 {profile.row_count:,} 条记录，"
            f"涵盖 {profile.column_count} 个字段。"
        )

        for insight in high_severity:
            summary_points.append(insight.description)

        # If we have trends, mention the direction
        trends = [i for i in insights if i.type == InsightType.TREND]
        anomalies = [i for i in insights if i.type == InsightType.ANOMALY]

        if anomalies:
            summary_points.append(
                f"⚠️ 检测到 {len(anomalies)} 个异常数据点，建议重点关注。"
            )

        section.content = "\n\n".join(f"- {p}" for p in summary_points)
        section.insights = high_severity

        return section

    def _build_data_overview(
        self,
        heading: str,
        profile: TableProfile,
        insights: list[Insight],
        include_charts: bool,
    ) -> ReportSection:
        """Build the data overview section."""
        section = ReportSection(heading=heading, level=2)

        lines = [self._stat_scope_note(profile, "overview"), ""]
        lines.append(f"| 属性 | 值 |")
        lines.append(f"|------|-----|")
        lines.append(f"| 表名 | {profile.table_name} |")
        lines.append(f"| 行数 | {profile.row_count:,} |")
        lines.append(f"| 列数 | {profile.column_count} |")

        if profile.date_columns:
            lines.append(f"| 日期列 | {', '.join(profile.date_columns)} |")
        if profile.metric_columns:
            lines.append(f"| 数值列 | {', '.join(profile.metric_columns)} |")
        if profile.category_columns:
            lines.append(f"| 分类列 | {', '.join(profile.category_columns)} |")
        if profile.geo_columns:
            lines.append(f"| 地理列 | {', '.join(profile.geo_columns)} |")

        section.content = "\n".join(lines)

        # Add column details
        col_lines = ["\n### 字段详情\n"]
        col_lines.append("| 字段 | 类型 | 缺失率 | 唯一值数 |")
        col_lines.append("|------|------|--------|----------|")
        for c in profile.columns:
            col_lines.append(
                f"| {c.name} | {c.dtype} | {c.null_pct}% | {c.unique_count:,} |"
            )
        section.content += "\n" + "\n".join(col_lines)

        summary_insights = [i for i in insights if i.type == InsightType.SUMMARY]
        section.insights = summary_insights

        return section

    def _build_key_metrics(
        self,
        heading: str,
        profile: TableProfile,
        insights: list[Insight],
        include_charts: bool,
    ) -> ReportSection:
        """Build the key metrics section with KPI-style cards."""
        section = ReportSection(heading=heading, level=2)

        metric_cols = profile.metric_columns[:5]
        lines = [self._stat_scope_note(profile, "metrics"), ""]
        lines.append("| 指标 | 均值 | 中位数 | 最小值 | 最大值 | 标准差 |")
        lines.append("|------|------|--------|--------|--------|--------|")

        for mc in metric_cols:
            col = next((c for c in profile.columns if c.name == mc), None)
            if col and col.mean is not None:
                lines.append(
                    f"| {col.name} | {col.mean:.1f} | {col.median:.1f} | "
                    f"{col.min_val:.1f} | {col.max_val:.1f} | {col.std:.1f} |"
                )

        section.content = "\n".join(lines)

        related = [
            i for i in insights
            if i.type in (InsightType.SUMMARY, InsightType.CHANGE)
            and any(c in profile.metric_columns for c in i.related_columns)
        ]
        section.insights = related

        return section

    def _build_dimension_analysis(
        self,
        heading: str,
        profile: TableProfile,
        insights: list[Insight],
        include_charts: bool,
    ) -> ReportSection:
        """Build dimension analysis section from ranking & composition insights."""
        section = ReportSection(heading=heading, level=2)

        ranking = [i for i in insights if i.type == InsightType.RANKING]
        composition = [i for i in insights if i.type == InsightType.COMPOSITION]

        # Group by dimension
        dim_groups: dict[str, list[Insight]] = {}
        for ins in ranking + composition:
            dim = ins.evidence.get("dimension", "其他")
            if dim not in dim_groups:
                dim_groups[dim] = []
            dim_groups[dim].append(ins)

        lines = [self._stat_scope_note(profile, "dimension"), ""]
        for dim, dim_insights in dim_groups.items():
            lines.append(f"### {dim}\n")
            for ins in dim_insights[:3]:
                lines.append(f"**{ins.title}**\n")
                lines.append(f"{ins.description}\n")

        section.content = "\n".join(lines)
        section.insights = ranking + composition

        return section

    def _build_trend_analysis(
        self,
        heading: str,
        profile: TableProfile,
        insights: list[Insight],
        include_charts: bool,
    ) -> ReportSection:
        """Build trend analysis section."""
        section = ReportSection(heading=heading, level=2)

        trends = [i for i in insights if i.type == InsightType.TREND]
        changes = [i for i in insights if i.type == InsightType.CHANGE]
        seasonality = [i for i in insights if i.type == InsightType.SEASONALITY]

        lines = [self._stat_scope_note(profile, "trend"), ""]

        if trends:
            lines.append("### 整体趋势\n")
            for ins in trends:
                lines.append(f"- **{ins.title}**：{ins.description}")

        if changes:
            lines.append("\n### 周期对比\n")
            for ins in changes:
                lines.append(f"- **{ins.title}**：{ins.description}")

        if seasonality:
            lines.append("\n### 季节性规律\n")
            for ins in seasonality:
                lines.append(f"- **{ins.title}**：{ins.description}")

        if profile.date_columns:
            lines.append(
                "\n### 波动原因边界\n"
                "当前只能基于已导入的时间、指标和维度字段观察波动。"
                "如需判断这是季节性波动还是外部因素导致，建议补充节假日、活动投放、价格调整、库存、天气、渠道策略等外部数据后再做交叉验证。"
            )

        section.content = "\n".join(lines)
        section.insights = trends + changes + seasonality

        return section

    def _build_anomaly_findings(
        self,
        heading: str,
        profile: TableProfile,
        insights: list[Insight],
        include_charts: bool,
    ) -> ReportSection:
        """Build anomaly findings section."""
        section = ReportSection(heading=heading, level=2)

        anomalies = [i for i in insights if i.type == InsightType.ANOMALY]

        if not anomalies:
            section.content = (
                f"{self._stat_scope_note(profile, 'anomaly')}\n\n"
                "未检测到显著异常数据点。该结论只基于当前数据表内的数值分布和时间变化，"
                "不等同于排除节假日、促销、投放、库存、天气等外部因素影响。"
            )
            return section

        lines = [self._stat_scope_note(profile, "anomaly"), ""]
        lines.append(f"检测到 **{len(anomalies)}** 个异常数据点：\n")
        lines.append("| 时间 | 指标 | 异常描述 | 严重程度 |")
        lines.append("|------|------|----------|----------|")

        sev_labels = {
            Severity.CRITICAL: "🔴 严重",
            Severity.HIGH: "🟠 重要",
            Severity.MEDIUM: "🟡 中等",
        }

        for ins in anomalies:
            period = ins.evidence.get("period", "N/A")
            metric = ins.evidence.get("metric", "N/A")
            sev = sev_labels.get(ins.severity, "低")
            lines.append(f"| {period} | {metric} | {ins.description[:60]}... | {sev} |")

        lines.append(
            "\n异常只能说明当前数据中存在明显偏离，不能直接证明原因。"
            "建议补充节假日、营销活动、价格、库存、履约、渠道变更等数据，进一步判断是季节性波动还是外部事件导致。"
        )

        section.content = "\n".join(lines)
        section.insights = anomalies

        return section

    def _build_correlation_analysis(
        self,
        heading: str,
        profile: TableProfile,
        insights: list[Insight],
        include_charts: bool,
    ) -> ReportSection:
        """Build correlation analysis section."""
        section = ReportSection(heading=heading, level=2)

        correlations = [i for i in insights if i.type == InsightType.CORRELATION]

        if not correlations:
            section.content = f"{self._stat_scope_note(profile, 'correlation')}\n\n未检测到显著相关性。"
            return section

        lines = [self._stat_scope_note(profile, "correlation"), ""]
        lines.append("| 指标 A | 指标 B | 相关系数 | 方向 | 强度 |")
        lines.append("|--------|--------|----------|------|------|")

        for ins in correlations:
            ev = ins.evidence
            lines.append(
                f"| {ev.get('column_a', 'N/A')} | {ev.get('column_b', 'N/A')} | "
                f"{ev.get('correlation', 'N/A')} | {ev.get('direction', 'N/A')} | "
                f"{ev.get('strength', 'N/A')} |"
            )

        section.content = "\n".join(lines)
        section.insights = correlations

        return section

    def _build_recommendations(
        self,
        heading: str,
        profile: TableProfile,
        insights: list[Insight],
        include_charts: bool,
    ) -> ReportSection:
        """Generate actionable recommendations based on insights."""
        section = ReportSection(heading=heading, level=2)

        scope_note = self._stat_scope_note(profile, "recommendations")
        recommendations = []

        # Check for high-severity anomalies → recommend investigation
        anomalies = [i for i in insights if i.type == InsightType.ANOMALY
                     and i.severity in (Severity.CRITICAL, Severity.HIGH)]
        if anomalies:
            cols = ", ".join(set(
                c for ins in anomalies for c in ins.related_columns
            ))
            recommendations.append(
                f"**深入调查异常数据**：建议对 {cols} 的 {len(anomalies)} 处异常值进行根因分析，并补充节假日、活动、价格、库存、渠道等外部数据，判断异常更接近季节性波动还是外部因素影响。"
            )

        # Check for negative trends → recommend action
        negative_trends = [
            i for i in insights
            if i.type == InsightType.TREND and "下降" in i.description
        ]
        if negative_trends:
            recommendations.append(
                f"**关注下降趋势**：部分指标呈下降趋势。当前数据可以确认趋势方向，但不能单独证明原因；建议补充外部环境、投放、价格、库存或运营动作数据后再判断原因。"
            )

        # Check concentration → recommend diversification
        high_conc = [
            i for i in insights
            if i.type == InsightType.COMPOSITION and i.severity == Severity.HIGH
        ]
        if high_conc:
            recommendations.append(
                f"**优化集中度风险**：部分维度过于集中，建议结合业务资源、供给能力和渠道策略确认是否需要分散风险。"
            )

        # Check data quality
        high_null = [c for c in profile.columns if c.null_pct >= 20]
        if high_null:
            recommendations.append(
                f"**提升数据质量**：{len(high_null)} 个字段缺失率超过 20%，建议完善数据采集流程，避免后续归因误判。"
            )

        # Positive findings
        positive_trends = [
            i for i in insights
            if i.type == InsightType.TREND and "增长" in i.description
        ]
        if positive_trends:
            recommendations.append(
                f"**巩固增长趋势**：部分指标呈现增长态势。建议结合渠道、活动、供给和外部环境数据确认增长来源，再决定是否复制相关动作。"
            )

        if not recommendations:
            recommendations.append(
                "基于当前数据，暂无特别需要关注的问题。建议持续监控关键指标变化。"
            )

        section.content = scope_note + "\n\n" + "\n\n".join(
            f"{i+1}. {r}" for i, r in enumerate(recommendations)
        )

        return section

    def _build_generic_section(
        self,
        heading: str,
        insights: list[Insight],
        include_charts: bool,
    ) -> ReportSection:
        """Build a generic section from any matching insights."""
        section = ReportSection(heading=heading, level=2)
        matching = insights[:5]  # take first 5

        if not matching:
            section.content = "暂无相关发现。"
            return section

        lines = []
        for ins in matching:
            lines.append(f"### {ins.title}\n")
            lines.append(f"{ins.description}\n")
            if include_charts and ins.suggested_chart:
                lines.append(f"📈 *建议图表类型: {ins.suggested_chart}*\n")

        section.content = "\n".join(lines)
        section.insights = matching

        return section

    def _stat_scope_note(self, profile: TableProfile, module: str) -> str:
        """Return a plain-language statistical scope note for a report module."""
        date_part = (
            f"时间上按 `{profile.date_columns[0]}` 观察"
            if profile.date_columns else "当前数据没有明确日期字段，所以不做时间周期判断"
        )
        metric_part = (
            f"数值上优先看 {', '.join(profile.metric_columns[:3])}"
            if profile.metric_columns else "当前数据没有明确数值指标，所以只做结构和数据质量观察"
        )
        category_part = (
            f"分组上优先按 {', '.join(profile.category_columns[:3])} 拆分"
            if profile.category_columns else "当前数据没有明确分类字段，所以不做维度拆分"
        )
        labels = {
            "summary": "本模块",
            "overview": "数据概览",
            "metrics": "关键指标",
            "dimension": "维度分析",
            "trend": "趋势分析",
            "anomaly": "异常分析",
            "correlation": "相关性分析",
            "recommendations": "行动建议",
        }
        label = labels.get(module, "本模块")
        return (
            f"**统计口径说明**：{label}基于当前导入表 `{profile.table_name}` 的 {profile.row_count:,} 条记录；"
            f"{date_part}；{metric_part}；{category_part}。"
            "没有在数据中出现、且用户没有明确提供的业务目标或 KPI，不纳入本报告判断。"
        )

    # ------------------------------------------------------------------
    # Output Formats
    # ------------------------------------------------------------------

    def _write_markdown(
        self,
        report: Report,
        output_path: str,
        include_charts: bool,
    ):
        """Write report as Markdown."""
        lines = []

        # Title
        lines.append(f"# {report.title}\n")
        if report.subtitle:
            lines.append(f"*{report.subtitle}*\n")
        lines.append(f"> 生成时间: {report.generated_at[:19]}\n")
        lines.append("---\n")

        # Table of contents
        lines.append("## 目录\n")
        for s in report.sections:
            anchor = s.heading.lower().replace(" ", "-")
            lines.append(f"- [{s.heading}](#{anchor})")
        lines.append("")

        # Sections
        for section in report.sections:
            lines.append(f"{'#' * section.level} {section.heading}\n")
            if section.content:
                lines.append(section.content)
                lines.append("")

            # Inline insights
            for ins in section.insights:
                lines.append(f"> **{ins.title}**")
                lines.append(f"> {ins.description}")
                if include_charts and ins.suggested_chart:
                    lines.append(f"> 📈 推荐图表: `{ins.suggested_chart}`")
                lines.append("")

        # Footer
        lines.append("---\n")
        lines.append(f"*报告由 Agent BI 自动生成 | {report.generated_at[:19]}*\n")

        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

    def _read_report_template(self) -> str:
        template_path = Path(__file__).resolve().parents[1] / "workflow_specs" / "html_templates" / "report_light.html"
        return template_path.read_text(encoding="utf-8")

    def _read_chart_recipe_context(self, recipe_name: str) -> str:
        """Read the ECharts md recipe from disk."""
        root = Path(__file__).resolve().parents[1]
        path = root / "references" / "examples" / recipe_name
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return ""

    def _load_echarts_js(self) -> str:
        path = Path(__file__).resolve().parents[1] / "assets" / "echarts" / "echarts.min.js"
        return path.read_text(encoding="utf-8")

    def _load_china_map_js(self) -> str:
        path = Path(__file__).resolve().parents[1] / "assets" / "echarts" / "china.js"
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return ""

    def _load_pdf_export_js(self) -> str:
        """Load local PDF export dependencies for standalone report HTML."""
        root = Path(__file__).resolve().parents[1] / "assets" / "dashboard"
        chunks = []
        for filename in ("html2canvas.min.js", "jspdf.umd.min.js"):
            path = root / filename
            try:
                chunks.append(path.read_text(encoding="utf-8"))
            except OSError:
                logger.warning("PDF 导出依赖缺失", path=str(path))
        return "\n".join(chunks)

    def _html_sections(self, report: Report) -> str:
        parts = []
        for idx, section in enumerate(report.sections, start=1):
            parts.append(f'<section id="section-{idx}">')
            parts.append(f"<h2>{idx}. {html.escape(section.heading)}</h2>")
            if section.content:
                parts.append(f'<div class="section-body">{self._md_to_html(section.content)}</div>')
            for ins in section.insights[:4]:
                severity = html.escape(ins.severity.value)
                parts.append(
                    '<div class="finding">'
                    f'<div class="finding-title">{html.escape(ins.title)}'
                    f'<span class="badge">{severity}</span></div>'
                    f'<p>{html.escape(ins.description)}</p>'
                    '</div>'
                )
            parts.append("</section>")
        return "\n".join(parts)

    def _html_toc(self, report: Report) -> str:
        items = "\n".join(
            f'<li><a href="#section-{idx}">{html.escape(section.heading)}</a></li>'
            for idx, section in enumerate(report.sections, start=1)
        )
        if report.metadata.get("has_charts"):
            chart_idx = len(report.sections) + 1
            items += f'\n<li><a href="#section-charts">图表举证</a></li>'
        return f'<nav class="toc"><h2>目录</h2><ol>{items}</ol></nav>'

    def _profile_for_table(self, table_name: str) -> TableProfile | None:
        try:
            return self.insight_engine.profile_table(table_name)
        except Exception:
            return None

    def _make_report_chart(
        self,
        chart_id: str,
        title: str,
        recipe_name: str,
        option: dict,
        appendix_id: str,
        note_prefix: str = "",
    ) -> ReportChart:
        """Create one chart spec from a selected Markdown recipe."""
        recipe_context = self._read_chart_recipe_context(recipe_name)
        if not recipe_context:
            raise ValueError(f"图表配方不存在或无法读取: references/examples/{recipe_name}")
        note = f"{note_prefix}基于 references/examples/{recipe_name} 配方上下文生成"
        return ReportChart(
            id=chart_id,
            title=title,
            recipe_name=recipe_name,
            recipe_context=recipe_context,
            note=note,
            option=option,
            appendix_id=appendix_id,
        )

    def _build_report_charts(self, table_name: str) -> tuple[str, str]:
        """Build ECharts panels one by one from Markdown recipe contexts."""
        profile = self._profile_for_table(table_name)
        if not profile:
            return "", ""

        chart_defs: list[ReportChart] = []
        date_col = profile.date_columns[0] if profile.date_columns else None
        metric_col = profile.metric_columns[0] if profile.metric_columns else None
        transaction_metric_col = self._select_transaction_metric(profile.metric_columns) or metric_col
        category_col = profile.category_columns[0] if profile.category_columns else None
        city_col = self._select_city_column(profile)

        with self.insight_engine.repo.connection() as conn:
            if date_col and metric_col:
                rows = conn.execute(
                    f'''
                    SELECT CAST({self._safe_identifier(date_col)} AS VARCHAR) AS label,
                           SUM({self._safe_identifier(metric_col)}) AS value
                    FROM {self._safe_identifier(table_name)}
                    WHERE {self._safe_identifier(date_col)} IS NOT NULL
                    GROUP BY 1
                    ORDER BY 1
                    LIMIT 30
                    '''
                ).fetchall()
                if rows:
                    chart_defs.append(self._make_report_chart(
                        "report_chart_trend",
                        f"{metric_col} 趋势",
                        "line-simple.md",
                        self._line_option(f"{metric_col} 趋势", rows),
                        "Data A1",
                    ))

            if category_col and metric_col:
                rows = conn.execute(
                    f'''
                    SELECT CAST({self._safe_identifier(category_col)} AS VARCHAR) AS label,
                           SUM({self._safe_identifier(metric_col)}) AS value
                    FROM {self._safe_identifier(table_name)}
                    WHERE {self._safe_identifier(category_col)} IS NOT NULL
                    GROUP BY 1
                    ORDER BY 2 DESC
                    LIMIT 12
                    '''
                ).fetchall()
                if rows:
                    chart_defs.append(self._make_report_chart(
                        "report_chart_bar",
                        f"{category_col} 贡献排行",
                        "bar-simple.md",
                        self._bar_option(f"{category_col} 贡献排行", rows),
                        "Data A2",
                    ))
                    chart_defs.append(self._make_report_chart(
                        "report_chart_pie",
                        f"{category_col} 结构占比",
                        "pie-simple.md",
                        self._pie_option(f"{category_col} 结构占比", rows[:8]),
                        "Data A2",
                    ))

            if city_col and transaction_metric_col:
                rows = conn.execute(
                    f'''
                    SELECT CAST({self._safe_identifier(city_col)} AS VARCHAR) AS label,
                           SUM({self._safe_identifier(transaction_metric_col)}) AS value
                    FROM {self._safe_identifier(table_name)}
                    WHERE {self._safe_identifier(city_col)} IS NOT NULL
                    GROUP BY 1
                    ORDER BY 2 DESC
                    LIMIT 40
                    '''
                ).fetchall()
                mapped_rows = [
                    (self._normalize_city_name(label), value)
                    for label, value in rows
                    if self._city_coord(self._normalize_city_name(label))
                ]
                if mapped_rows:
                    chart_defs.append(self._make_report_chart(
                        "report_chart_city_map",
                        f"城市{transaction_metric_col}地图",
                        "geo-map-scatter.md",
                        self._city_transaction_map_option(
                            f"城市{transaction_metric_col}分布",
                            mapped_rows,
                            transaction_metric_col,
                        ),
                        "Data A3",
                        note_prefix="检测到城市字段，",
                    ))

        panels = []
        chart_specs = []
        for chart in chart_defs:
            panels.append(
                f'<div class="chart-panel" data-recipe="{html.escape(chart.recipe_name)}" data-appendix="{html.escape(chart.appendix_id)}">'
                '<div class="chart-head">'
                f'<div class="chart-title">{html.escape(chart.title)}</div>'
                f'<div class="chart-note">{html.escape(chart.note)}；引用 {html.escape(chart.appendix_id)}</div>'
                '</div>'
                f'<div class="chart" id="{chart.id}" role="img" aria-label="{html.escape(chart.title)}"></div>'
                '</div>'
            )
            chart_specs.append({
                "id": chart.id,
                "title": chart.title,
                "recipe": f"references/examples/{chart.recipe_name}",
                "appendixId": chart.appendix_id,
                "option": chart.option,
            })

        boot = [
            "window.reportCharts = [];",
            f"window.reportChartSpecs = {json.dumps(chart_specs, ensure_ascii=False)};",
            """
function initReportChart(spec) {
  const el = document.getElementById(spec.id);
  if (!el) return;
  try {
    const chart = echarts.init(el);
    chart.setOption(spec.option, true);
    window.reportCharts.push(chart);
    window.requestAnimationFrame(function() { chart.resize(); });
  } catch (error) {
    console.error("Report chart render failed:", spec.id, spec.recipe, error);
    el.innerHTML = '<div class="chart-error">图表渲染失败：' + spec.title + '</div>';
  }
}
window.reportChartSpecs.forEach(initReportChart);
window.addEventListener("resize", function() {
  window.reportCharts.forEach(function(chart) {
    try { chart.resize(); } catch (error) {}
  });
});
""",
        ]
        return "\n".join(panels), "\n".join(boot)

    def _select_city_column(self, profile: TableProfile) -> str | None:
        candidates = profile.geo_columns + profile.category_columns
        city_keywords = ("city", "城市", "市")
        for col in candidates:
            lowered = col.lower()
            if any(keyword in lowered for keyword in city_keywords):
                return col
        return None

    def _select_transaction_metric(self, metric_columns: list[str]) -> str | None:
        keywords = ("交易额", "成交额", "销售额", "金额", "gmv", "amount", "sales", "revenue")
        for col in metric_columns:
            lowered = col.lower()
            if any(keyword in lowered for keyword in keywords):
                return col
        return None

    def _normalize_city_name(self, value: str) -> str:
        city = str(value).strip()
        aliases = {
            "北京": "北京市",
            "上海": "上海市",
            "天津": "天津市",
            "重庆": "重庆市",
            "广州": "广州市",
            "深圳": "深圳市",
            "杭州": "杭州市",
            "南京": "南京市",
            "苏州": "苏州市",
            "成都": "成都市",
            "武汉": "武汉市",
            "西安": "西安市",
            "郑州": "郑州市",
            "长沙": "长沙市",
            "青岛": "青岛市",
            "宁波": "宁波市",
            "厦门": "厦门市",
            "福州": "福州市",
            "东莞": "东莞市",
            "佛山": "佛山市",
        }
        if city in aliases:
            return aliases[city]
        return city

    def _city_coord(self, city: str) -> list[float] | None:
        coords = {
            "北京市": [116.4074, 39.9042],
            "上海市": [121.4737, 31.2304],
            "天津市": [117.2000, 39.1333],
            "重庆市": [106.5516, 29.5630],
            "广州市": [113.2644, 23.1291],
            "深圳市": [114.0579, 22.5431],
            "杭州市": [120.1551, 30.2741],
            "南京市": [118.7969, 32.0603],
            "苏州市": [120.5853, 31.2989],
            "成都市": [104.0665, 30.5728],
            "武汉市": [114.3055, 30.5928],
            "西安市": [108.9398, 34.3416],
            "郑州市": [113.6254, 34.7466],
            "长沙市": [112.9388, 28.2282],
            "青岛市": [120.3826, 36.0671],
            "宁波市": [121.5503, 29.8739],
            "厦门市": [118.0894, 24.4798],
            "福州市": [119.2965, 26.0745],
            "东莞市": [113.7518, 23.0207],
            "佛山市": [113.1214, 23.0215],
        }
        return coords.get(city)

    def _safe_identifier(self, identifier: str) -> str:
        return '"' + identifier.replace('"', '""') + '"'

    def _line_option(self, title: str, rows) -> dict:
        labels = [str(r[0]) for r in rows]
        values = [float(r[1] or 0) for r in rows]
        return {
            "title": {"text": title, "left": "center", "textStyle": {"fontSize": 13}},
            "tooltip": {"trigger": "axis"},
            "grid": {"left": 48, "right": 28, "top": 56, "bottom": 46},
            "xAxis": {"type": "category", "data": labels, "axisLabel": {"color": "#667085"}},
            "yAxis": {"type": "value", "axisLabel": {"color": "#667085"}, "splitLine": {"lineStyle": {"color": "#d8dee9"}}},
            "series": [{"data": values, "type": "line", "smooth": True, "areaStyle": {"opacity": 0.12}, "itemStyle": {"color": "#1f5eff"}}],
        }

    def _bar_option(self, title: str, rows) -> dict:
        labels = [str(r[0]) for r in rows]
        values = [float(r[1] or 0) for r in rows]
        return {
            "title": {"text": title, "left": "center", "textStyle": {"fontSize": 13}},
            "tooltip": {"trigger": "axis"},
            "grid": {"left": 56, "right": 28, "top": 56, "bottom": 72},
            "xAxis": {"type": "category", "data": labels, "axisLabel": {"color": "#667085", "rotate": 30}},
            "yAxis": {"type": "value", "axisLabel": {"color": "#667085"}, "splitLine": {"lineStyle": {"color": "#d8dee9"}}},
            "series": [{"data": values, "type": "bar", "itemStyle": {"color": "#1f5eff"}}],
        }

    def _pie_option(self, title: str, rows) -> dict:
        data = [{"name": str(r[0]), "value": float(r[1] or 0)} for r in rows]
        return {
            "title": {"text": title, "left": "center", "textStyle": {"fontSize": 13}},
            "tooltip": {"trigger": "item"},
            "legend": {"bottom": 4, "textStyle": {"color": "#667085"}},
            "series": [{"name": title, "type": "pie", "radius": ["38%", "66%"], "center": ["50%", "46%"], "data": data}],
        }

    def _city_transaction_map_option(self, title: str, rows, metric_name: str) -> dict:
        values = [float(r[1] or 0) for r in rows]
        max_value = max(values) if values else 0
        data = [
            {
                "name": city,
                "value": self._city_coord(city) + [float(value or 0)],
            }
            for city, value in rows
        ]
        return {
            "title": {"text": title, "left": "center", "textStyle": {"fontSize": 13}},
            "tooltip": {
                "trigger": "item",
                "formatter": "{b}<br/>" + metric_name + ": {@[2]}",
            },
            "geo": {
                "map": "china",
                "roam": False,
                "label": {"show": False},
                "itemStyle": {"areaColor": "#eef3fb", "borderColor": "#b8c2d1"},
                "emphasis": {"itemStyle": {"areaColor": "#dbeafe"}},
            },
            "visualMap": {
                "min": 0,
                "max": max_value,
                "left": 18,
                "bottom": 18,
                "calculable": True,
                "inRange": {"color": ["#c7d2fe", "#2563eb"]},
                "textStyle": {"color": "#667085"},
            },
            "series": [
                {
                    "name": metric_name,
                    "type": "effectScatter",
                    "coordinateSystem": "geo",
                    "data": data,
                    "symbolSize": 14,
                    "encode": {"value": 2},
                    "rippleEffect": {"brushType": "stroke"},
                    "itemStyle": {"color": "#1d4ed8"},
                }
            ],
        }

    def _write_html(
        self,
        report: Report,
        output_path: str,
        include_charts: bool,
    ):
        """Write report as template-based PDF-like HTML with real charts."""
        md_path = output_path.replace(".html", ".md")
        self._write_markdown(report, md_path, include_charts)

        table_name = report.metadata.get("table_name", "")
        row_count = report.metadata.get("row_count", "")
        chart_panels, chart_bootstrap = self._build_report_charts(table_name) if include_charts and table_name else ("", "")
        report.metadata["has_charts"] = bool(chart_panels)
        body = self._html_sections(report)
        if chart_panels:
            body += "\n<section id=\"section-charts\"><h2>图表举证</h2>" + chart_panels + "</section>"

        template = self._read_report_template()
        rendered = (
            template
            .replace("{{REPORT_TITLE}}", html.escape(report.title))
            .replace("{{REPORT_SUBTITLE}}", html.escape(report.subtitle or "企业级数据分析报告"))
            .replace("{{GENERATED_AT}}", html.escape(report.generated_at[:19]))
            .replace("{{TABLE_NAME}}", html.escape(str(table_name or "-")))
            .replace("{{ROW_COUNT}}", html.escape(str(row_count or "-")))
            .replace("{{TABLE_OF_CONTENTS}}", self._html_toc(report))
            .replace("{{REPORT_BODY}}", body)
            .replace("{{ECHARTS_JS}}", self._load_echarts_js() + "\n" + self._load_china_map_js())
            .replace("{{PDF_EXPORT_JS}}", self._load_pdf_export_js())
            .replace("{{CHART_BOOTSTRAP}}", chart_bootstrap)
        )

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(rendered)

    def _write_json(
        self,
        report: Report,
        insights: list[Insight],
        output_path: str,
    ):
        """Write report as structured JSON."""
        output = {
            "title": report.title,
            "subtitle": report.subtitle,
            "generated_at": report.generated_at,
            "sections": [
                {
                    "heading": s.heading,
                    "level": s.level,
                    "content": s.content,
                    "insights": [i.to_dict() for i in s.insights],
                }
                for s in report.sections
            ],
            "all_insights": [i.to_dict() for i in insights],
        }

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

    def _md_to_html(self, text: str) -> str:
        """Basic markdown-to-HTML conversion for report content."""
        import re

        # Tables: keep as-is
        if "|" in text:
            # Wrap tables in proper HTML
            lines = text.split("\n")
            in_table = False
            result = []
            for line in lines:
                if "|" in line and line.strip().startswith("|"):
                    if not in_table:
                        result.append("<table>")
                        in_table = True
                    cells = [c.strip() for c in line.split("|")[1:-1]]
                    tag = "th" if "---" in line else "td"
                    # Skip separator rows
                    if all(c.replace("-", "").replace(":", "").strip() == "" for c in cells):
                        continue
                    result.append(
                        "<tr>"
                        + "".join(f"<{tag}>{c}</{tag}>" for c in cells)
                        + "</tr>"
                    )
                else:
                    if in_table:
                        result.append("</table>")
                        in_table = False
                    if line.strip():
                        result.append(f"<p>{line}</p>")
            if in_table:
                result.append("</table>")
            return "\n".join(result)

        # Basic formatting
        text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)

        # Lists
        lines = text.split("\n")
        result = []
        in_list = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("- "):
                if not in_list:
                    result.append("<ul>")
                    in_list = True
                result.append(f"<li>{stripped[2:]}</li>")
            elif stripped.startswith(("1. ", "2. ", "3. ")):
                if not in_list:
                    result.append("<ol>")
                    in_list = True
                result.append(f"<li>{stripped[3:]}</li>")
            else:
                if in_list:
                    result.append("</ul>" if "<ul>" in result[-1] else "</ol>")
                    in_list = False
                if stripped:
                    result.append(f"<p>{stripped}</p>")
        if in_list:
            result.append("</ul>")
        return "\n".join(result)


# ---------------------------------------------------------------------------
# CLI Interface
# ---------------------------------------------------------------------------

def main():
    """Command-line entry point for the report engine."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Report Engine — Automated analysis report generation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/report_engine.py sales
  python scripts/report_engine.py sales --template sales --format html
  python scripts/report_engine.py sales --quick --format markdown
        """,
    )
    parser.add_argument("table", help="Table name to analyze and report")
    parser.add_argument("--title", "-t", help="Report title (auto-generated if omitted)")
    parser.add_argument("--template", choices=list(REPORT_TEMPLATES.keys()),
                       default="general", help="Report template")
    parser.add_argument("--format", "-f", choices=["markdown", "html", "json"],
                       default="markdown", help="Output format")
    parser.add_argument("--output", "-o", help="Output file path")
    parser.add_argument("--quick", action="store_true", help="Quick report mode")
    parser.add_argument("--db", default="workspace.duckdb", help="Database path")

    args = parser.parse_args()

    engine = ReportEngine(db_path=args.db)

    try:
        if args.quick:
            path = engine.quick_report(args.table, output_format=args.format)
        else:
            path = engine.generate(
                table=args.table,
                title=args.title,
                template=args.template,
                output_format=args.format,
                output_path=args.output,
            )
        print(f"✅ 报告已生成: {path}")
        if args.format in ("markdown", "html"):
            print(f"📂 在浏览器中打开: file://{os.path.abspath(path)}")
    except ValueError as e:
        print(f"❌ {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
