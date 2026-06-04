#!/usr/bin/env python3
"""特征提取 + 异常判定脚本 — monitoring-analysis Skill。

读取 monitoring_data.json，按测点类别分发分析逻辑，输出 monitoring_features.json。

Usage:
    python extract_monitoring_features.py \\
      --input /mnt/user-data/outputs/monitoring_data.json \\
      --analysis-focus full \\
      --output-dir /mnt/user-data/outputs/

analysis_focus:
    full     — 趋势 + 波形频谱 + 异常判定
    trend    — 仅趋势特征
    anomaly  — 仅异常判定
    spectrum — 仅波形频谱特征
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _thresholds import check_threshold, THRESHOLDS


# ===== 趋势特征提取 =====

def _moving_average(values: list[float], window: int = 5) -> list[float]:
    """简单移动平均。"""
    if len(values) < window:
        return list(values)
    result = []
    for i in range(len(values)):
        start = max(0, i - window // 2)
        end = min(len(values), i + window // 2 + 1)
        result.append(sum(values[start:end]) / (end - start))
    return result


def _detect_rising_periods(
    times: list[int], values: list[float], ma_values: list[float]
) -> list[dict]:
    """检测上涨段：连续 N 点移动平均上升。"""
    periods = []
    if len(ma_values) < 5:
        return periods

    start_idx = None
    for i in range(1, len(ma_values)):
        rising = ma_values[i] > ma_values[i - 1] * 1.01  # 1% 以上视为上升
        if rising and start_idx is None:
            start_idx = i - 1
        elif not rising and start_idx is not None:
            if i - start_idx >= 5:  # 至少 5 个连续上升点
                amplitude = values[i - 1] - values[start_idx]
                days = max(1, (times[i - 1] - times[start_idx]) / 86400000)
                rate = amplitude / days
                periods.append({
                    "start_time": datetime.fromtimestamp(times[start_idx] / 1000, tz=timezone.utc).isoformat(),
                    "end_time": datetime.fromtimestamp(times[i - 1] / 1000, tz=timezone.utc).isoformat(),
                    "amplitude": round(amplitude, 4),
                    "rate": round(rate, 4),
                    "duration_days": round(days, 1),
                    "confidence": min(1.0, (i - start_idx) / 20),
                })
            start_idx = None
    # 检查末尾
    if start_idx is not None and len(ma_values) - start_idx >= 5:
        amplitude = values[-1] - values[start_idx]
        days = max(1, (times[-1] - times[start_idx]) / 86400000)
        rate = amplitude / days
        periods.append({
            "start_time": datetime.fromtimestamp(times[start_idx] / 1000, tz=timezone.utc).isoformat(),
            "end_time": datetime.fromtimestamp(times[-1] / 1000, tz=timezone.utc).isoformat(),
            "amplitude": round(amplitude, 4),
            "rate": round(rate, 4),
            "duration_days": round(days, 1),
            "confidence": min(1.0, (len(ma_values) - start_idx) / 20),
        })
    return periods


def _detect_high_volatility_periods(
    times: list[int], values: list[float], window: int = 10
) -> list[dict]:
    """检测剧烈波动段：滑动窗口内标准差显著高于全局。"""
    if len(values) < window * 2:
        return []
    global_std = _std(values)
    if global_std == 0:
        return []
    periods = []
    i = 0
    while i < len(values) - window:
        seg = values[i:i + window]
        seg_std = _std(seg)
        if seg_std > global_std * 2:
            end = i + window
            while end < len(values) and _std(values[end - window:end]) > global_std * 2:
                end += 1
            periods.append({
                "start_time": datetime.fromtimestamp(times[i] / 1000, tz=timezone.utc).isoformat(),
                "end_time": datetime.fromtimestamp(times[min(end - 1, len(times) - 1)] / 1000, tz=timezone.utc).isoformat(),
                "peak_std": round(seg_std, 4),
                "global_std": round(global_std, 4),
                "confidence": min(1.0, seg_std / (global_std * 3)),
            })
            i = end
        else:
            i += 1
    return periods


def _detect_outliers(values: list[float], z_threshold: float = 3.0) -> list[int]:
    """检测异常点（z-score > 阈值）。"""
    if len(values) < 3:
        return []
    mean = sum(values) / len(values)
    std = _std(values)
    if std == 0:
        return []
    return [i for i, v in enumerate(values) if abs(v - mean) / std > z_threshold]


def _std(values: list[float]) -> float:
    """标准差。"""
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    return math.sqrt(variance)


def _mad(values: list[float]) -> float:
    """中位数绝对偏差。"""
    if not values:
        return 0.0
    median = sorted(values)[len(values) // 2]
    return sorted(abs(v - median) for v in values)[len(values) // 2]


def extract_trend_features(trend_rows: list[dict]) -> dict:
    """趋势特征提取。"""
    # 按 feature 组织时序数据
    feature_series: dict[str, list[tuple[int, float]]] = defaultdict(list)
    for row in trend_rows:
        for fname, fval in row.get("values", {}).items():
            if fval is not None and isinstance(fval, (int, float)):
                feature_series[fname].append((row["time_ms"], fval))

    feature_stats: dict[str, dict] = {}
    summaries: list[str] = []
    notable_points: list[str] = []

    for fname, series_data in sorted(feature_series.items()):
        if len(series_data) < 2:
            continue
        times = [t for t, _ in series_data]
        values = [v for _, v in series_data]

        ma_values = _moving_average(values)
        rising = _detect_rising_periods(times, values, ma_values)
        volatile = _detect_high_volatility_periods(times, values)
        outliers = _detect_outliers(values)

        detail = {
            "current": values[-1],
            "mean": round(sum(values) / len(values), 4),
            "min": round(min(values), 4),
            "max": round(max(values), 4),
            "std": round(_std(values), 4),
            "range": round(max(values) - min(values), 4),
            "mad": round(_mad(values), 4),
            "data_points": len(values),
            "rising_periods": rising,
            "high_volatility_periods": volatile,
            "anomaly_points": [
                {
                    "time": datetime.fromtimestamp(times[i] / 1000, tz=timezone.utc).isoformat(),
                    "value": round(values[i], 4),
                    "z_score": round(
                        abs(values[i] - sum(values) / len(values)) / max(_std(values), 1e-10), 2
                    ),
                }
                for i in outliers[:5]  # 最多 5 个
            ],
        }
        feature_stats[fname] = detail

        # 生成摘要
        if rising:
            latest = rising[-1]
            summaries.append(
                f"{fname} 呈上升趋势，{latest['duration_days']}天内变化 {latest['amplitude']:.2f}（置信度 {latest['confidence']:.0%}）"
            )
        if outliers:
            notable_points.append(f"{fname} 检测到 {len(outliers)} 个统计异常点")

    return {
        "features_analyzed": list(feature_stats.keys()),
        "feature_stats": feature_stats,
        "summary": summaries,
        "notable_points": notable_points,
    }


# ===== 波形频谱特征提取 =====

def extract_spectral_features(wave_data: dict, category: str) -> dict:
    """波形频谱特征提取（vib / vibc 类别）。"""
    wave_x = wave_data.get("wave_x", [])
    wave_y = wave_data.get("wave_y", [])
    spec_x = wave_data.get("spec_x", [])
    spec_y = wave_data.get("spec_y", [])
    sample_rate = wave_data.get("sample_rate", 0)
    speed = wave_data.get("speed", 0)

    result: dict = {
        "analysis_time_ms": wave_data.get("time_ms"),
        "summary": [],
        "spectral_findings": [],
        "waveform_findings": [],
        "suspected_faults": [],
        "feature_details": {},
    }

    # 时域特征
    if wave_y:
        rms = math.sqrt(sum(v ** 2 for v in wave_y) / len(wave_y)) if wave_y else 0
        peak = max(abs(v) for v in wave_y) if wave_y else 0
        pp = max(wave_y) - min(wave_y) if wave_y else 0
        crest_factor = peak / rms if rms > 0 else 0
        result["feature_details"].update({
            "rms": round(rms, 4),
            "peak": round(peak, 4),
            "peak_to_peak": round(pp, 4),
            "crest_factor": round(crest_factor, 4),
        })
        if crest_factor > 4:
            result["waveform_findings"].append(f"峰值因子 {crest_factor:.2f} 偏高，可能存在冲击信号")
        else:
            result["waveform_findings"].append(f"峰值因子 {crest_factor:.2f}，在正常范围内")

    # 频域特征
    if spec_x and spec_y:
        if max(spec_y) > 0:
            # 找主频
            max_idx = spec_y.index(max(spec_y))
            dominant_freq = spec_x[max_idx] if max_idx < len(spec_x) else 0
            dominant_amp = spec_y[max_idx]

            result["feature_details"].update({
                "dominant_frequency_hz": round(dominant_freq, 2),
                "dominant_amplitude": round(dominant_amp, 4),
            })
            result["spectral_findings"].append(
                f"主频 {dominant_freq:.1f} Hz，幅值 {dominant_amp:.2f}"
            )

            # 1X/2X 分析
            if speed and speed > 0:
                freq_1x = speed / 60.0
                freq_2x = speed / 30.0
                amp_1x = _interpolate_spectrum(spec_x, spec_y, freq_1x)
                amp_2x = _interpolate_spectrum(spec_x, spec_y, freq_2x)

                result["feature_details"].update({
                    "amp_1x": round(amp_1x, 4),
                    "amp_2x": round(amp_2x, 4),
                    "freq_1x_hz": round(freq_1x, 2),
                    "freq_2x_hz": round(freq_2x, 2),
                })
                if amp_1x > 0:
                    ratio = amp_2x / amp_1x if amp_1x > 0 else 0
                    result["feature_details"]["amp_2x_to_1x_ratio"] = round(ratio, 4)
                    result["spectral_findings"].append(
                        f"1X 幅值 {amp_1x:.2f}，2X 幅值 {amp_2x:.2f}，2X/1X 比 {ratio:.2f}"
                    )
                    if ratio > 0.75:
                        result["suspected_faults"].append("2X/1X > 0.75，疑似不对中")

            # 0.5X 分析（油膜涡动）
            if speed and speed > 0 and category == "vibc":
                freq_half = speed / 120.0
                amp_half = _interpolate_spectrum(spec_x, spec_y, freq_half)
                result["feature_details"]["amp_half_freq"] = round(amp_half, 4)
                if amp_half > dominant_amp * 0.3:
                    result["suspected_faults"].append("0.5X 成分显著，疑似油膜涡动")

    result["summary"] = result["spectral_findings"] + result["waveform_findings"]
    return result


def _interpolate_spectrum(freqs: list[float], amps: list[float], target_freq: float) -> float:
    """在频谱中插值获取目标频率的幅值。"""
    if not freqs or not amps or len(freqs) != len(amps):
        return 0.0
    # 找最近的频率 bin
    min_diff = float("inf")
    best_idx = 0
    for i, f in enumerate(freqs):
        diff = abs(f - target_freq)
        if diff < min_diff:
            min_diff = diff
            best_idx = i
    return amps[best_idx] if best_idx < len(amps) else 0.0


# ===== 异常判定 =====

def detect_anomalies(
    point: dict,
    trend_features: dict | None,
    spectral_features: dict | None,
) -> list[dict]:
    """综合异常判定。"""
    anomalies: list[dict] = []
    category = point.get("category", "vib")

    # 1. 趋势异常
    if trend_features:
        for fname, detail in trend_features.get("feature_stats", {}).items():
            for rp in detail.get("rising_periods", []):
                if rp.get("confidence", 0) >= 0.7:
                    severity = "critical" if rp["rate"] >= 0.1 else "warning"
                    anomalies.append({
                        "type": "trend_rising",
                        "severity": severity,
                        "description": f"{fname} 持续上升，{rp['duration_days']}天内变化 {rp['amplitude']:.2f}（置信度 {rp['confidence']:.0%}）",
                        "confidence": rp["confidence"],
                        "metric": fname,
                    })

    # 2. 阈值越限
    if trend_features:
        for fname, detail in trend_features.get("feature_stats", {}).items():
            current = detail.get("current")
            if current is not None:
                result = check_threshold(category, fname, current)
                if result:
                    severity, threshold_val, unit = result
                    anomalies.append({
                        "type": "threshold_exceeded",
                        "severity": severity,
                        "description": f"{fname} 当前值 {current:.2f} {unit}，超{severity}阈值 {threshold_val:.2f} {unit}",
                        "metric": fname,
                        "threshold": threshold_val,
                        "unit": unit,
                    })

    # 3. 频谱异常
    if spectral_features:
        details = spectral_features.get("feature_details", {})
        # 1X 超标
        amp_1x = details.get("amp_1x", 0)
        if amp_1x > 0:
            th = check_threshold(category, "one_freq_y", amp_1x)
            if th:
                severity, threshold_val, unit = th
                anomalies.append({
                    "type": "spectral_1x_high",
                    "severity": severity,
                    "description": f"1X 幅值 {amp_1x:.2f} {unit}，超{severity}阈值 {threshold_val:.2f}",
                    "metric": "one_freq_y",
                })
        # 2X/1X 比超标
        ratio = details.get("amp_2x_to_1x_ratio", 0)
        if ratio > 0.75:
            anomalies.append({
                "type": "spectral_2x_high",
                "severity": "warning",
                "description": f"2X/1X 比值 {ratio:.2f} > 0.75，疑似不对中",
                "metric": "amp_2x_to_1x_ratio",
            })
        # 疑似故障
        for fault in spectral_features.get("suspected_faults", []):
            anomalies.append({
                "type": "suspected_fault",
                "severity": "warning",
                "description": fault,
            })

    return anomalies


def compute_health_status(anomalies: list[dict]) -> str:
    """根据异常列表计算健康状态。"""
    severities = [a.get("severity", "") for a in anomalies]
    if "critical" in severities:
        return "critical"
    if "warning" in severities:
        return "warning"
    return "normal"


def generate_point_summary(point: dict, trend_features: dict | None, anomalies: list[dict]) -> str:
    """生成测点摘要。"""
    name = point.get("name", point.get("point_id", ""))
    status = compute_health_status(anomalies)
    status_cn = {"normal": "正常", "warning": "预警", "critical": "报警"}[status]

    parts = [f"{name}：状态 {status_cn}"]
    if anomalies:
        parts.append(f"检测到 {len(anomalies)} 项异常")
        for a in anomalies[:3]:
            parts.append(f"  - {a['description']}")
    else:
        parts.append("未检测到明显异常")
    return "\n".join(parts)


# ===== 主逻辑 =====

def extract_features(data: dict, analysis_focus: str) -> dict:
    """主入口：从 monitoring_data.json 提取特征并判定异常。"""
    point_features = []

    for point in data.get("points", []):
        pid = point["point_id"]
        category = point.get("category", "vib")

        feature: dict = {
            "point_id": pid,
            "point_name": point.get("name", ""),
            "point_type": point.get("point_type", 0),
            "endpoint_series": point.get("endpoint_series", ""),
            "category": category,
            "machine_id": point.get("machine_id", ""),
            "component_name": point.get("component_name", ""),
        }

        # 1. 趋势特征
        trend_rows = data.get("trend", {}).get(pid, [])
        trend_feat = None
        if trend_rows and analysis_focus in ("full", "trend", "anomaly"):
            trend_feat = extract_trend_features(trend_rows)
            feature["trend_features"] = trend_feat

        # 2. 波形频谱特征（仅 vib/vibc/thickness）
        wave_data = data.get("waveform", {}).get(pid)
        spectral_feat = None
        if wave_data and analysis_focus in ("full", "spectrum") and category in ("vib", "vibc"):
            spectral_feat = extract_spectral_features(wave_data, category)
            feature["spectral_features"] = spectral_feat

        # 3. 异常判定
        anomalies = detect_anomalies(point, trend_feat, spectral_feat)
        feature["anomalies"] = anomalies
        feature["health_status"] = compute_health_status(anomalies)
        feature["summary"] = generate_point_summary(point, trend_feat, anomalies)

        point_features.append(feature)

    # 综合结论
    statuses = [f["health_status"] for f in point_features]
    overall = "critical" if "critical" in statuses else ("warning" if "warning" in statuses else "normal")
    n_total = len(point_features)
    n_warning = statuses.count("warning")
    n_critical = statuses.count("critical")

    recommendations = []
    for f in point_features:
        if f["health_status"] != "normal":
            recommendations.append({
                "priority": f["health_status"],
                "action": f["summary"],
                "point_id": f["point_id"],
            })

    return {
        "schema_version": "2.0",
        "analysis_time": datetime.now(tz=timezone.utc).isoformat(),
        "points_analyzed": n_total,
        "point_features": point_features,
        "overall_status": overall,
        "overall_summary": f"共分析 {n_total} 个测点。{n_critical} 个 critical，{n_warning} 个 warning。",
        "recommendations": recommendations,
        "data_quality": {
            "total_points_expected": len(data.get("points", [])),
            "total_points_returned": n_total,
            "completeness_pct": round(n_total / max(len(data.get("points", [])), 1) * 100, 1),
            "gaps": [],
            "notes": data.get("data_notes", []),
        },
    }


def main():
    parser = argparse.ArgumentParser(description="监测特征提取 + 异常判定")
    parser.add_argument("--input", required=True, help="monitoring_data.json 路径")
    parser.add_argument("--analysis-focus", default="full", choices=["full", "trend", "anomaly", "spectrum"])
    parser.add_argument("--output-dir", default="/mnt/user-data/outputs")
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)

    result = extract_features(data, args.analysis_focus)

    os.makedirs(args.output_dir, exist_ok=True)
    output_path = os.path.join(args.output_dir, "monitoring_features.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)

    print(f"[extract] 特征提取完成: {output_path}", file=sys.stderr)
    print(f"[extract] 测点数: {result['points_analyzed']}, 整体状态: {result['overall_status']}", file=sys.stderr)


if __name__ == "__main__":
    main()
