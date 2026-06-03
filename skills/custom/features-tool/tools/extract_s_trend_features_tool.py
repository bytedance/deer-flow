import asyncio
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any

# 添加 features-tool 到 sys.path（ins 模块 + tools 包）
_FEATURES_TOOL_ROOT = Path(__file__).resolve().parent.parent
if str(_FEATURES_TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(_FEATURES_TOOL_ROOT))

from agents import function_tool
from pydantic import BaseModel, Field


class TrendSegment(BaseModel):
    start_time_ms: str
    end_time_ms: str
    start_index: int
    end_index: int
    point_count: int

    mean: float | None = None
    min: float | None = None
    max: float | None = None
    std: float | None = None
    range: float | None = None
    mad: float | None = None

    slope: float | None = None

    level_label: str = "unknown"
    volatility_label: str = "unknown"
    trend_label: str = "unknown"
    alarm_label: str = "unknown"
    state_label: str = "unknown"
    summary: str | None = None


class TrendFeatureDetail(BaseModel):
    # 1. 水平统计特征
    current: float | None = None
    mean: float | None = None
    median: float | None = None
    p95: float | None = None
    min: float | None = None
    max: float | None = None
    std: float | None = None

    # 2. 波动统计特征
    coefficient_of_variation: float | None = None
    range: float | None = None
    mad: float | None = None

    # 3. 变点检测特征
    changepoints: list[dict[str, Any]] = Field(default_factory=list)
    step_change_magnitude: float | None = None
    step_change_relative: float | None = None

    # 4. 越限与告警特征
    alarm_status: str = "normal"
    over_threshold_time: float | None = None
    max_over_threshold_duration: float | None = None
    over_threshold_ratio: float | None = None

    # 5. 趋势分段与状态特征
    segment_stats: list[TrendSegment] = Field(default_factory=list)
    dominant_state: str | None = None
    level_regime: str | None = None
    volatility_regime: str | None = None
    overall_direction: str | None = None


class TrendPointAnalysisResult(BaseModel):
    component_id: str = Field(description="测点 ID")
    features: list[str] = Field(default_factory=list, description="当前测点的特征值字段")
    feature_stats: dict[str, TrendFeatureDetail] = Field(description="当前测点各特征的趋势特征")
    summary: list[str] = Field(description="当前测点的趋势概括")
    notable_points: list[str] = Field(description="当前测点的显著时间点与波动说明")
    data: list[dict[str, object]] = Field(default_factory=list, description="当前测点的趋势原始数据")


class TrendAnalysisResult(BaseModel):
    component_ids: list[str] = Field(description="测点 ID 列表")
    start_time: str = Field(description="开始时间，毫秒时间戳")
    end_time: str = Field(description="结束时间，毫秒时间戳")
    component_features: dict[str, list[str]] = Field(description="各测点对应的特征值字段")
    point_results: list[TrendPointAnalysisResult] = Field(description="每个测点各自的趋势分析结果")


def _safe_mean(values: list[float]) -> float | None:
    if not values:
        return None
    return float(statistics.fmean(values))


def _safe_std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    return float(statistics.pstdev(values))


def _round_float(value: float | None, digits: int = 6) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return float(values[0])
    vals = sorted(values)
    pos = (len(vals) - 1) * q
    lower = int(math.floor(pos))
    upper = int(math.ceil(pos))
    if lower == upper:
        return float(vals[lower])
    weight = pos - lower
    return float(vals[lower] * (1 - weight) + vals[upper] * weight)


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    return float(statistics.median(values))


def _mad(values: list[float]) -> float | None:
    if not values:
        return None
    med = _median(values)
    if med is None:
        return None
    deviations = [abs(v - med) for v in values]
    return float(statistics.median(deviations))


def _parse_time_ms(value: str) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _extract_feature_series(
    point_data: list[dict[str, Any]],
    feature: str,
) -> list[tuple[str, float]]:
    series: list[tuple[str, float]] = []
    for item in point_data:
        time_ms = str(item.get("time_ms") or "")
        values = item.get("values") or {}
        if not isinstance(values, dict):
            continue
        raw = values.get(feature)
        if isinstance(raw, (int, float)) and math.isfinite(raw):
            series.append((time_ms, float(raw)))
    return series


def _infer_thresholds(point_data: list[dict[str, Any]]) -> tuple[float | None, float | None, float | None, float | None]:
    h_alarm = None
    hh_alarm = None
    l_alarm = None
    ll_alarm = None

    for item in point_data:
        for key in ("h_alarm", "hh_alarm", "l_alarm", "ll_alarm"):
            raw = item.get(key)
            if isinstance(raw, (int, float)) and math.isfinite(raw):
                if key == "h_alarm":
                    h_alarm = float(raw)
                elif key == "hh_alarm":
                    hh_alarm = float(raw)
                elif key == "l_alarm":
                    l_alarm = float(raw)
                elif key == "ll_alarm":
                    ll_alarm = float(raw)
    return h_alarm, hh_alarm, l_alarm, ll_alarm


def _moving_average(values: list[float], window: int) -> list[float]:
    if not values:
        return []
    if window <= 1:
        return [float(v) for v in values]

    n = len(values)
    half = window // 2
    result: list[float] = []
    for i in range(n):
        left = max(0, i - half)
        right = min(n, i + half + 1)
        result.append(float(statistics.fmean(values[left:right])))
    return result


def _rolling_std(values: list[float], window: int) -> list[float]:
    if not values:
        return []
    if window <= 1:
        return [0.0 for _ in values]

    n = len(values)
    half = window // 2
    result: list[float] = []
    for i in range(n):
        left = max(0, i - half)
        right = min(n, i + half + 1)
        result.append(_safe_std(values[left:right]))
    return result


def _rolling_slope(series: list[tuple[str, float]], window: int) -> list[float]:
    if not series:
        return []
    if window <= 2:
        return [0.0 for _ in series]

    n = len(series)
    half = window // 2
    result: list[float] = []

    for i in range(n):
        left = max(0, i - half)
        right = min(n, i + half + 1)
        sub = series[left:right]
        slope = _calc_slope(sub)
        result.append(float(slope or 0.0))

    return result


def _calc_slope_from_xy(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 2 or len(xs) != len(ys):
        return None

    x_mean = _safe_mean(xs)
    y_mean = _safe_mean(ys)
    if x_mean is None or y_mean is None:
        return None

    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
    denominator = sum((x - x_mean) ** 2 for x in xs)
    if abs(denominator) < 1e-12:
        return None

    return float(numerator / denominator)


def _calc_slope(series: list[tuple[str, float]]) -> float | None:
    if len(series) < 2:
        return None

    xs: list[float] = []
    ys: list[float] = []
    for ts, value in series:
        ts_i = _parse_time_ms(ts)
        if ts_i is None:
            continue
        xs.append(float(ts_i) / 1000.0)
        ys.append(value)

    return _calc_slope_from_xy(xs, ys)


def _classify_trend_from_relative_slope(relative_slope: float | None) -> tuple[str, str]:
    if relative_slope is None:
        return "unknown", "unknown"

    abs_rs = abs(relative_slope)
    if abs_rs <= 1e-6:
        trend_class = "stable"
    elif relative_slope > 0:
        trend_class = "increasing"
    else:
        trend_class = "decreasing"

    if abs_rs >= 8e-5:
        grade = "rapid"
    elif abs_rs >= 2e-5:
        grade = "moderate"
    else:
        grade = "slow"

    return trend_class, grade


def _label_level(segment_mean: float, global_mean: float, global_std: float) -> str:
    std_ref = global_std if global_std > 1e-12 else max(abs(global_mean) * 0.02, 1e-6)
    if segment_mean >= global_mean + 0.6 * std_ref:
        return "high"
    if segment_mean <= global_mean - 0.6 * std_ref:
        return "low"
    return "mid"


def _label_volatility(segment_std: float, global_std: float) -> str:
    std_ref = global_std if global_std > 1e-12 else max(segment_std, 1e-6)
    ratio = segment_std / std_ref if std_ref > 1e-12 else 1.0
    if ratio >= 1.2:
        return "wide"
    if ratio <= 0.8:
        return "narrow"
    return "normal"


def _classify_alarm_label(
    seg_min: float,
    seg_max: float,
    h_alarm: float | None,
    hh_alarm: float | None,
    l_alarm: float | None,
    ll_alarm: float | None,
) -> str:
    if hh_alarm is not None and seg_max >= hh_alarm:
        return "over_hh"
    if h_alarm is not None and seg_max >= h_alarm:
        return "over_h"
    if ll_alarm is not None and seg_min <= ll_alarm:
        return "over_ll"
    if l_alarm is not None and seg_min <= l_alarm:
        return "over_l"

    near_high = h_alarm is not None and seg_max >= h_alarm * 0.95
    near_low = l_alarm is not None and seg_min <= l_alarm * 1.05 if l_alarm is not None else False
    if near_high or near_low:
        return "near_alarm"
    return "normal"


def _classify_state_label(
    level_label: str,
    volatility_label: str,
    trend_label: str,
    alarm_label: str,
    mean_shift_vs_prev: float | None,
    global_std: float,
    baseline: float,
) -> str:
    shift_ref = max(global_std * 0.6, baseline * 0.03, 1e-6)
    if alarm_label in {"over_h", "over_hh", "over_l", "over_ll"}:
        return "over_limit_running"
    if mean_shift_vs_prev is not None and mean_shift_vs_prev >= shift_ref and level_label == "high":
        return "post_step_high"
    if mean_shift_vs_prev is not None and mean_shift_vs_prev <= -shift_ref and level_label == "low":
        return "post_step_low"
    if trend_label == "rapid_rising":
        return "rapid_rising"
    if trend_label == "rapid_falling":
        return "rapid_falling"
    if trend_label == "falling" and level_label == "high":
        return "recovery_falling"
    if level_label == "high" and trend_label == "stable":
        return "high_level_stable"
    if level_label == "low" and trend_label == "stable":
        return "low_level_stable"
    if volatility_label == "violent":
        return "fluctuating_active"
    if volatility_label == "active":
        return "active_running"
    if trend_label == "rising":
        return "rising"
    if trend_label == "falling":
        return "falling"
    return "stable_running"


def _build_segment_summary(
    state_label: str,
    level_label: str,
    volatility_label: str,
    trend_label: str,
    alarm_label: str,
) -> str:
    state_map = {
        "stable_running": "平稳波动运行",
        "active_running": "波动较活跃运行",
        "fluctuating_active": "剧烈波动运行",
        "rapid_rising": "快速上升",
        "rapid_falling": "快速下降",
        "rising": "缓慢上升",
        "falling": "缓慢下降",
        "over_limit_running": "越限运行",
        "high_level_stable": "高位平稳运行",
        "low_level_stable": "低位平稳运行",
        "post_step_high": "突然上升后处在高位",
        "post_step_low": "突然下降后处在低位",
        "recovery_falling": "越限后回落恢复",
    }
    level_map = {"high": "高位", "mid": "中位", "low": "低位", "unknown": "未知位"}
    vol_map = {"stable": "波动平稳", "active": "波动活跃", "violent": "波动剧烈", "unknown": "波动未知"}
    trend_map = {
        "stable": "趋势平稳",
        "rising": "缓慢上升",
        "falling": "缓慢下降",
        "rapid_rising": "快速上升",
        "rapid_falling": "快速下降",
        "unknown": "趋势未知",
    }
    alarm_map = {
        "normal": "未越限",
        "near_alarm": "接近告警",
        "over_h": "高报越限",
        "over_hh": "高高报越限",
        "over_l": "低报越限",
        "over_ll": "低低报越限",
        "unknown": "告警未知",
    }
    return f"{state_map.get(state_label, state_label)}（{level_map.get(level_label, level_label)}，{vol_map.get(volatility_label, volatility_label)}，{trend_map.get(trend_label, trend_label)}，{alarm_map.get(alarm_label, alarm_label)}）"


def _merge_small_breakpoints(
    candidates: list[tuple[int, dict[str, Any]]],
    n: int,
    min_seg_len: int,
) -> list[tuple[int, dict[str, Any]]]:
    if not candidates:
        return []

    points = sorted(candidates, key=lambda x: x[0])
    merged: list[tuple[int, dict[str, Any]]] = []
    prev = 0

    for idx, payload in points:
        if not (0 < idx < n):
            continue
        if idx - prev < min_seg_len:
            continue
        merged.append((idx, payload))
        prev = idx

    if merged and n - merged[-1][0] < min_seg_len:
        merged.pop()

    return merged


def _segment_series(
    series: list[tuple[str, float]],
    h_alarm: float | None = None,
    hh_alarm: float | None = None,
    l_alarm: float | None = None,
    ll_alarm: float | None = None,
) -> tuple[list[TrendSegment], list[dict[str, Any]], str | None, str | None, str | None, str | None]:
    if len(series) < 8:
        return [], [], None, None, None, None

    times = [ts for ts, _ in series]
    values = [v for _, v in series]

    global_mean = _safe_mean(values) or 0.0
    global_std = _safe_std(values)
    baseline = abs(global_mean) if abs(global_mean) > 1e-12 else 1.0
    n = len(values)

    feature_window = max(5, min(15, max(5, n // 12)))
    smooth_long = _moving_average(values, feature_window)
    rolling_vol = _rolling_std(values, feature_window)
    rolling_slopes = _rolling_slope(series, feature_window)

    diff_level = [abs(smooth_long[i] - smooth_long[i - 1]) for i in range(1, n)]
    diff_vol = [abs(rolling_vol[i] - rolling_vol[i - 1]) for i in range(1, n)]
    diff_slope = [abs(rolling_slopes[i] - rolling_slopes[i - 1]) for i in range(1, n)]

    level_threshold = max(global_std * 0.18, baseline * 0.01)
    vol_threshold = max(global_std * 0.12, baseline * 0.006)
    slope_threshold = max(abs(_safe_mean([abs(x) for x in rolling_slopes]) or 0.0) * 3.0, 1e-7)

    candidate_breakpoints: list[tuple[int, dict[str, Any]]] = []
    for i in range(1, n - 1):
        level_jump = diff_level[i - 1]
        vol_jump = diff_vol[i - 1]
        slope_jump = diff_slope[i - 1]

        chosen_type = None
        chosen_mag = 0.0
        if level_jump >= level_threshold:
            chosen_type = "level_shift"
            chosen_mag = level_jump
        if vol_jump >= vol_threshold and vol_jump > chosen_mag:
            chosen_type = "volatility_shift"
            chosen_mag = vol_jump
        if slope_jump >= slope_threshold and slope_jump > chosen_mag:
            chosen_type = "slope_shift"
            chosen_mag = slope_jump

        prev_value = values[i - 1]
        curr_value = values[i]
        alarm_shift_type = None
        if h_alarm is not None:
            if prev_value < h_alarm <= curr_value:
                alarm_shift_type = "cross_over_h"
            elif prev_value >= h_alarm > curr_value:
                alarm_shift_type = "leave_over_h"
        if hh_alarm is not None:
            if prev_value < hh_alarm <= curr_value:
                alarm_shift_type = "cross_over_hh"
            elif prev_value >= hh_alarm > curr_value:
                alarm_shift_type = "leave_over_hh"
        if l_alarm is not None:
            if prev_value > l_alarm >= curr_value:
                alarm_shift_type = "cross_over_l"
            elif prev_value <= l_alarm < curr_value:
                alarm_shift_type = "leave_over_l"
        if ll_alarm is not None:
            if prev_value > ll_alarm >= curr_value:
                alarm_shift_type = "cross_over_ll"
            elif prev_value <= ll_alarm < curr_value:
                alarm_shift_type = "leave_over_ll"

        if alarm_shift_type is not None:
            chosen_type = alarm_shift_type
            chosen_mag = max(chosen_mag, abs(curr_value - prev_value))

        if chosen_type is not None:
            score = chosen_mag / max(global_std, baseline * 0.01, 1e-6)
            payload = {
                "time_ms": times[i],
                "type": chosen_type,
                "magnitude": _round_float(chosen_mag, 6),
                "score": _round_float(score, 6),
                "relative_change": _round_float(chosen_mag / baseline, 6),
            }
            candidate_breakpoints.append((i, payload))

    min_seg_len = max(8, n // 10)
    kept = _merge_small_breakpoints(candidate_breakpoints, n, min_seg_len)
    boundaries = [0] + [idx for idx, _ in kept] + [n]
    changepoints = [payload for _, payload in kept]

    segments: list[TrendSegment] = []
    prev_seg_mean = None
    first_seg_mean = None
    last_seg_mean = None

    for idx in range(len(boundaries) - 1):
        start = boundaries[idx]
        end = boundaries[idx + 1]
        seg_values = values[start:end]
        seg_times = times[start:end]
        if len(seg_values) < 2:
            continue

        seg_mean = _safe_mean(seg_values)
        seg_std = _safe_std(seg_values)
        seg_min = min(seg_values)
        seg_max = max(seg_values)
        seg_range = seg_max - seg_min
        seg_mad = _mad(seg_values)
        seg_series = series[start:end]
        seg_slope = _calc_slope(seg_series)

        seg_relative_slope = None
        if seg_slope is not None and seg_mean is not None and abs(seg_mean) > 1e-12:
            seg_relative_slope = seg_slope / abs(seg_mean)

        slope_base_label, slope_grade = _classify_trend_from_relative_slope(seg_relative_slope)
        if slope_base_label == "stable":
            trend_label = "stable"
        elif slope_base_label == "increasing":
            trend_label = "rapid_rising" if slope_grade == "rapid" else "rising"
        else:
            trend_label = "rapid_falling" if slope_grade == "rapid" else "falling"

        level_label = _label_level(seg_mean or 0.0, global_mean, global_std)
        volatility_base = _label_volatility(seg_std, global_std)
        if volatility_base == "wide":
            volatility_label = "violent"
        elif volatility_base == "normal":
            volatility_label = "active"
        else:
            volatility_label = "stable"

        mean_shift_vs_prev = None
        if prev_seg_mean is not None and seg_mean is not None:
            mean_shift_vs_prev = seg_mean - prev_seg_mean

        alarm_label = _classify_alarm_label(seg_min, seg_max, h_alarm, hh_alarm, l_alarm, ll_alarm)
        state_label = _classify_state_label(
            level_label=level_label,
            volatility_label=volatility_label,
            trend_label=trend_label,
            alarm_label=alarm_label,
            mean_shift_vs_prev=mean_shift_vs_prev,
            global_std=global_std,
            baseline=baseline,
        )
        summary = _build_segment_summary(state_label, level_label, volatility_label, trend_label, alarm_label)

        segment = TrendSegment(
            start_time_ms=seg_times[0],
            end_time_ms=seg_times[-1],
            start_index=start,
            end_index=end - 1,
            point_count=len(seg_values),
            mean=_round_float(seg_mean, 6),
            min=_round_float(seg_min, 6),
            max=_round_float(seg_max, 6),
            std=_round_float(seg_std, 6),
            range=_round_float(seg_range, 6),
            mad=_round_float(seg_mad, 6),
            slope=_round_float(seg_slope, 9),
            level_label=level_label,
            volatility_label=volatility_label,
            trend_label=trend_label,
            alarm_label=alarm_label,
            state_label=state_label,
            summary=summary,
        )
        segments.append(segment)

        if first_seg_mean is None:
            first_seg_mean = seg_mean
        last_seg_mean = seg_mean
        prev_seg_mean = seg_mean

    if not segments:
        return [], [], None, None, None, None

    dominant_state = max(
        (seg.state_label for seg in segments),
        key=lambda name: sum(s.point_count for s in segments if s.state_label == name),
        default=None,
    )
    level_regime = max(
        (seg.level_label for seg in segments),
        key=lambda name: sum(s.point_count for s in segments if s.level_label == name),
        default=None,
    )
    volatility_regime = max(
        (seg.volatility_label for seg in segments),
        key=lambda name: sum(s.point_count for s in segments if s.volatility_label == name),
        default=None,
    )

    overall_direction = None
    if first_seg_mean is not None and last_seg_mean is not None:
        delta = last_seg_mean - first_seg_mean
        if abs(delta) <= max(global_std * 0.2, baseline * 0.01):
            overall_direction = "stable"
        elif delta > 0:
            overall_direction = "up"
        else:
            overall_direction = "down"

    return segments, changepoints[:8], dominant_state, level_regime, volatility_regime, overall_direction


def _calc_over_threshold_metrics(
    series: list[tuple[str, float]],
    h_alarm: float | None,
    hh_alarm: float | None,
    l_alarm: float | None,
    ll_alarm: float | None,
) -> tuple[str, float | None, float | None, float | None]:
    if len(series) < 2:
        current = series[-1][1] if series else None
        if current is None:
            return "normal", None, None, None
        if hh_alarm is not None and current >= hh_alarm:
            return "HH", 0.0, 0.0, 0.0
        if h_alarm is not None and current >= h_alarm:
            return "H", 0.0, 0.0, 0.0
        if ll_alarm is not None and current <= ll_alarm:
            return "LL", 0.0, 0.0, 0.0
        if l_alarm is not None and current <= l_alarm:
            return "L", 0.0, 0.0, 0.0
        return "normal", 0.0, 0.0, 0.0

    current_value = series[-1][1]
    if hh_alarm is not None and current_value >= hh_alarm:
        alarm_status = "HH"
    elif h_alarm is not None and current_value >= h_alarm:
        alarm_status = "H"
    elif ll_alarm is not None and current_value <= ll_alarm:
        alarm_status = "LL"
    elif l_alarm is not None and current_value <= l_alarm:
        alarm_status = "L"
    else:
        alarm_status = "normal"

    def is_over(v: float) -> bool:
        if hh_alarm is not None and v >= hh_alarm:
            return True
        if h_alarm is not None and v >= h_alarm:
            return True
        if ll_alarm is not None and v <= ll_alarm:
            return True
        if l_alarm is not None and v <= l_alarm:
            return True
        return False

    total_duration = 0.0
    current_run = 0.0
    max_run = 0.0
    total_window = 0.0

    for i in range(1, len(series)):
        prev_ts = _parse_time_ms(series[i - 1][0])
        curr_ts = _parse_time_ms(series[i][0])
        if prev_ts is None or curr_ts is None or curr_ts <= prev_ts:
            continue

        dt = (curr_ts - prev_ts) / 1000.0
        total_window += dt

        over_prev = is_over(series[i - 1][1])
        over_curr = is_over(series[i][1])

        if over_prev and over_curr:
            total_duration += dt
            current_run += dt
        else:
            if current_run > max_run:
                max_run = current_run
            current_run = 0.0

    if current_run > max_run:
        max_run = current_run

    ratio = (total_duration / total_window) if total_window > 0 else 0.0
    return (
        alarm_status,
        _round_float(total_duration, 3),
        _round_float(max_run, 3),
        _round_float(ratio, 6),
    )


def _segment_to_phrase(seg: TrendSegment) -> str:
    return seg.summary or seg.state_label


def _extract_main_changepoint_metrics(
    changepoints: list[dict[str, Any]],
) -> tuple[float | None, float | None]:
    if not changepoints:
        return None, None

    main_cp = changepoints[0]
    magnitude = None
    relative = None

    raw_mag = main_cp.get("magnitude")
    if isinstance(raw_mag, (int, float)):
        magnitude = float(raw_mag)

    raw_rel = main_cp.get("relative_change")
    if isinstance(raw_rel, (int, float)):
        relative = float(raw_rel)

    return _round_float(magnitude, 6), _round_float(relative, 6)


def _build_feature_detail(point_data: list[dict[str, Any]], series: list[tuple[str, float]]) -> TrendFeatureDetail:
    values = [v for _, v in series]
    if not values:
        return TrendFeatureDetail()

    current = values[-1]
    mean_v = _safe_mean(values)
    median_v = _median(values)
    p95_v = _percentile(values, 0.95)
    min_v = min(values)
    max_v = max(values)
    std_v = _safe_std(values)
    range_v = max_v - min_v
    mad_v = _mad(values)

    cov = None
    if mean_v is not None and abs(mean_v) > 1e-12:
        cov = std_v / abs(mean_v)

    h_alarm, hh_alarm, l_alarm, ll_alarm = _infer_thresholds(point_data)
    segments, regime_changepoints, dominant_state, level_regime, volatility_regime, overall_direction = _segment_series(
        series, h_alarm, hh_alarm, l_alarm, ll_alarm
    )
    step_mag, step_rel = _extract_main_changepoint_metrics(regime_changepoints)

    alarm_status, over_threshold_time, max_over_threshold_duration, over_threshold_ratio = _calc_over_threshold_metrics(
        series, h_alarm, hh_alarm, l_alarm, ll_alarm
    )

    return TrendFeatureDetail(
        current=_round_float(current, 6),
        mean=_round_float(mean_v, 6),
        median=_round_float(median_v, 6),
        p95=_round_float(p95_v, 6),
        min=_round_float(min_v, 6),
        max=_round_float(max_v, 6),
        std=_round_float(std_v, 6),
        coefficient_of_variation=_round_float(cov, 6),
        range=_round_float(range_v, 6),
        mad=_round_float(mad_v, 6),
        changepoints=regime_changepoints,
        step_change_magnitude=step_mag,
        step_change_relative=step_rel,
        alarm_status=alarm_status,
        over_threshold_time=over_threshold_time,
        max_over_threshold_duration=max_over_threshold_duration,
        over_threshold_ratio=over_threshold_ratio,
        segment_stats=segments,
        dominant_state=dominant_state,
        level_regime=level_regime,
        volatility_regime=volatility_regime,
        overall_direction=overall_direction,
    )


def _build_summary_for_feature(feature: str, detail: TrendFeatureDetail) -> list[str]:
    if detail.current is None:
        return [f"{feature} 无有效数据"]

    lines: list[str] = []

    lines.append(
        f"{feature} 当前值 {detail.current}，均值 {detail.mean}，P95 {detail.p95}，标准差 {detail.std}"
    )

    lines.append(
        f"{feature} 当前告警状态 {detail.alarm_status}，越限总时长 {detail.over_threshold_time} 秒，最长连续越限 {detail.max_over_threshold_duration} 秒，占比 {detail.over_threshold_ratio}"
    )

    lines.append(
        f"{feature} 主导状态 {detail.dominant_state or 'unknown'}，主导水平区间 {detail.level_regime or 'unknown'}，主导波动程度 {detail.volatility_regime or 'unknown'}，整体方向 {detail.overall_direction or 'unknown'}"
    )

    if detail.step_change_magnitude is not None or detail.step_change_relative is not None:
        lines.append(
            f"{feature} 主要变点变化幅度 {detail.step_change_magnitude}，相对变化幅度 {detail.step_change_relative}"
        )

    return lines[:4]


def _build_notable_points_for_feature(feature: str, series: list[tuple[str, float]], detail: TrendFeatureDetail) -> list[str]:
    if not series:
        return []

    values = [v for _, v in series]
    min_idx = values.index(min(values))
    max_idx = values.index(max(values))

    notable = [
        f"{series[min_idx][0]} 出现区间最低值 {round(series[min_idx][1], 3)}",
        f"{series[max_idx][0]} 出现区间最高值 {round(series[max_idx][1], 3)}",
    ]

    for seg in detail.segment_stats[:4]:
        notable.append(
            f"{seg.start_time_ms} 至 {seg.end_time_ms} 为一段 {_segment_to_phrase(seg)} 区间"
        )

    for cp in detail.changepoints[:3]:
        notable.append(
            f"{cp['time_ms']} 检测到变点 {cp['type']}，幅度 {cp.get('magnitude')}，相对变化 {cp.get('relative_change')}"
        )

    deduped: list[str] = []
    seen: set[str] = set()
    for item in notable:
        if item not in seen:
            seen.add(item)
            deduped.append(item)

    return deduped[:10]


def _merge_feature_summaries(feature_summaries: dict[str, list[str]]) -> list[str]:
    merged: list[str] = []
    for _, lines in feature_summaries.items():
        merged.extend(lines[:4])
    return merged[:20]


def _merge_feature_notable_points(feature_notables: dict[str, list[str]]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for _, lines in feature_notables.items():
        for line in lines:
            if line not in seen:
                seen.add(line)
                merged.append(line)
    return merged[:24]


@function_tool(strict_mode=False)
async def extract_trend_features_tool(trend_data_payload: dict[str, Any]) -> dict[str, Any]:
    """
    基于 get_trend_data_tool 返回的原始趋势数据，提取趋势特征。
    支持多个测点，不同测点可配置不同 feature。

    输入格式：
    {
      "component_ids": [...],
      "start_time": "...",
      "end_time": "...",
      "component_features": {
        "component_id_1": ["pp_value", "rms"],
        "component_id_2": ["value"]
      },
      "data": {
        "component_id_1": [
          {"component_id": "...", "time_ms": "...", "time": "...", "values": {...}},
          ...
        ],
        ...
      }
    }
    """
    component_ids = trend_data_payload.get("component_ids") or []
    start_time = str(trend_data_payload.get("start_time") or "")
    end_time = str(trend_data_payload.get("end_time") or "")
    component_features = trend_data_payload.get("component_features") or {}
    grouped_data = trend_data_payload.get("data") or {}

    point_results: list[TrendPointAnalysisResult] = []

    for component_id in component_ids:
        point_data = grouped_data.get(component_id) or []
        if not isinstance(point_data, list):
            point_data = []

        features = component_features.get(component_id) or []
        if not isinstance(features, list):
            features = []

        feature_stats: dict[str, TrendFeatureDetail] = {}
        feature_summaries: dict[str, list[str]] = {}
        feature_notables: dict[str, list[str]] = {}

        for feature in features:
            series = _extract_feature_series(point_data, feature)
            detail = _build_feature_detail(point_data, series)
            feature_stats[feature] = detail
            feature_summaries[feature] = _build_summary_for_feature(feature, detail)
            feature_notables[feature] = _build_notable_points_for_feature(feature, series, detail)

        point_results.append(
            TrendPointAnalysisResult(
                component_id=component_id,
                features=features,
                feature_stats=feature_stats,
                summary=_merge_feature_summaries(feature_summaries),
                notable_points=_merge_feature_notable_points(feature_notables),
                data=point_data,
            )
        )

    result = TrendAnalysisResult(
        component_ids=component_ids,
        start_time=start_time,
        end_time=end_time,
        component_features=component_features,
        point_results=point_results,
    )
    return result.model_dump()


async def main() -> None:
    """
    用法:
    python extract_trend_features_tool.py '{"component_ids":[...],"start_time":"...","end_time":"...","component_features":{...},"data":{...}}'
    """
    if len(sys.argv) < 2:
        raise SystemExit("用法: python extract_trend_features_tool.py '<trend_data_payload_json>'")

    payload = json.loads(sys.argv[1])
    result = await extract_trend_features_tool(payload)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
