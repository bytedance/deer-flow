from __future__ import annotations

import math
from typing import Any

import numpy as np


DEFAULT_BEARING_RATIO_CONFIG: dict[str, list[float]] = {
    "outer_race": [3.0, 3.6, 4.0],
    "inner_race": [4.5, 5.0, 5.5],
    "rolling_element": [2.0, 2.4],
    "cage": [0.35, 0.4, 0.45],
}

BEARING_CONFIG_KEYS: dict[str, list[str]] = {
    "outer_race": ["bpfo", "BPFO", "outerRaceFreq", "outerRaceRatio", "bearingOuterRaceRatio"],
    "inner_race": ["bpfi", "BPFI", "innerRaceFreq", "innerRaceRatio", "bearingInnerRaceRatio"],
    "rolling_element": ["bsf", "BSF", "rollingElementFreq", "rollingElementRatio", "bearingRollingElementRatio"],
    "cage": ["ftf", "FTF", "cageFreq", "cageRatio", "bearingCageRatio"],
}

BPF_CONFIG_KEYS = ["bpf", "BPF", "bladePassFreq", "bladePassRatio", "bpfRatio", "passingFreq", "passingRatio"]


def safe_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        numeric = float(value)
        return numeric if math.isfinite(numeric) else None
    if isinstance(value, str):
        try:
            numeric = float(value.strip())
        except ValueError:
            return None
        return numeric if math.isfinite(numeric) else None
    return None


def calc_fft(data: list[float] | np.ndarray, fs: float) -> tuple[np.ndarray, np.ndarray]:
    arr = np.asarray(data, dtype=float)
    if arr.size == 0 or fs <= 0:
        return np.asarray([], dtype=float), np.asarray([], dtype=float)
    fft_result = np.fft.fft(arr)
    fft_freq = np.fft.fftfreq(arr.size, d=1 / fs)
    return np.abs(fft_result)[: arr.size // 2], fft_freq[: arr.size // 2]


def calc_fft_energy_ratio(amplitude: np.ndarray) -> np.ndarray:
    if amplitude.size == 0:
        return np.asarray([], dtype=float)
    amplitude_squared = amplitude**2
    total_energy = float(np.sum(amplitude_squared))
    if total_energy <= 0:
        return np.zeros_like(amplitude_squared, dtype=float)
    return amplitude_squared / total_energy


def calc_band_energy(
    amplitude: np.ndarray,
    frequencies: np.ndarray,
    energy_ratio: np.ndarray,
    center_freq: float,
    base_freq: float,
) -> float:
    if center_freq <= 0 or base_freq <= 0 or amplitude.size == 0:
        return 0.0
    frequency_range = max(base_freq * 0.12, 2.0)
    indices = np.where((frequencies >= center_freq - frequency_range) & (frequencies <= center_freq + frequency_range))[0]
    valid_indices = [idx for idx in indices if amplitude[idx] >= 0.5]
    return float(np.sum(energy_ratio[valid_indices]))


def get_harmonic_ratio(wave: list[float], fs: float, base_freq: float) -> dict[str, float]:
    amplitude, frequencies = calc_fft(wave, fs)
    if amplitude.size == 0 or base_freq <= 0:
        return {}
    energy_ratio = calc_fft_energy_ratio(amplitude)
    harmonic_ratios: dict[str, float] = {}
    max_harmonic = int(np.max(frequencies) // base_freq) if frequencies.size else 0
    frequency_range = base_freq * 0.2
    for multiplier in [0.5] + list(range(1, max_harmonic + 1)):
        harmonic_freq = multiplier * base_freq
        indices = np.where((frequencies >= harmonic_freq - frequency_range) & (frequencies <= harmonic_freq + frequency_range))[0]
        valid_indices = [idx for idx in indices if amplitude[idx] >= 0.5]
        key = str(multiplier if multiplier == 0.5 else int(multiplier))
        harmonic_ratios[key] = float(np.sum(energy_ratio[valid_indices]))
    return harmonic_ratios


def get_config_value(config_info: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        value = config_info.get(key)
        if value not in (None, "", 0):
            return value
    return None


def normalize_ratio(value: float, base_freq: float) -> float:
    if value > 10 and base_freq > 0:
        return value / base_freq
    return value


def parse_ratio_config(config_value: Any, base_freq: float) -> list[float]:
    if isinstance(config_value, list):
        values = [safe_float(item) for item in config_value]
    elif isinstance(config_value, (int, float, str)):
        values = [safe_float(item.strip()) for item in str(config_value).split(",") if item.strip()]
    else:
        values = []
    return [normalize_ratio(value, base_freq) for value in values if value is not None]


def get_bearing_ratio_config(config_info: dict[str, Any], base_freq: float) -> dict[str, list[float]]:
    ratio_config: dict[str, list[float]] = {}
    for fault_name, keys in BEARING_CONFIG_KEYS.items():
        config_value = get_config_value(config_info, keys)
        parsed = parse_ratio_config(config_value, base_freq) if config_value is not None else []
        ratio_config[fault_name] = parsed or DEFAULT_BEARING_RATIO_CONFIG[fault_name]
    return ratio_config


def get_bearing_ratio(wave: list[float], fs: float, base_freq: float, config_info: dict[str, Any]) -> dict[str, dict[str, float]]:
    amplitude, frequencies = calc_fft(wave, fs)
    energy_ratio = calc_fft_energy_ratio(amplitude)
    bearing_ratios: dict[str, dict[str, float]] = {}
    for fault_name, ratios in get_bearing_ratio_config(config_info, base_freq).items():
        main_energy = 0.0
        harmonic_energy = 0.0
        sideband_energy = 0.0
        for ratio in ratios:
            fault_freq = ratio * base_freq
            main_energy = max(main_energy, calc_band_energy(amplitude, frequencies, energy_ratio, fault_freq, base_freq))
            harmonic_energy = max(harmonic_energy, calc_band_energy(amplitude, frequencies, energy_ratio, fault_freq * 2, base_freq))
            sideband_energy = max(
                sideband_energy,
                calc_band_energy(amplitude, frequencies, energy_ratio, fault_freq - base_freq, base_freq)
                + calc_band_energy(amplitude, frequencies, energy_ratio, fault_freq + base_freq, base_freq),
            )
        bearing_ratios[fault_name] = {"main": main_energy, "harmonic": harmonic_energy, "sideband": sideband_energy}
    return bearing_ratios


def get_bpf_ratio(wave: list[float], fs: float, base_freq: float, config_info: dict[str, Any]) -> dict[str, float] | None:
    config_value = get_config_value(config_info, BPF_CONFIG_KEYS)
    ratios = parse_ratio_config(config_value, base_freq) if config_value is not None else []
    if not ratios:
        return None
    amplitude, frequencies = calc_fft(wave, fs)
    energy_ratio = calc_fft_energy_ratio(amplitude)
    main_energy = 0.0
    harmonic_energy = 0.0
    sideband_energy = 0.0
    for ratio in ratios:
        bpf_freq = ratio * base_freq
        main_energy = max(main_energy, calc_band_energy(amplitude, frequencies, energy_ratio, bpf_freq, base_freq))
        harmonic_energy = max(harmonic_energy, calc_band_energy(amplitude, frequencies, energy_ratio, bpf_freq * 2, base_freq))
        sideband_energy = max(
            sideband_energy,
            calc_band_energy(amplitude, frequencies, energy_ratio, bpf_freq - base_freq, base_freq)
            + calc_band_energy(amplitude, frequencies, energy_ratio, bpf_freq + base_freq, base_freq),
        )
    return {"main": main_energy, "harmonic": harmonic_energy, "sideband": sideband_energy}


def infer_base_frequency(waves_by_point: dict[str, list[dict[str, Any]]]) -> float | None:
    standards = np.array([12.5, 25.0, 50.0])
    emd_bases = np.array([])
    max_freqs = np.array([])
    max_values = np.array([])

    for waves in waves_by_point.values():
        sorted_waves = sorted(waves, key=lambda x: safe_float(x.get("v_rms")) or 0.0, reverse=True)
        num_to_remove = int(len(sorted_waves) * 0.1)
        filtered_waves = sorted_waves[num_to_remove:] if num_to_remove > 0 else sorted_waves
        length = min(len(filtered_waves), 3)
        for item in filtered_waves[:length]:
            wave = item.get("wave") or []
            fs = safe_float(item.get("fs") or item.get("sample_rate")) or 0.0
            if not wave or fs <= 0:
                continue
            emd_base = _ceemdan_base_frequency(np.asarray(wave, dtype=float), fs)
            if emd_base is not None:
                emd_bases = np.append(emd_bases, emd_base)
            max_freq, max_value = _get_max_freq_amplitude(wave, fs)
            if max_freq is not None:
                max_freqs = np.append(max_freqs, max_freq)
                max_values = np.append(max_values, max_value)

    cleaned_data = emd_bases[emd_bases > 10]
    if len(cleaned_data) == 0:
        return _infer_base_frequency_fft_fallback(waves_by_point)
    cleaned_data = _remove_outliers_iqr(cleaned_data)
    if len(cleaned_data) == 0:
        return _infer_base_frequency_fft_fallback(waves_by_point)

    min_distance = float("inf")
    best_match = None
    for standard_speed in standards:
        distance = float(np.linalg.norm(cleaned_data - standard_speed))
        if distance < min_distance:
            min_distance = distance
            best_match = float(standard_speed)

    if len(max_values) == 0 or best_match is None:
        return best_match

    max_value_arg = int(np.argmax(max_values))
    max_freq = float(max_freqs[max_value_arg])

    differences = np.abs(max_freqs - best_match)
    closest_index = int(np.argmin(differences))
    closest_value = float(max_freqs[closest_index])
    if abs(closest_value - best_match) < 5:
        return closest_value

    z = _find_z(max_freq, best_match)
    return best_match + z


def _infer_base_frequency_fft_fallback(waves_by_point: dict[str, list[dict[str, Any]]]) -> float | None:
    candidates: list[float] = []
    max_freqs: list[tuple[float, float]] = []
    standards = (12.5, 25.0, 50.0)
    for waves in waves_by_point.values():
        for item in waves[:3]:
            wave = item.get("wave") or []
            fs = safe_float(item.get("fs") or item.get("sample_rate")) or 0.0
            amplitude, frequencies = calc_fft(wave, fs)
            if amplitude.size == 0:
                continue
            valid = np.where((frequencies > 5.0) & (frequencies < 200.0))[0]
            if valid.size == 0:
                continue
            idx = int(valid[np.argmax(amplitude[valid])])
            freq = float(frequencies[idx])
            amp = float(amplitude[idx])
            max_freqs.append((freq, amp))
            nearest = min(standards, key=lambda std: abs(freq - std))
            if abs(freq - nearest) < 5.0:
                candidates.append(freq)
    if candidates:
        return float(np.median(candidates))
    if not max_freqs:
        return None
    freq, _ = max(max_freqs, key=lambda item: item[1])
    nearest = min(standards, key=lambda std: abs(freq - std))
    return nearest


def _butter_lowpass_filter(signal: np.ndarray, cutoff: float, fs: float, order: int = 4) -> np.ndarray:
    try:
        from scipy.signal import butter, filtfilt
    except ImportError:
        return signal
    nyquist = 0.5 * fs
    if cutoff >= nyquist:
        return signal
    normal_cutoff = cutoff / nyquist
    b, a = butter(order, normal_cutoff, btype="low", analog=False)
    return filtfilt(b, a, signal)


def _ceemdan_dominant_frequency(imf: np.ndarray, fs: float) -> float:
    try:
        from scipy.signal import find_peaks
    except ImportError:
        return 0.0
    peaks, _ = find_peaks(imf)
    peak_intervals = np.diff(peaks) / fs
    if len(peak_intervals) == 0:
        return 0.0
    return 1.0 / float(np.mean(peak_intervals))


def _ceemdan_base_frequency(signal: np.ndarray, fs: float) -> float | None:
    try:
        from PyEMD import CEEMDAN
    except ImportError:
        amplitude, frequencies = calc_fft(signal.tolist(), fs)
        if amplitude.size == 0:
            return None
        valid = np.where((frequencies > 5.0) & (frequencies < 200.0))[0]
        if valid.size == 0:
            return None
        idx = int(valid[np.argmax(amplitude[valid])])
        return float(frequencies[idx])

    filtered_signal = _butter_lowpass_filter(signal, cutoff=120.0, fs=fs, order=4)
    ceemdan = CEEMDAN(trials=30, noise_width=0.2)
    ceemdan.noise_seed(42)
    try:
        imfs = ceemdan(filtered_signal)
    except Exception:
        return None

    frequencies = [_ceemdan_dominant_frequency(imf, fs) for imf in imfs]
    amplitudes = [float(np.mean(np.abs(imf))) for imf in imfs]

    threshold_frequency = 70.0
    valid_imfs = [(freq, amp) for freq, amp in zip(frequencies, amplitudes) if 0 < freq < threshold_frequency]
    if not valid_imfs:
        return None
    max_amplitude_imf = max(valid_imfs, key=lambda x: (x[1], -x[0]))
    return max_amplitude_imf[0]


def _get_max_freq_amplitude(signal: list[float] | np.ndarray, fs: float) -> tuple[float | None, float | None]:
    amplitude, frequencies = calc_fft(signal, fs)
    if amplitude.size == 0:
        return None, None
    filtered_indices = frequencies < 200.0
    if not np.any(filtered_indices):
        return None, None
    filtered_frequencies = frequencies[filtered_indices]
    filtered_amplitude = amplitude[filtered_indices]
    max_index = int(np.argmax(filtered_amplitude))
    return float(filtered_frequencies[max_index]), float(filtered_amplitude[max_index])


def _remove_outliers_iqr(data: np.ndarray) -> np.ndarray:
    if len(data) == 0:
        return data
    q1 = float(np.percentile(data, 25))
    q3 = float(np.percentile(data, 75))
    iqr = q3 - q1
    lower_bound = q1 - 1.5 * iqr
    upper_bound = q3 + 1.5 * iqr
    return data[(data >= lower_bound) & (data <= upper_bound)]


def _find_z(x: float, y: float) -> float:
    res = np.array([(x / i) - y for i in range(1, 20)])
    return float(res[np.argmin(np.abs(res))])
