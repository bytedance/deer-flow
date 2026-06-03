"""Interpretive trend analysis (§13.2 contract).

Sprint S1 enhancement — replaces the 118-line stub with a structured analyzer
that consumes the new ``query_trend.py`` output (``time_series[]``) and
produces a §13.2-compliant interpretive report. Output must include:

- ``findings[]`` — at least one per metric, classified into 4 kinds:
    trending_up / trending_down / volatility_spike / anomaly_cluster
- ``evidence[]`` — each finding maps to ≥1 evidence entry with
    source_type=timeseries, source_id={metric_key}, snapshot_path, checksum,
    time_range, retrieved_at
- ``confidence`` — derived from data_coverage + signal magnitude
- ``assumptions[]`` — analysis assumptions
- ``data_coverage`` — covered_metrics / missing_metrics / time_coverage_pct
- ``human_review_required`` — ALWAYS true for interpretive reports
- ``trend_chart`` — full ECharts option (no extra assembly in the renderer)
- ``forecast[]`` — naïve linear projection over forecast_horizon
- ``recommendations[]`` — mechanically derived (no LLM)

This file does NOT emit ``summary_markdown``; full markdown is rendered
exclusively by the platform's ``generic_renderer`` based on the sections
declared in the DSL template.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

from _stub_helpers import (
    base_parser,
    emit_error,
    iso_now,
    provenance_evidence,
    read_json,
    write_json,
)


SCHEMA_VERSION = "1"

# Heuristic thresholds — tuned for the deterministic sine demo but representative.
SLOPE_HIGH = 0.05  # magnitude per step that triggers a high-severity trend finding
SLOPE_MED = 0.01
VOLATILITY_HIGH = 0.10  # std/|mean| ratio for volatility spike
ANOMALY_Z = 2.0  # |z-score| threshold for anomaly cluster point detection
CLUSTER_MIN = 3  # need ≥3 anomalous points to count as a cluster

# Finding-kind → default confidence band.
KIND_CONFIDENCE = {
    "trending_up": "medium",
    "trending_down": "medium",
    "volatility_spike": "medium",
    "anomaly_cluster": "high",
}

FORECAST_COLOR = "#fac858"
SERIES_BASE_COLORS = ["#5470c6", "#91cc75", "#ee6666", "#73c0de", "#3ba272", "#fc8452"]


def _slope(values: list[float]) -> float:
    """Average per-step delta — coarse but stable for monotone-ish demo data."""
    if len(values) < 2:
        return 0.0
    return (values[-1] - values[0]) / (len(values) - 1)


def _mean_std(values: list[float]) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    mean = sum(values) / len(values)
    if len(values) <= 1:
        return mean, 0.0
    variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return mean, math.sqrt(variance)


def _z_scores(values: list[float]) -> list[float]:
    mean, std = _mean_std(values)
    if std == 0:
        return [0.0] * len(values)
    return [(v - mean) / std for v in values]


def _findings_for_series(series: dict) -> tuple[list[dict], list[dict], list[dict]]:
    """Return (findings, evidence, alert_rows) for one metric series."""
    metric_key = series["metric_key"]
    name = series.get("name", metric_key)
    unit = series.get("unit", "")
    better_when_higher = bool(series.get("better_when_higher", True))
    values: list[float] = series.get("values", [])
    timestamps: list[str] = series.get("timestamps", [])
    if not values:
        return [], [], []

    findings: list[dict] = []
    evidence: list[dict] = []
    alerts: list[dict] = []
    time_range = [timestamps[0], timestamps[-1]] if timestamps else []

    # 1. Trend finding (always emit one per metric)
    slope = _slope(values)
    mean, std = _mean_std(values)
    if abs(slope) >= SLOPE_HIGH:
        severity = "high"
    elif abs(slope) >= SLOPE_MED:
        severity = "medium"
    else:
        severity = "low"
    direction = "up" if slope > 0 else "down" if slope < 0 else "flat"
    kind = "trending_up" if slope > 0 else "trending_down" if slope < 0 else "trending_up"
    if direction == "flat":
        headline = f"{name} 趋势平稳，斜率 {slope:+.4f}{unit}/步"
    else:
        zh = "上升" if direction == "up" else "下降"
        headline = f"{name} 总体{zh}趋势 (斜率 {slope:+.4f}{unit}/步)"

    is_concerning = (
        severity == "high"
        and ((direction == "down" and better_when_higher) or (direction == "up" and not better_when_higher))
    )
    finding_id = f"FND-{metric_key}-trend"
    findings.append(
        {
            "id": finding_id,
            "kind": kind,
            "metric_key": metric_key,
            "metric_name": name,
            "headline": headline,
            "slope_per_step": round(slope, 6),
            "mean": round(mean, 4),
            "peak": round(max(values), 4),
            "trough": round(min(values), 4),
            "direction": direction,
            "severity": severity,
            "is_concerning": is_concerning,
            "unit": unit,
        }
    )
    # Evidence: ship the first/middle/last 3 points as a stable snapshot sample.
    sample_idx = sorted({0, len(values) // 2, len(values) - 1})
    sample = [{"t": timestamps[i] if i < len(timestamps) else None, "v": values[i]} for i in sample_idx]
    evidence.append(
        {
            **provenance_evidence(
                source_type="timeseries",
                source_id=metric_key,
                snapshot_path=f"data/trend_data.json#/time_series/{metric_key}",
                payload_sample=sample,
                time_range=time_range,
            ),
            "finding_id": finding_id,
            "description": f"采样首/中/尾各 1 点（共 {len(values)} 点）",
        }
    )

    # 2. Volatility-spike finding (when std/|mean| exceeds threshold)
    volatility = std / abs(mean) if mean else 0.0
    if volatility >= VOLATILITY_HIGH:
        vol_id = f"FND-{metric_key}-volatility"
        findings.append(
            {
                "id": vol_id,
                "kind": "volatility_spike",
                "metric_key": metric_key,
                "metric_name": name,
                "headline": f"{name} 波动率 {volatility:.2%}，超过阈值 {VOLATILITY_HIGH:.0%}",
                "volatility": round(volatility, 4),
                "std": round(std, 4),
                "severity": "high" if volatility >= 2 * VOLATILITY_HIGH else "medium",
                "is_concerning": True,
                "unit": unit,
            }
        )
        evidence.append(
            {
                **provenance_evidence(
                    source_type="timeseries",
                    source_id=metric_key,
                    snapshot_path=f"data/trend_data.json#/time_series/{metric_key}",
                    payload_sample={"mean": mean, "std": std, "volatility": volatility},
                    time_range=time_range,
                ),
                "finding_id": vol_id,
                "description": "整窗 std/|mean| 比值",
            }
        )

    # 3. Anomaly-cluster finding (≥CLUSTER_MIN consecutive |z| > Z threshold)
    z_scores = _z_scores(values)
    cluster_start = None
    cluster_size = 0
    detected_clusters: list[tuple[int, int]] = []  # (start_idx, length)
    for i, z in enumerate(z_scores):
        if abs(z) > ANOMALY_Z:
            if cluster_start is None:
                cluster_start = i
                cluster_size = 1
            else:
                cluster_size += 1
        else:
            if cluster_start is not None and cluster_size >= CLUSTER_MIN:
                detected_clusters.append((cluster_start, cluster_size))
            cluster_start = None
            cluster_size = 0
    if cluster_start is not None and cluster_size >= CLUSTER_MIN:
        detected_clusters.append((cluster_start, cluster_size))

    for idx, (start_idx, length) in enumerate(detected_clusters):
        cluster_id = f"FND-{metric_key}-cluster-{idx}"
        end_idx = start_idx + length - 1
        cluster_range = [
            timestamps[start_idx] if start_idx < len(timestamps) else None,
            timestamps[end_idx] if end_idx < len(timestamps) else None,
        ]
        findings.append(
            {
                "id": cluster_id,
                "kind": "anomaly_cluster",
                "metric_key": metric_key,
                "metric_name": name,
                "headline": f"{name} 在 {cluster_range[0]} 至 {cluster_range[1]} 出现 {length} 个连续异常点",
                "cluster_length": length,
                "cluster_range": cluster_range,
                "severity": "high",
                "is_concerning": True,
                "unit": unit,
            }
        )
        cluster_sample = [
            {"t": timestamps[i] if i < len(timestamps) else None, "v": values[i], "z": round(z_scores[i], 3)}
            for i in range(start_idx, end_idx + 1)
        ]
        evidence.append(
            {
                **provenance_evidence(
                    source_type="timeseries",
                    source_id=metric_key,
                    snapshot_path=f"data/trend_data.json#/time_series/{metric_key}",
                    payload_sample=cluster_sample,
                    time_range=cluster_range,
                ),
                "finding_id": cluster_id,
                "description": f"|z|>{ANOMALY_Z} 连续 {length} 点",
            }
        )

    # Surface high-severity findings to the flat alert_list table
    for f in findings:
        if f.get("severity") == "high":
            alerts.append(
                {
                    "metric_key": metric_key,
                    "metric_name": name,
                    "kind": f["kind"],
                    "severity": f["severity"],
                    "headline": f["headline"],
                }
            )

    return findings, evidence, alerts


def _forecast(series: dict, horizon: int) -> dict:
    """Naïve linear extrapolation from the last observed slope."""
    values = series.get("values", [])
    timestamps = series.get("timestamps", [])
    if not values or horizon <= 0:
        return {
            "metric_key": series["metric_key"],
            "horizon_points": 0,
            "method": "none",
            "forecast_points": [],
        }
    slope = _slope(values)
    last_val = values[-1]
    # We don't know the agg step here; just label as t+1, t+2, ...
    forecast_points = []
    for i in range(1, horizon + 1):
        forecast_points.append({"step_offset": i, "value": round(last_val + slope * i, 4)})
    return {
        "metric_key": series["metric_key"],
        "horizon_points": horizon,
        "method": "naive_linear",
        "last_observed_value": last_val,
        "last_observed_timestamp": timestamps[-1] if timestamps else None,
        "forecast_points": forecast_points,
    }


def _build_trend_chart(time_series: list[dict], forecasts: list[dict]) -> dict:
    if not time_series:
        return {}
    # Pick the longest series as the x-axis reference.
    reference = max(time_series, key=lambda s: s.get("point_count", 0))
    x_axis_data = list(reference.get("timestamps", []))
    forecast_by_key = {fc["metric_key"]: fc for fc in forecasts}

    legend_data: list[str] = []
    series: list[dict] = []
    for idx, s in enumerate(time_series):
        name = s.get("name", s["metric_key"])
        legend_data.append(name)
        series.append(
            {
                "name": name,
                "type": "line",
                "data": s.get("values", []),
                "itemStyle": {"color": SERIES_BASE_COLORS[idx % len(SERIES_BASE_COLORS)]},
                "smooth": True,
            }
        )
        fc = forecast_by_key.get(s["metric_key"])
        if fc and fc.get("forecast_points"):
            forecast_values = [None] * len(s.get("values", [])) + [pt["value"] for pt in fc["forecast_points"]]
            forecast_name = f"{name}（预测）"
            legend_data.append(forecast_name)
            series.append(
                {
                    "name": forecast_name,
                    "type": "line",
                    "data": forecast_values,
                    "lineStyle": {"type": "dashed", "color": FORECAST_COLOR},
                    "itemStyle": {"color": FORECAST_COLOR},
                    "smooth": True,
                }
            )

    # Pad x-axis with forecast step labels so dashed segment shows up.
    if forecasts and forecasts[0]["forecast_points"]:
        for i in range(1, len(forecasts[0]["forecast_points"]) + 1):
            x_axis_data.append(f"+{i}")

    return {
        "title": {"text": "指标趋势 + 预测"},
        "tooltip": {"trigger": "axis"},
        "legend": {"data": legend_data, "selected": {n: True for n in legend_data}},
        "xAxis": {"type": "category", "data": x_axis_data},
        "yAxis": {"type": "value"},
        "series": series,
    }


def _data_coverage(time_series: list[dict], requested_metrics: list[str]) -> dict:
    covered = [s["metric_key"] for s in time_series if s.get("point_count", 0) > 0]
    missing = [m for m in requested_metrics if m not in covered]
    # Expect every series to have the same point_count as the longest; if not,
    # surface per-metric coverage so downstream renderers can warn.
    if not time_series:
        max_points = 0
    else:
        max_points = max((s.get("point_count", 0) for s in time_series), default=0)
    if max_points == 0:
        time_coverage_pct = 0.0
    else:
        actual_total = sum(s.get("point_count", 0) for s in time_series)
        expected_total = max_points * len(requested_metrics) if requested_metrics else max_points
        time_coverage_pct = round(actual_total / expected_total, 4) if expected_total else 1.0
    return {
        "requested_metrics": requested_metrics,
        "covered_metrics": covered,
        "missing_metrics": missing,
        "time_coverage_pct": time_coverage_pct,
        "max_points": max_points,
    }


def _overall_confidence(findings: list[dict], coverage: dict) -> str:
    if coverage["time_coverage_pct"] < 0.5:
        return "low"
    high_count = sum(1 for f in findings if f.get("severity") == "high")
    if high_count >= 2:
        return "high"
    if high_count == 1:
        return "medium"
    return "low"


def _recommendations(findings: list[dict], alerts: list[dict]) -> list[str]:
    if not findings:
        return ["数据无显著趋势，下个周期继续观察。"]
    recs: list[str] = []
    for f in findings:
        if not f.get("is_concerning"):
            continue
        if f["kind"] == "trending_down":
            recs.append(f"{f['metric_name']} 持续下行，建议在下个周期复盘其驱动因素并制定改进计划。")
        elif f["kind"] == "trending_up":
            recs.append(f"{f['metric_name']} 持续上行（可能负面）。复核运行参数与告警阈值。")
        elif f["kind"] == "volatility_spike":
            recs.append(f"{f['metric_name']} 波动剧烈，排查传感器漂移或运行工况切换。")
        elif f["kind"] == "anomaly_cluster":
            recs.append(
                f"{f['metric_name']} 出现连续异常点 ({f.get('cluster_range', [None, None])[0]} ~ "
                f"{f.get('cluster_range', [None, None])[1]})，安排故障诊断。"
            )
    if not recs:
        recs.append("当前 finding 严重度均为低/中等，保持当前监控节奏即可。")
    if alerts:
        recs.append(f"已生成 {len(alerts)} 条 high 级别告警，纳入下个周期复盘。")
    return recs[:8]


def main() -> int:
    parser = base_parser("Interpretive trend analysis (§13.2)")
    parser.add_argument("--input", required=True, help="trend_data.json path")
    args = parser.parse_args()

    try:
        raw = read_json(Path(args.input))
    except (FileNotFoundError, ValueError) as exc:
        return emit_error("INPUT_UNREADABLE", str(exc))

    time_series = raw.get("time_series") or []
    if not isinstance(time_series, list) or not time_series:
        return emit_error("EMPTY_METRICS", "trend_data has no time_series")

    metadata = raw.get("metadata") or {}
    requested_metrics = metadata.get("requested_metric_keys") or [s.get("metric_key") for s in time_series]
    horizon = int(metadata.get("forecast_horizon", 0) or 0)
    date_range = metadata.get("date_range") or []

    all_findings: list[dict] = []
    all_evidence: list[dict] = []
    all_alerts: list[dict] = []
    for series in time_series:
        findings, evidence, alerts = _findings_for_series(series)
        all_findings.extend(findings)
        all_evidence.extend(evidence)
        all_alerts.extend(alerts)

    forecasts = [_forecast(s, horizon) for s in time_series]
    trend_chart = _build_trend_chart(time_series, forecasts)
    coverage = _data_coverage(time_series, requested_metrics)
    confidence = _overall_confidence(all_findings, coverage)
    recommendations = _recommendations(all_findings, all_alerts)
    concerning_count = sum(1 for f in all_findings if f.get("is_concerning"))

    overall_status = {
        "level": "critical" if concerning_count >= 2 else "warning" if concerning_count == 1 else "good",
        "summary": (
            f"分析 {len(time_series)} 个指标，发现 {len(all_findings)} 项要点，"
            f"其中 {concerning_count} 项需要关注。"
        )[:80],
    }

    output = {
        "schema_version": SCHEMA_VERSION,
        "metadata": {
            "date_range": date_range,
            "aggregation": metadata.get("aggregation"),
            "forecast_horizon": horizon,
            "data_source": metadata.get("data_source"),
        },
        "overall_status": overall_status,
        "findings": all_findings,
        "evidence": all_evidence,
        "trend_chart": trend_chart,
        "alert_list": all_alerts,
        "forecast": forecasts,
        "recommendations": recommendations,
        "confidence": confidence,
        "assumptions": [
            "演示数据由 query_trend 的确定性正弦生成，不代表真实生产工况",
            f"斜率阈值 {SLOPE_HIGH} 仅用于演示，正式实现需结合 KPI 业务口径调优",
            f"异常点判定使用 |z|>{ANOMALY_Z} 且连续 {CLUSTER_MIN} 点以上聚集",
            "预测使用末段斜率线性外推，非真实时序模型",
        ],
        "data_coverage": coverage,
        "human_review_required": True,  # §13.2: interpretive reports always require review
        "_meta": {"stub": True, "generated_at": iso_now()},
    }

    write_json(Path(args.output_dir), "trend_analysis", output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
