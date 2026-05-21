from __future__ import annotations

import math
from typing import Any

import numpy as np


def _safe_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def _latest(values: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not values:
        return None
    return max(values, key=lambda item: int(item.get("time") or item.get("time_ms") or 0))


def _slopes(values: list[dict[str, Any]], value_key: str, current_time: int, windows: dict[str, int], mins: dict[str, int]) -> dict[str, float]:
    result: dict[str, float] = {}
    for key, start_time in windows.items():
        series = [item for item in values if int(item.get("time") or item.get("time_ms") or 0) >= start_time]
        if len(series) < mins[key]:
            result[key] = 0.0
            continue
        y = np.asarray([_safe_float(item.get(value_key)) or 0.0 for item in series], dtype=float)
        x = np.arange(len(series), dtype=float)
        if len(y) < 2:
            result[key] = 0.0
            continue
        result[key] = float(np.polyfit(x, y, 1)[0])
    return result


def calc_trend_k(c_threshold: float | None) -> float:
    if c_threshold is None:
        return 1.0
    if 2.5 <= c_threshold <= 4.6:
        return 1.0
    if c_threshold > 4.6:
        return 1.2
    return 0.8


def check_vibration_health(point_id: str, point_name: str, values: list[dict[str, Any]], thresholds: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    latest = _latest(values)
    if latest is None:
        return findings
    latest_time = int(latest.get("time") or latest.get("time_ms") or 0)
    latest_rms = _safe_float(latest.get("rms") or latest.get("v_rms"))
    b = _safe_float(thresholds.get("rms_b") or thresholds.get("B") or thresholds.get("b"))
    c = _safe_float(thresholds.get("rms_c") or thresholds.get("C") or thresholds.get("c") or thresholds.get("cValue"))
    d = _safe_float(thresholds.get("rms_d") or thresholds.get("D") or thresholds.get("d"))

    if latest_rms is not None and d is not None and latest_rms > d:
        findings.append(_finding("D", "当前处于D区", point_id, point_name, latest_rms, d, latest_time, "rms"))
    elif latest_rms is not None and c is not None and latest_rms > c:
        findings.append(_finding("C", "当前处于C区", point_id, point_name, latest_rms, c, latest_time, "rms"))

    if c is not None:
        since = latest_time - 12 * 60 * 60 * 1000
        for item in values:
            rms = _safe_float(item.get("rms") or item.get("v_rms"))
            ts = int(item.get("time") or item.get("time_ms") or 0)
            if ts >= since and rms is not None and rms > c:
                findings.append(_finding("C_His", "12h内进入C区", point_id, point_name, rms, c, ts, "rms"))
                break

    if latest_rms is not None and b is not None and latest_rms >= b:
        k = calc_trend_k(c)
        windows = {
            "K1": latest_time - 7 * 24 * 60 * 60 * 1000,
            "K2": latest_time - 3 * 24 * 60 * 60 * 1000,
            "K3": latest_time - 1 * 24 * 60 * 60 * 1000,
        }
        slopes = _slopes(values, "rms", latest_time, windows, {"K1": 75, "K2": 32, "K3": 11})
        for status, desc, key, threshold in (
            ("Rms_1", "速度1天趋势报警", "K3", 0.0725 * k),
            ("Rms_3", "速度3天趋势报警", "K2", 0.05 * k),
            ("Rms_7", "速度7天趋势报警", "K1", 0.03 * k),
        ):
            if slopes.get(key, 0.0) > threshold:
                findings.append(_finding(status, desc, point_id, point_name, slopes[key], threshold, latest_time, key))

    peak = _safe_float(latest.get("peak") or latest.get("a_peak"))
    if peak is not None and peak >= 15:
        windows = {
            "K1": latest_time - 7 * 24 * 60 * 60 * 1000,
            "K2": latest_time - 3 * 24 * 60 * 60 * 1000,
        }
        slopes = _slopes(values, "peak", latest_time, windows, {"K1": 75, "K2": 32})
        for status, desc, key, threshold in (
            ("Acc_3", "加速度3天趋势报警", "K2", 0.1275 * calc_trend_k(c)),
            ("Acc_7", "加速度7天趋势报警", "K1", 0.0525 * calc_trend_k(c)),
        ):
            if slopes.get(key, 0.0) > threshold:
                findings.append(_finding(status, desc, point_id, point_name, slopes[key], threshold, latest_time, key))
    return findings


def check_temperature_health(point_id: str, point_name: str, values: list[dict[str, Any]], thresholds: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    latest = _latest(values)
    if latest is None:
        return findings
    latest_time = int(latest.get("time") or latest.get("time_ms") or 0)
    temp_h = _safe_float(thresholds.get("temp_h") or thresholds.get("h_alarm") or thresholds.get("H"))
    for item in values:
        value = _safe_float(item.get("value") or item.get("temperature"))
        ts = int(item.get("time") or item.get("time_ms") or 0)
        if temp_h is not None and value is not None and value > temp_h:
            findings.append(_finding("Temperature", "温度报警", point_id, point_name, value, temp_h, ts, "value"))
            break

    current_temp = _safe_float(latest.get("value") or latest.get("temperature"))
    if current_temp is None:
        return findings
    windows = {
        "K1": latest_time - 7 * 24 * 60 * 60 * 1000,
        "K2": latest_time - 3 * 24 * 60 * 60 * 1000,
    }
    slopes = _slopes(values, "value", latest_time, windows, {"K1": 75, "K2": 32})
    for status, desc, key, threshold in (
        ("Temp_3", "温度3天趋势", "K2", 0.2),
        ("Temp_7", "温度7天趋势", "K1", 0.095),
    ):
        if slopes.get(key, 0.0) > threshold:
            findings.append(_finding(status, desc, point_id, point_name, slopes[key], threshold, latest_time, key))
    return findings


def _finding(
    status: str,
    description: str,
    point_id: str,
    point_name: str,
    value: float,
    threshold: float,
    timestamp: int,
    feature: str,
) -> dict[str, Any]:
    return {
        "status": status,
        "description": description,
        "point_id": point_id,
        "point_name": point_name,
        "feature": feature,
        "value": float(value),
        "threshold": float(threshold),
        "time": timestamp,
    }
