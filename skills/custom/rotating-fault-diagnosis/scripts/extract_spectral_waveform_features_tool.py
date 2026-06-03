import asyncio
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any

# 添加 features-tool 路径以导入 ins/agents 模块
_SKILL_ROOT = Path(__file__).resolve().parent.parent
_FEATURES_TOOL_ROOT = Path("/mnt/skills/custom/features-tool")
for _p in [str(_SKILL_ROOT), str(_FEATURES_TOOL_ROOT)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agents import function_tool
from pydantic import BaseModel, Field
from tools.get_waveform_data_tool import _get_waveform_data_impl


class WaveformFeatureDetail(BaseModel):
    # 时域特征
    rms: float | None = Field(default=None, description="波形均方根值")
    std: float | None = Field(default=None, description="波形标准差")
    peak: float | None = Field(default=None, description="波形绝对峰值")
    peak_to_peak: float | None = Field(default=None, description="波形峰峰值")

    # 时域无量纲指标
    crest_factor: float | None = Field(default=None, description="峰值因子")
    impulse_factor: float | None = Field(default=None, description="脉冲因子")
    margin_factor: float | None = Field(default=None, description="裕度因子")
    waveform_factor: float | None = Field(default=None, description="波形因子")
    kurtosis_factor: float | None = Field(default=None, description="峭度指标")
    skewness_factor: float | None = Field(default=None, description="偏度指标")

    # 频域特征
    dominant_frequency_hz: float | None = Field(default=None, description="频谱主峰频率，单位 Hz")
    dominant_amplitude: float | None = Field(default=None, description="频谱主峰幅值")
    total_spectral_energy: float | None = Field(default=None, description="频谱总能量")

    running_frequency_hz: float | None = Field(default=None, description="运行频率，单位 Hz")
    amp_1x: float | None = Field(default=None, description="1X 幅值")
    amp_2x: float | None = Field(default=None, description="2X 幅值")
    amp_1x_ratio: float | None = Field(default=None, description="1X 能量占比")
    amp_2x_to_1x_ratio: float | None = Field(default=None, description="2X/1X 幅值比")

    top_peaks: list[dict[str, float | str]] = Field(
        default_factory=list,
        description="频谱主峰列表，频率同时给出 Hz 和转频倍数 X"
    )
    peaks_3_to_5um: list[dict[str, float | str]] = Field(
        default_factory=list,
        description="幅值3-5微米的频率列表和对应幅值，频率同时给出 Hz 和转频倍数 X"
    )
    peaks_over_5um: list[dict[str, float | str]] = Field(
        default_factory=list,
        description="幅值超过5微米的频率列表和对应幅值，频率同时给出 Hz 和转频倍数 X"
    )

    # 削波与不对称特征
    clipping_detected: bool = Field(default=False, description="是否存在削波")
    mean_positive_peak: float | None = Field(default=None, description="各周期正峰值均值")
    mean_negative_peak_abs: float | None = Field(default=None, description="各周期负峰值绝对值均值")
    positive_negative_peak_abs_diff: float | None = Field(default=None, description="正负峰绝对值差值")
    peak_valley_asymmetry_ratio: float | None = Field(default=None, description="峰谷不对称度")
    positive_negative_peak_ratio: float | None = Field(default=None, description="正负峰值比")

    # 毛刺特征
    glitch_ratio: float | None = Field(default=None, description="毛刺占比")
    glitch_count: int = Field(default=0, description="毛刺数量")

    #漂移特征
    drift_detected: bool = Field(default=False, description="是否存在基线漂移")
    drift_value: float | None = Field(default=None, description="波形基线漂移量")

    # 正弦拟合与周期间一致性特征
    sine_fit_score: float | None = Field(default=None, description="正弦拟合得分")
    periodicity_score: float | None = Field(default=None, description="波形周期性得分")
    cycle_repeatability_score: float | None = Field(default=None, description="周期间重复性得分")
    amplitude_stability_across_cycles: float | None = Field(default=None, description="周期间幅值稳定性得分")


class SpectralWaveformAnalysisResult(BaseModel):
    component_id: str = Field(description="测点 ID")
    time_ms: str = Field(description="查询时间点，毫秒时间戳")
    summary: list[str] = Field(description="波形和频谱的整体概括")
    spectral_findings: list[str] = Field(description="频谱特征")
    waveform_findings: list[str] = Field(description="时域波形特征")
    suspected_faults: list[str] = Field(description="可能的故障类型或机理")
    feature_details: WaveformFeatureDetail = Field(description="提取出的结构化特征")


# =========================
# 基础统计函数
# =========================

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


def _safe_rms(values: list[float]) -> float | None:
    if not values:
        return None
    return math.sqrt(sum(v * v for v in values) / len(values))


def _time_domain_dimensionless_features(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {
            "crest_factor": None,
            "impulse_factor": None,
            "margin_factor": None,
            "waveform_factor": None,
            "kurtosis_factor": None,
            "skewness_factor": None,
        }

    rms_v = _safe_rms(values)
    peak_v = max((abs(v) for v in values), default=None)
    mean_abs = _safe_mean([abs(v) for v in values])
    mean_sqrt_abs = _safe_mean([math.sqrt(abs(v)) for v in values])
    mean_v = _safe_mean(values) or 0.0
    centered = [v - mean_v for v in values]
    std_v = _safe_std(values)

    crest_factor = None
    if peak_v is not None and rms_v not in (None, 0.0):
        crest_factor = peak_v / rms_v

    impulse_factor = None
    if peak_v is not None and mean_abs not in (None, 0.0):
        impulse_factor = peak_v / mean_abs

    margin_factor = None
    if peak_v is not None and mean_sqrt_abs not in (None, 0.0):
        denom = mean_sqrt_abs ** 2
        if denom > 1e-12:
            margin_factor = peak_v / denom

    waveform_factor = None
    if rms_v not in (None, 0.0) and mean_abs not in (None, 0.0):
        waveform_factor = rms_v / mean_abs

    kurtosis_factor = None
    skewness_factor = None
    if len(values) >= 2 and std_v > 1e-12:
        m3 = sum(v ** 3 for v in centered) / len(centered)
        m4 = sum(v ** 4 for v in centered) / len(centered)
        skewness_factor = m3 / (std_v ** 3)
        kurtosis_factor = m4 / (std_v ** 4)

    return {
        "crest_factor": crest_factor,
        "impulse_factor": impulse_factor,
        "margin_factor": margin_factor,
        "waveform_factor": waveform_factor,
        "kurtosis_factor": kurtosis_factor,
        "skewness_factor": skewness_factor,
    }


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


def _periodicity_score(values: list[float]) -> float | None:
    if len(values) < 8:
        return None
    mean_v = _safe_mean(values) or 0.0
    centered = [v - mean_v for v in values]
    denom = sum(v * v for v in centered)
    if denom <= 1e-12:
        return None

    max_corr = 0.0
    max_lag = min(len(values) // 2, 200)
    for lag in range(1, max_lag):
        num = sum(centered[i] * centered[i - lag] for i in range(lag, len(centered)))
        corr = num / denom
        if corr > max_corr:
            max_corr = corr
    return max_corr


# =========================
# 频域函数
# =========================

def _hz_to_order(freq_hz: float, running_frequency_hz: float | None) -> float | None:
    if running_frequency_hz is None or running_frequency_hz <= 0:
        return None
    return freq_hz / running_frequency_hz


def _format_order_label(freq_hz: float, running_frequency_hz: float | None) -> str:
    order = _hz_to_order(freq_hz, running_frequency_hz)
    if order is None:
        return "NA"
    return f"{round(order, 2)}X"


def _find_local_peaks(spec_x: list[float], spec_y: list[float]) -> list[tuple[float, float]]:
    if len(spec_x) != len(spec_y) or len(spec_x) < 3:
        return []

    peaks: list[tuple[float, float]] = []
    for i in range(1, len(spec_y) - 1):
        if spec_y[i] >= spec_y[i - 1] and spec_y[i] >= spec_y[i + 1]:
            peaks.append((float(spec_x[i]), float(spec_y[i])))
    return peaks


def _build_peak_item(freq_hz: float, amp: float, running_frequency_hz: float | None) -> dict[str, float | str]:
    return {
        "frequency_hz": round(freq_hz, 6),
        "order": _format_order_label(freq_hz, running_frequency_hz),
        "amplitude": round(amp, 6),
    }


def _find_top_peaks_in_order(
    spec_x: list[float],
    spec_y: list[float],
    running_frequency_hz: float | None,
    top_n: int = 5,
) -> list[dict[str, float | str]]:
    peaks = _find_local_peaks(spec_x, spec_y)
    peaks.sort(key=lambda item: item[1], reverse=True)
    return [_build_peak_item(freq, amp, running_frequency_hz) for freq, amp in peaks[:top_n]]


# def _find_peaks_by_amplitude_range(
#     spec_x: list[float],
#     spec_y: list[float],
#     running_frequency_hz: float | None,
#     min_amp: float,
#     max_amp: float | None = None,
#     top_n: int = 50,
# ) -> list[dict[str, float | str]]:
#     peaks = _find_local_peaks(spec_x, spec_y)
#     filtered: list[tuple[float, float]] = []
#     for freq, amp in peaks:
#         if amp < min_amp:
#             continue
#         if max_amp is not None and amp > max_amp:
#             continue
#         filtered.append((freq, amp))

#     filtered.sort(key=lambda item: (item[1], item[0]), reverse=True)
#     return [_build_peak_item(freq, amp, running_frequency_hz) for freq, amp in filtered[:top_n]]

def _find_peaks_by_amplitude_range(
    spec_x: list[float],
    spec_y: list[float],
    running_frequency_hz: float | None,
    min_amp: float,
    max_amp: float | None = None,
    top_n: int = 50,
) -> list[dict[str, float | str]]:
    # 原代码：peaks = _find_local_peaks(spec_x, spec_y)
    # 改为：遍历所有点，筛选幅值在区间内的点
    filtered = []
    for i in range(len(spec_x)):
        amp = spec_y[i]
        if amp < min_amp:
            continue
        if max_amp is not None and amp > max_amp:
            continue
        filtered.append((spec_x[i], amp))
    
    # 按幅值降序，同幅值按频率降序
    filtered.sort(key=lambda item: (item[1], item[0]), reverse=True)
    # 取前 top_n 个
    return [_build_peak_item(freq, amp, running_frequency_hz) for freq, amp in filtered[:top_n]]

def _find_nearest_amp(
    spec_x: list[float],
    spec_y: list[float],
    target_freq: float,
    tolerance_ratio: float = 0.03,
) -> float | None:
    if len(spec_x) != len(spec_y) or not spec_x or target_freq <= 0:
        return None

    tolerance = max(target_freq * tolerance_ratio, 0.5)
    candidates = [(abs(x - target_freq), y) for x, y in zip(spec_x, spec_y) if abs(x - target_freq) <= tolerance]
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return float(candidates[0][1])


# =========================
# 波形预处理与事件检测
# =========================

def _moving_average(values: list[float], window: int) -> list[float]:
    if not values:
        return []
    if window <= 1:
        return [float(v) for v in values]

    half = window // 2
    result: list[float] = []
    for i in range(len(values)):
        left = max(0, i - half)
        right = min(len(values), i + half + 1)
        result.append(float(statistics.fmean(values[left:right])))
    return result


def _diff(values: list[float]) -> list[float]:
    if len(values) < 2:
        return []
    return [values[i] - values[i - 1] for i in range(1, len(values))]


def _robust_scale(values: list[float]) -> float:
    mad_v = _mad(values)
    if mad_v is not None and mad_v > 1e-12:
        return 1.4826 * mad_v
    std_v = _safe_std(values)
    if std_v > 1e-12:
        return std_v
    rms_v = _safe_rms(values)
    if rms_v not in (None, 0.0):
        return float(rms_v)
    return 1.0


def _local_peaks(values: list[float], threshold: float, min_distance: int = 1) -> list[int]:
    if len(values) < 3:
        return []

    peaks: list[int] = []
    last_idx = -10**9
    for i in range(1, len(values) - 1):
        if values[i] < threshold:
            continue
        if values[i] >= values[i - 1] and values[i] >= values[i + 1]:
            if i - last_idx < min_distance:
                if peaks and values[i] > values[peaks[-1]]:
                    peaks[-1] = i
                    last_idx = i
                continue
            peaks.append(i)
            last_idx = i
    return peaks


def _event_width(abs_signal: list[float], peak_idx: int, threshold: float) -> int:
    left = peak_idx
    while left > 0 and abs_signal[left - 1] >= threshold:
        left -= 1
    right = peak_idx
    while right < len(abs_signal) - 1 and abs_signal[right + 1] >= threshold:
        right += 1
    return right - left + 1


def _estimate_cycle_signal_quality(
    wave_y: list[float],
    sample_rate: float | None,
    running_frequency_hz: float | None,
) -> dict[str, float | None]:
    if not wave_y or sample_rate is None or sample_rate <= 0 or running_frequency_hz is None or running_frequency_hz <= 0:
        return {
            "sine_fit_score": None,
            "cycle_repeatability_score": None,
            "amplitude_stability_across_cycles": None,
        }

    samples_per_cycle = sample_rate / running_frequency_hz
    if samples_per_cycle < 8 or len(wave_y) < samples_per_cycle * 2:
        return {
            "sine_fit_score": None,
            "cycle_repeatability_score": None,
            "amplitude_stability_across_cycles": None,
        }

    cycle_len = max(8, int(round(samples_per_cycle)))
    cycle_count = len(wave_y) // cycle_len
    if cycle_count < 2:
        return {
            "sine_fit_score": None,
            "cycle_repeatability_score": None,
            "amplitude_stability_across_cycles": None,
        }

    trimmed = wave_y[: cycle_count * cycle_len]
    cycles = [trimmed[i * cycle_len : (i + 1) * cycle_len] for i in range(cycle_count)]
    cycle_amplitudes = [(max(c) - min(c)) / 2.0 for c in cycles if c]

    template = [float(statistics.fmean(c[i] for c in cycles)) for i in range(cycle_len)]
    template_mean = _safe_mean(template) or 0.0
    centered_template = [v - template_mean for v in template]
    template_norm = math.sqrt(sum(v * v for v in centered_template))

    repeat_scores: list[float] = []
    for cycle in cycles:
        cycle_mean = _safe_mean(cycle) or 0.0
        centered_cycle = [v - cycle_mean for v in cycle]
        cycle_norm = math.sqrt(sum(v * v for v in centered_cycle))
        if template_norm <= 1e-12 or cycle_norm <= 1e-12:
            continue
        corr = sum(a * b for a, b in zip(centered_template, centered_cycle)) / (template_norm * cycle_norm)
        repeat_scores.append(max(-1.0, min(1.0, corr)))

    cycle_repeatability = None
    if repeat_scores:
        cycle_repeatability = sum((score + 1.0) / 2.0 for score in repeat_scores) / len(repeat_scores)

    amplitude_stability = None
    if len(cycle_amplitudes) >= 2:
        amp_mean = _safe_mean(cycle_amplitudes)
        amp_std = _safe_std(cycle_amplitudes)
        if amp_mean not in (None, 0.0):
            amplitude_stability = 1.0 / (1.0 + (amp_std / amp_mean))

    sine_fit_score = None
    rms_v = _safe_rms(trimmed)
    if rms_v not in (None, 0.0):
        t_values = [i / sample_rate for i in range(len(trimmed))]
        cos_term = [math.cos(2.0 * math.pi * running_frequency_hz * t) for t in t_values]
        sin_term = [math.sin(2.0 * math.pi * running_frequency_hz * t) for t in t_values]

        denom_cos = sum(v * v for v in cos_term)
        denom_sin = sum(v * v for v in sin_term)
        if denom_cos > 1e-12 and denom_sin > 1e-12:
            a = sum(y * c for y, c in zip(trimmed, cos_term)) / denom_cos
            b = sum(y * s for y, s in zip(trimmed, sin_term)) / denom_sin
            fitted = [a * c + b * s for c, s in zip(cos_term, sin_term)]
            residual = [y - f for y, f in zip(trimmed, fitted)]
            residual_rms = _safe_rms(residual)
            if residual_rms is not None:
                sine_fit_score = max(0.0, min(1.0, 1.0 - residual_rms / rms_v))

    return {
        "sine_fit_score": sine_fit_score,
        "cycle_repeatability_score": cycle_repeatability,
        "amplitude_stability_across_cycles": amplitude_stability,
    }


def _build_time_domain_enhanced_features(
    wave_y: list[float],
    sample_rate: float | None,
    running_frequency_hz: float | None,
) -> dict[str, float | int | bool | None]:
    if len(wave_y) < 8:
        return {
            "clipping_detected": False,
            "mean_positive_peak": None,
            "mean_negative_peak_abs": None,
            "positive_negative_peak_abs_diff": None,
            "peak_valley_asymmetry_ratio": None,
            "positive_negative_peak_ratio": None,
            "glitch_ratio": None,
            "glitch_count": 0,
        }

    mean_v = _safe_mean(wave_y) or 0.0
    centered = [v - mean_v for v in wave_y]

    # ===== 基于周期的正负峰统计 =====
    mean_positive_peak = None
    mean_negative_peak_abs = None
    positive_negative_peak_abs_diff = None
    peak_valley_asymmetry_ratio = None
    positive_negative_peak_ratio = None
    clipping_detected = False

    if sample_rate is not None and sample_rate > 0 and running_frequency_hz is not None and running_frequency_hz > 0:
        samples_per_cycle = sample_rate / running_frequency_hz
        cycle_len = int(round(samples_per_cycle))

        if cycle_len >= 8 and len(centered) >= cycle_len * 2:
            cycle_count = len(centered) // cycle_len
            trimmed = centered[: cycle_count * cycle_len]
            cycles = [trimmed[i * cycle_len : (i + 1) * cycle_len] for i in range(cycle_count)]

            positive_peaks = [max(cycle) for cycle in cycles if cycle]
            negative_peaks_abs = [abs(min(cycle)) for cycle in cycles if cycle]

            mean_positive_peak = _safe_mean(positive_peaks)
            mean_negative_peak_abs = _safe_mean(negative_peaks_abs)

            if (
                mean_positive_peak not in (None, 0.0)
                and mean_negative_peak_abs not in (None, 0.0)
            ):
                positive_negative_peak_abs_diff = abs(mean_positive_peak - mean_negative_peak_abs)

                denom = max(mean_positive_peak, mean_negative_peak_abs)
                if denom > 1e-12:
                    peak_valley_asymmetry_ratio = positive_negative_peak_abs_diff / denom

                if mean_negative_peak_abs > 1e-12:
                    positive_negative_peak_ratio = mean_positive_peak / mean_negative_peak_abs

                # 削波判定逻辑：基于周期正负峰长期不对称
                # 阈值可按现场数据再调，建议先用 0.2
                clipping_detected = bool(
                    peak_valley_asymmetry_ratio is not None
                    and peak_valley_asymmetry_ratio >= 0.2
                )
    else:
        # 没有转频/采样率时，退化为全波形正负峰
        positive_peak = max(centered) if centered else None
        negative_peak_abs = abs(min(centered)) if centered else None

        mean_positive_peak = positive_peak
        mean_negative_peak_abs = negative_peak_abs

        if (
            mean_positive_peak not in (None, 0.0)
            and mean_negative_peak_abs not in (None, 0.0)
        ):
            positive_negative_peak_abs_diff = abs(mean_positive_peak - mean_negative_peak_abs)

            denom = max(mean_positive_peak, mean_negative_peak_abs)
            if denom > 1e-12:
                peak_valley_asymmetry_ratio = positive_negative_peak_abs_diff / denom

            if mean_negative_peak_abs > 1e-12:
                positive_negative_peak_ratio = mean_positive_peak / mean_negative_peak_abs

            clipping_detected = bool(
                peak_valley_asymmetry_ratio is not None
                and peak_valley_asymmetry_ratio >= 0.2
            )

    # ===== 毛刺特征保留 =====
    smooth_window = max(5, min(31, len(centered) // 25 if len(centered) >= 25 else 5))
    if smooth_window % 2 == 0:
        smooth_window += 1
    smooth = _moving_average(centered, smooth_window)
    residual = [x - s for x, s in zip(centered, smooth)]
    abs_residual = [abs(v) for v in residual]

    spike_threshold = max(
        (_median(abs_residual) or 0.0) + 3.5 * (_mad(abs_residual) or 0.0),
        _percentile(abs_residual, 0.98) or 0.0,
    )
    glitch_threshold = max(
        (_median(abs_residual) or 0.0) + 2.8 * (_mad(abs_residual) or 0.0),
        _percentile(abs_residual, 0.95) or 0.0,
    )

    if sample_rate and running_frequency_hz and running_frequency_hz > 0:
        samples_per_rev = sample_rate / running_frequency_hz
        min_distance = max(1, int(samples_per_rev * 0.03))
    else:
        min_distance = max(1, len(centered) // 200)

    _ = _local_peaks(abs_residual, spike_threshold, min_distance=max(1, min_distance // 2))
    glitch_indices = _local_peaks(abs_residual, glitch_threshold, min_distance=1)

    glitch_count = 0
    glitch_points = 0
    narrow_width_limit = max(1, min(3, int((sample_rate / 2000.0)) if sample_rate else 2))
    low_glitch_threshold = max(glitch_threshold * 0.6, 1e-12)
    for idx in glitch_indices:
        width = _event_width(abs_residual, idx, low_glitch_threshold)
        if width <= narrow_width_limit:
            glitch_count += 1
            glitch_points += width
    glitch_ratio = (glitch_points / len(centered)) if centered else None

    # ===== 漂移特征 =====
    p2p = (max(centered) - min(centered)) if centered else None

    if sample_rate and running_frequency_hz and running_frequency_hz > 0:
        samples_per_cycle = sample_rate / running_frequency_hz
        drift_window = int(max(21, round(samples_per_cycle * 5)))
    else:
        drift_window = max(21, len(centered) // 20)

    if drift_window % 2 == 0:
        drift_window += 1
    drift_window = min(drift_window, len(centered) if len(centered) % 2 == 1 else len(centered) - 1)
    if drift_window < 3:
        baseline = centered[:]
    else:
        baseline = _moving_average(centered, drift_window)

    drift_value = (max(baseline) - min(baseline)) if baseline else None

    drift_detected = False
    if drift_value is not None and p2p not in (None, 0.0):
        drift_detected = (drift_value / p2p) >= 0.10

    return {
        "clipping_detected": clipping_detected,
        "mean_positive_peak": mean_positive_peak,
        "mean_negative_peak_abs": mean_negative_peak_abs,
        "positive_negative_peak_abs_diff": positive_negative_peak_abs_diff,
        "peak_valley_asymmetry_ratio": peak_valley_asymmetry_ratio,
        "positive_negative_peak_ratio": positive_negative_peak_ratio,
        "glitch_ratio": glitch_ratio,
        "glitch_count": glitch_count,
        "drift_detected": drift_detected,
        "drift_value": drift_value,
    }

# =========================
# 主特征提取
# =========================

def _extract_feature_detail(data: dict[str, Any]) -> WaveformFeatureDetail:
    wave_y = [float(v) * 1000.0 for v in (data.get("wave_y") or []) if isinstance(v, (int, float)) and math.isfinite(v)]
    spec_x = [float(v) for v in (data.get("spec_x") or []) if isinstance(v, (int, float)) and math.isfinite(v)]
    spec_y = [float(v) for v in (data.get("spec_y") or []) if isinstance(v, (int, float)) and math.isfinite(v)]

    n_spec = min(len(spec_x), len(spec_y))
    spec_x = spec_x[:n_spec]
    spec_y = spec_y[:n_spec]

    rms_v = _safe_rms(wave_y)
    std_v = _safe_std(wave_y)
    peak_v = max((abs(v) for v in wave_y), default=None)
    p2p_v = (max(wave_y) - min(wave_y)) if wave_y else None
    periodicity_v = _periodicity_score(wave_y)
    dimensionless = _time_domain_dimensionless_features(wave_y)

    dominant_frequency = None
    dominant_amplitude = None
    if spec_y:
        idx = max(range(len(spec_y)), key=lambda i: spec_y[i])
        dominant_frequency = spec_x[idx]
        dominant_amplitude = spec_y[idx]

    total_energy = sum(max(v, 0.0) for v in spec_y) if spec_y else None

    speed = data.get("speed")
    running_frequency_hz = None
    if isinstance(speed, (int, float)) and math.isfinite(speed) and speed > 0:
        running_frequency_hz = float(speed) / 60.0

    amp_1x = _find_nearest_amp(spec_x, spec_y, running_frequency_hz) if running_frequency_hz else None
    amp_2x = _find_nearest_amp(spec_x, spec_y, running_frequency_hz * 2.0) if running_frequency_hz else None

    amp_1x_ratio = None
    if amp_1x is not None and total_energy not in (None, 0.0):
        amp_1x_ratio = amp_1x / total_energy

    amp_2x_to_1x_ratio = None
    if amp_1x not in (None, 0.0) and amp_2x is not None:
        amp_2x_to_1x_ratio = amp_2x / amp_1x

    top_peaks = _find_top_peaks_in_order(spec_x, spec_y, running_frequency_hz, top_n=5)
    peaks_3_to_5um = _find_peaks_by_amplitude_range(
        spec_x,
        spec_y,
        running_frequency_hz,
        min_amp=3.0,
        max_amp=5.0,
        top_n=50,
    )
    peaks_over_5um = _find_peaks_by_amplitude_range(
        spec_x,
        spec_y,
        running_frequency_hz,
        min_amp=5.0,
        max_amp=None,
        top_n=50,
    )

    sample_rate = data.get("sample_rate")
    sample_rate_float = (
        float(sample_rate)
        if isinstance(sample_rate, (int, float)) and math.isfinite(sample_rate) and sample_rate > 0
        else None
    )
    enhanced = _build_time_domain_enhanced_features(wave_y, sample_rate_float, running_frequency_hz)
    cycle_quality = _estimate_cycle_signal_quality(wave_y, sample_rate_float, running_frequency_hz)

    return WaveformFeatureDetail(
        rms=_round_float(rms_v, 6),
        std=_round_float(std_v, 6),
        peak=_round_float(peak_v, 6),
        peak_to_peak=_round_float(p2p_v, 6),
        crest_factor=_round_float(dimensionless.get("crest_factor"), 6),
        impulse_factor=_round_float(dimensionless.get("impulse_factor"), 6),
        margin_factor=_round_float(dimensionless.get("margin_factor"), 6),
        waveform_factor=_round_float(dimensionless.get("waveform_factor"), 6),
        kurtosis_factor=_round_float(dimensionless.get("kurtosis_factor"), 6),
        skewness_factor=_round_float(dimensionless.get("skewness_factor"), 6),
        periodicity_score=_round_float(periodicity_v, 6),

        dominant_frequency_hz=_round_float(dominant_frequency, 6),
        dominant_amplitude=_round_float(dominant_amplitude, 6),
        total_spectral_energy=_round_float(total_energy, 6),

        running_frequency_hz=_round_float(running_frequency_hz, 6),
        amp_1x=_round_float(amp_1x, 6),
        amp_2x=_round_float(amp_2x, 6),
        amp_1x_ratio=_round_float(amp_1x_ratio, 6),
        amp_2x_to_1x_ratio=_round_float(amp_2x_to_1x_ratio, 6),

        top_peaks=top_peaks,
        peaks_3_to_5um=peaks_3_to_5um,
        peaks_over_5um=peaks_over_5um,

        clipping_detected=bool(enhanced.get("clipping_detected", False)),
        mean_positive_peak=_round_float(enhanced.get("mean_positive_peak"), 6),
        mean_negative_peak_abs=_round_float(enhanced.get("mean_negative_peak_abs"), 6),
        positive_negative_peak_abs_diff=_round_float(enhanced.get("positive_negative_peak_abs_diff"), 6),
        peak_valley_asymmetry_ratio=_round_float(enhanced.get("peak_valley_asymmetry_ratio"), 6),
        positive_negative_peak_ratio=_round_float(enhanced.get("positive_negative_peak_ratio"), 6),
        glitch_ratio=_round_float(enhanced.get("glitch_ratio"), 6),
        glitch_count=int(enhanced.get("glitch_count") or 0),
        drift_detected=bool(enhanced.get("drift_detected", False)),
        drift_value=_round_float(enhanced.get("drift_value"), 6),
        
        sine_fit_score=_round_float(cycle_quality.get("sine_fit_score"), 6),
        cycle_repeatability_score=_round_float(cycle_quality.get("cycle_repeatability_score"), 6),
        amplitude_stability_across_cycles=_round_float(cycle_quality.get("amplitude_stability_across_cycles"), 6),
    )


# =========================
# 文本化输出
# =========================

def _build_waveform_findings(detail: WaveformFeatureDetail) -> list[str]:
    findings: list[str] = []

    if detail.rms is not None and detail.peak_to_peak is not None:
        findings.append(f"时域波形 RMS={detail.rms}，峰峰值={detail.peak_to_peak}")

    if detail.periodicity_score is not None:
        if detail.periodicity_score >= 0.6:
            findings.append("时域波形周期性较强")
        elif detail.periodicity_score >= 0.3:
            findings.append("时域波形存在一定周期性")
        else:
            findings.append("时域波形周期性不突出")

    if detail.sine_fit_score is not None:
        if detail.sine_fit_score >= 0.75:
            findings.append("波形与标准正弦拟合度较高")
        elif detail.sine_fit_score >= 0.5:
            findings.append("波形具备一定正弦特征")

    if detail.cycle_repeatability_score is not None and detail.cycle_repeatability_score >= 0.7:
        findings.append("各周期波形重复性较好")

    if detail.amplitude_stability_across_cycles is not None and detail.amplitude_stability_across_cycles >= 0.7:
        findings.append("周期间幅值稳定性较好，接近等幅特征")

    if detail.clipping_detected:
        if (
            detail.mean_positive_peak is not None
            and detail.mean_negative_peak_abs is not None
            and detail.peak_valley_asymmetry_ratio is not None
        ):
            findings.append(
                f"检测到削波迹象，各周期正峰均值={detail.mean_positive_peak}，"
                f"负峰绝对值均值={detail.mean_negative_peak_abs}，"
                f"峰谷不对称度约 {detail.peak_valley_asymmetry_ratio}"
            )

    if detail.glitch_ratio is not None and detail.glitch_ratio >= 0.005:
        findings.append(f"波形中存在毛刺型窄脉冲，毛刺占比约 {detail.glitch_ratio}")

    return findings[:10]


def _parse_order_value(order_str: str | None) -> float | None:
    if not order_str or not isinstance(order_str, str):
        return None
    s = order_str.strip().upper()
    if s.endswith("X"):
        s = s[:-1]
    try:
        return float(s)
    except Exception:
        return None


def _build_peak_pattern_findings(detail: WaveformFeatureDetail) -> list[str]:
    findings: list[str] = []

    all_peaks = []
    if detail.peaks_3_to_5um:
        all_peaks.extend(detail.peaks_3_to_5um)
    if detail.peaks_over_5um:
        all_peaks.extend(detail.peaks_over_5um)

    if not all_peaks:
        return findings

    orders: list[float] = []
    high_amp_orders: list[float] = []
    freqs_hz: list[float] = []
    ultra_low_freq_hz_peaks: list[float] = []
    ultra_low_freq_high_amp_hz_peaks: list[float] = []

    for peak in all_peaks:
        order_v = _parse_order_value(str(peak.get("order")))
        amp_v = peak.get("amplitude")
        freq_hz = peak.get("frequency_hz")

        if isinstance(freq_hz, (int, float)):
            freq_hz = float(freq_hz)
            freqs_hz.append(freq_hz)
            if 1.0 <= freq_hz <= 30.0:
                ultra_low_freq_hz_peaks.append(freq_hz)
                if isinstance(amp_v, (int, float)) and amp_v > 5:
                    ultra_low_freq_high_amp_hz_peaks.append(freq_hz)

        if order_v is None:
            continue

        orders.append(order_v)
        if isinstance(amp_v, (int, float)) and amp_v > 5:
            high_amp_orders.append(order_v)

    if not orders and not ultra_low_freq_hz_peaks:
        return findings

    def _dedup_close(vals: list[float], tol: float = 0.08) -> list[float]:
        vals = sorted(vals)
        merged: list[float] = []
        for v in vals:
            if not merged or abs(v - merged[-1]) > tol:
                merged.append(v)
        return merged

    uniq_orders = _dedup_close(orders) if orders else []
    uniq_high_orders = _dedup_close(high_amp_orders) if high_amp_orders else []
    uniq_ultra_low_freq_hz = _dedup_close(ultra_low_freq_hz_peaks, tol=0.5)
    uniq_ultra_low_freq_high_amp_hz = _dedup_close(ultra_low_freq_high_amp_hz_peaks, tol=0.5)

    # ===== 新增：1~30Hz 超低频 =====
    if uniq_ultra_low_freq_hz:
        shown = "、".join(f"{round(x, 2)}Hz" for x in uniq_ultra_low_freq_hz[:5])
        findings.append(f"检测到1~30Hz超低频成分，主要包括{shown}")

    if len(uniq_ultra_low_freq_high_amp_hz) >= 2:
        shown = "、".join(f"{round(x, 2)}Hz" for x in uniq_ultra_low_freq_high_amp_hz[:5])
        findings.append(f"1~30Hz范围内存在较强低频成分，主要集中在{shown}")

    if not uniq_orders:
        return findings[:6]

    # 基础分类
    one_x_like = [x for x in uniq_orders if abs(x - 1.0) <= 0.12]
    sub_sync = [x for x in uniq_orders if 0.1 <= x < 1.0 - 0.12]
    fractional = [
        x for x in uniq_orders
        if abs(x - round(x)) > 0.12 and x >= 1.0
    ]
    integer_harmonics = [x for x in uniq_orders if x >= 2.0 and abs(x - round(x)) <= 0.12]
    even_harmonics = [x for x in integer_harmonics if int(round(x)) % 2 == 0]
    odd_harmonics = [x for x in integer_harmonics if int(round(x)) % 2 == 1]

    # 1X 主导
    if detail.amp_1x_ratio is not None:
        if detail.amp_1x_ratio >= 0.6:
            findings.append("频谱以1X成分为主导")
        elif detail.amp_1x_ratio >= 0.3:
            findings.append("频谱中1X成分较明显")

    # 整数倍频丰富
    if len(integer_harmonics) >= 3:
        shown = "、".join(f"{int(round(x))}X" for x in integer_harmonics[:5])
        findings.append(f"存在较丰富的整数倍频成分，主要包括{shown}")

    # 偶数倍频突出
    if len(even_harmonics) >= 2:
        shown = "、".join(f"{int(round(x))}X" for x in even_harmonics[:4])
        findings.append(f"偶数倍频成分相对突出，表现为{shown}")

    # 奇数倍频
    if len(odd_harmonics) >= 2:
        shown = "、".join(f"{int(round(x))}X" for x in odd_harmonics[:4])
        findings.append(f"可见一定奇数倍频成分，表现为{shown}")

    # 分数谐波 / 半倍频
    half_like = [x for x in uniq_orders if abs(x * 2 - round(x * 2)) <= 0.12 and abs(x - round(x)) > 0.12]
    if len(half_like) >= 2:
        shown = "、".join(f"{round(x, 2)}X" for x in half_like[:5])
        findings.append(f"存在分数谐波成分，主要包括{shown}")

    # 亚同步低频
    if len(sub_sync) >= 1:
        shown = "、".join(f"{round(x, 2)}X" for x in sub_sync[:4])
        findings.append(f"检测到低于1X的低频成分，主要为{shown}")

    # 高幅值峰较多
    if len(uniq_high_orders) >= 3:
        shown = "、".join(f"{round(x, 2)}X" for x in uniq_high_orders[:5])
        findings.append(f">5μm 的较高幅值频率成分较多，主要集中在{shown}")

    # 多倍频丰富
    if len(uniq_orders) >= 5:
        findings.append("频谱中多倍频成分较为丰富")

    return findings[:8]


def _build_spectral_findings(detail: WaveformFeatureDetail) -> list[str]:
    findings: list[str] = []

    if detail.dominant_frequency_hz is not None and detail.dominant_amplitude is not None:
        if detail.running_frequency_hz not in (None, 0.0):
            dominant_order = round(detail.dominant_frequency_hz / detail.running_frequency_hz, 2)
            findings.append(f"主峰位于 {dominant_order}X，幅值={detail.dominant_amplitude}")
        else:
            findings.append(f"主峰位于 {detail.dominant_frequency_hz} Hz，幅值={detail.dominant_amplitude}")

    if detail.running_frequency_hz is not None:
        findings.append(f"运行频率={detail.running_frequency_hz} Hz")

    if detail.amp_1x is not None:
        findings.append(f"1X 幅值={detail.amp_1x}")

    if detail.amp_2x is not None:
        findings.append(f"2X 幅值={detail.amp_2x}")

    if detail.amp_1x_ratio is not None:
        findings.append(f"1X 能量占比={detail.amp_1x_ratio}")

    if detail.amp_2x_to_1x_ratio is not None:
        findings.append(f"2X/1X 幅值比={detail.amp_2x_to_1x_ratio}")

    if detail.peaks_over_5um:
        findings.append(f"检测到 {len(detail.peaks_over_5um)} 个幅值超过5微米的谱峰")

    if detail.peaks_3_to_5um:
        findings.append(f"检测到 {len(detail.peaks_3_to_5um)} 个幅值在3-5微米的谱峰")

    # 新增：模式化自然语言
    findings.extend(_build_peak_pattern_findings(detail))

    # 去重
    deduped = []
    seen = set()
    for item in findings:
        if item not in seen:
            seen.add(item)
            deduped.append(item)

    return deduped[:12]


def _build_summary(detail: WaveformFeatureDetail) -> list[str]:
    summary: list[str] = []

    if detail.amp_1x_ratio is not None:
        if detail.amp_1x_ratio >= 0.3:
            summary.append("振动能量对 1X 同步成分依赖明显")
        elif detail.amp_1x_ratio >= 0.1:
            summary.append("1X 成分较明显，但不是唯一主导")
        else:
            summary.append("1X 成分不占绝对主导")

    if detail.amp_2x_to_1x_ratio is not None and detail.amp_2x_to_1x_ratio >= 0.3:
        summary.append("2X 成分相对突出")

    if detail.peaks_over_5um:
        summary.append("存在高幅值谱峰（>5微米）")

    if detail.peaks_3_to_5um:
        summary.append("存在中等幅值谱峰（3-5微米）")

    if detail.sine_fit_score is not None and detail.sine_fit_score >= 0.75:
        summary.append("波形接近标准正弦")

    if detail.cycle_repeatability_score is not None and detail.cycle_repeatability_score >= 0.7:
        summary.append("波形周期重复性较好")

    if detail.clipping_detected:
        summary.append("波形存在削波现象")

    if detail.peak_valley_asymmetry_ratio is not None and detail.peak_valley_asymmetry_ratio >= 0.2:
        summary.append("波峰和波谷存在明显不对称")

    return summary[:8]


def _build_suspected_faults(detail: WaveformFeatureDetail) -> list[str]:
    suspects: list[str] = []

    if (
        detail.amp_1x_ratio is not None
        and detail.amp_1x_ratio >= 0.25
        and detail.sine_fit_score is not None
        and detail.sine_fit_score >= 0.7
    ):
        suspects.append("疑似同步类振动问题（如不平衡、弯曲、临界响应偏大）")

    if detail.amp_2x_to_1x_ratio is not None and detail.amp_2x_to_1x_ratio >= 0.3:
        suspects.append("疑似不对中或松动方向特征")

    if (
        detail.clipping_detected
        and detail.peak_valley_asymmetry_ratio is not None
        and detail.peak_valley_asymmetry_ratio >= 0.25
    ):
        suspects.append("存在非对称削波，需排查单侧接触、偏置摩擦或单边受限")

    if (
        detail.peak_valley_asymmetry_ratio is not None
        and detail.peak_valley_asymmetry_ratio >= 0.25
    ):
        suspects.append("波峰/波谷不对称，需关注摩擦或局部异常接触")

    if detail.peaks_over_5um and len(detail.peaks_over_5um) >= 3:
        suspects.append("高幅值频谱峰较多，需结合工况排查多源激励或结构共振")

    deduped: list[str] = []
    seen: set[str] = set()
    for item in suspects:
        if item not in seen:
            seen.add(item)
            deduped.append(item)

    return deduped[:8]


async def _extract_spectral_waveform_features_impl(
    component_id: str | None = None,
    time: str | None = None,
    time_ms: str | None = None,
    waveform_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    提取精简版波形频谱特征。

    输入格式一：直接传入原始波形/频谱数据
    {
      "waveform_payload": {
        "component_id": ".",
        "time_ms": ".",
        "data": {
          "wave_x": [...],
          "wave_y": [...],
          "spec_x": [...],
          "spec_y": [...],
          "sample_rate": .,
          "speed": .,   # rpm
          "unit": .
        }
      }
    }

    输入格式二：只提供查询参数，工具内部按需调用 get_waveform_data_tool
    {
      "component_id": ".",
      "time": "趋势分析返回的异常毫秒时间戳，或可解析时间字符串",
      "time_ms": "趋势分析返回的异常毫秒时间戳，可选，优先于 time"
    }
    """
    if waveform_payload is None:
        waveform_payload = {}

    if "data" not in waveform_payload:
        payload_component_id = str(component_id or waveform_payload.get("component_id") or "")
        payload_time = str(time_ms or time or waveform_payload.get("time_ms") or waveform_payload.get("time") or "")
        if not payload_component_id:
            raise ValueError("component_id is required when waveform data is not provided")
        if not payload_time:
            raise ValueError("time is required when waveform data is not provided")
        waveform_payload = await _get_waveform_data_impl(payload_component_id, payload_time)

    component_id = str(waveform_payload.get("component_id") or "")
    time_ms = str(waveform_payload.get("time_ms") or "")
    data = waveform_payload.get("data") or {}

    if not isinstance(data, dict):
        data = {}

    normalized_data = dict(data)
    normalized_wave_y = [
        float(v) * 1000.0
        for v in (data.get("wave_y") or [])
        if isinstance(v, (int, float)) and math.isfinite(v)
    ]
    if normalized_wave_y:
        normalized_data["wave_y"] = normalized_wave_y
    normalized_data["unit"] = "μm"

    feature_details = _extract_feature_detail(normalized_data)
    result = SpectralWaveformAnalysisResult(
        component_id=component_id,
        time_ms=time_ms,
        summary=_build_summary(feature_details),
        spectral_findings=_build_spectral_findings(feature_details),
        waveform_findings=_build_waveform_findings(feature_details),
        suspected_faults=_build_suspected_faults(feature_details),
        feature_details=feature_details,
    )
    return result.model_dump()


@function_tool(strict_mode=False)
async def extract_spectral_waveform_features_tool(
    component_id: str | None = None,
    time: str | None = None,
    time_ms: str | None = None,
    waveform_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return await _extract_spectral_waveform_features_impl(
        component_id=component_id,
        time=time,
        time_ms=time_ms,
        waveform_payload=waveform_payload,
    )


async def main() -> None:
    """
    用法：
    python extract_spectral_waveform_features_tool.py '{"waveform_payload":{"component_id":".","time_ms":".","data":{...}}}'
    """
    if len(sys.argv) < 2:
        raise SystemExit("用法: python extract_spectral_waveform_features_tool.py '<payload_json>'")

    payload = json.loads(sys.argv[1])
    if not isinstance(payload, dict):
        raise SystemExit("payload_json 必须是 JSON 对象")
    result = await extract_spectral_waveform_features_tool(**payload)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
