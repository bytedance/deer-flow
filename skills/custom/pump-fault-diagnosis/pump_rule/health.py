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
        acc_short_finding = _acc_short_term_check(values, point_id, point_name, latest_time)
        if acc_short_finding is not None:
            findings.append(acc_short_finding)

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


def check_temperature_health(point_id: str, point_name: str, values: list[dict[str, Any]], thresholds: dict[str, Any], vibration_k: float = 1.0) -> list[dict[str, Any]]:
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

    temp_short_finding = _temperature_short_check(values, point_id, point_name, latest_time)
    if temp_short_finding is not None:
        findings.append(temp_short_finding)

    windows = {
        "K1": latest_time - 7 * 24 * 60 * 60 * 1000,
        "K2": latest_time - 3 * 24 * 60 * 60 * 1000,
    }
    slopes = _slopes(values, "value", latest_time, windows, {"K1": 75, "K2": 32})

    def _window_mean(window_key: str) -> float:
        window_data = [
            _safe_float(item.get("value") or item.get("temperature"))
            for item in values
            if int(item.get("time") or item.get("time_ms") or 0) >= windows[window_key]
            and int(item.get("time") or item.get("time_ms") or 0) < latest_time
        ]
        window_data = [v for v in window_data if v is not None]
        return float(np.mean(window_data)) if window_data else float("-inf")

    k1_mean = _window_mean("K1")
    k2_mean = _window_mean("K2")

    for status, desc, key, base_threshold, mean_val in (
        ("Temp_3", "温度3天趋势", "K2", 0.2 * vibration_k, k2_mean),
        ("Temp_7", "温度7天趋势", "K1", 0.095 * vibration_k, k1_mean),
    ):
        if slopes.get(key, 0.0) > base_threshold and current_temp > mean_val:
            findings.append(_finding(status, desc, point_id, point_name, slopes[key], base_threshold, latest_time, key))
    return findings


def _acc_short_term_check(values: list[dict[str, Any]], point_id: str, point_name: str, latest_time: int) -> dict[str, Any] | None:
    sorted_data = sorted(values, key=lambda x: int(x.get("time") or x.get("time_ms") or 0), reverse=True)
    sorted_data = [item for item in sorted_data if _safe_float(item.get("peak") or item.get("a_peak")) is not None]
    if len(sorted_data) < 3:
        return None
    min_item = sorted_data[-1]
    min_time = int(min_item.get("time") or min_item.get("time_ms") or 0)
    if latest_time - min_time < 7 * 24 * 60 * 60 * 1000:
        return None
    data_without_latest = sorted_data[1:]
    peak_values = [_safe_float(item.get("peak") or item.get("a_peak")) for item in data_without_latest]
    peak_values = [v for v in peak_values if v is not None]
    if len(peak_values) < 2:
        return None
    acc_mean = float(np.mean(peak_values))
    acc_std = float(np.std(peak_values))
    last_two = sorted(data_without_latest, key=lambda x: int(x.get("time") or x.get("time_ms") or 0), reverse=True)[:2]
    threshold = acc_mean + 3.25 * acc_std
    if all((_safe_float(item.get("peak") or item.get("a_peak")) or 0.0) > threshold for item in last_two):
        return _finding("Acc_Short", "加速度短期突变报警", point_id, point_name, threshold, acc_mean, latest_time, "peak")
    return None


def _temperature_short_check(values: list[dict[str, Any]], point_id: str, point_name: str, latest_time: int) -> dict[str, Any] | None:
    sorted_data = sorted(values, key=lambda x: int(x.get("time") or x.get("time_ms") or 0), reverse=True)
    sorted_data = [item for item in sorted_data if _safe_float(item.get("value") or item.get("temperature")) is not None]
    if len(sorted_data) < 3:
        return None
    seven_days_ago = latest_time - 7 * 24 * 60 * 60 * 1000
    previous_data = [item for item in sorted_data if int(item.get("time") or item.get("time_ms") or 0) > seven_days_ago]
    previous_data = previous_data[:-1] if previous_data else []
    recent_data = [item for item in values if int(item.get("time") or item.get("time_ms") or 0) >= latest_time - 6 * 60 * 60 * 1000]
    if len(recent_data) < 3:
        return None
    threshold = 20.0
    if not all((_safe_float(item.get("value") or item.get("temperature")) or 0.0) > threshold for item in recent_data):
        return None
    time_1 = latest_time
    time_2 = latest_time - 2 * 60 * 60 * 1000
    time_3 = latest_time - 4 * 60 * 60 * 1000

    def _closest_temp(target_time: int) -> float:
        closest = min(recent_data, key=lambda item: abs(int(item.get("time") or item.get("time_ms") or 0) - target_time))
        return _safe_float(closest.get("value") or closest.get("temperature")) or 0.0

    temp1 = _closest_temp(time_1)
    temp2 = _closest_temp(time_2)
    temp3 = _closest_temp(time_3)
    average_temp = ((temp1 - temp2) + (temp2 - temp3)) / 2.0
    temp_change = temp1 - temp2
    if average_temp > 4.0 and temp_change > 4.0:
        return _finding("Temp_Short", "温度短期突变报警", point_id, point_name, average_temp, 4.0, latest_time, "value")
    return None


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
