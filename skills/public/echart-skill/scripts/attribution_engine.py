"""
Attribution Engine — Root cause & contribution analysis.

Answers "why did X change?" by analyzing how each dimension contributes
to metric changes. Decomposes total change into per-dimension contributions
and recommends drill-down paths.

Methods:
    Contribution  — Multi-factor contribution decomposition
    Drill-down    — Auto-recommend the most informative drill paths
    Change-compare — Compare two periods and attribute the delta

Usage:
    from scripts.attribution_engine import AttributionEngine

    engine = AttributionEngine("workspace.duckdb")
    result = engine.explain_change("sales", "amount", "order_date",
                                    "2024-01", "2024-06", ["region", "category"])
"""

import sys, os
from dataclasses import dataclass, field
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import get_repository
from logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class Contribution:
    """A single dimension value's contribution to a change."""
    dimension: str
    value: str
    before_value: float
    after_value: float
    change: float
    change_pct: float
    contribution_pct: float  # % of total change
    is_primary_driver: bool = False


@dataclass
class AttributionResult:
    """Complete attribution analysis result."""
    metric: str
    date_column: str
    period_before: str
    period_after: str
    total_before: float
    total_after: float
    total_change: float
    total_change_pct: float
    change_direction: str  # "increase" or "decrease"
    contributions: list[Contribution] = field(default_factory=list)
    top_drivers: list[Contribution] = field(default_factory=list)
    drill_recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "metric": self.metric, "date_column": self.date_column,
            "period_before": self.period_before, "period_after": self.period_after,
            "total_before": self.total_before, "total_after": self.total_after,
            "total_change": self.total_change, "total_change_pct": self.total_change_pct,
            "change_direction": self.change_direction,
            "contributions": [
                {"dimension": c.dimension, "value": c.value,
                 "before": c.before_value, "after": c.after_value,
                 "change": c.change, "change_pct": c.change_pct,
                 "contribution_pct": c.contribution_pct,
                 "is_primary_driver": c.is_primary_driver}
                for c in self.contributions
            ],
            "top_drivers": [
                {"dimension": c.dimension, "value": c.value,
                 "change": c.change, "contribution_pct": c.contribution_pct}
                for c in self.top_drivers
            ],
            "drill_recommendations": self.drill_recommendations,
        }


class AttributionEngine:
    """Root cause analysis — answers "why did X change?"."""

    DRIVER_THRESHOLD = 15.0  # Min contribution % to be a primary driver

    def __init__(self, db_path: str = "workspace.duckdb"):
        self.db_path = db_path
        self.repo = get_repository(db_path)

    def explain_change(
        self,
        table: str,
        metric: str,
        date_column: str,
        period_before: str,
        period_after: str,
        dimensions: list[str],
        top_n: int = 8,
    ) -> AttributionResult:
        """Explain what drove the change in a metric between two periods.

        Args:
            table: Table name.
            metric: Metric column.
            date_column: Date column.
            period_before: Start of baseline period (YYYY-MM-DD).
            period_after: Start of comparison period.
            dimensions: Dimension columns to analyze.
            top_n: Max contributions to return per dimension.

        Returns:
            AttributionResult with contribution breakdown.
        """
        logger.info("归因分析开始", metric=metric, dims=dimensions)

        safe_date = f'"{date_column}"'
        safe_metric = f'"{metric}"'

        # Get totals for both periods
        total_before = self._get_period_total(table, metric, date_column, period_before)
        total_after = self._get_period_total(table, metric, date_column, period_after)
        total_change = total_after - total_before
        total_change_pct = round(total_change / max(abs(total_before), 0.01) * 100, 1)

        result = AttributionResult(
            metric=metric, date_column=date_column,
            period_before=period_before, period_after=period_after,
            total_before=total_before, total_after=total_after,
            total_change=total_change, total_change_pct=total_change_pct,
            change_direction="increase" if total_change > 0 else "decrease",
        )

        # Analyze each dimension
        for dim in dimensions:
            contributions = self._analyze_dimension(
                table, metric, date_column, dim,
                period_before, period_after, total_change, top_n,
            )
            result.contributions.extend(contributions)

        # Sort by absolute contribution
        result.contributions.sort(key=lambda c: abs(c.contribution_pct), reverse=True)

        # Identify top drivers
        result.top_drivers = [
            c for c in result.contributions
            if abs(c.contribution_pct) >= self.DRIVER_THRESHOLD
        ][:5]

        # Generate drill recommendations
        result.drill_recommendations = self._generate_recommendations(result)

        logger.info("归因分析完成", drivers=len(result.top_drivers))
        return result

    def quick_explain(
        self, table: str, metric: str, date_column: str,
        period_before: str, period_after: str,
    ) -> AttributionResult:
        """Quick attribution with auto-detected dimensions."""
        from scripts.insight_engine import InsightEngine
        engine = InsightEngine(self.db_path)
        profile = engine.profile_table(table)
        dimensions = profile.category_columns[:3] if profile else []
        return self.explain_change(table, metric, date_column,
                                   period_before, period_after, dimensions)

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _get_period_total(self, table, metric, date_col, period_start) -> float:
        safe_date = f'"{date_col}"'
        safe_metric = f'"{metric}"'
        # period_start should be a month identifier like "2024-01"
        rows = self.repo.execute_query(
            f"""SELECT SUM({safe_metric}) AS total FROM "{table}"
                WHERE DATE_TRUNC('month', {safe_date}) = '{period_start}-01'::DATE"""
        )
        return float(rows[0]["total"] or 0) if rows else 0.0

    def _analyze_dimension(
        self, table, metric, date_col, dim,
        period_before, period_after, total_change, top_n,
    ) -> list[Contribution]:
        """Analyze how a dimension contributes to the total change."""
        safe_dim = f'"{dim}"'
        safe_metric = f'"{metric}"'
        safe_date = f'"{date_col}"'

        rows = self.repo.execute_query(
            f"""SELECT {safe_dim} AS dim_val,
                   SUM(CASE WHEN DATE_TRUNC('month', {safe_date}) = '{period_before}-01'::DATE
                       THEN {safe_metric} ELSE 0 END) AS before_val,
                   SUM(CASE WHEN DATE_TRUNC('month', {safe_date}) = '{period_after}-01'::DATE
                       THEN {safe_metric} ELSE 0 END) AS after_val
            FROM "{table}"
            WHERE {safe_dim} IS NOT NULL
            GROUP BY {safe_dim}
            ORDER BY ABS(after_val - before_val) DESC
            LIMIT {top_n}"""
        )

        contributions = []
        for r in rows:
            before = float(r["before_val"] or 0)
            after = float(r["after_val"] or 0)
            change = after - before
            change_pct = round(change / max(abs(before), 0.01) * 100, 1) if before else 0
            contrib = round(change / max(abs(total_change), 0.01) * 100, 1) if total_change else 0

            contributions.append(Contribution(
                dimension=dim, value=str(r["dim_val"]),
                before_value=before, after_value=after,
                change=change, change_pct=change_pct,
                contribution_pct=contrib,
                is_primary_driver=abs(contrib) >= AttributionEngine.DRIVER_THRESHOLD,
            ))

        return contributions

    def _generate_recommendations(self, result: AttributionResult) -> list[str]:
        """Generate human-readable drill recommendations."""
        recs = []

        if result.top_drivers:
            top = result.top_drivers[0]
            direction = "增长" if top.change > 0 else "下降"
            recs.append(
                f"🔍 主要{'增长' if result.total_change > 0 else '下降'}驱动力是"
                f"{top.dimension}维度的「{top.value}」（{direction}{abs(top.change):.1f}，"
                f"贡献{abs(top.contribution_pct):.0f}%）。建议深挖该维度的明细数据。"
            )

        # Check for compensating effects
        increasers = [c for c in result.contributions if c.change > 0]
        decreasers = [c for c in result.contributions if c.change < 0]
        if increasers and decreasers:
            recs.append(
                f"⚖️ 存在抵消效应：{len(increasers)}个维度增长、"
                f"{len(decreasers)}个维度下降，建议分别分析。"
            )

        if not result.top_drivers:
            recs.append("📊 变化分散在多个维度，无单一主导因素。建议扩大分析范围。")

        return recs


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    import argparse, json

    parser = argparse.ArgumentParser(
        description="Attribution Engine — Root cause analysis",
        epilog="Example: python scripts/attribution_engine.py orders 金额 交易时间 2016-01 2016-06 -d 商品分类,渠道",
    )
    parser.add_argument("table")
    parser.add_argument("metric")
    parser.add_argument("date_column")
    parser.add_argument("period_before")
    parser.add_argument("period_after")
    parser.add_argument("--dimensions", "-d", help="Comma-separated dimensions")
    parser.add_argument("--db", default="workspace.duckdb")
    parser.add_argument("--top-n", type=int, default=8)
    parser.add_argument("--format", choices=["text", "json"], default="text")

    args = parser.parse_args()
    dims = args.dimensions.split(",") if args.dimensions else ["商品分类", "渠道", "支付方式"]

    engine = AttributionEngine(args.db)
    result = engine.explain_change(
        args.table, args.metric, args.date_column,
        args.period_before, args.period_after, dims, args.top_n,
    )

    if args.format == "json":
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"\n🔍 归因分析: {result.metric}")
        print(f"   {result.period_before} → {result.period_after}")
        print(f"   变化: {result.total_before:.1f} → {result.total_after:.1f} "
              f"({result.total_change_pct:+.1f}%)\n")
        if result.top_drivers:
            print("   📌 主要驱动力:")
            for c in result.top_drivers:
                print(f"     {c.dimension}「{c.value}」: {c.change:+.1f} ({c.contribution_pct:+.1f}%)")
        print(f"\n   💡 建议:")
        for rec in result.drill_recommendations:
            print(f"     {rec}")


if __name__ == "__main__":
    main()
