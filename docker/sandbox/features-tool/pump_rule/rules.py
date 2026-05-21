from __future__ import annotations

from typing import Any, Callable


MALFUNCTION_NAMES: dict[str, str] = {
    "unbalance": "不平衡或刚性不足",
    "bearing_outer_race": "滚动轴承外圈故障",
    "bearing_inner_race": "滚动轴承内圈故障",
    "bearing_rolling_element": "滚动轴承滚动体故障",
    "bearing_cage": "滚动轴承保持架故障",
    "misalignment": "不对中",
    "bpf": "BPF频率异常",
}

BEARING_FAULT_CONFIG = {
    "outer_race": {"code": "bearing_outer_race", "main_threshold": 0.08, "strong_threshold": 0.16},
    "inner_race": {"code": "bearing_inner_race", "main_threshold": 0.08, "strong_threshold": 0.16},
    "rolling_element": {"code": "bearing_rolling_element", "main_threshold": 0.06, "strong_threshold": 0.13},
    "cage": {"code": "bearing_cage", "main_threshold": 0.05, "strong_threshold": 0.10},
}


def _clip_probability(value: float, cap: float = 0.88) -> float:
    if value < 0.5:
        return 0.0
    return float(min(value, cap))


def calc_unbalance_probability(harmonic_ratio: dict[str, float]) -> float:
    one = harmonic_ratio.get("1", 0.0)
    probability = 0.0
    if one >= 0.8:
        probability += 0.65 + (one - 0.8)
    elif one >= 0.5:
        probability += 0.4 + (one - 0.5)
    return float(probability)


def check_unbalance(spectrum_ratio_map: dict[str, list[dict[str, Any]]]) -> tuple[float, dict[str, Any]]:
    wave_count = 0
    condition_count = 0
    max_probability = 0.0
    condition_point_ids: list[str] = []
    time: Any = None
    for point_id, waves in spectrum_ratio_map.items():
        for spectrum in waves:
            wave_count += 1
            rms = spectrum.get("rms")
            c_threshold = spectrum.get("c_threshold")
            if c_threshold is not None and rms is not None and rms < c_threshold:
                continue
            probability = calc_unbalance_probability(spectrum.get("harmonic_ratio") or {})
            if probability > 0:
                condition_count += 1
                if probability > max_probability:
                    max_probability = probability
                    condition_point_ids = [point_id]
                    time = spectrum.get("time")
    if wave_count > 0:
        max_probability += (condition_count / wave_count) * 0.2
    return _clip_probability(max_probability, 0.85), {"point_ids": condition_point_ids, "time": time}


def _bearing_probability(ratios: dict[str, float], config: dict[str, Any]) -> float:
    main_energy = float(ratios.get("main") or 0.0)
    harmonic_energy = float(ratios.get("harmonic") or 0.0)
    sideband_energy = float(ratios.get("sideband") or 0.0)
    main_threshold = float(config["main_threshold"])
    strong_threshold = float(config["strong_threshold"])
    probability = 0.0
    if main_energy >= strong_threshold:
        probability = 0.62 + min(main_energy - strong_threshold, 0.18)
    elif main_energy >= main_threshold:
        probability = 0.42 + min(main_energy - main_threshold, 0.15)
    if probability == 0:
        return 0.0
    if harmonic_energy >= main_threshold * 0.7:
        probability += 0.08
    if sideband_energy >= main_threshold * 0.6:
        probability += 0.08
    return float(probability)


def _check_by_probability(
    spectrum_ratio_map: dict[str, list[dict[str, Any]]],
    calc_probability: Callable[[dict[str, Any]], float],
) -> tuple[float, dict[str, Any]]:
    wave_count = 0
    condition_count = 0
    max_probability = 0.0
    condition_point_ids: list[str] = []
    time: Any = None
    for point_id, waves in spectrum_ratio_map.items():
        for spectrum in waves:
            wave_count += 1
            rms = spectrum.get("rms")
            c_threshold = spectrum.get("c_threshold")
            if c_threshold is not None and rms is not None and rms < c_threshold:
                continue
            probability = calc_probability(spectrum)
            if probability > 0:
                condition_count += 1
                if probability > max_probability:
                    max_probability = probability
                    condition_point_ids = [point_id]
                    time = spectrum.get("time")
    if wave_count > 0:
        max_probability += (condition_count / wave_count) * 0.18
    return _clip_probability(max_probability), {"point_ids": condition_point_ids, "time": time}


def check_bearing_faults(spectrum_ratio_map: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for fault_name, config in BEARING_FAULT_CONFIG.items():
        probability, param = _check_by_probability(
            spectrum_ratio_map,
            lambda spectrum, fn=fault_name, cfg=config: _bearing_probability(
                (spectrum.get("bearing_ratio") or {}).get(fn) or {},
                cfg,
            ),
        )
        if probability > 0:
            code = str(config["code"])
            results.append(
                {
                    "type": code,
                    "name": MALFUNCTION_NAMES[code],
                    "probability": probability,
                    "point_ids": param["point_ids"],
                    "time": param["time"],
                }
            )
    return results


def calc_misalignment_probability(spectrum: dict[str, Any]) -> float:
    harmonic_ratio = spectrum.get("harmonic_ratio") or {}
    half = harmonic_ratio.get("0.5", 0.0)
    one = harmonic_ratio.get("1", 0.0)
    two = harmonic_ratio.get("2", 0.0)
    three = harmonic_ratio.get("3", 0.0)
    probability = 0.0
    if two >= 0.22:
        probability = 0.62 + min(two - 0.22, 0.16)
    elif two >= 0.14 and one >= 0.18:
        probability = 0.52
    elif two >= 0.10 and half >= 0.05:
        probability = 0.45
    if probability == 0:
        return 0.0
    if three >= 0.06:
        probability += 0.06
    if half >= 0.04:
        probability += 0.05
    return float(probability)


def calc_bpf_probability(spectrum: dict[str, Any]) -> float:
    bpf_ratio = spectrum.get("bpf_ratio")
    if not isinstance(bpf_ratio, dict):
        return 0.0
    main_energy = float(bpf_ratio.get("main") or 0.0)
    harmonic_energy = float(bpf_ratio.get("harmonic") or 0.0)
    sideband_energy = float(bpf_ratio.get("sideband") or 0.0)
    probability = 0.0
    if main_energy >= 0.16:
        probability = 0.62 + min(main_energy - 0.16, 0.18)
    elif main_energy >= 0.08:
        probability = 0.42 + min(main_energy - 0.08, 0.15)
    if probability == 0:
        return 0.0
    if harmonic_energy >= 0.06:
        probability += 0.08
    if sideband_energy >= 0.05:
        probability += 0.08
    return float(probability)


def check_frequency_faults(spectrum_ratio_map: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for code, name, calculator in (
        ("misalignment", MALFUNCTION_NAMES["misalignment"], calc_misalignment_probability),
        ("bpf", MALFUNCTION_NAMES["bpf"], calc_bpf_probability),
    ):
        probability, param = _check_by_probability(spectrum_ratio_map, calculator)
        if probability > 0:
            results.append(
                {
                    "type": code,
                    "name": name,
                    "probability": probability,
                    "point_ids": param["point_ids"],
                    "time": param["time"],
                }
            )
    return results


def check_malfunctions(spectrum_ratio_map: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    probability, param = check_unbalance(spectrum_ratio_map)
    if probability > 0:
        results.append(
            {
                "type": "unbalance",
                "name": MALFUNCTION_NAMES["unbalance"],
                "probability": probability,
                "point_ids": param["point_ids"],
                "time": param["time"],
            }
        )
    results.extend(check_bearing_faults(spectrum_ratio_map))
    results.extend(check_frequency_faults(spectrum_ratio_map))
    results.sort(key=lambda item: float(item.get("probability") or 0.0), reverse=True)
    return results
