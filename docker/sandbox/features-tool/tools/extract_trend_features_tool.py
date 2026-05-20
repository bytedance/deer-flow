import asyncio
import json
import math
import statistics
import sys
from typing import Any

from agents import function_tool
from pydantic import BaseModel, Field
from tools.get_trend_data_tool import _get_trend_data_impl


class RisingPeriod(BaseModel):
    start_time_ms: str
    end_time_ms: str
    start_index: int
    end_index: int
    point_count: int

    rise_amplitude: float | None = None
    rise_rate: float | None = None
    relative_rise: float | None = None
    confidence: float | None = None
    summary: str | None = None


class HighVolatilityPeriod(BaseModel):
    start_time_ms: str
    end_time_ms: str
    start_index: int
    end_index: int
    point_count: int

    mean_abs_residual: float | None = None
    residual_std: float | None = None
    peak_volatility_score: float | None = None
    mean_volatility_score: float | None = None
    confidence: float | None = None
    summary: str | None = None


class TrendFeatureDetail(BaseModel):
    # 基础统计
    current: float | None = None
    mean: float | None = None
    min: float | None = None
    max: float | None = None
    std: float | None = None
    range: float | None = None
    mad: float | None = None

    # 趋势相关
    trend_method: str = "double_moving_average"
    trend_window: int | None = None
    trend_values: list[float] = Field(default_factory=list)
    trend_slope_values: list[float] = Field(default_factory=list)

    rising_periods: list[RisingPeriod] = Field(default_factory=list)
    rise_period_count: int = 0
    total_rise_points: int = 0
    max_rise_amplitude: float | None = None
    max_rise_rate: float | None = None

    # 去趋势波动相关
    residual_values: list[float] = Field(default_factory=list)
    residual_volatility_values: list[float] = Field(default_factory=list)

    high_volatility_periods: list[HighVolatilityPeriod] = Field(default_factory=list)
    high_volatility_period_count: int = 0
    total_high_volatility_points: int = 0
    max_volatility_score: float | None = None

    # 辅助
    narrative_summary: str | None = None


class TrendPointAnalysisResult(BaseModel):
    component_id: str = Field(description="测点 ID")
    features: list[str] = Field(default_factory=list, description="当前测点的特征值字段")
    feature_stats: dict[str, TrendFeatureDetail] = Field(description="当前测点各特征的趋势特征")
    summary: list[str] = Field(description="当前测点的趋势概括")
    notable_points: list[str] = Field(description="当前测点的显著时间段说明")


class TrendAnalysisResult(BaseModel):
    component_ids: list[str] = Field(description="测点 ID 列表")
    start_time: str = Field(description="开始时间，毫秒时间戳")
    end_time: str = Field(description="结束时间，毫秒时间戳")
    component_features: dict[str, list[str]] = Field(description="各测点对应的特征值字段")
    point_results: list[TrendPointAnalysisResult] = Field(description="每个测点各自的趋势分析结果")


def _round_float(value: float | None, digits: int = 6) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _safe_mean(values: list[float]) -> float | None:
    if not values:
        return None
    return float(statistics.fmean(values))


def _safe_std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    return float(statistics.pstdev(values))


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


def _normalize_component_features_input(
    value: dict[str, list[str]] | str | None,
) -> dict[str, list[str]]:
    if value is None:
        return {}

    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return {}
        try:
            loaded = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("component_features string is not valid JSON") from exc
        value = loaded

    if not isinstance(value, dict):
        raise ValueError("component_features must be a dictionary or a JSON string of a dictionary")

    normalized: dict[str, list[str]] = {}
    for raw_component_id, raw_features in value.items():
        component_id = str(raw_component_id).strip()
        if not component_id or not isinstance(raw_features, list):
            continue
        cleaned_features: list[str] = []
        seen: set[str] = set()
        for raw_feature in raw_features:
            feature = str(raw_feature).strip()
            if feature and feature not in seen:
                seen.add(feature)
                cleaned_features.append(feature)
        if cleaned_features:
            normalized[component_id] = cleaned_features
    return normalized


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


def _rolling_mean_abs(values: list[float], window: int) -> list[float]:
    if not values:
        return []
    if window <= 1:
        return [abs(v) for v in values]

    n = len(values)
    half = window // 2
    result: list[float] = []
    for i in range(n):
        left = max(0, i - half)
        right = min(n, i + half + 1)
        sub = values[left:right]
        result.append(float(statistics.fmean(abs(v) for v in sub)))
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


def _estimate_base_window(n: int) -> int:
    if n <= 12:
        return 3
    if n <= 48:
        return 5
    if n <= 144:
        return 7
    return max(9, min(31, n // 20 * 2 + 1))


def _extract_trend_component(values: list[float]) -> tuple[list[float], int]:
    """
    用双重移动平均提取趋势项，优先保证“看上涨段”时能忽略局部波动。
    """
    if not values:
        return [], 1

    n = len(values)
    window = _estimate_base_window(n)
    first = _moving_average(values, window)
    second = _moving_average(first, window)
    return second, window


def _calc_trend_slope_values(times: list[str], trend_values: list[float], window: int) -> list[float]:
    if not trend_values:
        return []

    n = len(trend_values)
    if n < 2:
        return [0.0] * n

    slope_window = max(3, min(max(3, window), n if n % 2 == 1 else n - 1))
    half = slope_window // 2
    slopes: list[float] = []

    for i in range(n):
        left = max(0, i - half)
        right = min(n, i + half + 1)

        xs: list[float] = []
        ys: list[float] = []
        for j in range(left, right):
            ts_i = _parse_time_ms(times[j])
            if ts_i is None:
                continue
            xs.append(float(ts_i) / 1000.0)
            ys.append(trend_values[j])

        slope = _calc_slope_from_xy(xs, ys)
        slopes.append(float(slope or 0.0))

    return slopes


def _merge_boolean_segments(
    flags: list[bool],
    max_gap: int,
    min_len: int,
) -> list[tuple[int, int]]:
    """
    先允许短缺口，再抽取连续区间。
    返回 (start_idx, end_idx)，end_idx 为闭区间。
    """
    n = len(flags)
    if n == 0:
        return []

    merged = flags[:]

    # 填补短缺口
    i = 0
    while i < n:
        if merged[i]:
            i += 1
            continue
        gap_start = i
        while i < n and not merged[i]:
            i += 1
        gap_end = i - 1

        left_true = gap_start - 1 >= 0 and merged[gap_start - 1]
        right_true = i < n and merged[i]
        gap_len = gap_end - gap_start + 1

        if left_true and right_true and gap_len <= max_gap:
            for k in range(gap_start, gap_end + 1):
                merged[k] = True

    # 抽取连续 True 区间
    segments: list[tuple[int, int]] = []
    i = 0
    while i < n:
        if not merged[i]:
            i += 1
            continue
        start = i
        while i < n and merged[i]:
            i += 1
        end = i - 1
        if end - start + 1 >= min_len:
            segments.append((start, end))

    return segments


def _detect_rising_periods(
    times: list[str],
    values: list[float],
    trend_values: list[float],
    trend_slope_values: list[float],
) -> list[RisingPeriod]:
    if len(values) < 6 or len(trend_values) != len(values):
        return []

    n = len(values)
    baseline = abs(_safe_mean(trend_values) or 0.0)
    trend_range = (max(trend_values) - min(trend_values)) if trend_values else 0.0
    slope_abs_mean = _safe_mean([abs(v) for v in trend_slope_values]) or 0.0

    slope_threshold = max(
        slope_abs_mean * 0.8,
        trend_range / max(n, 1) * 0.15,
        max(baseline, 1.0) * 1e-5,
    )

    diff_flags: list[bool] = []
    for i in range(n):
        if i == 0:
            diff_flags.append(False)
            continue
        # 同时要求趋势项本身在涨，且局部斜率为正
        rise_diff = trend_values[i] - trend_values[i - 1]
        diff_flags.append(rise_diff > 0 and trend_slope_values[i] > slope_threshold)

    min_len = max(3, n // 20)
    max_gap = max(1, min_len // 3)
    candidate_segments = _merge_boolean_segments(diff_flags, max_gap=max_gap, min_len=min_len)

    periods: list[RisingPeriod] = []
    global_std = _safe_std(values)
    amplitude_threshold = max(global_std * 0.5, trend_range * 0.05, max(baseline, 1.0) * 0.01)

    for start, end in candidate_segments:
        if end <= start:
            continue

        rise_amplitude = trend_values[end] - trend_values[start]
        if rise_amplitude < amplitude_threshold:
            continue

        start_ts = _parse_time_ms(times[start])
        end_ts = _parse_time_ms(times[end])
        if start_ts is None or end_ts is None or end_ts <= start_ts:
            continue

        duration_sec = (end_ts - start_ts) / 1000.0
        rise_rate = rise_amplitude / duration_sec if duration_sec > 0 else None
        relative_rise = rise_amplitude / max(abs(trend_values[start]), 1e-6)

        slope_strength = (_safe_mean(trend_slope_values[start:end + 1]) or 0.0) / max(slope_threshold, 1e-9)
        amp_strength = rise_amplitude / max(amplitude_threshold, 1e-9)
        confidence = min(1.0, max(0.0, 0.35 * min(slope_strength, 3.0) + 0.35 * min(amp_strength, 3.0) + 0.3))

        periods.append(
            RisingPeriod(
                start_time_ms=times[start],
                end_time_ms=times[end],
                start_index=start,
                end_index=end,
                point_count=end - start + 1,
                rise_amplitude=_round_float(rise_amplitude, 6),
                rise_rate=_round_float(rise_rate, 9),
                relative_rise=_round_float(relative_rise, 6),
                confidence=_round_float(confidence, 6),
                summary=(
                    f"平滑趋势持续上涨，累计上涨 {_round_float(rise_amplitude, 3)}，"
                    f"相对涨幅 {_round_float(relative_rise * 100 if relative_rise is not None else None, 2)}%"
                ),
            )
        )

    return periods[:12]


def _detect_high_volatility_periods(
    times: list[str],
    residual_values: list[float],
) -> tuple[list[HighVolatilityPeriod], list[float]]:
    if len(residual_values) < 6:
        return [], [0.0 for _ in residual_values]

    n = len(residual_values)
    # 比旧版本更敏感：缩短窗口，避免长平台把剧烈抖动“平均掉”
    window = max(5, min(15, _estimate_base_window(n)))
    rolling_std = _rolling_std(residual_values, window)
    rolling_mean_abs = _rolling_mean_abs(residual_values, window)

    point_abs = [abs(v) for v in residual_values]
    point_mad = _mad(residual_values) or 0.0
    diff_values = [0.0]
    for i in range(1, n):
        diff_values.append(abs(residual_values[i] - residual_values[i - 1]))
    rolling_jump = _rolling_mean_abs(diff_values, max(3, window // 2 * 2 - 1))

    vol_center = _median(rolling_std) or 0.0
    vol_spread = _mad(rolling_std) or _safe_std(rolling_std) or 0.0
    amp_center = _median(rolling_mean_abs) or 0.0
    amp_spread = _mad(rolling_mean_abs) or _safe_std(rolling_mean_abs) or 0.0
    jump_center = _median(rolling_jump) or 0.0
    jump_spread = _mad(rolling_jump) or _safe_std(rolling_jump) or 0.0

    # 阈值从“取最大”改为更温和的稳健统计阈值
    std_threshold = max(vol_center + 1.2 * vol_spread, point_mad * 1.35, 1e-9)
    mean_abs_threshold = max(amp_center + 1.0 * amp_spread, point_mad * 1.1, 1e-9)
    jump_threshold = max(jump_center + 1.0 * jump_spread, point_mad * 0.9, 1e-9)

    volatility_scores: list[float] = []
    flags: list[bool] = []
    for i in range(n):
        std_score = rolling_std[i] / std_threshold if std_threshold > 0 else 0.0
        amp_score = rolling_mean_abs[i] / mean_abs_threshold if mean_abs_threshold > 0 else 0.0
        jump_score = rolling_jump[i] / jump_threshold if jump_threshold > 0 else 0.0

        # 以滚动方差为主，同时允许“高幅值 + 高频跳动”把区间顶出来
        score = 0.55 * std_score + 0.25 * amp_score + 0.20 * jump_score
        volatility_scores.append(score)

        is_high = (
            std_score >= 1.0 or
            (amp_score >= 1.0 and jump_score >= 0.85) or
            score >= 1.0
        )
        flags.append(is_high)

    min_len = max(2, n // 36)
    max_gap = max(1, min_len)
    candidate_segments = _merge_boolean_segments(flags, max_gap=max_gap, min_len=min_len)

    periods: list[HighVolatilityPeriod] = []
    for start, end in candidate_segments:
        sub_res = residual_values[start:end + 1]
        sub_std = rolling_std[start:end + 1]
        sub_amp = rolling_mean_abs[start:end + 1]
        sub_jump = rolling_jump[start:end + 1]
        sub_scores = volatility_scores[start:end + 1]
        if not sub_res or not sub_std or not sub_scores:
            continue

        peak_score = max(sub_scores)
        mean_score = (_safe_mean(sub_scores) or 0.0)
        mean_abs_residual = _safe_mean([abs(v) for v in sub_res])
        residual_std = _safe_std(sub_res)

        # 再做一次结果过滤，避免非常边缘的小噪声段被误报
        if peak_score < 1.05 and mean_score < 0.95:
            continue

        confidence = min(
            1.0,
            max(
                0.0,
                0.40 * min(peak_score / 1.8, 1.0) +
                0.35 * min(mean_score / 1.3, 1.0) +
                0.15 * min((max(sub_jump) / max(jump_threshold, 1e-9)) / 1.5, 1.0) +
                0.10
            ),
        )

        periods.append(
            HighVolatilityPeriod(
                start_time_ms=times[start],
                end_time_ms=times[end],
                start_index=start,
                end_index=end,
                point_count=end - start + 1,
                mean_abs_residual=_round_float(mean_abs_residual, 6),
                residual_std=_round_float(residual_std, 6),
                peak_volatility_score=_round_float(peak_score, 6),
                mean_volatility_score=_round_float(mean_score, 6),
                confidence=_round_float(confidence, 6),
                summary=(
                    f"去趋势后该时段波动剧烈，综合波动得分峰值为阈值的 "
                    f"{_round_float(peak_score, 2)} 倍，均值为 {_round_float(mean_score, 2)} 倍"
                ),
            )
        )

    return periods[:12], [_round_float(v, 6) or 0.0 for v in volatility_scores]


def _build_narrative_summary(
    feature: str,
    rising_periods: list[RisingPeriod],
    high_volatility_periods: list[HighVolatilityPeriod],
    current: float | None,
    mean_v: float | None,
) -> str:
    if not rising_periods and not high_volatility_periods:
        return f"{feature} 整体未识别到明显持续上涨段，也未识别到明显剧烈波动段"

    parts: list[str] = []
    if current is not None and mean_v is not None:
        parts.append(f"{feature} 当前值 {current}，均值 {mean_v}")

    if rising_periods:
        top_rise = max(
            rising_periods,
            key=lambda x: (x.rise_amplitude or 0.0, x.point_count),
        )
        parts.append(
            f"识别到 {len(rising_periods)} 段持续上涨区间，"
            f"其中最显著一段为 {top_rise.start_time_ms} 至 {top_rise.end_time_ms}，"
            f"累计上涨 {top_rise.rise_amplitude}"
        )

    if high_volatility_periods:
        top_vol = max(
            high_volatility_periods,
            key=lambda x: (x.peak_volatility_score or 0.0, x.point_count),
        )
        parts.append(
            f"识别到 {len(high_volatility_periods)} 段去趋势后剧烈波动区间，"
            f"其中最显著一段为 {top_vol.start_time_ms} 至 {top_vol.end_time_ms}，"
            f"峰值波动强度 {top_vol.peak_volatility_score}"
        )

    return "；".join(parts)


def _build_summary_for_feature(feature: str, detail: TrendFeatureDetail) -> list[str]:
    if detail.current is None:
        return [f"{feature} 无有效数据"]

    lines: list[str] = []

    if detail.narrative_summary:
        lines.append(detail.narrative_summary)

    if detail.rising_periods:
        for seg in detail.rising_periods[:2]:
            lines.append(
                f"{feature} 在 {seg.start_time_ms} 至 {seg.end_time_ms} 为持续上涨区间，"
                f"累计上涨 {seg.rise_amplitude}"
            )
    else:
        lines.append(f"{feature} 未识别到明显持续上涨区间")

    if detail.high_volatility_periods:
        for seg in detail.high_volatility_periods[:2]:
            lines.append(
                f"{feature} 在 {seg.start_time_ms} 至 {seg.end_time_ms} 为去趋势后剧烈波动区间，"
                f"峰值波动强度 {seg.peak_volatility_score}"
            )
    else:
        lines.append(f"{feature} 未识别到明显去趋势后剧烈波动区间")

    return lines[:6]


def _build_notable_points_for_feature(
    feature: str,
    series: list[tuple[str, float]],
    detail: TrendFeatureDetail,
) -> list[str]:
    if not series:
        return []

    values = [v for _, v in series]
    min_idx = values.index(min(values))
    max_idx = values.index(max(values))

    notable = [
        f"{feature} 在 {series[min_idx][0]} 出现区间最低值 {round(series[min_idx][1], 3)}",
        f"{feature} 在 {series[max_idx][0]} 出现区间最高值 {round(series[max_idx][1], 3)}",
    ]

    for seg in detail.rising_periods[:4]:
        notable.append(
            f"{feature} 在 {seg.start_time_ms} 至 {seg.end_time_ms} 出现持续上涨，累计上涨 {seg.rise_amplitude}"
        )

    for seg in detail.high_volatility_periods[:4]:
        notable.append(
            f"{feature} 在 {seg.start_time_ms} 至 {seg.end_time_ms} 出现去趋势后剧烈波动，峰值强度 {seg.peak_volatility_score}"
        )

    deduped: list[str] = []
    seen: set[str] = set()
    for item in notable:
        if item not in seen:
            seen.add(item)
            deduped.append(item)

    return deduped[:12]


def _merge_feature_summaries(feature_summaries: dict[str, list[str]]) -> list[str]:
    merged: list[str] = []
    for _, lines in feature_summaries.items():
        merged.extend(lines[:4])
    return merged[:24]


def _merge_feature_notable_points(feature_notables: dict[str, list[str]]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for _, lines in feature_notables.items():
        for line in lines:
            if line not in seen:
                seen.add(line)
                merged.append(line)
    return merged[:24]


def _build_feature_detail(
    point_data: list[dict[str, Any]],
    series: list[tuple[str, float]],
) -> TrendFeatureDetail:
    values = [v for _, v in series]
    times = [ts for ts, _ in series]

    if not values:
        return TrendFeatureDetail()

    current = values[-1]
    mean_v = _safe_mean(values)
    min_v = min(values)
    max_v = max(values)
    std_v = _safe_std(values)
    range_v = max_v - min_v
    mad_v = _mad(values)

    trend_values, trend_window = _extract_trend_component(values)
    trend_slope_values = _calc_trend_slope_values(times, trend_values, trend_window)
    residual_values = [v - t for v, t in zip(values, trend_values)]

    rising_periods = _detect_rising_periods(
        times=times,
        values=values,
        trend_values=trend_values,
        trend_slope_values=trend_slope_values,
    )

    high_volatility_periods, residual_volatility_values = _detect_high_volatility_periods(
        times=times,
        residual_values=residual_values,
    )

    max_rise_amplitude = None
    max_rise_rate = None
    if rising_periods:
        max_rise_amplitude = max((x.rise_amplitude or 0.0) for x in rising_periods)
        max_rise_rate = max((x.rise_rate or 0.0) for x in rising_periods)

    max_volatility_score = None
    if high_volatility_periods:
        max_volatility_score = max((x.peak_volatility_score or 0.0) for x in high_volatility_periods)

    narrative_summary = _build_narrative_summary(
        feature=series and "feature" or "",
        rising_periods=rising_periods,
        high_volatility_periods=high_volatility_periods,
        current=_round_float(current, 6),
        mean_v=_round_float(mean_v, 6),
    )

    return TrendFeatureDetail(
        current=_round_float(current, 6),
        mean=_round_float(mean_v, 6),
        min=_round_float(min_v, 6),
        max=_round_float(max_v, 6),
        std=_round_float(std_v, 6),
        range=_round_float(range_v, 6),
        mad=_round_float(mad_v, 6),
        trend_method="double_moving_average",
        trend_window=trend_window,
        trend_values=[_round_float(v, 6) or 0.0 for v in trend_values],
        trend_slope_values=[_round_float(v, 9) or 0.0 for v in trend_slope_values],
        rising_periods=rising_periods,
        rise_period_count=len(rising_periods),
        total_rise_points=sum(x.point_count for x in rising_periods),
        max_rise_amplitude=_round_float(max_rise_amplitude, 6),
        max_rise_rate=_round_float(max_rise_rate, 9),
        residual_values=[_round_float(v, 6) or 0.0 for v in residual_values],
        residual_volatility_values=residual_volatility_values,
        high_volatility_periods=high_volatility_periods,
        high_volatility_period_count=len(high_volatility_periods),
        total_high_volatility_points=sum(x.point_count for x in high_volatility_periods),
        max_volatility_score=_round_float(max_volatility_score, 6),
        narrative_summary=narrative_summary,
    )


async def _extract_trend_features_impl(
    component_features: dict[str, list[str]] | str | None = None,
    start: str | None = None,
    end: str | None = None,
    trend_data_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    提取趋势特征。

    输入格式一：直接传入原始趋势数据
    {
      "trend_data_payload": {
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
    }

    输入格式二：只提供查询参数，工具内部按需调用 get_trend_data_tool
    {
      "component_features": {
        "component_id_1": ["pp_value", "rms"],
        "component_id_2": ["value"]
      },
      "start": "...",
      "end": "..."
    }

    注意：
    - `component_features` 必须优先传 JSON 对象，不要传 JSON 字符串
    - 错误示例：{"component_features": "{\"id\": [\"pp_value\"]}", "start": "...", "end": "..."}
    - 正确示例：{"component_features": {"id": ["pp_value"]}, "start": "...", "end": "..."}
    - 若上游模型仍误传 JSON 字符串，工具会尝试自动解析兼容

    输出包含两类核心结果：
    1. 平滑后的持续上涨时间段
    2. 去趋势后的剧烈波动时间段
    """
    if trend_data_payload is None:
        trend_data_payload = {}

    if "data" not in trend_data_payload:
        payload_component_features = _normalize_component_features_input(
            component_features if component_features is not None else trend_data_payload.get("component_features")
        )
        payload_start = str(start or trend_data_payload.get("start_time") or trend_data_payload.get("start") or "")
        payload_end = str(end or trend_data_payload.get("end_time") or trend_data_payload.get("end") or "")
        if not payload_component_features:
            raise ValueError("component_features is required when trend data is not provided")
        if not payload_start:
            raise ValueError("start is required when trend data is not provided")
        if not payload_end:
            raise ValueError("end is required when trend data is not provided")
        trend_data_payload = await _get_trend_data_impl(payload_component_features, payload_start, payload_end)

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

            # 修正 narrative 里的 feature 名
            detail.narrative_summary = _build_narrative_summary(
                feature=feature,
                rising_periods=detail.rising_periods,
                high_volatility_periods=detail.high_volatility_periods,
                current=detail.current,
                mean_v=detail.mean,
            )

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


@function_tool(strict_mode=False)
async def extract_trend_features_tool(
    component_features: dict[str, list[str]] | str | None = None,
    start: str | None = None,
    end: str | None = None,
    trend_data_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return await _extract_trend_features_impl(
        component_features=component_features,
        start=start,
        end=end,
        trend_data_payload=trend_data_payload,
    )


async def main() -> None:
    """
    用法:
    python extract_trend_features_tool.py '{"trend_data_payload":{"component_ids":[...],"start_time":"...","end_time":"...","component_features":{...},"data":{...}}}'
    """
    if len(sys.argv) < 2:
        raise SystemExit("用法: python extract_trend_features_tool.py '<payload_json>'")

    payload = json.loads(sys.argv[1])
    if not isinstance(payload, dict):
        raise SystemExit("payload_json 必须是 JSON 对象")
    result = await extract_trend_features_tool(**payload)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
