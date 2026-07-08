"""
Forecast Engine — Time-series prediction for Agent BI.

Provides lightweight, zero-dependency time-series forecasting with
multiple methods suitable for business data analysis. All computation
is local (DuckDB + pure Python), preserving data privacy.

Methods:
    Moving Average   — Simple rolling average, best for stable series
    Exponential      — Holt-Winters-style exponential smoothing
    Linear Trend     — Linear regression extrapolation
    Ensemble         — Weighted average of all methods

Each method produces:
    - Forecast values for N periods ahead
    - Prediction intervals (upper/lower bounds)
    - Confidence score (0-1)
    - Method-appropriate parameters

Usage:
    from scripts.forecast_engine import ForecastEngine

    engine = ForecastEngine("workspace.duckdb")
    result = engine.forecast("sales", "order_date", "amount", periods=6)
    print(f"Next 6 months forecast: {result.forecast_values}")
"""

import sys
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import get_repository
from logging_config import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

class ForecastMethod(str, Enum):
    MOVING_AVERAGE = "moving_average"
    EXPONENTIAL = "exponential"
    LINEAR_TREND = "linear_trend"
    ENSEMBLE = "ensemble"


@dataclass
class ForecastPoint:
    """A single forecast data point."""
    period: str              # Period label (e.g., "2024-07")
    value: float             # Forecast value
    lower_bound: float       # Lower prediction interval
    upper_bound: float       # Upper prediction interval


@dataclass
class ForecastResult:
    """Complete forecast result."""
    method: ForecastMethod
    metric: str
    date_column: str
    periods_ahead: int
    historical_periods: list[str] = field(default_factory=list)
    historical_values: list[float] = field(default_factory=list)
    forecast_points: list[ForecastPoint] = field(default_factory=list)
    confidence: float = 0.0          # 0-1 overall confidence
    trend_direction: str = ""         # "up", "down", "flat"
    trend_strength_pct: float = 0.0   # % change per period
    params: dict = field(default_factory=dict)

    @property
    def forecast_values(self) -> list[float]:
        return [p.value for p in self.forecast_points]

    @property
    def forecast_periods(self) -> list[str]:
        return [p.period for p in self.forecast_points]

    def to_dict(self) -> dict:
        return {
            "method": self.method.value,
            "metric": self.metric,
            "date_column": self.date_column,
            "periods_ahead": self.periods_ahead,
            "confidence": self.confidence,
            "trend_direction": self.trend_direction,
            "trend_strength_pct": self.trend_strength_pct,
            "historical": [
                {"period": p, "value": v}
                for p, v in zip(self.historical_periods, self.historical_values)
            ],
            "forecast": [
                {"period": p.period, "value": p.value,
                 "lower": p.lower_bound, "upper": p.upper_bound}
                for p in self.forecast_points
            ],
            "params": self.params,
        }


# ---------------------------------------------------------------------------
# Forecast Engine
# ---------------------------------------------------------------------------

class ForecastEngine:
    """Time-series forecasting engine for business data.

    All methods are pure Python/DuckDB — no sklearn, no statsmodels,
    no external API calls. Data never leaves the machine.

    Attributes:
        db_path: Path to DuckDB database.
        repo: DatabaseRepository instance.
    """

    # Default confidence interval (80%)
    CONFIDENCE_Z = 1.28

    def __init__(self, db_path: str = "workspace.duckdb"):
        self.db_path = db_path
        self.repo = get_repository(db_path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def forecast(
        self,
        table: str,
        date_column: str,
        metric: str,
        periods: int = 6,
        method: ForecastMethod = ForecastMethod.ENSEMBLE,
        granularity: str = "month",
        filter_sql: str = "",
    ) -> ForecastResult:
        """Generate a forecast for a time-series metric.

        Args:
            table: Table name.
            date_column: Date column for time series.
            metric: Metric column to forecast.
            periods: Number of periods to forecast ahead.
            method: Forecasting method.
            granularity: Time granularity (day/week/month/quarter/year).
            filter_sql: Optional WHERE clause.

        Returns:
            ForecastResult with historical + forecast data.
        """
        logger.info("开始预测", table=table, metric=metric, method=method.value)

        # Step 1: Get historical data
        historical = self._get_time_series(table, date_column, metric, granularity, filter_sql)
        if len(historical) < 4:
            raise ValueError(f"数据点不足（需要至少4个，实际{len(historical)}个）")

        periods_labels = [str(r["period"]) for r in historical]
        values = [r["metric_val"] for r in historical]

        # Step 2: Generate forecast based on method
        if method == ForecastMethod.MOVING_AVERAGE:
            result = self._forecast_ma(values, periods_labels, periods, metric, date_column)
        elif method == ForecastMethod.EXPONENTIAL:
            result = self._forecast_exp(values, periods_labels, periods, metric, date_column)
        elif method == ForecastMethod.LINEAR_TREND:
            result = self._forecast_linear(values, periods_labels, periods, metric, date_column)
        else:
            # Ensemble: weighted average of all methods
            ma = self._forecast_ma(values, periods_labels, periods, metric, date_column)
            exp = self._forecast_exp(values, periods_labels, periods, metric, date_column)
            lin = self._forecast_linear(values, periods_labels, periods, metric, date_column)
            result = self._blend_forecasts([ma, exp, lin], values, periods_labels,
                                           periods, metric, date_column)

        logger.info("预测完成", metric=metric, periods=periods)
        return result

    def quick_forecast(
        self, table: str, date_column: str, metric: str, periods: int = 3
    ) -> ForecastResult:
        """Quick ensemble forecast with fewer periods."""
        return self.forecast(table, date_column, metric, periods=periods,
                            method=ForecastMethod.ENSEMBLE)

    # ------------------------------------------------------------------
    # Forecasting Methods
    # ------------------------------------------------------------------

    def _forecast_ma(
        self, values: list[float], labels: list[str],
        periods: int, metric: str, date_col: str,
    ) -> ForecastResult:
        """Moving average forecast."""
        n = len(values)
        window = min(3, max(2, n // 3))  # Adaptive window
        recent_avg = sum(values[-window:]) / window

        # Calculate residuals for prediction intervals
        ma_values = []
        for i in range(window, n):
            ma_values.append(sum(values[i-window:i]) / window)
        residuals = [values[i] - ma_values[i-window] for i in range(window, n)]
        std_residual = self._std(residuals) if residuals else recent_avg * 0.1

        forecast_points = []
        future_labels = self._generate_future_periods(labels[-1], periods)
        for i, label in enumerate(future_labels):
            margin = self.CONFIDENCE_Z * std_residual * (1 + 0.1 * i)
            forecast_points.append(ForecastPoint(
                period=label,
                value=round(recent_avg, 2),
                lower_bound=round(recent_avg - margin, 2),
                upper_bound=round(recent_avg + margin, 2),
            ))

        return ForecastResult(
            method=ForecastMethod.MOVING_AVERAGE,
            metric=metric, date_column=date_col,
            periods_ahead=periods,
            historical_periods=labels, historical_values=values,
            forecast_points=forecast_points,
            confidence=self._calc_confidence(std_residual, recent_avg),
            trend_direction="flat",
            trend_strength_pct=0,
            params={"window": window, "base_value": recent_avg},
        )

    def _forecast_exp(
        self, values: list[float], labels: list[str],
        periods: int, metric: str, date_col: str,
    ) -> ForecastResult:
        """Exponential smoothing forecast with trend detection."""
        n = len(values)

        # Fit exponential smoothing with trend
        alpha = 0.3  # Level smoothing
        beta = 0.1   # Trend smoothing

        level = values[0]
        trend = (values[-1] - values[0]) / max(n - 1, 1)

        fitted = [level]
        for i in range(1, n):
            prev_level = level
            level = alpha * values[i] + (1 - alpha) * (level + trend)
            trend = beta * (level - prev_level) + (1 - beta) * trend
            fitted.append(level)

        # Residuals
        residuals = [values[i] - fitted[i] for i in range(n)]
        std_residual = self._std(residuals) if residuals else abs(level) * 0.1

        # Forecast
        forecast_points = []
        future_labels = self._generate_future_periods(labels[-1], periods)
        for i, label in enumerate(future_labels):
            f_val = level + trend * (i + 1)
            margin = self.CONFIDENCE_Z * std_residual * (1 + 0.15 * (i + 1))
            forecast_points.append(ForecastPoint(
                period=label,
                value=round(f_val, 2),
                lower_bound=round(f_val - margin, 2),
                upper_bound=round(f_val + margin, 2),
            ))

        avg_val = sum(values) / n if n > 0 else 1
        trend_pct = round(trend / max(abs(avg_val), 0.01) * 100, 2)
        direction = "up" if trend_pct > 1 else "down" if trend_pct < -1 else "flat"

        return ForecastResult(
            method=ForecastMethod.EXPONENTIAL,
            metric=metric, date_column=date_col,
            periods_ahead=periods,
            historical_periods=labels, historical_values=values,
            forecast_points=forecast_points,
            confidence=self._calc_confidence(std_residual, avg_val),
            trend_direction=direction,
            trend_strength_pct=trend_pct,
            params={"alpha": alpha, "beta": beta, "level": level, "trend": trend},
        )

    def _forecast_linear(
        self, values: list[float], labels: list[str],
        periods: int, metric: str, date_col: str,
    ) -> ForecastResult:
        """Linear regression forecast."""
        n = len(values)
        x_mean = (n - 1) / 2
        y_mean = sum(values) / n

        numerator = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
        denominator = sum((i - x_mean) ** 2 for i in range(n))
        slope = numerator / denominator if denominator != 0 else 0
        intercept = y_mean - slope * x_mean

        # R-squared
        fitted = [intercept + slope * i for i in range(n)]
        ss_res = sum((values[i] - fitted[i]) ** 2 for i in range(n))
        ss_tot = sum((v - y_mean) ** 2 for v in values)
        r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0

        # Residual std
        residuals = [values[i] - fitted[i] for i in range(n)]
        std_residual = self._std(residuals) if residuals else abs(y_mean) * 0.1

        # Forecast
        forecast_points = []
        future_labels = self._generate_future_periods(labels[-1], periods)
        for i, label in enumerate(future_labels):
            x_val = n + i
            f_val = intercept + slope * x_val
            margin = self.CONFIDENCE_Z * std_residual * (1 + 0.2 * (i + 1))
            forecast_points.append(ForecastPoint(
                period=label,
                value=round(max(0, f_val) if y_mean > 0 else f_val, 2),
                lower_bound=round(max(0, f_val - margin) if y_mean > 0 else f_val - margin, 2),
                upper_bound=round(f_val + margin, 2),
            ))

        trend_pct = round(slope / max(abs(y_mean), 0.01) * 100, 2)
        direction = "up" if trend_pct > 1 else "down" if trend_pct < -1 else "flat"

        return ForecastResult(
            method=ForecastMethod.LINEAR_TREND,
            metric=metric, date_column=date_col,
            periods_ahead=periods,
            historical_periods=labels, historical_values=values,
            forecast_points=forecast_points,
            confidence=round(min(r_squared, 1.0), 3),
            trend_direction=direction,
            trend_strength_pct=trend_pct,
            params={"slope": slope, "intercept": intercept, "r_squared": r_squared},
        )

    def _blend_forecasts(
        self,
        results: list[ForecastResult],
        values: list[float], labels: list[str],
        periods: int, metric: str, date_col: str,
    ) -> ForecastResult:
        """Blend multiple forecasts using confidence-weighted averaging."""
        weights = [max(r.confidence, 0.1) for r in results]
        total_w = sum(weights)
        norm_weights = [w / total_w for w in weights]

        # Blend forecast points
        blended_points = []
        future_labels = self._generate_future_periods(labels[-1], periods)
        for i, label in enumerate(future_labels):
            vals = [r.forecast_points[i].value for r in results]
            lowers = [r.forecast_points[i].lower_bound for r in results]
            uppers = [r.forecast_points[i].upper_bound for r in results]

            blended_val = sum(v * w for v, w in zip(vals, norm_weights))
            blended_lower = sum(l * w for l, w in zip(lowers, norm_weights))
            blended_upper = sum(u * w for u, w in zip(uppers, norm_weights))

            blended_points.append(ForecastPoint(
                period=label,
                value=round(blended_val, 2),
                lower_bound=round(blended_lower, 2),
                upper_bound=round(blended_upper, 2),
            ))

        # Use best method's trend
        best = max(results, key=lambda r: r.confidence)

        return ForecastResult(
            method=ForecastMethod.ENSEMBLE,
            metric=metric, date_column=date_col,
            periods_ahead=periods,
            historical_periods=labels, historical_values=values,
            forecast_points=blended_points,
            confidence=round(sum(r.confidence for r in results) / len(results), 3),
            trend_direction=best.trend_direction,
            trend_strength_pct=best.trend_strength_pct,
            params={
                "methods": [r.method.value for r in results],
                "weights": [round(w, 3) for w in norm_weights],
            },
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_time_series(
        self, table: str, date_col: str, metric: str,
        granularity: str, filter_sql: str,
    ) -> list[dict]:
        """Query time-series data from DuckDB."""
        safe_date = f'"{date_col}"'
        safe_metric = f'"{metric}"'

        where = f"WHERE {filter_sql}" if filter_sql else ""
        query = f"""
            SELECT
                DATE_TRUNC('{granularity}', {safe_date}) AS period,
                SUM({safe_metric}) AS metric_val
            FROM "{table}"
            {where}
            GROUP BY DATE_TRUNC('{granularity}', {safe_date})
            ORDER BY period
        """
        # Clean up empty WHERE
        query = query.replace("WHERE ", "") if not filter_sql else query
        return self.repo.execute_query(query)

    def _generate_future_periods(self, last_period_str: str, n: int) -> list[str]:
        """Generate N future period labels."""
        # Parse the last period (format: "YYYY-MM-DD HH:MM:SS" or "YYYY-MM-DD")
        date_str = str(last_period_str)[:10]
        try:
            last_date = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            # Fallback: just enumerate
            return [f"T+{i+1}" for i in range(n)]

        labels = []
        for i in range(1, n + 1):
            next_date = last_date + timedelta(days=30 * i)
            labels.append(next_date.strftime("%Y-%m-%d"))
        return labels

    @staticmethod
    def _std(values: list[float]) -> float:
        """Compute standard deviation."""
        n = len(values)
        if n < 2:
            return 0.0
        mean = sum(values) / n
        return (sum((v - mean) ** 2 for v in values) / (n - 1)) ** 0.5

    @staticmethod
    def _calc_confidence(std_residual: float, mean_val: float) -> float:
        """Calculate confidence score (0-1) based on CV."""
        if abs(mean_val) < 0.001:
            return 0.0
        cv = std_residual / abs(mean_val)
        # Lower CV → higher confidence
        if cv < 0.05:
            return 0.95
        elif cv < 0.1:
            return 0.85
        elif cv < 0.2:
            return 0.7
        elif cv < 0.3:
            return 0.5
        elif cv < 0.5:
            return 0.3
        return 0.1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    import argparse
    import json

    parser = argparse.ArgumentParser(
        description="Forecast Engine — Time-series prediction",
        epilog="Example: python scripts/forecast_engine.py orders 交易时间 金额 --periods 6",
    )
    parser.add_argument("table", help="Table name")
    parser.add_argument("date_column", help="Date column")
    parser.add_argument("metric", help="Metric column to forecast")
    parser.add_argument("--periods", "-p", type=int, default=6, help="Periods ahead")
    parser.add_argument("--method", "-m", choices=["moving_average", "exponential", "linear_trend", "ensemble"],
                       default="ensemble")
    parser.add_argument("--granularity", "-g", default="month")
    parser.add_argument("--db", default="workspace.duckdb")
    parser.add_argument("--filter", default="")
    parser.add_argument("--format", choices=["text", "json"], default="text")

    args = parser.parse_args()
    engine = ForecastEngine(args.db)

    try:
        result = engine.forecast(
            args.table, args.date_column, args.metric,
            periods=args.periods,
            method=ForecastMethod(args.method),
            granularity=args.granularity,
            filter_sql=args.filter,
        )

        if args.format == "json":
            print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(f"\n📈 预测结果: {result.metric}")
            print(f"   方法: {result.method.value} | 置信度: {result.confidence:.0%}")
            print(f"   趋势: {result.trend_direction} ({result.trend_strength_pct:+.1f}%/期)")
            print(f"\n   历史数据 ({len(result.historical_values)} 期):")
            for p, v in zip(result.historical_periods[-6:], result.historical_values[-6:]):
                print(f"     {str(p)[:10]:12s} {v:>12.1f}")
            print(f"\n   预测 ({len(result.forecast_points)} 期):")
            print(f"   {'期数':<12s} {'预测值':>10s} {'下限':>10s} {'上限':>10s}")
            for fp in result.forecast_points:
                print(f"   {fp.period[:10]:12s} {fp.value:>10.1f} {fp.lower_bound:>10.1f} {fp.upper_bound:>10.1f}")

    except ValueError as e:
        print(f"❌ {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
