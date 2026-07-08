"""
Insight Engine — Automated Data Pattern Discovery & Natural Language Insights.

This module provides the core analytical intelligence for the Agent BI system.
It automatically profiles data, discovers patterns (trends, anomalies, correlations),
and generates structured natural-language insights.

Architecture:
    Data Profiling → Multi-dim Aggregation → Pattern Discovery → Insight Generation

Usage:
    from scripts.insight_engine import InsightEngine

    engine = InsightEngine("workspace.duckdb")
    insights = engine.analyze("sales", dimensions=["region", "category"])
    for insight in insights:
        print(insight.severity, insight.title, insight.description)
"""

import sys
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Any, Optional

import duckdb
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import get_repository
from logging_config import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Type definitions
# ---------------------------------------------------------------------------

class InsightType(str, Enum):
    """Types of insights the engine can discover."""
    TREND = "trend"               # 上升/下降趋势
    ANOMALY = "anomaly"           # 异常点/离群值
    SEASONALITY = "seasonality"   # 周期性规律
    RANKING = "ranking"           # Top-N / Bottom-N 排名
    CORRELATION = "correlation"   # 相关性发现
    COMPOSITION = "composition"   # 构成/占比
    CHANGE = "change"             # 变化（环比/同比）
    SUMMARY = "summary"           # 汇总描述
    OUTLIER = "outlier"           # 离群值（个体级别）
    GAP = "gap"                   # 差距/差异


class Severity(str, Enum):
    """Insight severity level."""
    CRITICAL = "critical"   # 重大发现，需要立即关注
    HIGH = "high"           # 重要发现
    MEDIUM = "medium"       # 一般发现
    LOW = "low"             # 补充信息
    INFO = "info"           # 纯信息


@dataclass
class ColumnProfile:
    """Profiling result for a single column."""
    name: str
    dtype: str
    count: int
    unique_count: int
    null_count: int
    null_pct: float
    # Numeric columns only
    mean: Optional[float] = None
    median: Optional[float] = None
    std: Optional[float] = None
    min_val: Optional[float] = None
    max_val: Optional[float] = None
    p25: Optional[float] = None
    p75: Optional[float] = None
    # String columns only
    avg_length: Optional[float] = None
    top_values: Optional[list[dict]] = None  # [{value, count, pct}]
    # Date columns only
    min_date: Optional[str] = None
    max_date: Optional[str] = None
    date_range_days: Optional[int] = None
    # Category detection
    is_metric: bool = False
    is_category: bool = False
    is_date: bool = False
    is_geo: bool = False
    is_id: bool = False


@dataclass
class Insight:
    """A single analytical insight."""
    type: InsightType
    severity: Severity
    title: str
    description: str
    evidence: dict = field(default_factory=dict)  # supporting data
    related_columns: list[str] = field(default_factory=list)
    suggested_chart: Optional[str] = None  # e.g., "bar", "line", "heatmap"
    suggested_chart_config: dict = field(default_factory=dict)
    confidence: float = 0.0
    limitations: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        result = asdict(self)
        result["type"] = self.type.value
        result["severity"] = self.severity.value
        return result


@dataclass
class TableProfile:
    """Complete profile of a database table."""
    table_name: str
    row_count: int
    column_count: int
    columns: list[ColumnProfile] = field(default_factory=list)
    # Auto-detected roles
    date_columns: list[str] = field(default_factory=list)
    metric_columns: list[str] = field(default_factory=list)
    category_columns: list[str] = field(default_factory=list)
    geo_columns: list[str] = field(default_factory=list)
    id_columns: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Insight Engine
# ---------------------------------------------------------------------------

class InsightEngine:
    """Automated data pattern discovery and insight generation engine.

    This engine profiles data, discovers statistical patterns, and generates
    structured natural-language insights suitable for reports, dashboards,
    and conversational AI responses.

    Attributes:
        db_path: Path to the DuckDB database file.
        repo: DatabaseRepository instance.
    """

    # Thresholds for insight detection
    ANOMALY_ZSCORE_THRESHOLD = 2.5
    TREND_CHANGE_PCT_THRESHOLD = 10.0   # 10% change triggers trend insight
    CORRELATION_THRESHOLD = 0.7
    TOP_N_DEFAULT = 5
    HIGH_CARDINALITY_THRESHOLD = 100
    LOW_CARDINALITY_MAX = 20

    def __init__(self, db_path: str = "workspace.duckdb"):
        """Initialize the insight engine.

        Args:
            db_path: Path to the DuckDB database file.
        """
        self.db_path = db_path
        self.repo = get_repository(db_path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(
        self,
        table: str,
        dimensions: Optional[list[str]] = None,
        metric_columns: Optional[list[str]] = None,
        date_column: Optional[str] = None,
        top_n: int = 5,
        include_summary: bool = True,
    ) -> list[Insight]:
        """Run full analysis on a table and return ranked insights.

        This is the main entry point. It orchestrates profiling, pattern
        discovery, and insight generation.

        Args:
            table: Name of the table to analyze.
            dimensions: Category columns to slice by (auto-detected if None).
            metric_columns: Numeric columns to analyze (auto-detected if None).
            date_column: Date column for time-series analysis (auto-detected if None).
            top_n: Number of top items for ranking insights.
            include_summary: Whether to include summary insights.

        Returns:
            List of Insight objects, ranked by severity then impact.
        """
        logger.info("开始分析", table=table)
        all_insights: list[Insight] = []

        # Step 1: Profile the table
        profile = self.profile_table(table)
        if profile is None:
            logger.error("表不存在或无法读取", table=table)
            return []

        if include_summary:
            all_insights.extend(self._generate_summary_insights(profile))

        # Auto-detect columns if not specified
        if metric_columns is None:
            metric_columns = profile.metric_columns
        if date_column is None and profile.date_columns:
            date_column = profile.date_columns[0]
        if dimensions is None:
            dimensions = profile.category_columns[:3]

        if not metric_columns:
            logger.warning("未检测到数值列", table=table)
            return all_insights

        # Step 2: Ranking insights (per dimension)
        for dim in dimensions:
            for metric in metric_columns[:3]:  # limit to 3 metrics to avoid explosion
                ranking = self._discover_ranking(table, dim, metric, top_n)
                all_insights.extend(ranking)

        # Step 3: Composition insights
        for metric in metric_columns[:2]:
            for dim in dimensions[:2]:
                comp = self._discover_composition(table, dim, metric, top_n)
                all_insights.extend(comp)

        # Step 4: Trend insights (if date column available)
        if date_column:
            for metric in metric_columns[:2]:
                trends = self._discover_trends(table, date_column, metric)
                all_insights.extend(trends)

            # Step 5: Anomaly detection
            for metric in metric_columns[:2]:
                anomalies = self._detect_anomalies(table, date_column, metric)
                all_insights.extend(anomalies)

            # Step 6: Seasonality detection
            for metric in metric_columns[:2]:
                seasonality = self._detect_seasonality(table, date_column, metric)
                all_insights.extend(seasonality)

        # Step 7: Correlation insights (between metric columns)
        if len(metric_columns) >= 2:
            correlations = self._discover_correlations(table, metric_columns)
            all_insights.extend(correlations)

        # Step 8: Change insights (period-over-period)
        if date_column and len(metric_columns) >= 1:
            changes = self._discover_changes(table, date_column, metric_columns[0])
            all_insights.extend(changes)

        # Step 9: Confidence and limitation annotation
        all_insights = [self._annotate_insight_confidence(insight) for insight in all_insights]

        # Sort by severity priority
        severity_order = {
            Severity.CRITICAL: 0,
            Severity.HIGH: 1,
            Severity.MEDIUM: 2,
            Severity.LOW: 3,
            Severity.INFO: 4,
        }
        all_insights.sort(key=lambda i: severity_order.get(i.severity, 99))

        logger.info("分析完成", table=table, insight_count=len(all_insights))
        return all_insights

    def _annotate_insight_confidence(self, insight: Insight) -> Insight:
        """Populate confidence and limitations when not set by detectors."""
        if insight.confidence <= 0:
            base_by_type = {
                InsightType.SUMMARY: 0.95,
                InsightType.RANKING: 0.88,
                InsightType.COMPOSITION: 0.86,
                InsightType.TREND: 0.78,
                InsightType.CHANGE: 0.76,
                InsightType.ANOMALY: 0.72,
                InsightType.SEASONALITY: 0.65,
                InsightType.CORRELATION: 0.62,
                InsightType.OUTLIER: 0.68,
                InsightType.GAP: 0.70,
            }
            confidence = base_by_type.get(insight.type, 0.70)
            if not insight.evidence:
                confidence -= 0.20
            if insight.type in {InsightType.TREND, InsightType.ANOMALY, InsightType.SEASONALITY}:
                period_count = insight.evidence.get("period_count") or len(insight.evidence.get("monthly_averages", {}))
                if period_count and period_count < 6:
                    confidence -= 0.10
            insight.confidence = round(max(0.1, min(confidence, 0.99)), 2)

        if not insight.limitations:
            limitations = []
            if insight.type == InsightType.CORRELATION:
                limitations.append("相关性不等于因果，需要结合业务事件或外部变量验证。")
            if insight.type in {InsightType.SEASONALITY, InsightType.TREND, InsightType.ANOMALY, InsightType.CHANGE}:
                limitations.append("该判断基于当前表内时间序列，未纳入节假日、活动、价格、库存等外部因素。")
            if not insight.evidence:
                limitations.append("当前洞察缺少结构化证据，只能作为初步提示。")
            insight.limitations = limitations

        return insight

    def quick_scan(self, table: str) -> list[Insight]:
        """Fast scan — just profiling + ranking + anomalies.

        Use this when you need a quick overview without running all analyses.

        Args:
            table: Name of the table to scan.

        Returns:
            List of Insight objects.
        """
        return self.analyze(
            table,
            include_summary=True,
            top_n=3,
        )

    # ------------------------------------------------------------------
    # Data Profiling
    # ------------------------------------------------------------------

    def profile_table(self, table: str) -> Optional[TableProfile]:
        """Profile all columns in a table.

        Auto-detects column roles: metric (numeric), category (low-cardinality),
        date, geo, and id columns.

        Args:
            table: Name of the table to profile.

        Returns:
            TableProfile or None if table doesn't exist.
        """
        # Check table exists
        try:
            row_count = self.repo.execute_query(f'SELECT COUNT(*) AS cnt FROM "{table}"')
            row_count = row_count[0]["cnt"] if row_count else 0
        except Exception:
            return None

        # Get column info
        cols_info = self.repo.execute_query(f"DESCRIBE \"{table}\"")
        if not cols_info:
            return None

        profile = TableProfile(
            table_name=table,
            row_count=row_count,
            column_count=len(cols_info),
        )

        for col in cols_info:
            col_name = col["column_name"]
            col_type = str(col["column_type"]).lower()

            cp = self._profile_column(table, col_name, col_type, row_count)
            profile.columns.append(cp)

            # Auto-classify column roles
            if cp.is_metric:
                profile.metric_columns.append(col_name)
            if cp.is_category:
                profile.category_columns.append(col_name)
            if cp.is_date:
                profile.date_columns.append(col_name)
            if cp.is_geo:
                profile.geo_columns.append(col_name)
            if cp.is_id:
                profile.id_columns.append(col_name)

        return profile

    def _profile_column(
        self, table: str, col_name: str, col_type: str, total_rows: int
    ) -> ColumnProfile:
        """Profile a single column and classify its role."""
        safe_col = f'"{col_name}"'
        cp = ColumnProfile(
            name=col_name,
            dtype=col_type,
            count=total_rows,
            unique_count=0,
            null_count=0,
            null_pct=0.0,
        )

        # Get null and unique count
        try:
            stats = self.repo.execute_query(
                f"""
                SELECT
                    COUNT({safe_col}) AS non_null,
                    COUNT(DISTINCT {safe_col}) AS unique_vals
                FROM "{table}"
                """
            )
            if stats:
                non_null = stats[0]["non_null"] or 0
                cp.null_count = total_rows - non_null
                cp.null_pct = round(cp.null_count / max(total_rows, 1) * 100, 1)
                cp.unique_count = stats[0]["unique_vals"] or 0
        except Exception:
            pass

        # Numeric profiling
        if any(t in col_type for t in ("int", "float", "double", "decimal", "numeric", "bigint", "smallint", "tinyint", "hugeint")):
            cp.is_metric = True
            try:
                num_stats = self.repo.execute_query(
                    f"""
                    SELECT
                        AVG({safe_col}) AS mean_val,
                        MEDIAN({safe_col}) AS median_val,
                        STDDEV({safe_col}) AS std_val,
                        MIN({safe_col}) AS min_val,
                        MAX({safe_col}) AS max_val,
                        PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY {safe_col}) AS p25,
                        PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY {safe_col}) AS p75
                    FROM "{table}"
                    WHERE {safe_col} IS NOT NULL
                    """
                )
                if num_stats:
                    s = num_stats[0]
                    cp.mean = round(s["mean_val"], 2) if s["mean_val"] is not None else None
                    cp.median = round(s["median_val"], 2) if s["median_val"] is not None else None
                    cp.std = round(s["std_val"], 2) if s["std_val"] is not None else None
                    cp.min_val = round(s["min_val"], 2) if s["min_val"] is not None else None
                    cp.max_val = round(s["max_val"], 2) if s["max_val"] is not None else None
                    cp.p25 = round(s["p25"], 2) if s["p25"] is not None else None
                    cp.p75 = round(s["p75"], 2) if s["p75"] is not None else None
            except Exception:
                pass

            # Check if it's actually an ID column (high cardinality, almost all unique)
            if cp.unique_count > max(total_rows * 0.9, 100) and cp.unique_count > 50:
                cp.is_id = True
                cp.is_metric = False

        # Date profiling
        elif "date" in col_type or "timestamp" in col_type or "time" in col_type:
            cp.is_date = True
            try:
                date_stats = self.repo.execute_query(
                    f"""
                    SELECT
                        MIN({safe_col})::VARCHAR AS min_d,
                        MAX({safe_col})::VARCHAR AS max_d,
                        DATEDIFF('day', MIN({safe_col}), MAX({safe_col})) AS day_range
                    FROM "{table}"
                    WHERE {safe_col} IS NOT NULL
                    """
                )
                if date_stats:
                    cp.min_date = str(date_stats[0]["min_d"]) if date_stats[0]["min_d"] else None
                    cp.max_date = str(date_stats[0]["max_d"]) if date_stats[0]["max_d"] else None
                    cp.date_range_days = date_stats[0]["day_range"]
            except Exception:
                pass

        # String profiling
        elif "varchar" in col_type or "text" in col_type or "string" in col_type:
            try:
                str_stats = self.repo.execute_query(
                    f'SELECT AVG(LENGTH({safe_col})) AS avg_len FROM "{table}" WHERE {safe_col} IS NOT NULL'
                )
                if str_stats:
                    cp.avg_length = round(str_stats[0]["avg_len"], 1) if str_stats[0]["avg_len"] else None
            except Exception:
                pass

            # Classify: category vs. text
            if cp.unique_count <= self.LOW_CARDINALITY_MAX and cp.unique_count > 1:
                cp.is_category = True
                # Get top values
                try:
                    top = self.repo.execute_query(
                        f"""
                        SELECT {safe_col} AS val, COUNT(*) AS cnt
                        FROM "{table}"
                        WHERE {safe_col} IS NOT NULL
                        GROUP BY {safe_col}
                        ORDER BY cnt DESC
                        LIMIT 10
                        """
                    )
                    if top:
                        cp.top_values = [
                            {"value": str(r["val"]), "count": r["cnt"],
                             "pct": round(r["cnt"] / max(total_rows, 1) * 100, 1)}
                            for r in top
                        ]
                except Exception:
                    pass

                # Detect geo columns (province/city/region names)
                geo_keywords = ["省", "市", "区", "县", "地区", "区域", "省份", "城市",
                               "province", "city", "region", "country", "state", "area",
                               "地域", "地点", "位置"]
                if any(kw in col_name.lower() for kw in geo_keywords):
                    cp.is_geo = True

        return cp

    # ------------------------------------------------------------------
    # Pattern Discovery Methods
    # ------------------------------------------------------------------

    def _discover_ranking(
        self, table: str, dimension: str, metric: str, top_n: int
    ) -> list[Insight]:
        """Discover Top-N and Bottom-N rankings for a dimension-metric pair."""
        insights = []
        safe_dim = f'"{dimension}"'
        safe_metric = f'"{metric}"'

        try:
            # Top N
            agg_func = "SUM" if self._is_additive_metric(metric) else "AVG"
            top = self.repo.execute_query(
                f"""
                SELECT {safe_dim} AS dim_val, {agg_func}({safe_metric}) AS metric_val
                FROM "{table}"
                WHERE {safe_dim} IS NOT NULL AND {safe_metric} IS NOT NULL
                GROUP BY {safe_dim}
                ORDER BY metric_val DESC
                LIMIT {top_n}
                """
            )

            if top and len(top) >= 2:
                top_names = [str(r["dim_val"]) for r in top]
                top_values = [round(r["metric_val"], 1) for r in top]
                total = sum(v for v in top_values if v)
                concentration = round(top_values[0] / max(total, 0.01) * 100, 1) if total else 0

                if concentration >= 50 and top_n >= 3:
                    sev = Severity.HIGH
                elif concentration >= 30:
                    sev = Severity.MEDIUM
                else:
                    sev = Severity.LOW

                top_label = "、".join(top_names[:3])
                insights.append(Insight(
                    type=InsightType.RANKING,
                    severity=sev,
                    title=f"{dimension}维度 Top {top_n}",
                    description=f"{metric}最高的{top_n}个{dimension}为：{top_label}。"
                               f"其中{top_names[0]}以{top_values[0]}位居第一，"
                               f"占Top{top_n}总量的{concentration}%。",
                    evidence={
                        "dimension": dimension,
                        "metric": metric,
                        "top_items": [{"name": n, "value": v} for n, v in zip(top_names, top_values)],
                        "concentration_pct": concentration,
                    },
                    related_columns=[dimension, metric],
                    suggested_chart="bar",
                    suggested_chart_config={
                        "title": f"{dimension} - {metric} Top {top_n}",
                        "x_axis": "dim_val",
                        "y_axis": "metric_val",
                    },
                ))

            # Bottom N (only if interesting — e.g. negative values or large gaps)
            bottom = self.repo.execute_query(
                f"""
                SELECT {safe_dim} AS dim_val, {agg_func}({safe_metric}) AS metric_val
                FROM "{table}"
                WHERE {safe_dim} IS NOT NULL AND {safe_metric} IS NOT NULL
                GROUP BY {safe_dim}
                ORDER BY metric_val ASC
                LIMIT {top_n}
                """
            )
            if bottom and len(bottom) >= 2:
                bottom_names = [str(r["dim_val"]) for r in bottom]
                bottom_values = [round(r["metric_val"], 1) for r in bottom]

                # Only report bottom if values are notably low or negative
                if bottom_values[-1] < 0 or (top and top_values[-1] > bottom_values[-1] * 5):
                    insights.append(Insight(
                        type=InsightType.RANKING,
                        severity=Severity.MEDIUM,
                        title=f"{dimension}维度 Bottom {top_n}",
                        description=f"{metric}最低的{top_n}个{dimension}为：{'、'.join(bottom_names)}。"
                                   f"其中{bottom_names[0]}仅{bottom_values[0]}，值得关注。",
                        evidence={
                            "dimension": dimension,
                            "metric": metric,
                            "bottom_items": [{"name": n, "value": v} for n, v in zip(bottom_names, bottom_values)],
                        },
                        related_columns=[dimension, metric],
                        suggested_chart="bar",
                    ))

        except Exception as e:
            logger.warning("排名分析失败", dimension=dimension, metric=metric, error=str(e))

        return insights

    def _discover_composition(
        self, table: str, dimension: str, metric: str, top_n: int
    ) -> list[Insight]:
        """Discover composition/distribution insights (for pie/treemap charts)."""
        insights = []
        safe_dim = f'"{dimension}"'
        safe_metric = f'"{metric}"'

        try:
            dist = self.repo.execute_query(
                f"""
                SELECT {safe_dim} AS dim_val, SUM({safe_metric}) AS metric_val
                FROM "{table}"
                WHERE {safe_dim} IS NOT NULL AND {safe_metric} IS NOT NULL
                GROUP BY {safe_dim}
                ORDER BY metric_val DESC
                """
            )

            if dist and len(dist) >= 2:
                total = sum(r["metric_val"] for r in dist)
                if total == 0:
                    return []

                top_pct = round(dist[0]["metric_val"] / total * 100, 1)
                top2_pct = round(
                    (dist[0]["metric_val"] + (dist[1]["metric_val"] if len(dist) > 1 else 0)) / total * 100, 1
                )
                category_count = len(dist)

                if top_pct >= 70:
                    sev = Severity.HIGH
                    desc = (f"{metric}分布高度集中，{str(dist[0]['dim_val'])}占{top_pct}%，"
                            f"远超其他{category_count - 1}个{dimension}。")
                elif top2_pct >= 50:
                    sev = Severity.MEDIUM
                    desc = (f"前2个{dimension}（{str(dist[0]['dim_val'])}、{str(dist[1]['dim_val'])}）"
                            f"合计占{top2_pct}%，集中度较高。")
                else:
                    sev = Severity.LOW
                    desc = f"{category_count}个{dimension}分布相对均匀，无单一维度主导。"

                insights.append(Insight(
                    type=InsightType.COMPOSITION,
                    severity=sev,
                    title=f"{dimension}占比分析",
                    description=desc,
                    evidence={
                        "dimension": dimension,
                        "metric": metric,
                        "category_count": category_count,
                        "top_category": str(dist[0]["dim_val"]),
                        "top_pct": top_pct,
                        "top2_pct": top2_pct,
                    },
                    related_columns=[dimension, metric],
                    suggested_chart="pie",
                    suggested_chart_config={
                        "title": f"{dimension} - {metric} 占比",
                        "data": [{"name": str(r["dim_val"]), "value": r["metric_val"]} for r in dist[:10]],
                    },
                ))

        except Exception as e:
            logger.warning("占比分析失败", dimension=dimension, metric=metric, error=str(e))

        return insights

    def _discover_trends(
        self, table: str, date_column: str, metric: str
    ) -> list[Insight]:
        """Discover trend patterns in time series data."""
        insights = []
        safe_date = f'"{date_column}"'
        safe_metric = f'"{metric}"'

        try:
            # Determine granularity based on date range
            granularity = self._detect_time_granularity(table, date_column)

            # Monthly aggregation
            agg_query = f"""
                SELECT
                    DATE_TRUNC('{granularity}', {safe_date}) AS period,
                    SUM({safe_metric}) AS metric_val
                FROM "{table}"
                WHERE {safe_date} IS NOT NULL AND {safe_metric} IS NOT NULL
                GROUP BY DATE_TRUNC('{granularity}', {safe_date})
                ORDER BY period
            """
            rows = self.repo.execute_query(agg_query)

            if not rows or len(rows) < 3:
                return []

            values = [r["metric_val"] for r in rows]
            periods = [str(r["period"]) for r in rows]

            # Calculate trend using linear regression slope
            n = len(values)
            x_mean = (n - 1) / 2
            y_mean = sum(values) / n
            numerator = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
            denominator = sum((i - x_mean) ** 2 for i in range(n))
            slope = numerator / denominator if denominator != 0 else 0

            # Normalize slope as % of mean
            slope_pct = round(slope / max(abs(y_mean), 0.01) * 100, 2) if y_mean != 0 else 0

            # Determine trend direction and strength
            if abs(slope_pct) < 1:
                direction = "平稳"
                sev = Severity.INFO
                desc = f"{metric}在{periods[0]}至{periods[-1]}期间基本保持平稳，无明显趋势。"
            elif slope_pct > 0:
                strength = "强劲" if slope_pct >= 10 else "温和" if slope_pct >= 3 else "微弱"
                sev = Severity.HIGH if slope_pct >= 10 else Severity.MEDIUM if slope_pct >= 3 else Severity.LOW
                direction = f"{strength}上升"
                desc = (f"{metric}呈{strength}上升趋势，从{periods[0]}的{values[0]:.1f}到"
                       f"{periods[-1]}的{values[-1]:.1f}，月均增长约{slope_pct:.1f}%。")
            else:
                abs_pct = abs(slope_pct)
                strength = "显著" if abs_pct >= 10 else "温和" if abs_pct >= 3 else "微弱"
                sev = Severity.HIGH if abs_pct >= 10 else Severity.MEDIUM if abs_pct >= 3 else Severity.LOW
                direction = f"{strength}下降"
                desc = (f"{metric}呈{strength}下降趋势，从{periods[0]}的{values[0]:.1f}到"
                       f"{periods[-1]}的{values[-1]:.1f}，月均下降约{abs_pct:.1f}%。")

            insights.append(Insight(
                type=InsightType.TREND,
                severity=sev,
                title=f"{metric}趋势分析",
                description=desc,
                evidence={
                    "metric": metric,
                    "date_column": date_column,
                    "granularity": granularity,
                    "period_count": n,
                    "slope_pct": slope_pct,
                    "direction": direction,
                    "first_value": values[0],
                    "last_value": values[-1],
                    "first_period": periods[0],
                    "last_period": periods[-1],
                },
                related_columns=[date_column, metric],
                suggested_chart="line",
                suggested_chart_config={
                    "title": f"{metric} 趋势",
                    "x_data": periods,
                    "y_data": values,
                },
            ))

            # Detect recent acceleration/deceleration
            if n >= 6:
                first_half = sum(values[:n//2]) / (n//2)
                second_half = sum(values[n//2:]) / (n - n//2)
                if first_half != 0:
                    half_change = round((second_half - first_half) / abs(first_half) * 100, 1)
                    if abs(half_change) >= 20:
                        direction_word = "加速增长" if half_change > 0 else "加速下滑"
                        insights.append(Insight(
                            type=InsightType.TREND,
                            severity=Severity.HIGH if abs(half_change) >= 30 else Severity.MEDIUM,
                            title=f"{metric}趋势加速",
                            description=f"近期{metric}{direction_word}，后半段均值({second_half:.1f})"
                                       f"较前半段({first_half:.1f})变化{half_change}%。",
                            evidence={"half_change_pct": half_change},
                            related_columns=[date_column, metric],
                            suggested_chart="line",
                        ))

        except Exception as e:
            logger.warning("趋势分析失败", metric=metric, error=str(e))

        return insights

    def _detect_anomalies(
        self, table: str, date_column: str, metric: str
    ) -> list[Insight]:
        """Detect anomalous data points using Z-score method."""
        insights = []
        safe_date = f'"{date_column}"'
        safe_metric = f'"{metric}"'

        try:
            # Get monthly data
            rows = self.repo.execute_query(
                f"""
                SELECT
                    DATE_TRUNC('month', {safe_date}) AS period,
                    SUM({safe_metric}) AS metric_val
                FROM "{table}"
                WHERE {safe_date} IS NOT NULL AND {safe_metric} IS NOT NULL
                GROUP BY DATE_TRUNC('month', {safe_date})
                ORDER BY period
                """
            )
            if not rows or len(rows) < 6:
                return []

            values = [r["metric_val"] for r in rows]
            periods = [str(r["period"]) for r in rows]

            mean_val = sum(values) / len(values)
            std_val = (sum((v - mean_val) ** 2 for v in values) / len(values)) ** 0.5

            if std_val == 0:
                return []

            for i, (period, val) in enumerate(zip(periods, values)):
                zscore = (val - mean_val) / std_val
                if abs(zscore) >= self.ANOMALY_ZSCORE_THRESHOLD:
                    direction = "飙升" if zscore > 0 else "骤降"
                    sev = Severity.CRITICAL if abs(zscore) >= 3.5 else Severity.HIGH
                    deviation_pct = round((val - mean_val) / abs(mean_val) * 100, 1)

                    insights.append(Insight(
                        type=InsightType.ANOMALY,
                        severity=sev,
                        title=f"{period} {metric}异常{direction}",
                        description=f"{period}的{metric}为{val:.1f}，较均值({mean_val:.1f})"
                                   f"{direction}{abs(deviation_pct)}%（Z-score: {zscore:.1f}），属于异常波动。",
                        evidence={
                            "metric": metric,
                            "period": period,
                            "value": val,
                            "mean": mean_val,
                            "z_score": round(zscore, 2),
                            "deviation_pct": deviation_pct,
                        },
                        related_columns=[date_column, metric],
                        suggested_chart="line",
                    ))

        except Exception as e:
            logger.warning("异常检测失败", metric=metric, error=str(e))

        return insights

    def _detect_seasonality(
        self, table: str, date_column: str, metric: str
    ) -> list[Insight]:
        """Detect seasonal patterns by comparing month-of-year averages."""
        insights = []
        safe_date = f'"{date_column}"'
        safe_metric = f'"{metric}"'

        try:
            monthly_avg = self.repo.execute_query(
                f"""
                SELECT
                    EXTRACT(MONTH FROM {safe_date}) AS month_num,
                    AVG({safe_metric}) AS avg_val
                FROM "{table}"
                WHERE {safe_date} IS NOT NULL AND {safe_metric} IS NOT NULL
                GROUP BY EXTRACT(MONTH FROM {safe_date})
                ORDER BY month_num
                """
            )
            if not monthly_avg or len(monthly_avg) < 4:
                return []

            avgs = [r["avg_val"] for r in monthly_avg]
            overall_avg = sum(avgs) / len(avgs)
            max_avg = max(avgs)
            min_avg = min(avgs)

            if overall_avg == 0:
                return []

            # Check if seasonal variation is significant (>30% variation)
            variation = (max_avg - min_avg) / abs(overall_avg) * 100

            if variation >= 30:
                peak_month = monthly_avg[avgs.index(max_avg)]["month_num"]
                trough_month = monthly_avg[avgs.index(min_avg)]["month_num"]

                month_names = {1: "1月", 2: "2月", 3: "3月", 4: "4月", 5: "5月", 6: "6月",
                              7: "7月", 8: "8月", 9: "9月", 10: "10月", 11: "11月", 12: "12月"}

                insights.append(Insight(
                    type=InsightType.SEASONALITY,
                    severity=Severity.MEDIUM,
                    title=f"{metric}存在季节性规律",
                    description=f"{metric}呈现明显季节性波动（变动幅度{variation:.0f}%）。"
                               f"旺季为{month_names.get(peak_month, str(peak_month))}"
                               f"（均值{max_avg:.1f}），"
                               f"淡季为{month_names.get(trough_month, str(trough_month))}"
                               f"（均值{min_avg:.1f}）。",
                    evidence={
                        "metric": metric,
                        "variation_pct": round(variation, 1),
                        "peak_month": int(peak_month),
                        "trough_month": int(trough_month),
                        "peak_value": max_avg,
                        "trough_value": min_avg,
                        "monthly_averages": {str(r["month_num"]): r["avg_val"] for r in monthly_avg},
                    },
                    related_columns=[date_column, metric],
                    suggested_chart="line",
                ))

        except Exception as e:
            logger.warning("季节性分析失败", metric=metric, error=str(e))

        return insights

    def _discover_correlations(
        self, table: str, metric_columns: list[str]
    ) -> list[Insight]:
        """Discover correlations between metric columns."""
        insights = []

        try:
            # Build correlation query for all pairs
            if len(metric_columns) < 2:
                return []

            # Compute pairwise correlations using DuckDB's corr function
            for i in range(min(len(metric_columns), 5)):
                for j in range(i + 1, min(len(metric_columns), 5)):
                    col_a = metric_columns[i]
                    col_b = metric_columns[j]

                    corr_result = self.repo.execute_query(
                        f"""
                        SELECT CORR("{col_a}", "{col_b}") AS r_val
                        FROM "{table}"
                        WHERE "{col_a}" IS NOT NULL AND "{col_b}" IS NOT NULL
                        """
                    )
                    if not corr_result or corr_result[0]["r_val"] is None:
                        continue

                    r = corr_result[0]["r_val"]
                    if abs(r) >= self.CORRELATION_THRESHOLD:
                        direction = "正相关" if r > 0 else "负相关"
                        strength = "强" if abs(r) >= 0.85 else "中等"

                        insights.append(Insight(
                            type=InsightType.CORRELATION,
                            severity=Severity.MEDIUM if abs(r) >= 0.85 else Severity.LOW,
                            title=f"{col_a} 与 {col_b} {strength}{direction}",
                            description=f"{col_a}与{col_b}呈{strength}{direction}"
                                       f"（相关系数 r={r:.2f}），说明两者存在显著关联。",
                            evidence={
                                "column_a": col_a,
                                "column_b": col_b,
                                "correlation": round(r, 3),
                                "direction": direction,
                                "strength": strength,
                            },
                            related_columns=[col_a, col_b],
                            suggested_chart="scatter",
                            suggested_chart_config={
                                "x_axis": col_a,
                                "y_axis": col_b,
                                "title": f"{col_a} vs {col_b}",
                            },
                        ))

        except Exception as e:
            logger.warning("相关性分析失败", error=str(e))

        return insights

    def _discover_changes(
        self, table: str, date_column: str, metric: str
    ) -> list[Insight]:
        """Discover period-over-period changes."""
        insights = []
        safe_date = f'"{date_column}"'
        safe_metric = f'"{metric}"'

        try:
            # Month-over-month comparison for the last 2 months
            latest_months = self.repo.execute_query(
                f"""
                SELECT
                    DATE_TRUNC('month', {safe_date}) AS period,
                    SUM({safe_metric}) AS metric_val
                FROM "{table}"
                WHERE {safe_date} IS NOT NULL AND {safe_metric} IS NOT NULL
                GROUP BY DATE_TRUNC('month', {safe_date})
                ORDER BY period DESC
                LIMIT 3
                """
            )

            if len(latest_months) >= 2:
                current = latest_months[0]["metric_val"]
                previous = latest_months[1]["metric_val"]
                if previous and previous != 0:
                    mom_change = round((current - previous) / abs(previous) * 100, 1)

                    if abs(mom_change) >= self.TREND_CHANGE_PCT_THRESHOLD:
                        direction = "增长" if mom_change > 0 else "下降"
                        sev = (Severity.HIGH if abs(mom_change) >= 30
                               else Severity.MEDIUM if abs(mom_change) >= 20
                               else Severity.LOW)
                        cur_period = str(latest_months[0]["period"])
                        prev_period = str(latest_months[1]["period"])

                        insights.append(Insight(
                            type=InsightType.CHANGE,
                            severity=sev,
                            title=f"{metric}环比{direction}{abs(mom_change)}%",
                            description=f"{cur_period}的{metric}为{current:.1f}，"
                                       f"较上一期({prev_period}，{previous:.1f})"
                                       f"环比{direction}{abs(mom_change)}%。",
                            evidence={
                                "metric": metric,
                                "current_period": cur_period,
                                "previous_period": prev_period,
                                "current_value": current,
                                "previous_value": previous,
                                "change_pct": mom_change,
                                "direction": direction,
                            },
                            related_columns=[date_column, metric],
                            suggested_chart="bar",
                        ))

            # Year-over-year (same month, previous year)
            if len(latest_months) >= 1:
                current_month = latest_months[0]
                cur_period_str = str(current_month["period"])[:7]  # e.g., "2024-03"

                # Try to find the same month last year
                prev_year_month = self.repo.execute_query(
                    f"""
                    SELECT SUM({safe_metric}) AS metric_val
                    FROM "{table}"
                    WHERE {safe_date} IS NOT NULL AND {safe_metric} IS NOT NULL
                      AND DATE_TRUNC('month', {safe_date}) = DATE_TRUNC('month', {safe_date}) - INTERVAL '1 year'
                      AND DATE_TRUNC('month', {safe_date}) = '{cur_period_str}-01'::DATE
                    """
                )

                # DuckDB might not support the above syntax directly, use alternative
                try:
                    yoy = self.repo.execute_query(
                        f"""
                        SELECT
                            DATE_TRUNC('month', {safe_date}) AS period,
                            SUM({safe_metric}) AS metric_val
                        FROM "{table}"
                        WHERE {safe_date} IS NOT NULL
                          AND {safe_metric} IS NOT NULL
                          AND DATE_TRUNC('month', {safe_date}) = '{cur_period_str}-01'::DATE
                           OR DATE_TRUNC('month', {safe_date}) = (
                               '{cur_period_str}-01'::DATE - INTERVAL 1 YEAR
                           )
                        GROUP BY DATE_TRUNC('month', {safe_date})
                        ORDER BY period DESC
                        """
                    )
                    if len(yoy) >= 2:
                        cur_val = yoy[0]["metric_val"]
                        prev_val = yoy[1]["metric_val"]
                        if prev_val and prev_val != 0:
                            yoy_change = round((cur_val - prev_val) / abs(prev_val) * 100, 1)
                            if abs(yoy_change) >= self.TREND_CHANGE_PCT_THRESHOLD:
                                direction = "增长" if yoy_change > 0 else "下降"
                                sev = (Severity.HIGH if abs(yoy_change) >= 30
                                       else Severity.MEDIUM)
                                insights.append(Insight(
                                    type=InsightType.CHANGE,
                                    severity=sev,
                                    title=f"{metric}同比增长{yoy_change}%",
                                    description=f"{metric}较去年同期{direction}{abs(yoy_change)}%。",
                                    evidence={
                                        "metric": metric,
                                        "yoy_change_pct": yoy_change,
                                    },
                                    related_columns=[date_column, metric],
                                    suggested_chart="bar",
                                ))
                except Exception:
                    pass  # YoY comparison is best-effort

        except Exception as e:
            logger.warning("变化分析失败", metric=metric, error=str(e))

        return insights

    # ------------------------------------------------------------------
    # Summary Generation
    # ------------------------------------------------------------------

    def _generate_summary_insights(self, profile: TableProfile) -> list[Insight]:
        """Generate summary insights from table profile."""
        insights = []

        # Table overview
        col_summary = []
        if profile.metric_columns:
            col_summary.append(f"{len(profile.metric_columns)}个数值列")
        if profile.category_columns:
            col_summary.append(f"{len(profile.category_columns)}个分类列")
        if profile.date_columns:
            col_summary.append(f"{len(profile.date_columns)}个日期列")
        if profile.geo_columns:
            col_summary.append(f"{len(profile.geo_columns)}个地理列")

        insights.append(Insight(
            type=InsightType.SUMMARY,
            severity=Severity.INFO,
            title=f"数据概览：{profile.table_name}",
            description=f"该表包含{profile.row_count}条记录，{profile.column_count}个字段"
                       f"（{'、'.join(col_summary)}）。",
            evidence={
                "table": profile.table_name,
                "row_count": profile.row_count,
                "column_count": profile.column_count,
                "metric_columns": profile.metric_columns,
                "category_columns": profile.category_columns,
                "date_columns": profile.date_columns,
                "geo_columns": profile.geo_columns,
            },
        ))

        # Data quality: null rates
        high_null_cols = [
            c for c in profile.columns
            if c.null_pct >= 20 and not c.is_id
        ]
        if high_null_cols:
            col_names = "、".join(
                f"{c.name}({c.null_pct}%)" for c in high_null_cols[:5]
            )
            insights.append(Insight(
                type=InsightType.SUMMARY,
                severity=Severity.HIGH if any(c.null_pct >= 50 for c in high_null_cols) else Severity.MEDIUM,
                title="数据质量提醒",
                description=f"以下字段缺失率较高：{col_names}。建议在分析时注意数据完整性。",
                evidence={
                    "high_null_columns": [
                        {"name": c.name, "null_pct": c.null_pct}
                        for c in high_null_cols
                    ],
                },
            ))

        # Date range
        date_cols = [c for c in profile.columns if c.is_date and c.min_date and c.max_date]
        for dc in date_cols:
            insights.append(Insight(
                type=InsightType.SUMMARY,
                severity=Severity.INFO,
                title=f"时间范围：{dc.name}",
                description=f"数据时间跨度：{dc.min_date} 至 {dc.max_date}"
                           f"（共{dc.date_range_days}天）。",
                evidence={
                    "column": dc.name,
                    "min_date": dc.min_date,
                    "max_date": dc.max_date,
                    "range_days": dc.date_range_days,
                },
            ))

        # Key metrics summary
        for mc in profile.metric_columns[:3]:
            col_profile = next((c for c in profile.columns if c.name == mc), None)
            if col_profile and col_profile.mean is not None:
                # Build description safely handling None values
                mean_s = f"{col_profile.mean:.1f}" if col_profile.mean is not None else "N/A"
                median_s = f"{col_profile.median:.1f}" if col_profile.median is not None else "N/A"
                min_s = f"{col_profile.min_val:.1f}" if col_profile.min_val is not None else "N/A"
                max_s = f"{col_profile.max_val:.1f}" if col_profile.max_val is not None else "N/A"
                std_s = f"{col_profile.std:.1f}" if col_profile.std is not None else "N/A"
                insights.append(Insight(
                    type=InsightType.SUMMARY,
                    severity=Severity.INFO,
                    title=f"{mc}统计摘要",
                    description=(f"{mc}：均值{mean_s}，中位数{median_s}，"
                               f"范围[{min_s}, {max_s}]，标准差{std_s}。"),
                    evidence={
                        "column": mc,
                        "mean": col_profile.mean,
                        "median": col_profile.median,
                        "min": col_profile.min_val,
                        "max": col_profile.max_val,
                        "std": col_profile.std,
                    },
                    suggested_chart="boxplot",
                ))

        return insights

    # ------------------------------------------------------------------
    # Utility Methods
    # ------------------------------------------------------------------

    def _is_additive_metric(self, column_name: str) -> bool:
        """Guess whether a metric is additive (summable) vs. ratio/average.

        Ratio-like metrics (rates, percentages, averages) should use AVG
        instead of SUM for aggregation.
        """
        ratio_keywords = [
            "rate", "ratio", "pct", "percent", "percentage",
            "率", "比", "比例", "占比", "百分比",
            "avg", "average", "mean", "均", "平均",
            "price", "单价", "价格",
            "score", "评分", "分数",
        ]
        col_lower = column_name.lower()
        return not any(kw in col_lower for kw in ratio_keywords)

    def _detect_time_granularity(self, table: str, date_column: str) -> str:
        """Detect the best time granularity for trend analysis.

        Returns:
            One of 'day', 'week', 'month', 'quarter', 'year'.
        """
        safe_date = f'"{date_column}"'
        try:
            result = self.repo.execute_query(
                f"""
                SELECT DATEDIFF('day', MIN({safe_date}), MAX({safe_date})) AS day_range
                FROM "{table}"
                WHERE {safe_date} IS NOT NULL
                """
            )
            if result and result[0]["day_range"]:
                days = result[0]["day_range"]
                if days <= 31:
                    return "day"
                elif days <= 120:
                    return "week"
                elif days <= 730:
                    return "month"
                elif days <= 1825:
                    return "quarter"
                else:
                    return "year"
        except Exception:
            pass
        return "month"


# ---------------------------------------------------------------------------
# CLI Interface
# ---------------------------------------------------------------------------

def main():
    """Command-line entry point for the insight engine."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Insight Engine — Automated data pattern discovery",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/insight_engine.py analyze sales
  python scripts/insight_engine.py analyze sales --dimensions region,category --metric amount
  python scripts/insight_engine.py analyze sales --date-column order_date --quick
  python scripts/insight_engine.py profile sales
        """,
    )
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # analyze command
    analyze_parser = subparsers.add_parser("analyze", help="Run full analysis on a table")
    analyze_parser.add_argument("table", help="Table name")
    analyze_parser.add_argument("--dimensions", "-d", help="Comma-separated dimension columns")
    analyze_parser.add_argument("--metric", "-m", help="Comma-separated metric columns")
    analyze_parser.add_argument("--date-column", help="Date column for time-series analysis")
    analyze_parser.add_argument("--top-n", type=int, default=5, help="Top-N for rankings (default: 5)")
    analyze_parser.add_argument("--quick", action="store_true", help="Quick scan mode")
    analyze_parser.add_argument("--db", default="workspace.duckdb", help="Database path")
    analyze_parser.add_argument("--format", choices=["text", "json"], default="text", help="Output format")

    # profile command
    profile_parser = subparsers.add_parser("profile", help="Profile a table")
    profile_parser.add_argument("table", help="Table name")
    profile_parser.add_argument("--db", default="workspace.duckdb", help="Database path")
    profile_parser.add_argument("--format", choices=["text", "json"], default="text", help="Output format")

    args = parser.parse_args()

    engine = InsightEngine(args.db)

    if args.command == "analyze":
        dimensions = args.dimensions.split(",") if args.dimensions else None
        metric_cols = args.metric.split(",") if args.metric else None

        if args.quick:
            insights = engine.quick_scan(args.table)
        else:
            insights = engine.analyze(
                args.table,
                dimensions=dimensions,
                metric_columns=metric_cols,
                date_column=args.date_column,
                top_n=args.top_n,
            )

        if args.format == "json":
            import json
            print(json.dumps([i.to_dict() for i in insights], ensure_ascii=False, indent=2))
        else:
            _print_insights(insights)

    elif args.command == "profile":
        profile = engine.profile_table(args.table)
        if profile is None:
            print(f"❌ 表 '{args.table}' 不存在或无法读取")
            sys.exit(1)

        if args.format == "json":
            import json
            output = {
                "table": profile.table_name,
                "row_count": profile.row_count,
                "column_count": profile.column_count,
                "columns": [
                    {
                        "name": c.name,
                        "dtype": c.dtype,
                        "role": _get_column_role(c),
                        "null_pct": c.null_pct,
                        "unique_count": c.unique_count,
                        "mean": c.mean,
                        "median": c.median,
                        "min": c.min_val,
                        "max": c.max_val,
                    }
                    for c in profile.columns
                ],
            }
            print(json.dumps(output, ensure_ascii=False, indent=2))
        else:
            _print_profile(profile)

    else:
        parser.print_help()


def _get_column_role(col: ColumnProfile) -> str:
    """Get the primary role label for a column."""
    if col.is_date:
        return "日期"
    if col.is_id:
        return "ID"
    if col.is_geo:
        return "地理"
    if col.is_metric:
        return "数值"
    if col.is_category:
        return "分类"
    return "文本"


def _print_insights(insights: list[Insight]):
    """Pretty-print insights to terminal."""
    if not insights:
        print("📊 未发现显著洞察。数据可能比较均匀，或数据量不足。")
        return

    severity_icons = {
        Severity.CRITICAL: "🔴",
        Severity.HIGH: "🟠",
        Severity.MEDIUM: "🟡",
        Severity.LOW: "🔵",
        Severity.INFO: "⚪",
    }
    type_labels = {
        InsightType.TREND: "趋势",
        InsightType.ANOMALY: "异常",
        InsightType.SEASONALITY: "周期",
        InsightType.RANKING: "排名",
        InsightType.CORRELATION: "相关",
        InsightType.COMPOSITION: "占比",
        InsightType.CHANGE: "变化",
        InsightType.SUMMARY: "概要",
        InsightType.OUTLIER: "离群",
        InsightType.GAP: "差距",
    }

    print(f"\n{'='*70}")
    print(f"  📊 分析洞察报告 — 共 {len(insights)} 条发现")
    print(f"{'='*70}\n")

    for i, insight in enumerate(insights, 1):
        icon = severity_icons.get(insight.severity, "⚪")
        type_label = type_labels.get(insight.type, insight.type.value)
        print(f"  {i}. {icon} [{type_label}] {insight.title}")
        print(f"     {insight.description}")
        if insight.suggested_chart:
            print(f"     📈 推荐图表: {insight.suggested_chart}")
        print()


def _print_profile(profile: TableProfile):
    """Pretty-print table profile."""
    print(f"\n{'='*70}")
    print(f"  📋 数据画像: {profile.table_name}")
    print(f"{'='*70}")
    print(f"  行数: {profile.row_count:,}")
    print(f"  列数: {profile.column_count}")
    print(f"  数值列: {', '.join(profile.metric_columns) if profile.metric_columns else '无'}")
    print(f"  分类列: {', '.join(profile.category_columns) if profile.category_columns else '无'}")
    print(f"  日期列: {', '.join(profile.date_columns) if profile.date_columns else '无'}")
    print(f"  地理列: {', '.join(profile.geo_columns) if profile.geo_columns else '无'}")
    print(f"\n  列详情:")
    print(f"  {'名称':<20} {'类型':<12} {'角色':<6} {'缺失率':<8} {'唯一值':<8} {'均值/范围'}")
    print(f"  {'-'*70}")
    for c in profile.columns:
        role = _get_column_role(c)
        if c.mean is not None:
            summary = f"μ={c.mean:.1f} [{c.min_val}, {c.max_val}]"
        elif c.min_date:
            summary = f"{str(c.min_date)[:10]} ~ {str(c.max_date)[:10]}"
        else:
            summary = f"{c.unique_count} 个不同值"
        print(f"  {c.name:<20} {c.dtype:<12} {role:<6} {c.null_pct:>5.1f}%  {c.unique_count:>6,}  {summary}")
    print()


if __name__ == "__main__":
    main()
