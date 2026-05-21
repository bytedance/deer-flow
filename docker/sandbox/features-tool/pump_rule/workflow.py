from __future__ import annotations

import json
import os
import platform
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .context import build_target_context_from_point_configs
from .health import check_temperature_health, check_vibration_health
from .models import PumpDiagnosisResult
from .provider import InsPumpDataProvider, JsonFixturePumpDataProvider, PumpDataProvider
from .rules import check_malfunctions
from .spectral import get_bearing_ratio, get_bpf_ratio, get_harmonic_ratio, infer_base_frequency, safe_float


_PROVIDERS: list[PumpDataProvider] = []


def _artifact_root() -> Path:
    root = Path(os.environ.get("DIAGNOSIS_OUTPUT_DIR", "/mnt/user-data/outputs"))
    path = root / "pump_rule_cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_cache(prefix: str, name: str, payload: dict[str, Any]) -> str:
    safe_name = "".join(ch if ch.isalnum() or ch in {"_", "-", "."} else "_" for ch in name)
    path = _artifact_root() / f"{prefix}_{safe_name}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def _provider_from_env() -> PumpDataProvider:
    fixture = os.environ.get("PUMP_RULE_FIXTURE")
    if fixture:
        provider = JsonFixturePumpDataProvider(fixture)
    else:
        provider = InsPumpDataProvider()
    _PROVIDERS.append(provider)
    return provider


def self_check() -> dict[str, Any]:
    checks: dict[str, Any] = {
        "python_version": platform.python_version(),
        "numpy": False,
        "ins_access_token": bool(os.environ.get("INS_ACCESS_TOKEN")),
        "ins_base_url": os.environ.get("INS_BASE_URL"),
    }
    try:
        import numpy  # noqa: F401

        checks["numpy"] = True
    except Exception as exc:  # noqa: BLE001
        checks["numpy_error"] = str(exc)
    return checks


async def close_all_clients() -> None:
    providers = list(_PROVIDERS)
    _PROVIDERS.clear()
    for provider in providers:
        await provider.close()


async def run_diagnosis(
    machine_id: str,
    component_id: str,
    diagnosis_time: str,
    *,
    start_time: str | None = None,
    end_time: str | None = None,
    component_name: str | None = None,
    base_freq: float | None = None,
    provider: PumpDataProvider | None = None,
) -> PumpDiagnosisResult:
    start, end = _resolve_window(diagnosis_time, start_time, end_time)
    provider = provider or _provider_from_env()
    warnings: list[str] = []

    point_configs = await provider.get_point_configs(machine_id)
    _write_cache("point_configs", machine_id, point_configs)
    context = build_target_context_from_point_configs(
        machine_id,
        component_id,
        point_configs,
        component_name=component_name,
    )
    warnings.extend(context.warnings)

    vibration_points = [point for point in context.points if point.point_kind == "vibration"]
    temperature_points = [point for point in context.points if point.point_kind == "temperature"]
    if not vibration_points:
        warnings.append("目标子设备未解析到振动测点，无法执行频谱故障规则")

    point_ids = [point.point_id for point in vibration_points + temperature_points]
    trend_by_point = await provider.get_trend_data(point_ids, start, end) if point_ids else {}
    _write_cache("trend", f"{machine_id}_{component_id}_{start}_{end}", trend_by_point)

    wave_by_point = await provider.get_waveforms([point.point_id for point in vibration_points], start, end) if vibration_points else {}
    _write_cache("waveform", f"{machine_id}_{component_id}_{start}_{end}", wave_by_point)

    resolved_base_freq = base_freq or infer_base_frequency(wave_by_point)
    if resolved_base_freq is None and vibration_points:
        warnings.append("无法从波形推断基频，已跳过依赖基频的故障规则")

    health_findings = _build_health_findings(vibration_points, temperature_points, trend_by_point)
    spectrum_ratio_map, sampled_waveforms, spectrum_warnings = _build_spectrum_ratio_map(vibration_points, wave_by_point, resolved_base_freq)
    warnings.extend(spectrum_warnings)
    malfunction_findings = check_malfunctions(spectrum_ratio_map) if spectrum_ratio_map else []
    evidence = _build_evidence(health_findings, malfunction_findings, spectrum_ratio_map, machine_id)

    target_info = context.model_dump()
    target_info["diagnosis_time"] = diagnosis_time
    target_info["diagnosis_window"] = {"start": start, "end": end}
    return PumpDiagnosisResult(
        machine_id=machine_id,
        component_id=component_id,
        diagnosis_time=diagnosis_time,
        diagnosis_window={"start": start, "end": end},
        target_info=target_info,
        base_freq=round(float(resolved_base_freq), 6) if resolved_base_freq is not None else None,
        health_findings=health_findings,
        malfunction_findings=malfunction_findings,
        evidence=evidence,
        sampled_waveforms=sampled_waveforms,
        warnings=_dedupe(warnings),
    )


def _resolve_window(diagnosis_time: str, start_time: str | None, end_time: str | None) -> tuple[str, str]:
    if start_time and end_time:
        return start_time, end_time
    if "T" in diagnosis_time:
        prefix = diagnosis_time[:13]
        return f"{prefix}:00:00", f"{prefix}:59:59"
    if len(diagnosis_time) == 10:
        return f"{diagnosis_time}T00:00:00", f"{diagnosis_time}T00:59:59"
    return diagnosis_time, diagnosis_time


def _build_health_findings(
    vibration_points: list[Any],
    temperature_points: list[Any],
    trend_by_point: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for point in vibration_points:
        values = [_normalize_trend_value(item) for item in trend_by_point.get(point.point_id, [])]
        findings.extend(check_vibration_health(point.point_id, point.name, values, point.thresholds))
    for point in temperature_points:
        values = [_normalize_trend_value(item) for item in trend_by_point.get(point.point_id, [])]
        findings.extend(check_temperature_health(point.point_id, point.name, values, point.thresholds))
    return findings


def _normalize_trend_value(item: dict[str, Any]) -> dict[str, Any]:
    values = item.get("values") if isinstance(item.get("values"), dict) else item
    ts = item.get("time_ms") or item.get("time") or values.get("time")
    return {
        "time": int(ts) if str(ts).isdigit() else 0,
        "rms": values.get("rms") or values.get("v_rms"),
        "v_rms": values.get("v_rms") or values.get("rms"),
        "peak": values.get("peak") or values.get("a_peak"),
        "a_peak": values.get("a_peak") or values.get("peak"),
        "value": values.get("value") or values.get("temperature"),
    }


def _build_spectrum_ratio_map(
    vibration_points: list[Any],
    wave_by_point: dict[str, list[dict[str, Any]]],
    base_freq: float | None,
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]], list[str]]:
    if base_freq is None:
        return {}, [], []
    warnings: list[str] = []
    ratio_map: dict[str, list[dict[str, Any]]] = {}
    sampled: list[dict[str, Any]] = []
    point_by_id = {point.point_id: point for point in vibration_points}
    for point_id, waves in wave_by_point.items():
        point = point_by_id.get(point_id)
        if point is None:
            continue
        for item in waves[:5]:
            if item.get("error"):
                warnings.append(f"测点 {point_id} 波形获取失败：{item.get('error')}")
                continue
            wave = [float(v) for v in (item.get("wave") or item.get("wave_y") or [])]
            fs = safe_float(item.get("fs") or item.get("sample_rate")) or 0.0
            if not wave or fs <= 0:
                warnings.append(f"测点 {point_id} 波形为空或采样频率无效")
                continue
            spectrum = {
                "harmonic_ratio": get_harmonic_ratio(wave, fs, base_freq),
                "bearing_ratio": get_bearing_ratio(wave, fs, base_freq, point.config),
                "bpf_ratio": get_bpf_ratio(wave, fs, base_freq, point.config),
                "rms": safe_float(item.get("v_rms")) or _latest_rms_from_wave(wave),
                "c_threshold": safe_float(point.thresholds.get("rms_c") or point.thresholds.get("v_rms_c")),
                "time": item.get("time"),
            }
            ratio_map.setdefault(point_id, []).append(spectrum)
            sampled.append({"point_id": point_id, "point_name": point.name, "time": item.get("time"), "fs": fs, "sample_count": len(wave)})
    return ratio_map, sampled, warnings


def _latest_rms_from_wave(wave: list[float]) -> float:
    if not wave:
        return 0.0
    return float((sum(value * value for value in wave) / len(wave)) ** 0.5)


def _build_evidence(
    health_findings: list[dict[str, Any]],
    malfunction_findings: list[dict[str, Any]],
    spectrum_ratio_map: dict[str, list[dict[str, Any]]],
    machine_id: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for finding in health_findings:
        rows.append(
            {
                "category": "health",
                "equipment_id": machine_id,
                "point": finding.get("point_name") or finding.get("point_id"),
                "feature": finding.get("description") or finding.get("status"),
                "value": finding.get("value"),
                "threshold": finding.get("threshold"),
                "verdict": "exceed",
            }
        )
    for finding in malfunction_findings:
        rows.append(
            {
                "category": "rule",
                "equipment_id": machine_id,
                "point": ",".join(str(item) for item in (finding.get("point_ids") or [])),
                "feature": finding.get("name") or finding.get("type"),
                "value": round(float(finding.get("probability") or 0.0), 4),
                "threshold": ">=0.5",
                "verdict": "exceed",
            }
        )
    for point_id, spectra in spectrum_ratio_map.items():
        for spectrum in spectra[:2]:
            one = (spectrum.get("harmonic_ratio") or {}).get("1")
            if one is not None:
                rows.append(
                    {
                        "category": "spectrum",
                        "equipment_id": machine_id,
                        "point": point_id,
                        "feature": "1X energy ratio",
                        "value": round(float(one), 4),
                        "threshold": 0.5,
                        "verdict": "exceed" if float(one) >= 0.5 else "normal",
                    }
                )
    return rows


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result
