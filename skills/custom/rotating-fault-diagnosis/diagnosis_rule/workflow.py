from __future__ import annotations
import asyncio
import hashlib
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from diagnosis.context_index import resolve_sub_device_targets
from diagnosis.models import CandidateFault, DeviceContext, DiagnosisResult, FinalFault
from ins.client import close_shared_http_client, datetime_input_to_ms
from tools.device_analysis import close_clients as close_device_clients
from tools.extract_orbit_centerline_features_tool import _extract_orbit_centerline_features_impl
from tools.extract_s_trend_features_tool import extract_trend_features_tool as _extract_segmented_trend_features_tool
from tools.extract_spectral_waveform_features_tool import _extract_spectral_waveform_features_impl
from tools.extract_trend_features_tool import _extract_trend_features_impl as _extract_rise_vol_trend_features_impl
from tools.get_orbit_data_tool import _get_orbit_data_impl, close_clients as close_orbit_clients
from tools.get_trend_data_tool import (
    _get_trend_data_impl,
    close_clients as close_trend_clients,
    collect_union_features,
)
from tools.get_waveform_data_tool import _get_waveform_data_impl, close_clients as close_waveform_clients

from .config import load_config
from .context import build_rule_device_context, close_clients as close_rule_context_clients


def _artifact_root() -> Path:
    root = Path(os.environ.get("DIAGNOSIS_OUTPUT_DIR", "/mnt/user-data/outputs"))
    path = root / "rotating_rule_cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_cache(prefix: str, name: str, payload: dict[str, Any]) -> None:
    safe_name = "".join(ch if ch.isalnum() or ch in {"_", "-", "."} else "_" for ch in name)
    if len(safe_name) > 120:
        digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:16]
        safe_name = f"{safe_name[:80]}_{digest}"
    path = _artifact_root() / f"{prefix}_{safe_name}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


async def cached_get_trend_data(component_features: dict[str, list[str]], start: str, end: str) -> dict[str, Any]:
    payload = await _get_trend_data_impl(component_features=component_features, start=start, end=end)
    component_key = "-".join(sorted(component_features.keys()))
    _write_cache("trend", f"{component_key}_{start}_{end}", payload)
    return payload


async def cached_extract_trend_features(trend_data_payload: dict[str, Any]) -> dict[str, Any]:
    payload = await _extract_rise_vol_trend_features_impl(trend_data_payload=trend_data_payload)
    component_key = "-".join(sorted(str(item) for item in (trend_data_payload.get("component_ids") or [])))
    _write_cache(
        "trend_features",
        f"{component_key}_{trend_data_payload.get('start_time')}_{trend_data_payload.get('end_time')}",
        payload,
    )
    return payload


async def cached_extract_segmented_trend_features(trend_data_payload: dict[str, Any]) -> dict[str, Any]:
    payload = await _extract_segmented_trend_features_tool(trend_data_payload=trend_data_payload)
    component_key = "-".join(sorted(str(item) for item in (trend_data_payload.get("component_ids") or [])))
    _write_cache(
        "trend_segments",
        f"{component_key}_{trend_data_payload.get('start_time')}_{trend_data_payload.get('end_time')}",
        payload,
    )
    return payload


async def cached_extract_waveform(component_id: str, time_ms: str) -> dict[str, Any]:
    waveform_payload = await _get_waveform_data_impl(component_id=component_id, time=time_ms)
    _write_cache("waveform", f"{component_id}_{time_ms}", waveform_payload)
    payload = await _extract_spectral_waveform_features_impl(waveform_payload=waveform_payload)
    _write_cache("waveform_features", f"{component_id}_{time_ms}", payload)
    return payload


async def cached_extract_orbit(
    root_device_id: str,
    bearing_id: str,
    time_ms: str,
    probe_ids: list[str] | None = None,
) -> dict[str, Any]:
    orbit_payload = await _get_orbit_data_impl(
        machine_id=root_device_id,
        bearing_id=bearing_id,
        time=time_ms,
        probe_ids=probe_ids,
    )
    _write_cache("orbit", f"{bearing_id}_{time_ms}", orbit_payload)
    payload = await _extract_orbit_centerline_features_impl(orbit_payload=orbit_payload)
    _write_cache("orbit_features", f"{bearing_id}_{time_ms}", payload)
    return payload


@dataclass
class TrendSnapshot:
    component_id: str
    point_type: str
    bearing_id: str | None
    bearing_direction: str | None
    owner_device_id: str | None
    owner_device_name: str | None
    feature: str
    current: float | None
    mean: float | None
    std: float | None
    trend_class: str
    rise_count: int
    volatility_count: int
    max_relative_rise: float
    max_rise_confidence: float
    max_volatility_score: float
    alarm_status: str | None
    narrative_summary: str | None
    raw_feature_stats: dict[str, Any]
    point_name: str | None = None
    bearing_types: tuple[str, ...] = ()
    seg_alarm_status: str | None = None
    dominant_state: str | None = None
    level_regime: str | None = None
    volatility_regime: str | None = None
    overall_direction: str | None = None
    over_threshold_ratio: float = 0.0
    max_over_threshold_duration: float = 0.0
    step_change_relative: float = 0.0
    step_change_magnitude: float = 0.0
    changepoint_types: tuple[str, ...] = ()
    window: str = "30d"  # "1d" | "3d" | "30d"


@dataclass
class TrendCollectionResult:
    snapshots: list[TrendSnapshot]
    failures: list[dict[str, Any]]
    raw_30d_data: dict[str, Any] | None = None


@dataclass(frozen=True)
class DiagnosisTarget:
    root_device_id: str
    owner_device_id: str | None
    owner_device_name: str | None
    target_device_type: str
    target_info: dict[str, Any]


PROCESS_PARAMETER_POINT_TYPES: tuple[str, ...] = (
    "润滑油温度",
    "防喘振阀开度",
    "压缩机进气参数",
    "出口温度",
    "入口流量",
    "其他工艺参数",
    "其他",
)
GENERIC_PROCESS_SYNC_POINT_TYPES: frozenset[str] = frozenset(
    point_type for point_type in PROCESS_PARAMETER_POINT_TYPES if point_type != "润滑油温度"
)


def _safe_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        numeric = float(value)
        if math.isfinite(numeric):
            return numeric
    return None


def _clip_score(value: float) -> float:
    return max(0.0, min(1.0, value))


def _best_device_type_alias_match(text: str, config: dict[str, Any]) -> str | None:
    lowered = text.lower()
    best_match: tuple[int, int, str] | None = None
    for canonical, keywords in (config.get("device_type_aliases") or {}).items():
        for keyword in keywords:
            alias = str(keyword or "").strip()
            if not alias:
                continue
            lowered_alias = alias.lower()
            if lowered_alias not in lowered:
                continue
            score = (1 if lowered == lowered_alias else 0, len(alias))
            if best_match is None or score > best_match[:2]:
                best_match = (score[0], score[1], str(canonical))
    return best_match[2] if best_match else None


def _normalize_device_type(device_type: str, config: dict[str, Any]) -> str:
    text = str(device_type or "").strip()
    if text in (config.get("fault_mapping") or {}):
        return text
    matched = _best_device_type_alias_match(text, config)
    if matched:
        return matched
    return "汽轮机" if not text or text == "未知" else text


def _range_value(snapshot: TrendSnapshot) -> float:
    return _safe_float(snapshot.raw_feature_stats.get("range")) or 0.0


def _normalized_feature_list(point_type: str, feature_list: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_item in feature_list:
        item = str(raw_item).strip()
        if not item or item in seen:
            continue
        seen.add(item)
        normalized.append(item)
    return normalized


def _normalize_segment_alarm_status(value: Any) -> str | None:
    text = str(value or "").strip().upper()
    mapping = {
        "HH": "hh",
        "H": "h",
        "LL": "ll",
        "L": "l",
    }
    return mapping.get(text)


def _merge_trend_feature_stats(
    primary_detail: dict[str, Any],
    segmented_detail: dict[str, Any] | None,
) -> dict[str, Any]:
    merged = dict(primary_detail)
    if not isinstance(segmented_detail, dict):
        return merged

    for key in (
        "changepoints",
        "step_change_magnitude",
        "step_change_relative",
        "alarm_status",
        "over_threshold_time",
        "max_over_threshold_duration",
        "over_threshold_ratio",
        "segment_stats",
        "dominant_state",
        "level_regime",
        "volatility_regime",
        "overall_direction",
    ):
        if key in segmented_detail:
            merged[key] = segmented_detail.get(key)
    return merged


def _resolve_target(context: DeviceContext, sub_device_id: str, root_device_id: str, config: dict[str, Any]) -> DiagnosisTarget:
    target_info = resolve_sub_device_targets(context, sub_device_id)
    owner_device_id = str(target_info.get("owner_device_id") or "") or None
    owner_device_name = None

    if owner_device_id:
        for probe in context.probes:
            if probe.owner_device_id == owner_device_id and probe.owner_device_name:
                owner_device_name = probe.owner_device_name
                break
        if owner_device_name is None:
            for bearing in context.bearings:
                if bearing.owner_device_id == owner_device_id and bearing.owner_device_name:
                    owner_device_name = bearing.owner_device_name
                    break

    # Prefer the LLM-inferred type stored on the tree node (type_num=80 → type field)
    llm_type = context.rotor_device_type_map.get(owner_device_id or "") or context.rotor_device_type_map.get(sub_device_id, "")
    if llm_type and llm_type in (config.get("fault_mapping") or {}):
        target_device_type = llm_type
    else:
        target_device_type = _normalize_device_type(llm_type or owner_device_name or context.device_type, config)
    return DiagnosisTarget(
        root_device_id=root_device_id,
        owner_device_id=owner_device_id,
        owner_device_name=owner_device_name,
        target_device_type=target_device_type,
        target_info=target_info,
    )


def _build_component_features(
    context: DeviceContext,
    target_info: dict[str, Any],
    config: dict[str, Any],
    sub_device_id: str | None = None,
) -> dict[str, list[str]]:
    feature_map = config.get("trend_feature_map") or {}
    component_features: dict[str, list[str]] = {}
    probe_ids = [str(item) for item in (target_info.get("probe_ids") or [])]
    owner_device_id = str(target_info.get("owner_device_id") or "")

    # 构建目标测点 ID 集合（resolve_sub_device_targets 已正确过滤）
    target_probe_ids: set[str] = set(probe_ids)

    for probe_id in probe_ids:
        probe = context.probe_index.get(probe_id)
        if probe is None:
            continue
        feature_list = feature_map.get(probe.point_type)
        if isinstance(feature_list, list) and feature_list:
            component_features[probe_id] = _normalized_feature_list(probe.point_type, feature_list)

    for process_probe in context.process_points:
        # 只包含 point_id 已在 target_probe_ids 中的工艺参数
        # （InS 树扁平化导致所有测点挂在同一个轴承下，owner_device_id 无法准确过滤）
        if process_probe.point_id not in target_probe_ids:
            continue
        feature_list = feature_map.get(process_probe.point_type) or feature_map.get("其他工艺参数")
        if isinstance(feature_list, list) and feature_list:
            component_features[process_probe.point_id] = _normalized_feature_list(process_probe.point_type, feature_list)

    return component_features


def _alarm_status(current: float | None, h_alarm: float | None, hh_alarm: float | None, thresholds: dict[str, Any]) -> str | None:
    if current is None:
        return None
    hh_ratio = _safe_float(thresholds.get("hh_alarm_ratio")) or 1.0
    h_ratio = _safe_float(thresholds.get("high_alarm_ratio")) or 1.0
    if hh_alarm is not None and current >= hh_alarm * hh_ratio:
        return "hh"
    if h_alarm is not None and current >= h_alarm * h_ratio:
        return "h"
    return None


def _classify_trend(rise_count: int, volatility_count: int) -> str:
    if rise_count > 0 and volatility_count > 0:
        return "rising_volatile"
    if rise_count > 0:
        return "rising"
    if volatility_count > 0:
        return "volatile"
    return "stable"


def _group_process_items_by_type(trends: list[TrendSnapshot]) -> dict[str, list[TrendSnapshot]]:
    grouped: dict[str, list[TrendSnapshot]] = {point_type: [] for point_type in PROCESS_PARAMETER_POINT_TYPES}
    for item in trends:
        bucket = grouped.get(item.point_type)
        if bucket is not None:
            bucket.append(item)
    return grouped


def _summarize_process_items_by_type(
    process_items_by_type: dict[str, list[TrendSnapshot]],
    rise_threshold: float,
    volatility_threshold: float,
) -> dict[str, dict[str, Any]]:
    summary: dict[str, dict[str, Any]] = {}
    for point_type in PROCESS_PARAMETER_POINT_TYPES:
        items = process_items_by_type.get(point_type) or []
        point_states: dict[str, dict[str, Any]] = {}
        for item in items:
            point_key = str(item.component_id or item.point_name or "")
            if not point_key:
                continue
            state = point_states.setdefault(
                point_key,
                {
                    "point_name": item.point_name or point_key,
                    "rise": False,
                    "volatility": False,
                    "alarm": False,
                },
            )
            if item.rise_count > 0 and item.max_relative_rise >= rise_threshold:
                state["rise"] = True
            if item.volatility_count > 0 and item.max_volatility_score >= volatility_threshold:
                state["volatility"] = True
            if item.alarm_status in {"h", "hh"}:
                state["alarm"] = True

        rise_count = sum(1 for state in point_states.values() if bool(state.get("rise")))
        volatility_count = sum(1 for state in point_states.values() if bool(state.get("volatility")))
        alarm_count = sum(1 for state in point_states.values() if bool(state.get("alarm")))
        active_point_names = [
            str(state.get("point_name") or "")
            for state in point_states.values()
            if bool(state.get("rise")) or bool(state.get("volatility")) or bool(state.get("alarm"))
        ]
        summary[point_type] = {
            "rise_count": rise_count,
            "volatility_count": volatility_count,
            "alarm_count": alarm_count,
            "point_count": len(point_states),
            "anomaly_count": sum(
                1
                for state in point_states.values()
                if bool(state.get("rise")) or bool(state.get("volatility")) or bool(state.get("alarm"))
            ),
            "active_point_names": active_point_names[:5],
        }
    return summary


def _build_process_signal_profile(process_type_summary: dict[str, dict[str, Any]]) -> dict[str, Any]:
    def _aggregate(point_types: tuple[str, ...] | list[str] | frozenset[str]) -> dict[str, int]:
        normalized = tuple(str(point_type) for point_type in point_types)
        return {
            "anomaly_count": sum(int((process_type_summary.get(point_type) or {}).get("anomaly_count") or 0) for point_type in normalized),
            "active_type_count": sum(
                1
                for point_type in normalized
                if int((process_type_summary.get(point_type) or {}).get("anomaly_count") or 0) > 0
            ),
            "point_count": sum(int((process_type_summary.get(point_type) or {}).get("point_count") or 0) for point_type in normalized),
        }

    surge = _aggregate(("防喘振阀开度", "入口流量"))
    gas_path = _aggregate(("压缩机进气参数", "出口温度"))
    load_related = _aggregate(("其他工艺参数", "其他"))
    lube_related = _aggregate(("润滑油温度",))
    generic = _aggregate(GENERIC_PROCESS_SYNC_POINT_TYPES)

    surge_support_strength = 1.0 if surge["active_type_count"] >= 2 else (0.65 if surge["active_type_count"] == 1 else 0.0)
    gas_path_support_strength = 0.9 if gas_path["active_type_count"] >= 2 else (0.45 if gas_path["active_type_count"] == 1 else 0.0)
    load_support_strength = 0.85 if load_related["active_type_count"] >= 2 else (0.6 if load_related["active_type_count"] == 1 else 0.0)

    fluid_support_strength = min(
        1.0,
        surge_support_strength * 0.75
        + gas_path_support_strength * 0.35,
    )
    process_sync_support_strength = max(
        0.0,
        min(
            1.0,
            load_support_strength * 0.85
            + (0.10 if generic["active_type_count"] >= 2 else 0.0)
            - (0.20 if surge["active_type_count"] > 0 else 0.0),
        ),
    )

    return {
        "generic_anomaly_count": generic["anomaly_count"],
        "generic_active_type_count": generic["active_type_count"],
        "surge_anomaly_count": surge["anomaly_count"],
        "surge_active_type_count": surge["active_type_count"],
        "gas_path_anomaly_count": gas_path["anomaly_count"],
        "gas_path_active_type_count": gas_path["active_type_count"],
        "load_anomaly_count": load_related["anomaly_count"],
        "load_active_type_count": load_related["active_type_count"],
        "lube_anomaly_count": lube_related["anomaly_count"],
        "lube_active_type_count": lube_related["active_type_count"],
        "fluid_support_strength": round(fluid_support_strength, 4),
        "process_sync_support_strength": round(process_sync_support_strength, 4),
    }


def _slice_trend_data_by_window(raw_payload: dict[str, Any], window_days: int, end_ms: int) -> dict[str, Any]:
    """Slice 30-day trend data in-memory to produce a smaller window subset.

    Since the 30d fetch contains all data points, we can filter by time_ms
    to get 1d / 3d subsets without additional HTTP calls.
    """
    if window_days >= 30:
        return raw_payload  # 30d = full data, no slicing needed
    window_ms = window_days * 24 * 3600 * 1000
    start_ms_threshold = str(max(0, end_ms - window_ms))
    component_ids = raw_payload.get("component_ids") or []
    data = raw_payload.get("data") or {}
    sliced: dict[str, list[Any]] = {}
    for cid in component_ids:
        points = data.get(cid) or []
        sliced[cid] = [p for p in points if str(p.get("time_ms") or "") >= start_ms_threshold]
    return {**raw_payload, "data": sliced}


async def _collect_trend_snapshots(
    context: DeviceContext,
    target_info: dict[str, Any],
    time_ms: str,
    config: dict[str, Any],
    sub_device_id: str | None = None,
) -> TrendCollectionResult:
    component_features = _build_component_features(context, target_info, config, sub_device_id=sub_device_id)
    if not component_features:
        return TrendCollectionResult(
            snapshots=[],
            failures=[
                {
                    "stage": "build_component_features",
                    "reason": "empty_component_features",
                    "target_info": {
                        "target_kind": target_info.get("target_kind"),
                        "owner_device_id": target_info.get("owner_device_id"),
                        "probe_count": len([str(item) for item in (target_info.get("probe_ids") or []) if str(item)]),
                    },
                }
            ],
        )

    end_ms = int(datetime_input_to_ms(time_ms))
    window_days = int(_safe_float(config.get("trend_window_days")) or 30)
    windows: list[tuple[str, int]] = [
        ("1d", 1),
        ("3d", 3),
        ("30d", window_days),
    ]

    # ── Step 1: Fetch 30d raw data ONCE (saves 2 HTTP round-trips) ──────
    window_30d_ms = window_days * 24 * 3600 * 1000
    start_30d_ms = str(max(0, end_ms - window_30d_ms))
    try:
        raw_30d = await cached_get_trend_data(
            component_features=component_features,
            start=start_30d_ms,
            end=str(end_ms),
        )
    except Exception as exc:
        return TrendCollectionResult(
            snapshots=[],
            failures=[{
                "window": "30d",
                "stage": "get_trend_data",
                "start_ms": start_30d_ms,
                "end_ms": str(end_ms),
                "component_count": len(component_features),
                "feature_union": collect_union_features(component_features),
                "component_features": component_features,
                "error": str(exc),
            }],
        )

    # Validate that we got some data
    raw_data = raw_30d.get("data") or {}
    if not any(raw_data.get(cid) for cid in raw_30d.get("component_ids") or []):
        return TrendCollectionResult(
            snapshots=[],
            failures=[{
                "window": "30d",
                "stage": "get_trend_data",
                "start_ms": start_30d_ms,
                "end_ms": str(end_ms),
                "component_count": len(component_features),
                "reason": "empty_trend_data",
                "component_ids": raw_30d.get("component_ids") or [],
            }],
            raw_30d_data=raw_30d,
        )

    # ── Step 2: Slice 30d data in-memory for 1d / 3d ────────────────────
    raw_by_window: dict[str, dict[str, Any]] = {}
    for label, days in windows:
        raw_by_window[label] = _slice_trend_data_by_window(raw_30d, days, end_ms)

    # ── Step 3: All feature extraction tasks in parallel (3 windows × 2 = 6) ─
    extraction_tasks: list[Any] = []
    task_labels: list[tuple[str, str]] = []  # (window_label, "trend"|"segmented")
    for label, _days in windows:
        raw = raw_by_window[label]
        extraction_tasks.append(cached_extract_trend_features(trend_data_payload=raw))
        task_labels.append((label, "trend"))
        extraction_tasks.append(cached_extract_segmented_trend_features(trend_data_payload=raw))
        task_labels.append((label, "segmented"))

    extraction_results = await asyncio.gather(*extraction_tasks, return_exceptions=True)

    # Map results back to per-window payloads
    trend_payloads: dict[str, dict[str, Any]] = {}
    segmented_payloads: dict[str, dict[str, Any]] = {}
    all_failures: list[dict[str, Any]] = []
    for idx, ((label, kind), result) in enumerate(zip(task_labels, extraction_results)):
        if isinstance(result, Exception):
            all_failures.append({
                "window": label,
                "stage": f"extract_{'trend' if kind == 'trend' else 'segmented_trend'}_features",
                "error": str(result),
            })
            continue
        if kind == "trend":
            trend_payloads[label] = result
        else:
            segmented_payloads[label] = result

    # ── Step 4: Build TrendSnapshot per window (pure in-memory) ─────────
    all_snapshots: list[TrendSnapshot] = []
    for label, _days in windows:
        trend_payload = trend_payloads.get(label)
        if not trend_payload:
            continue
        segmented_payload = segmented_payloads.get(label, {"point_results": []})
        thresholds = config.get("thresholds") or {}
        raw = raw_by_window[label]
        window_ms = _days * 24 * 3600 * 1000
        start_ms = str(max(0, end_ms - window_ms))

        segmented_results = {
            str(pr.get("component_id") or ""): pr
            for pr in (segmented_payload.get("point_results") or [])
            if isinstance(pr, dict)
        }
        for point_result in trend_payload.get("point_results") or []:
            component_id = str(point_result.get("component_id") or "")
            probe = context.probe_index.get(component_id)
            if probe is None:
                continue
            segmented_point_result = segmented_results.get(component_id) or {}
            segmented_feature_stats = segmented_point_result.get("feature_stats") or {}
            feature_stats = point_result.get("feature_stats") or {}
            if not isinstance(feature_stats, dict):
                continue
            for feature, detail in feature_stats.items():
                if not isinstance(detail, dict):
                    continue
                segmented_detail = segmented_feature_stats.get(feature) if isinstance(segmented_feature_stats, dict) else None
                merged_detail = _merge_trend_feature_stats(detail, segmented_detail if isinstance(segmented_detail, dict) else None)
                rising_periods = detail.get("rising_periods") or []
                high_volatility_periods = detail.get("high_volatility_periods") or []
                relative_rises = [_safe_float(item.get("relative_rise")) or 0.0 for item in rising_periods if isinstance(item, dict)]
                rise_confidences = [_safe_float(item.get("confidence")) or 0.0 for item in rising_periods if isinstance(item, dict)]
                volatility_scores = [_safe_float(item.get("peak_volatility_score")) or 0.0 for item in high_volatility_periods if isinstance(item, dict)]
                current = _safe_float(detail.get("current"))
                seg_alarm_status = _normalize_segment_alarm_status((segmented_detail or {}).get("alarm_status"))
                normalized_alarm = _alarm_status(current, probe.h_alarm, probe.hh_alarm, thresholds) or seg_alarm_status
                changepoint_types = tuple(
                    str(item.get("type"))
                    for item in ((segmented_detail or {}).get("changepoints") or [])
                    if isinstance(item, dict) and item.get("type")
                )
                all_snapshots.append(
                    TrendSnapshot(
                        component_id=component_id,
                        point_type=probe.point_type,
                        bearing_id=probe.bearing_id,
                        bearing_direction=probe.bearing_direction,
                        owner_device_id=probe.owner_device_id,
                        owner_device_name=probe.owner_device_name,
                        feature=str(feature),
                        current=current,
                        mean=_safe_float(detail.get("mean")),
                        std=_safe_float(detail.get("std")),
                        trend_class=_classify_trend(len(rising_periods), len(high_volatility_periods)),
                        rise_count=len(rising_periods),
                        volatility_count=len(high_volatility_periods),
                        max_relative_rise=max(relative_rises) if relative_rises else 0.0,
                        max_rise_confidence=max(rise_confidences) if rise_confidences else 0.0,
                        max_volatility_score=max(volatility_scores) if volatility_scores else 0.0,
                        alarm_status=normalized_alarm,
                        narrative_summary=str(detail.get("narrative_summary") or "") or None,
                        raw_feature_stats=merged_detail,
                        point_name=probe.point_name,
                        bearing_types=tuple(str(item) for item in (probe.bearing_types or [])),
                        seg_alarm_status=seg_alarm_status,
                        dominant_state=str((segmented_detail or {}).get("dominant_state") or "") or None,
                        level_regime=str((segmented_detail or {}).get("level_regime") or "") or None,
                        volatility_regime=str((segmented_detail or {}).get("volatility_regime") or "") or None,
                        overall_direction=str((segmented_detail or {}).get("overall_direction") or "") or None,
                        over_threshold_ratio=_safe_float((segmented_detail or {}).get("over_threshold_ratio")) or 0.0,
                        max_over_threshold_duration=_safe_float((segmented_detail or {}).get("max_over_threshold_duration")) or 0.0,
                        step_change_relative=_safe_float((segmented_detail or {}).get("step_change_relative")) or 0.0,
                        step_change_magnitude=_safe_float((segmented_detail or {}).get("step_change_magnitude")) or 0.0,
                        changepoint_types=changepoint_types,
                        window=label,
                    )
                )
    return TrendCollectionResult(snapshots=all_snapshots, failures=all_failures, raw_30d_data=raw_30d)


def _select_anomaly_times(trend_snapshots: list[TrendSnapshot], input_time_ms: str) -> list[str]:
    # 优先用 30d 窗口的快照（时间范围最完整），其次用 3d
    preferred = [s for s in trend_snapshots if s.window == "30d"] or [s for s in trend_snapshots if s.window == "3d"] or trend_snapshots
    scored_times: list[tuple[float, str]] = []
    for snapshot in preferred:
        for item in snapshot.raw_feature_stats.get("rising_periods") or []:
            if not isinstance(item, dict):
                continue
            end_time = str(item.get("end_time_ms") or "")
            if not end_time:
                continue
            score = (_safe_float(item.get("relative_rise")) or 0.0) + (_safe_float(item.get("confidence")) or 0.0)
            scored_times.append((score, end_time))
        for item in snapshot.raw_feature_stats.get("high_volatility_periods") or []:
            if not isinstance(item, dict):
                continue
            end_time = str(item.get("end_time_ms") or "")
            if not end_time:
                continue
            score = (_safe_float(item.get("peak_volatility_score")) or 0.0) + (_safe_float(item.get("confidence")) or 0.0)
            scored_times.append((score, end_time))
        for item in snapshot.raw_feature_stats.get("changepoints") or []:
            if not isinstance(item, dict):
                continue
            time_ms = str(item.get("time_ms") or "")
            if not time_ms:
                continue
            score = (
                (_safe_float(item.get("score")) or 0.0)
                + (_safe_float(item.get("relative_change")) or 0.0)
                + (_safe_float(item.get("magnitude")) or 0.0) * 0.05
            )
            scored_times.append((score, time_ms))

    scored_times.sort(key=lambda item: item[0], reverse=True)
    candidates = [time_ms for _, time_ms in scored_times[:6]]
    candidates.append(str(input_time_ms))

    deduped: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        if item and item not in seen:
            seen.add(item)
            deduped.append(item)
    return deduped[:3]


async def _resolve_waveform_times(
    waveform_probe_ids: list[str],
    trend_snapshots: list[TrendSnapshot],
    input_time_ms: str,
    config: dict[str, Any],
) -> list[str]:
    """
    从原始趋势数据中选取有代表性的精确毫秒时间戳，用于波形和轨迹查询。

    策略：
    1. 从 trend_snapshots 的轴振测点里，收集 _build_summary_for_feature 标注的
       rising_periods 和 high_volatility_periods 时间区间
    2. 对每个区间，查询该区间内的原始 pp_value 数据，取区间内 pp_value 最大的点
    3. 若无任何异常区间，fallback：查整个趋势窗口，取全局峰值点 + 最接近输入时间的点
    4. 始终包含最接近输入时间的实际数据点
    5. 去重后最多返回 3 个时间戳，按时间倒序排列
    """
    if not waveform_probe_ids:
        return [str(input_time_ms)]

    probe_id = waveform_probe_ids[0]
    input_int = int(input_time_ms)

    # 收集所有异常区间 (start_ms, end_ms, score)，用 1d 窗口（最近的异常最有代表性）
    anomaly_ranges: list[tuple[int, int, float]] = []
    preferred_snapshots = [s for s in trend_snapshots if s.window == "1d" and s.point_type == "轴振"] \
        or [s for s in trend_snapshots if s.point_type == "轴振"]
    changepoint_window_ms = 30 * 60 * 1000
    for snapshot in preferred_snapshots:
        for item in snapshot.raw_feature_stats.get("rising_periods") or []:
            if not isinstance(item, dict):
                continue
            s = _safe_float(item.get("start_time_ms"))
            e = _safe_float(item.get("end_time_ms"))
            if s and e and e > s:
                score = (_safe_float(item.get("relative_rise")) or 0.0) + (_safe_float(item.get("confidence")) or 0.0)
                anomaly_ranges.append((int(s), int(e), score))
        for item in snapshot.raw_feature_stats.get("high_volatility_periods") or []:
            if not isinstance(item, dict):
                continue
            s = _safe_float(item.get("start_time_ms"))
            e = _safe_float(item.get("end_time_ms"))
            if s and e and e > s:
                score = (_safe_float(item.get("peak_volatility_score")) or 0.0) + (_safe_float(item.get("confidence")) or 0.0)
                anomaly_ranges.append((int(s), int(e), score))
        for item in snapshot.raw_feature_stats.get("changepoints") or []:
            if not isinstance(item, dict):
                continue
            ts = _safe_float(item.get("time_ms"))
            if ts is None:
                continue
            score = (
                (_safe_float(item.get("score")) or 0.0)
                + (_safe_float(item.get("relative_change")) or 0.0)
                + (_safe_float(item.get("magnitude")) or 0.0) * 0.05
            )
            anomaly_ranges.append(
                (
                    max(0, int(ts) - changepoint_window_ms),
                    int(ts) + changepoint_window_ms,
                    score,
                )
            )

    # 按 score 降序，取前 2 个区间
    anomaly_ranges.sort(key=lambda x: x[2], reverse=True)
    top_ranges = anomaly_ranges[:2]

    candidates: dict[str, float] = {}  # ts -> pp_value

    async def _fetch_peak_in_range(start: int, end: int) -> str | None:
        """查询区间内 pp_value 最大的时间戳"""
        try:
            raw = await cached_get_trend_data(
                component_features={probe_id: ["pp_value"]},
                start=str(start),
                end=str(end),
            )
            points = (raw.get("data") or {}).get(probe_id) or []
            best_ts: str | None = None
            best_val = float("-inf")
            for point in points:
                ts = str(point.get("time_ms") or "")
                val = _safe_float((point.get("values") or {}).get("pp_value"))
                if ts and val is not None and val > best_val:
                    best_val = val
                    best_ts = ts
            if best_ts:
                candidates[best_ts] = best_val
            return best_ts
        except Exception:
            return None

    if top_ranges:
        # 从各异常区间内取峰值点
        for start, end, _ in top_ranges:
            await _fetch_peak_in_range(start, end)

        # 取最接近输入时间的实际数据点（在最近的异常区间附近查）
        nearest_range_end = max(e for _, e, _ in top_ranges)
        window = 2 * 60 * 60 * 1000  # 前后 2 小时
        try:
            raw = await cached_get_trend_data(
                component_features={probe_id: ["pp_value"]},
                start=str(max(0, input_int - window)),
                end=str(input_int + window),
            )
            points = (raw.get("data") or {}).get(probe_id) or []
            best_ts: str | None = None
            best_diff = float("inf")
            for point in points:
                ts = str(point.get("time_ms") or "")
                val = _safe_float((point.get("values") or {}).get("pp_value"))
                if ts:
                    diff = abs(int(ts) - input_int)
                    if diff < best_diff:
                        best_diff = diff
                        best_ts = ts
                        best_val_input = val or 0.0
            if best_ts:
                candidates.setdefault(best_ts, best_val_input)
        except Exception:
            candidates.setdefault(str(input_time_ms), 0.0)
    else:
        # fallback：查输入时间前后各 1 天窗口，找峰值 + 最接近的时间戳
        window_ms = 24 * 3600 * 1000
        try:
            raw = await cached_get_trend_data(
                component_features={probe_id: ["pp_value"]},
                start=str(max(0, input_int - window_ms)),
                end=str(input_int + window_ms),
            )
            points = (raw.get("data") or {}).get(probe_id) or []
            best_peak_ts: str | None = None
            best_peak_val = float("-inf")
            best_close_ts: str | None = None
            best_close_diff = float("inf")
            for point in points:
                ts = str(point.get("time_ms") or "")
                val = _safe_float((point.get("values") or {}).get("pp_value"))
                if not ts:
                    continue
                if val is not None and val > best_peak_val:
                    best_peak_val = val
                    best_peak_ts = ts
                diff = abs(int(ts) - input_int)
                if diff < best_close_diff:
                    best_close_diff = diff
                    best_close_ts = ts
            if best_peak_ts:
                candidates[best_peak_ts] = best_peak_val
            if best_close_ts:
                candidates.setdefault(best_close_ts, 0.0)
        except Exception:
            candidates[str(input_time_ms)] = 0.0

    if not candidates:
        return [str(input_time_ms)]

    # 按 pp_value 降序取前 3，再按时间倒序排列
    sorted_by_val = sorted(candidates.items(), key=lambda x: x[1], reverse=True)[:3]
    result = sorted(
        [ts for ts, _ in sorted_by_val],
        key=lambda ts: int(ts),
        reverse=True,
    )
    return result


def _resolve_waveform_times_from_trend(
    waveform_probe_ids: list[str],
    trend_raw_data: dict[str, Any],
    trend_snapshots: list[TrendSnapshot],
    input_time_ms: str,
) -> list[str]:
    """Resolve waveform timestamps from already-fetched trend data (zero API calls).

    The 30d trend fetch includes pp_value for all probes. Instead of making
    additional HTTP calls to find peak timestamps (as _resolve_waveform_times does),
    we search pp_value directly from the in-memory trend data.

    This eliminates 4-6 redundant API calls per diagnosis run.
    """
    if not waveform_probe_ids:
        return [str(input_time_ms)]

    probe_id = waveform_probe_ids[0]
    input_int = int(input_time_ms)

    # Get pp_value series from the already-fetched 30d trend data
    trend_points = (trend_raw_data.get("data") or {}).get(probe_id) or []

    # Collect anomaly ranges from trend snapshots (same logic as original)
    anomaly_ranges: list[tuple[int, int, float]] = []
    preferred_snapshots = [s for s in trend_snapshots if s.window == "1d" and s.point_type == "轴振"] \
        or [s for s in trend_snapshots if s.point_type == "轴振"]
    changepoint_window_ms = 30 * 60 * 1000
    for snapshot in preferred_snapshots:
        for item in snapshot.raw_feature_stats.get("rising_periods") or []:
            if not isinstance(item, dict):
                continue
            s = _safe_float(item.get("start_time_ms"))
            e = _safe_float(item.get("end_time_ms"))
            if s and e and e > s:
                score = (_safe_float(item.get("relative_rise")) or 0.0) + (_safe_float(item.get("confidence")) or 0.0)
                anomaly_ranges.append((int(s), int(e), score))
        for item in snapshot.raw_feature_stats.get("high_volatility_periods") or []:
            if not isinstance(item, dict):
                continue
            s = _safe_float(item.get("start_time_ms"))
            e = _safe_float(item.get("end_time_ms"))
            if s and e and e > s:
                score = (_safe_float(item.get("peak_volatility_score")) or 0.0) + (_safe_float(item.get("confidence")) or 0.0)
                anomaly_ranges.append((int(s), int(e), score))
        for item in snapshot.raw_feature_stats.get("changepoints") or []:
            if not isinstance(item, dict):
                continue
            ts = _safe_float(item.get("time_ms"))
            if ts is None:
                continue
            score = (
                (_safe_float(item.get("score")) or 0.0)
                + (_safe_float(item.get("relative_change")) or 0.0)
                + (_safe_float(item.get("magnitude")) or 0.0) * 0.05
            )
            anomaly_ranges.append((max(0, int(ts) - changepoint_window_ms), int(ts) + changepoint_window_ms, score))

    anomaly_ranges.sort(key=lambda x: x[2], reverse=True)
    top_ranges = anomaly_ranges[:2]

    candidates: dict[str, float] = {}  # ts -> pp_value

    def _find_peak_in_range(start: int, end: int) -> tuple[str | None, float]:
        """Find the timestamp with highest pp_value within [start, end] from in-memory data."""
        best_ts: str | None = None
        best_val = float("-inf")
        for point in trend_points:
            ts = str(point.get("time_ms") or "")
            if not ts:
                continue
            ts_int = int(ts)
            if ts_int < start or ts_int > end:
                continue
            val = _safe_float((point.get("values") or {}).get("pp_value"))
            if val is not None and val > best_val:
                best_val = val
                best_ts = ts
        return best_ts, best_val if best_ts else (None, float("-inf"))

    def _find_nearest_in_window(start: int, end: int) -> tuple[str | None, float]:
        """Find the timestamp closest to input_time_ms within [start, end] from in-memory data."""
        best_ts: str | None = None
        best_diff = float("inf")
        best_val = 0.0
        for point in trend_points:
            ts = str(point.get("time_ms") or "")
            if not ts:
                continue
            ts_int = int(ts)
            if ts_int < start or ts_int > end:
                continue
            diff = abs(ts_int - input_int)
            if diff < best_diff:
                best_diff = diff
                best_ts = ts
                best_val = _safe_float((point.get("values") or {}).get("pp_value")) or 0.0
        return best_ts, best_val

    if top_ranges:
        # Find peaks in each top anomaly range (in-memory, zero API calls)
        for start, end, _ in top_ranges:
            ts, val = _find_peak_in_range(start, end)
            if ts:
                candidates[ts] = val

        # Find nearest to input time around the closest anomaly range
        nearest_range_end = max(e for _, e, _ in top_ranges)
        window = 2 * 60 * 60 * 1000  # ±2 hours
        ts, val = _find_nearest_in_window(max(0, input_int - window), input_int + window)
        if ts:
            candidates.setdefault(ts, val)
        else:
            candidates.setdefault(str(input_time_ms), 0.0)
    else:
        # Fallback: search ±1 day around input time
        window_ms = 24 * 3600 * 1000
        ts_peak, val_peak = _find_peak_in_range(max(0, input_int - window_ms), input_int + window_ms)
        ts_near, val_near = _find_nearest_in_window(max(0, input_int - window_ms), input_int + window_ms)
        if ts_peak:
            candidates[ts_peak] = val_peak
        if ts_near:
            candidates.setdefault(ts_near, val_near)
        if not candidates:
            candidates[str(input_time_ms)] = 0.0

    if not candidates:
        return [str(input_time_ms)]

    # Sort by pp_value descending, take top 3, then sort by time descending
    sorted_by_val = sorted(candidates.items(), key=lambda x: x[1], reverse=True)[:3]
    return sorted(
        [ts for ts, _ in sorted_by_val],
        key=lambda ts: int(ts),
        reverse=True,
    )


async def _collect_waveform_results(target_info: dict[str, Any], times_ms: list[str], config: dict[str, Any]) -> list[dict[str, Any]]:
    import asyncio
    waveform_probe_ids = [str(item) for item in (target_info.get("waveform_probe_ids") or [])]
    results: list[dict[str, Any]] = []

    # 构建所有提取任务
    tasks = []
    for component_id in waveform_probe_ids:
        for time_ms in times_ms:
            tasks.append(cached_extract_waveform(component_id=component_id, time_ms=time_ms))

    # 并行执行
    if tasks:
        task_results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in task_results:
            if not isinstance(result, Exception):
                results.append(result)

    return results


def _bearing_waveform_probe_ids(context: DeviceContext, bearing_id: str) -> list[str]:
    bearing_probe_ids = [str(item) for item in (context.bearing_probe_map.get(bearing_id) or []) if str(item)]
    shaft_vibration_ids = [
        point_id
        for point_id in bearing_probe_ids
        if (context.probe_index.get(point_id) and context.probe_index[point_id].point_type == "轴振")
    ]
    return shaft_vibration_ids or bearing_probe_ids[:2]


async def _collect_orbit_results(
    root_device_id: str,
    context: DeviceContext,
    target_info: dict[str, Any],
    times_ms: list[str],
    config: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    bearing_ids = [str(item) for item in (target_info.get("bearing_ids") or [])]
    max_points = int(_safe_float(config.get("max_orbit_points")) or 2)
    if not root_device_id:
        return [], []
    results: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []

    # 构建所有 (bearing_id, time_ms) 组合的提取任务
    extraction_tasks = []
    task_metadata = []  # 用于记录每个任务对应的 metadata
    for bearing_id in bearing_ids[:max_points]:
        probe_ids = _bearing_waveform_probe_ids(context, bearing_id)
        for time_ms in times_ms:
            extraction_tasks.append(
                cached_extract_orbit(
                    root_device_id=root_device_id,
                    bearing_id=bearing_id,
                    time_ms=time_ms,
                    probe_ids=probe_ids,
                )
            )
            task_metadata.append((bearing_id, time_ms, probe_ids))

    # 并行执行所有提取任务
    if extraction_tasks:
        task_results = await asyncio.gather(*extraction_tasks, return_exceptions=True)
        for (bearing_id, time_ms, probe_ids), result in zip(task_metadata, task_results):
            if isinstance(result, Exception):
                failures.append(
                    {
                        "bearing_id": bearing_id,
                        "time_ms": time_ms,
                        "probe_ids": ",".join(probe_ids),
                        "error": str(result),
                    }
                )
                print(f"[orbit.fail] machine_id={root_device_id} bearing_id={bearing_id} time_ms={time_ms} error={result}")
            else:
                results.append(result)

    return results, failures


def _trend_filter(trends: list[TrendSnapshot], *, point_type: str | None = None, feature: str | None = None) -> list[TrendSnapshot]:
    items = trends
    if point_type is not None:
        items = [item for item in items if item.point_type == point_type]
    if feature is not None:
        items = [item for item in items if item.feature == feature]
    return items


def _count_alarm(items: list[TrendSnapshot]) -> int:
    return sum(1 for item in items if item.alarm_status in {"h", "hh"})


def _count_rising(items: list[TrendSnapshot], relative_threshold: float = 0.0) -> int:
    return sum(1 for item in items if item.rise_count > 0 and item.max_relative_rise >= relative_threshold)


def _count_volatile(items: list[TrendSnapshot], min_score: float = 0.0) -> int:
    return sum(1 for item in items if item.volatility_count > 0 and item.max_volatility_score >= min_score)


def _count_large_ranges(items: list[TrendSnapshot], threshold: float) -> int:
    return sum(1 for item in items if _range_value(item) >= threshold)


def _count_gap_stable(items: list[TrendSnapshot], threshold: float) -> int:
    return sum(1 for item in items if _range_value(item) <= threshold)


def _count_high_deviation(items: list[TrendSnapshot], ratio: float) -> int:
    count = 0
    for item in items:
        if item.current is None or item.mean is None:
            continue
        if item.current >= item.mean + max(abs(item.mean) * ratio, item.std or 0.0):
            count += 1
    return count


def _count_dominant_state(items: list[TrendSnapshot], states: set[str]) -> int:
    return sum(1 for item in items if item.dominant_state in states)


def _count_level_regime(items: list[TrendSnapshot], levels: set[str]) -> int:
    return sum(1 for item in items if item.level_regime in levels)


def _count_overall_direction(items: list[TrendSnapshot], directions: set[str]) -> int:
    return sum(1 for item in items if item.overall_direction in directions)


def _count_over_threshold_ratio(items: list[TrendSnapshot], min_ratio: float) -> int:
    return sum(1 for item in items if item.over_threshold_ratio >= min_ratio)


def _count_step_change(items: list[TrendSnapshot], min_relative: float = 0.0, types: set[str] | None = None) -> int:
    count = 0
    for item in items:
        if item.step_change_relative < min_relative:
            continue
        if types is not None and not any(cp_type in types for cp_type in item.changepoint_types):
            continue
        count += 1
    return count


def _count_high_level_stable(items: list[TrendSnapshot]) -> int:
    count = 0
    for item in items:
        is_high_level = item.level_regime == "high" or item.current is not None and item.mean is not None and item.current >= item.mean
        if not is_high_level:
            continue
        if item.dominant_state == "high_level_stable" or (
            item.overall_direction in {"stable", "down"} and item.volatility_regime in {None, "stable", "normal"}
        ):
            count += 1
    return count


def _same_bearing_pairs(items: list[TrendSnapshot]) -> dict[str, list[TrendSnapshot]]:
    grouped: dict[str, list[TrendSnapshot]] = {}
    for item in items:
        if item.bearing_id:
            grouped.setdefault(item.bearing_id, []).append(item)
    return grouped


def _waveform_metric(results: list[dict[str, Any]], key: str) -> list[float]:
    values: list[float] = []
    for item in results:
        details = item.get("feature_details") or {}
        value = _safe_float(details.get(key))
        if value is not None:
            values.append(value)
    return values


def _waveform_flag(results: list[dict[str, Any]], key: str) -> int:
    return sum(1 for item in results if bool((item.get("feature_details") or {}).get(key)))


def _orbit_metric(results: list[dict[str, Any]], key: str) -> list[float]:
    values: list[float] = []
    for item in results:
        details = item.get("feature_details") or {}
        value = _safe_float(details.get(key))
        if value is not None:
            values.append(value)
    return values


def _build_candidate(
    rule_id: str,
    mapping: tuple[str, str] | None,
    score: float,
    matched_conditions: list[str],
    missing_evidence: list[str],
    contradictions: list[str],
) -> CandidateFault | None:
    if mapping is None:
        return None
    return CandidateFault(
        rule_id=rule_id,
        fault_type=mapping[0],
        fault_subtype=mapping[1],
        score=round(_clip_score(score), 4),
        matched_conditions=matched_conditions,
        missing_evidence=missing_evidence,
        contradictions=contradictions,
    )


def _device_mapping(device_type: str, rule_key: str, config: dict[str, Any]) -> tuple[str, str] | None:
    device_map = (config.get("fault_mapping") or {}).get(device_type) or {}
    raw = device_map.get(rule_key)
    if isinstance(raw, list) and len(raw) >= 2:
        return str(raw[0]), str(raw[1])
    return None


def _score_candidates(
    diagnosis_target: DiagnosisTarget,
    trends: list[TrendSnapshot],
    waveform_results: list[dict[str, Any]],
    orbit_results: list[dict[str, Any]],
    config: dict[str, Any],
) -> list[CandidateFault]:
    thresholds = config.get("thresholds") or {}
    device_type = diagnosis_target.target_device_type

    vib_items = _trend_filter(trends, point_type="轴振", feature="pp_value") or _trend_filter(trends, point_type="轴振")
    gap_items = _trend_filter(trends, point_type="轴振", feature="gap")
    one_x_items = [item for item in trends if item.point_type == "轴振" and item.feature in {"one_freq_x", "one_freq_y"}]
    two_x_items = [item for item in trends if item.point_type == "轴振" and item.feature in {"two_freq_x", "two_freq_y"}]
    half_freq_items = [item for item in trends if item.point_type == "轴振" and item.feature in {"half_freq", "optional_freq_one"}]
    remain_freq_items = [item for item in trends if item.point_type == "轴振" and item.feature in {"remain_freq", "optional_freq_two"}]
    disp_items = _trend_filter(trends, point_type="轴位移")
    bearing_temp_items = _trend_filter(trends, point_type="轴承温度")
    oil_temp_items = _trend_filter(trends, point_type="润滑油温度")
    temp_items = bearing_temp_items + oil_temp_items
    support_temp_items = [item for item in bearing_temp_items if "推力轴承" not in item.bearing_types]
    thrust_temp_items = [item for item in bearing_temp_items if "推力轴承" in item.bearing_types]
    process_items_by_type = _group_process_items_by_type(trends)
    process_items = [
        item
        for point_type in PROCESS_PARAMETER_POINT_TYPES
        if point_type in GENERIC_PROCESS_SYNC_POINT_TYPES
        for item in process_items_by_type.get(point_type) or []
    ]

    # 按时间窗口分组（用于多窗口加权）
    def _by_window(items: list[TrendSnapshot], w: str) -> list[TrendSnapshot]:
        return [s for s in items if s.window == w]

    vib_1d = _by_window(vib_items, "1d")
    vib_3d = _by_window(vib_items, "3d")
    vib_30d = _by_window(vib_items, "30d")
    one_x_1d = _by_window(one_x_items, "1d")
    one_x_3d = _by_window(one_x_items, "3d")
    one_x_30d = _by_window(one_x_items, "30d")
    two_x_1d = _by_window(two_x_items, "1d")
    two_x_30d = _by_window(two_x_items, "30d")
    half_freq_1d = _by_window(half_freq_items, "1d")
    half_freq_30d = _by_window(half_freq_items, "30d")
    remain_freq_1d = _by_window(remain_freq_items, "1d")
    remain_freq_30d = _by_window(remain_freq_items, "30d")
    support_temp_30d = _by_window(support_temp_items, "30d")
    thrust_temp_30d = _by_window(thrust_temp_items, "30d")

    high_vib_threshold = _safe_float(thresholds.get("vibration_high_um")) or 35.0
    medium_vib_threshold = _safe_float(thresholds.get("vibration_medium_um")) or 25.0
    vibration_jump_threshold = _safe_float(thresholds.get("vibration_jump_um")) or 10.0
    temp_high_threshold = _safe_float(thresholds.get("temperature_high_c")) or 90.0
    gradual_rise = _safe_float(thresholds.get("gradual_rise_relative")) or 0.10
    rapid_rise = _safe_float(thresholds.get("rapid_rise_relative")) or 0.25
    long_term_deviation_ratio = _safe_float(thresholds.get("long_term_high_deviation_ratio")) or 1.2
    gap_change_threshold = _safe_float(thresholds.get("gap_change_v")) or 0.3
    disp_change_threshold = _safe_float(thresholds.get("shaft_displacement_change_mm")) or 0.1
    amp_1x_high = _safe_float(thresholds.get("amp_1x_ratio_high")) or 0.75
    amp_1x_medium = _safe_float(thresholds.get("amp_1x_ratio_medium")) or 0.55
    amp_1x_low = _safe_float(thresholds.get("amp_1x_ratio_low")) or 0.35
    misalign_2x = _safe_float(thresholds.get("amp_2x_to_1x_ratio_misalignment")) or 0.25
    high_2x_ratio = _safe_float(thresholds.get("amp_2x_to_1x_ratio_high")) or 0.8
    low_freq_upper = _safe_float(thresholds.get("low_freq_order_upper")) or 0.55
    very_low_freq_upper = _safe_float(thresholds.get("very_low_freq_order_upper")) or 0.35
    oil_whirl_lower = _safe_float(thresholds.get("oil_whirl_order_lower")) or 0.30
    oil_whirl_upper = _safe_float(thresholds.get("oil_whirl_order_upper")) or 0.52
    sub_sync_peak_min_amplitude = _safe_float(thresholds.get("sub_sync_peak_min_amplitude")) or 1.0
    sub_sync_peak_relative_to_dominant_min = _safe_float(thresholds.get("sub_sync_peak_relative_to_dominant_min")) or 0.12
    sub_sync_peak_relative_to_1x_min = _safe_float(thresholds.get("sub_sync_peak_relative_to_1x_min")) or 0.18
    low_freq_peak_min_amplitude = _safe_float(thresholds.get("low_freq_peak_min_amplitude")) or 1.0
    low_freq_peak_relative_to_dominant_min = _safe_float(thresholds.get("low_freq_peak_relative_to_dominant_min")) or 0.18
    low_freq_peak_relative_to_1x_min = _safe_float(thresholds.get("low_freq_peak_relative_to_1x_min")) or 0.22
    waveform_min_cases_for_pattern_rules = max(1, int(_safe_float(thresholds.get("waveform_min_cases_for_pattern_rules")) or 2))
    orbit_min_cases_for_pattern_rules = max(1, int(_safe_float(thresholds.get("orbit_min_cases_for_pattern_rules")) or 1))
    sine_fit_high = _safe_float(thresholds.get("waveform_sine_fit_high")) or 0.80
    periodicity_high = _safe_float(thresholds.get("waveform_periodicity_high")) or 0.75
    orbit_rep_high = _safe_float(thresholds.get("orbit_repetition_high")) or 0.72
    orbit_rep_low = _safe_float(thresholds.get("orbit_repetition_low")) or 0.45
    orbit_axis_ratio = _safe_float(thresholds.get("orbit_axis_ratio_elongated")) or 2.2
    bearing_xy_diff = _safe_float(thresholds.get("bearing_xy_diff_um")) or 20.0

    dominant_1x_count = sum(1 for value in _waveform_metric(waveform_results, "amp_1x_ratio") if value >= amp_1x_medium)
    strong_1x_count = sum(1 for value in _waveform_metric(waveform_results, "amp_1x_ratio") if value >= amp_1x_high)
    weak_1x_count = sum(1 for value in _waveform_metric(waveform_results, "amp_1x_ratio") if value <= amp_1x_low)

    # 1X 相对主峰的占比：真正衡量"1X 是否是主导频率"
    # amp_1x_ratio = 1X/总能量 会被噪声稀释，改用 1X/主峰幅值
    _amp_1x_vals = _waveform_metric(waveform_results, "amp_1x")
    _dominant_amp_vals = _waveform_metric(waveform_results, "dominant_amplitude")
    true_1x_dominant_count = 0
    for a1, da in zip(_amp_1x_vals, _dominant_amp_vals):
        if a1 is not None and da not in (None, 0.0) and (a1 / da) >= 0.70:
            true_1x_dominant_count += 1

    # 1X 在主峰中的占比：amp_1x / sum(top_peaks_amplitudes)，不被宽带噪声稀释
    _peak_1x_ratios: list[float] = []
    for item in waveform_results:
        details = item.get("feature_details") or {}
        a1 = _safe_float(details.get("amp_1x"))
        top_peaks = details.get("top_peaks")
        if a1 is None or not isinstance(top_peaks, list) or not top_peaks:
            _peak_1x_ratios.append(0.0)
            continue
        peaks_sum = sum(_safe_float(p.get("amplitude")) or 0.0 for p in top_peaks if isinstance(p, dict))
        if peaks_sum <= 0:
            _peak_1x_ratios.append(0.0)
            continue
        _peak_1x_ratios.append(a1 / peaks_sum)

    # 用新的 peak-based 1X 占比替换旧的 amp_1x_ratio（旧度量被全频谱噪声稀释，永远 < 0.75）
    _old_strong_1x = strong_1x_count
    _old_dominant_1x = dominant_1x_count
    _old_weak_1x = weak_1x_count
    # 新旧结合：旧度量看信噪比，新度量看主峰份额，任一达标即可
    strong_1x_count = 0
    dominant_1x_count = 0
    weak_1x_count = 0
    _old_1x_ratios = _waveform_metric(waveform_results, "amp_1x_ratio")
    _wf_count = len(waveform_results)
    for i in range(_wf_count):
        old_r = _old_1x_ratios[i] if i < len(_old_1x_ratios) else 0.0
        new_r = _peak_1x_ratios[i] if i < len(_peak_1x_ratios) else 0.0
        # strong: 旧度量 >= 0.55 或 新度量 >= 0.70
        if old_r >= 0.55 or new_r >= 0.70:
            strong_1x_count += 1
        # dominant: 旧度量 >= 0.40 或 新度量 >= 0.55
        if old_r >= 0.40 or new_r >= 0.55:
            dominant_1x_count += 1
        # weak: 旧度量 <= 0.20 且 新度量 <= 0.35
        if old_r <= 0.20 and new_r <= 0.35:
            weak_1x_count += 1

    strong_2x_count = sum(1 for value in _waveform_metric(waveform_results, "amp_2x_to_1x_ratio") if value >= misalign_2x)
    very_strong_2x_count = sum(1 for value in _waveform_metric(waveform_results, "amp_2x_to_1x_ratio") if value >= high_2x_ratio)

    sine_like_count = 0
    for item in waveform_results:
        details = item.get("feature_details") or {}
        sine_fit = _safe_float(details.get("sine_fit_score")) or 0.0
        periodicity = _safe_float(details.get("periodicity_score")) or 0.0
        if sine_fit >= sine_fit_high and periodicity >= periodicity_high:
            sine_like_count += 1

    clipping_count = _waveform_flag(waveform_results, "clipping_detected")
    drift_count = _waveform_flag(waveform_results, "drift_detected")
    glitch_count = sum(int(value) for value in _waveform_metric(waveform_results, "glitch_count"))

    # --- new waveform features ---
    kurtosis_values = _waveform_metric(waveform_results, "kurtosis_factor")
    kurtosis_impact_min = _safe_float(thresholds.get("kurtosis_impact_min")) or 3.5
    kurtosis_sensor_min = _safe_float(thresholds.get("kurtosis_sensor_min")) or 6.0
    kurtosis_normal_max = _safe_float(thresholds.get("kurtosis_normal_max")) or 2.0
    kurtosis_outlier_max = _safe_float(thresholds.get("kurtosis_outlier_max")) or 20.0
    # 极端峭度（>outlier_max）视为传感器异常/放电脉冲，不计入摩擦冲击
    outlier_kurtosis_count = sum(1 for v in kurtosis_values if v >= kurtosis_outlier_max)
    high_kurtosis_count = sum(1 for v in kurtosis_values if kurtosis_impact_min <= v < kurtosis_outlier_max)
    sensor_kurtosis_count = sum(1 for v in kurtosis_values if v >= kurtosis_sensor_min)
    normal_kurtosis_count = sum(1 for v in kurtosis_values if v <= kurtosis_normal_max)
    moderate_kurtosis_count = sum(1 for v in kurtosis_values if kurtosis_normal_max < v < kurtosis_sensor_min)

    crest_values = _waveform_metric(waveform_results, "crest_factor")
    crest_sine_max = _safe_float(thresholds.get("crest_factor_sine_max")) or 1.6
    crest_impact_min = _safe_float(thresholds.get("crest_factor_impact_min")) or 2.0
    crest_sensor_min = _safe_float(thresholds.get("crest_factor_sensor_min")) or 4.0
    sine_crest_count = sum(1 for v in crest_values if v <= crest_sine_max)
    high_crest_count = sum(1 for v in crest_values if v >= crest_impact_min)
    sensor_crest_count = sum(1 for v in crest_values if v >= crest_sensor_min)

    asymmetry_values = _waveform_metric(waveform_results, "peak_valley_asymmetry_ratio")
    asymmetry_friction_min = _safe_float(thresholds.get("asymmetry_ratio_friction_min")) or 1.3
    asymmetry_normal_max = _safe_float(thresholds.get("asymmetry_ratio_normal_max")) or 1.2
    asymmetric_count = sum(1 for v in asymmetry_values if v >= asymmetry_friction_min)
    symmetric_count = sum(1 for v in asymmetry_values if v <= asymmetry_normal_max)

    skewness_values = [abs(v) for v in _waveform_metric(waveform_results, "skewness_factor")]
    skewness_friction_min = _safe_float(thresholds.get("skewness_friction_min")) or 0.5
    high_skewness_count = sum(1 for v in skewness_values if v >= skewness_friction_min)

    repeatability_values = _waveform_metric(waveform_results, "cycle_repeatability_score")
    repeat_high = _safe_float(thresholds.get("cycle_repeatability_high")) or 0.80
    repeat_low = _safe_float(thresholds.get("cycle_repeatability_low")) or 0.45
    high_repeatability_count = sum(1 for v in repeatability_values if v >= repeat_high)
    low_repeatability_count = sum(1 for v in repeatability_values if v <= repeat_low)

    glitch_ratio_values = _waveform_metric(waveform_results, "glitch_ratio")
    glitch_ratio_high = _safe_float(thresholds.get("glitch_ratio_high")) or 0.05
    high_glitch_ratio_count = sum(1 for v in glitch_ratio_values if v >= glitch_ratio_high)

    drift_values = _waveform_metric(waveform_results, "drift_value")
    drift_value_high = _safe_float(thresholds.get("drift_value_high")) or 5.0
    large_drift_count = sum(1 for v in drift_values if abs(v) >= drift_value_high)

    # fractional harmonics from top_peaks
    frac_tol = _safe_float(thresholds.get("fractional_harmonic_order_tolerance")) or 0.08
    fractional_harmonic_count = 0
    sub_sync_peak_count = 0
    significant_sub_sync_case_count = 0
    for item in waveform_results:
        details = item.get("feature_details") or {}
        running_hz = _safe_float(details.get("running_frequency_hz"))
        dominant_amp = _safe_float(details.get("dominant_amplitude")) or 0.0
        amp_1x = _safe_float(details.get("amp_1x"))
        top_peaks = details.get("top_peaks")
        if not isinstance(top_peaks, list) or not running_hz or running_hz <= 0:
            continue
        significant_sub_sync_peaks = 0
        for peak in top_peaks:
            if not isinstance(peak, dict):
                continue
            freq_hz = _safe_float(peak.get("frequency_hz")) or 0.0
            amp = _safe_float(peak.get("amplitude")) or 0.0
            if freq_hz <= 0:
                continue
            order = freq_hz / running_hz
            for target in (0.5, 1.5, 2.5):
                if abs(order - target) <= frac_tol:
                    fractional_harmonic_count += 1
                    break
            relative_to_dominant = amp / dominant_amp if dominant_amp > 1e-6 else 0.0
            relative_to_1x = amp / amp_1x if amp_1x and amp_1x > 1e-6 else None
            if (
                1.0 <= freq_hz <= 30.0
                and amp >= sub_sync_peak_min_amplitude
                and (
                    relative_to_dominant >= sub_sync_peak_relative_to_dominant_min
                    or relative_to_1x is None
                    or relative_to_1x >= sub_sync_peak_relative_to_1x_min
                )
            ):
                sub_sync_peak_count += 1
                significant_sub_sync_peaks += 1
        if significant_sub_sync_peaks > 0:
            significant_sub_sync_case_count += 1

    low_freq_count = 0
    strong_low_freq_count = 0
    very_low_freq_count = 0
    strong_very_low_freq_count = 0
    oil_whirl_count = 0
    strong_oil_whirl_count = 0
    multiple_low_freq_count = 0
    significant_low_freq_case_count = 0
    for item in waveform_results:
        details = item.get("feature_details") or {}
        running_hz = _safe_float(details.get("running_frequency_hz"))
        dominant_hz = _safe_float(details.get("dominant_frequency_hz"))
        dominant_amp = _safe_float(details.get("dominant_amplitude")) or 0.0
        if running_hz and dominant_hz and running_hz > 0:
            order = dominant_hz / running_hz
            if order <= low_freq_upper:
                low_freq_count += 1
                if dominant_amp >= low_freq_peak_min_amplitude:
                    strong_low_freq_count += 1
            if order <= very_low_freq_upper:
                very_low_freq_count += 1
                if dominant_amp >= low_freq_peak_min_amplitude:
                    strong_very_low_freq_count += 1
            if oil_whirl_lower <= order <= oil_whirl_upper:
                oil_whirl_count += 1
                if dominant_amp >= low_freq_peak_min_amplitude:
                    strong_oil_whirl_count += 1
        # 多低频成分检测：top_peaks 中存在 2 个以上显著低频峰值（区别于油膜涡动的单一低频）
        top_peaks = details.get("top_peaks")
        amp_1x = _safe_float(details.get("amp_1x"))
        if isinstance(top_peaks, list) and running_hz and running_hz > 0:
            low_freq_peaks = 0
            for peak in top_peaks:
                if not isinstance(peak, dict):
                    continue
                freq_hz = _safe_float(peak.get("frequency_hz")) or 0.0
                amp = _safe_float(peak.get("amplitude")) or 0.0
                relative_to_dominant = amp / dominant_amp if dominant_amp > 1e-6 else 0.0
                relative_to_1x = amp / amp_1x if amp_1x and amp_1x > 1e-6 else None
                if (
                    0 < freq_hz < running_hz * 0.8
                    and amp >= low_freq_peak_min_amplitude
                    and (
                        relative_to_dominant >= low_freq_peak_relative_to_dominant_min
                        or relative_to_1x is None
                        or relative_to_1x >= low_freq_peak_relative_to_1x_min
                    )
                ):
                    low_freq_peaks += 1
            if low_freq_peaks >= 2:
                multiple_low_freq_count += 1
            if low_freq_peaks > 0:
                significant_low_freq_case_count += 1

    repetition_values = _orbit_metric(orbit_results, "raw_repetition_score")
    axis_ratio_values = _orbit_metric(orbit_results, "first_cycle_axis_ratio")
    straight_values = _orbit_metric(orbit_results, "first_cycle_straight_transition_score")
    concavity_values = _orbit_metric(orbit_results, "first_cycle_concavity_score")
    self_intersections = _orbit_metric(orbit_results, "first_cycle_self_intersection_count")

    ellipse_like_count = sum(
        1
        for rep, axis_ratio_value in zip(repetition_values, axis_ratio_values)
        if rep >= orbit_rep_high and (axis_ratio_value is None or axis_ratio_value >= 1.0)
    )
    irregular_orbit_count = sum(
        1
        for rep, intersections in zip(repetition_values, self_intersections)
        if rep <= orbit_rep_low or intersections >= 1
    )
    elongated_orbit_count = sum(1 for value in axis_ratio_values if value >= orbit_axis_ratio)

    # --- new orbit features ---
    figure_eight_min = _safe_float(thresholds.get("figure_eight_score_min")) or 0.40
    crescent_min = _safe_float(thresholds.get("crescent_score_min")) or 0.40
    circle_likeness_high_th = _safe_float(thresholds.get("circle_likeness_high")) or 0.70
    orbit_shape_sim_high = _safe_float(thresholds.get("orbit_shape_similarity_high")) or 0.70
    orbit_shape_sim_low = _safe_float(thresholds.get("orbit_shape_similarity_low")) or 0.40

    figure_eight_values = _orbit_metric(orbit_results, "first_cycle_figure_eight_score")
    crescent_values = _orbit_metric(orbit_results, "first_cycle_crescent_score")
    circle_likeness_values = _orbit_metric(orbit_results, "first_cycle_circle_likeness_score")
    shape_similarity_values = _orbit_metric(orbit_results, "raw_cycle_shape_similarity")

    figure_eight_count = sum(1 for v in figure_eight_values if v >= figure_eight_min)
    crescent_count = sum(1 for v in crescent_values if v >= crescent_min)
    circle_like_count = sum(1 for v in circle_likeness_values if v >= circle_likeness_high_th)
    shape_consistent_count = sum(1 for v in shape_similarity_values if v >= orbit_shape_sim_high)
    shape_inconsistent_count = sum(1 for v in shape_similarity_values if v <= orbit_shape_sim_low)

    forward_precession_count = 0
    reverse_precession_count = 0
    for item in orbit_results:
        details = item.get("feature_details") or {}
        direction = str(details.get("one_x_precession_direction") or "")
        if "正" in direction:
            forward_precession_count += 1
        elif "反" in direction:
            reverse_precession_count += 1

    # --- 新轨道指标：椭圆拟合残差 + 周期大小相似度 ---
    _ellipse_residual_threshold = _safe_float(thresholds.get("ellipse_fit_residual_high")) or 1.5
    _cycle_size_sim_low_threshold = _safe_float(thresholds.get("cycle_size_similarity_low")) or 0.55
    ellipse_fit_residual_values = _orbit_metric(orbit_results, "first_cycle_ellipse_fit_residual")
    cycle_size_similarity_values = _orbit_metric(orbit_results, "raw_cycle_size_similarity")
    high_ellipse_residual_count = sum(1 for v in ellipse_fit_residual_values if v is not None and v >= _ellipse_residual_threshold)
    low_ellipse_residual_count = sum(1 for v in ellipse_fit_residual_values if v is not None and v < _ellipse_residual_threshold)
    low_cycle_size_similarity_count = sum(1 for v in cycle_size_similarity_values if v is not None and v <= _cycle_size_sim_low_threshold)
    high_cycle_size_similarity_count = sum(1 for v in cycle_size_similarity_values if v is not None and v > _cycle_size_sim_low_threshold)

    # --- 趋势 CV：振动趋势变异系数高 → 波动幅度大 → 流体特征 ---
    _cv_high_threshold = _safe_float(thresholds.get("trend_cv_high")) or 0.25
    high_cv_vib_count = sum(
        1 for item in vib_30d
        if (_safe_float(item.raw_feature_stats.get("coefficient_of_variation")) or 0.0) >= _cv_high_threshold
    )

    # 多窗口加权计数
    # current/alarm 用 30d（最稳定），volatile/jump 用 1d（最敏感），gradual_rise 用 30d（渐变需要长窗口）
    high_vib_count = sum(1 for item in vib_30d if (item.current or 0.0) >= high_vib_threshold or item.alarm_status in {"h", "hh"})
    medium_vib_count = sum(1 for item in vib_30d if (item.current or 0.0) >= medium_vib_threshold)

    # 突变/跳变：1d 窗口最敏感，3d 作为确认
    jump_vib_count = max(_count_large_ranges(vib_1d, vibration_jump_threshold),
                         _count_large_ranges(vib_3d, vibration_jump_threshold))
    rapid_rising_vib_count = max(_count_rising(vib_1d, rapid_rise),
                                 _count_rising(vib_3d, rapid_rise))

    # 波动：1d 最真实（不被长期均值稀释）
    volatile_vib_count = max(_count_volatile(vib_1d, 1.0), _count_volatile(vib_3d, 1.0))

    # 渐变上涨：30d 才能看出来
    rising_vib_count = _count_rising(vib_30d, gradual_rise)
    high_deviation_vib_count = _count_high_deviation(vib_30d, long_term_deviation_ratio)
    post_step_high_vib_count = max(
        _count_dominant_state(vib_1d, {"post_step_high", "rapid_rising"}),
        _count_dominant_state(vib_3d, {"post_step_high", "rapid_rising"}),
        _count_step_change(vib_1d, 0.10, {"level_shift", "slope_shift", "cross_over_h", "cross_over_hh"}),
        _count_step_change(vib_3d, 0.10, {"level_shift", "slope_shift", "cross_over_h", "cross_over_hh"}),
    )
    over_limit_vib_count = max(
        _count_dominant_state(vib_1d, {"over_limit_running"}),
        _count_dominant_state(vib_3d, {"over_limit_running"}),
        _count_over_threshold_ratio(vib_1d, 0.03),
        _count_over_threshold_ratio(vib_3d, 0.03),
    )
    stable_high_vib_count = _count_high_level_stable(vib_30d)
    high_alarm_vib_count = _count_alarm(vib_30d)

    one_x_recent_rise_count = max(_count_rising(one_x_1d, gradual_rise), _count_rising(one_x_3d, gradual_rise))
    one_x_long_rise_count = _count_rising(one_x_30d, gradual_rise * 0.8)
    one_x_high_deviation_count = _count_high_deviation(one_x_30d, 0.8)
    one_x_volatile_count = max(_count_volatile(one_x_1d, 0.85), _count_volatile(one_x_3d, 0.85))
    two_x_activity_count = max(
        _count_rising(two_x_1d, gradual_rise * 0.8),
        _count_volatile(two_x_1d, 0.8),
        _count_rising(two_x_30d, gradual_rise * 0.8),
    )
    half_freq_activity_count = max(
        _count_rising(half_freq_1d, gradual_rise * 0.8),
        _count_volatile(half_freq_1d, 0.75),
        _count_high_deviation(half_freq_30d, 0.8),
    )
    remain_freq_activity_count = max(
        _count_rising(remain_freq_1d, gradual_rise * 0.8),
        _count_volatile(remain_freq_1d, 0.75),
        _count_high_deviation(remain_freq_30d, 0.8),
    )
    one_x_clean_support = 1.0 if one_x_recent_rise_count + one_x_long_rise_count + one_x_high_deviation_count > 0 and (two_x_activity_count + half_freq_activity_count + remain_freq_activity_count) == 0 else 0.0

    process_type_summary = _summarize_process_items_by_type(process_items_by_type, gradual_rise, 1.0)
    process_profile = _build_process_signal_profile(process_type_summary)
    process_anomaly_count = int(process_profile.get("generic_anomaly_count") or 0)
    process_active_type_count = int(process_profile.get("generic_active_type_count") or 0)
    surge_process_count = int(process_profile.get("surge_anomaly_count") or 0)
    surge_active_type_count = int(process_profile.get("surge_active_type_count") or 0)
    gas_path_process_count = int(process_profile.get("gas_path_anomaly_count") or 0)
    gas_path_active_type_count = int(process_profile.get("gas_path_active_type_count") or 0)
    load_process_count = int(process_profile.get("load_anomaly_count") or 0)
    load_active_type_count = int(process_profile.get("load_active_type_count") or 0)
    fluid_process_support = _safe_float(process_profile.get("fluid_support_strength")) or 0.0
    process_sync_support = _safe_float(process_profile.get("process_sync_support_strength")) or 0.0
    load_only_process_signature = load_active_type_count > 0 and surge_active_type_count == 0 and gas_path_active_type_count == 0
    high_temp_count = sum(1 for item in temp_items if (item.current or 0.0) >= temp_high_threshold)
    rising_temp_count = _count_rising(temp_items, gradual_rise)
    support_temp_stable_high_count = _count_high_level_stable(support_temp_30d)
    thrust_temp_stable_high_count = _count_high_level_stable(thrust_temp_30d)
    temp_step_high_count = max(
        _count_dominant_state(temp_items, {"post_step_high", "rapid_rising"}),
        _count_step_change(temp_items, 0.08, {"level_shift", "cross_over_h", "cross_over_hh"}),
    )
    gap_change_count = _count_large_ranges(gap_items, gap_change_threshold)
    gap_stable_count = _count_gap_stable(gap_items, gap_change_threshold)
    disp_change_count = sum(
        1
        for item in disp_items
        if _range_value(item) >= disp_change_threshold
        or item.rise_count > 0
        or item.step_change_relative >= 0.08
        or item.overall_direction == "up"
    )

    bearing_groups = _same_bearing_pairs(vib_30d)
    bearing_pair_high = 0
    bearing_pair_medium = 0
    bearing_pair_diff = 0
    coupling_side_high = 0
    for items in bearing_groups.values():
        values = [item.current or 0.0 for item in items]
        if len(values) >= 2 and min(values) >= medium_vib_threshold:
            bearing_pair_high += 1
        if len(values) >= 2 and min(values) >= medium_vib_threshold * 0.75:
            bearing_pair_medium += 1
        if len(values) >= 2 and (max(values) - min(values)) >= bearing_xy_diff:
            bearing_pair_diff += 1
        if any(item.bearing_direction == "联端" and (item.current or 0.0) >= medium_vib_threshold for item in items):
            coupling_side_high += 1

    bearing_wear_strong = (
        (bearing_pair_high > 0 or bearing_pair_medium > 0)
        and (rising_temp_count > 0 or high_temp_count > 0 or support_temp_stable_high_count > 0)
        and (rising_vib_count >= 2 or high_deviation_vib_count >= 2 or volatile_vib_count >= 2)
    ) or (
        # 备选路径：无温度测点时，同轴承多通道 + 振动异常 + GAP持续变化(>=3) 也支持轴承磨损
        (bearing_pair_high > 0 or bearing_pair_medium > 0)
        and rising_temp_count == 0 and high_temp_count == 0 and support_temp_stable_high_count == 0
        and (rising_vib_count >= 2 or high_deviation_vib_count >= 2 or volatile_vib_count >= 2)
        and gap_change_count >= 3
    )

    waveform_case_count = len(waveform_results)
    orbit_case_count = len(orbit_results)
    waveform_pattern_ready = waveform_case_count >= waveform_min_cases_for_pattern_rules
    orbit_pattern_ready = orbit_case_count >= orbit_min_cases_for_pattern_rules
    pattern_data_sparse = not waveform_pattern_ready and not orbit_pattern_ready
    fluid_low_freq_case_threshold = max(1, math.ceil(waveform_case_count * 0.25)) if waveform_case_count else 1
    high_repeatability_majority = max(1, waveform_case_count // 2) if waveform_case_count else 1
    smooth_repeatable_waveform = (
        waveform_case_count > 0
        and high_repeatability_count >= high_repeatability_majority
        and normal_kurtosis_count >= high_repeatability_majority
        and glitch_count == 0
        and high_kurtosis_count == 0
        and fractional_harmonic_count == 0
    )
    gradual_unbalance_bias = (
        one_x_long_rise_count > 0
        and rising_vib_count >= 2
        and high_repeatability_count >= 1
        and glitch_count == 0
        and high_kurtosis_count == 0
    )
    sustained_high_1x_signature = (
        high_deviation_vib_count >= 2
        and one_x_high_deviation_count >= 2
        and gap_stable_count >= 2
        and high_alarm_vib_count >= 2
        and high_repeatability_count >= 1
        and glitch_count == 0
        and high_kurtosis_count == 0
        and post_step_high_vib_count == 0
        and rapid_rising_vib_count == 0
        and one_x_recent_rise_count == 0
    )
    critical_fast_change_signature = (
        post_step_high_vib_count > 0
        or rapid_rising_vib_count > 0
        or one_x_recent_rise_count > 0
        or over_limit_vib_count > 0
    )
    clean_gradual_rotor_signature = (
        smooth_repeatable_waveform
        and strong_1x_count >= 2
        and (one_x_long_rise_count > 0 or sustained_high_1x_signature)
        and one_x_recent_rise_count == 0
        and post_step_high_vib_count == 0
        and rapid_rising_vib_count == 0
    )
    friction_impact_signature = (
        glitch_count > 0
        or (clipping_count > 1 and (high_crest_count > 0 or high_kurtosis_count > 0 or asymmetric_count > 0))
    )
    friction_nonlinear_signature = (
        friction_impact_signature
        or irregular_orbit_count > 0
        or reverse_precession_count > 0
        or fractional_harmonic_count > 0
        or high_skewness_count > 0
    )
    wear_smooth_support = (
        bearing_pair_medium > 0
        and smooth_repeatable_waveform
        and (irregular_orbit_count > 0 or shape_inconsistent_count > 0)
        and figure_eight_count == 0
        and reverse_precession_count == 0
    )
    clearance_wear_signature = (
        wear_smooth_support
        and gap_stable_count >= 2
        and process_anomaly_count == 0
    )
    strong_low_freq_signature = (
        strong_low_freq_count >= fluid_low_freq_case_threshold
        or strong_very_low_freq_count >= fluid_low_freq_case_threshold
        or significant_low_freq_case_count >= fluid_low_freq_case_threshold
        or multiple_low_freq_count >= fluid_low_freq_case_threshold
        or significant_sub_sync_case_count >= fluid_low_freq_case_threshold
    )
    weak_fluid_without_process_signature = (
        process_anomaly_count == 0
        and surge_process_count == 0
        and gas_path_active_type_count == 0
        and load_active_type_count == 0
        and not strong_low_freq_signature
    )
    mechanical_1x_bias_signature = (
        strong_1x_count >= 2
        and high_repeatability_count >= 1
        and (one_x_long_rise_count > 0 or one_x_high_deviation_count >= 2 or gap_stable_count >= 2)
        and not strong_low_freq_signature
    )
    bearing_wear_multisource_signature = (
        sum(
            1
            for condition in (
                bearing_pair_high > 0 or bearing_pair_medium > 0,
                rising_temp_count > 0 or high_temp_count > 0 or support_temp_stable_high_count > 0,
                gap_change_count > 0,
                moderate_kurtosis_count > 0 or irregular_orbit_count > 0 or crescent_count > 0,
            )
            if condition
        )
        >= 3
    )
    oil_whirl_hard_support = (
        strong_oil_whirl_count >= max(2, fluid_low_freq_case_threshold)
        and low_repeatability_count > 0
        and irregular_orbit_count > 0
        and multiple_low_freq_count == 0
        and process_anomaly_count == 0
    )
    soft_rub_signature_missing = (
        glitch_count == 0
        and reverse_precession_count == 0
        and fractional_harmonic_count == 0
        and high_kurtosis_count == 0
        and one_x_recent_rise_count == 0
        and post_step_high_vib_count == 0
    )
    compressor_like = "压缩机" in str(device_type)
    compressor_fouling_signature = (
        compressor_like
        and rising_vib_count >= 2
        and gap_stable_count >= 2
        and strong_1x_count >= 1
        and glitch_count == 0
        and high_kurtosis_count == 0
    )
    soft_rub_signature = (
        not compressor_like
        and volatile_vib_count >= 2
        and reverse_precession_count > 0
        and (
            irregular_orbit_count > 0
            or strong_2x_count > 0
            or fractional_harmonic_count > 0
            or one_x_recent_rise_count > 0
            or one_x_long_rise_count > 0
        )
    )
    screw_like = "螺杆" in str(device_type)
    surge_hard_support = (
        surge_active_type_count >= 2
        or (surge_active_type_count >= 1 and gas_path_active_type_count >= 1)
    )
    steam_fouling_like_signature = (
        not compressor_like
        and disp_change_count > 0
        and load_active_type_count > 0
        and surge_active_type_count == 0
        and high_kurtosis_count == 0
        and reverse_precession_count == 0
    )
    thrust_friction_conflict = (
        reverse_precession_count > 0
        or irregular_orbit_count > 0
        or strong_2x_count > 0
        or fractional_harmonic_count > 0
    )
    # 摩擦证据充分度：必须同时满足多个独立证据才算充分（避免弱证据误判）
    friction_evidence_strong = (
        (friction_impact_signature and (rapid_rising_vib_count > 0 or volatile_vib_count > 0))
        or (friction_impact_signature and irregular_orbit_count > 0 and reverse_precession_count > 0)
        or (fractional_harmonic_count > 0 and irregular_orbit_count > 0)
        or (friction_impact_signature and fractional_harmonic_count > 0)
        or (high_kurtosis_count > 0 and asymmetric_count > 0 and irregular_orbit_count > 0)
        # 汽轮机 + 明显波动 + 反进动：典型汽封/油封摩擦，即使没有冲击特征也应识别
        or (
            not compressor_like
            and volatile_vib_count >= 2
            and reverse_precession_count > 0
            and (
                irregular_orbit_count > 0
                or strong_2x_count > 0
                or fractional_harmonic_count > 0
                or high_kurtosis_count > 0
                or one_x_recent_rise_count > 0
            )
        )
        # 明显波动 + 1X 同步上涨 + 反进动：摩擦导致热弯曲的典型模式
        or (volatile_vib_count >= 2 and one_x_recent_rise_count > 0 and reverse_precession_count > 0)
        # 汽轮机 + 明显波动 + 1X 近期上涨：汽封漆膜摩擦的典型模式（间歇性规律波动+1X同步变化）
        or (not compressor_like and volatile_vib_count >= 2 and one_x_recent_rise_count > 0)
        # 波动 + 不规则轨迹 + 2X 活跃：摩擦非线性特征组合
        or (volatile_vib_count >= 2 and irregular_orbit_count > 0 and strong_2x_count > 0)
    )
    # GAP 稳定性：密封摩擦时 GAP 应无明显持续变化（区别于轴承磨损）
    gap_stable_for_friction = gap_change_count <= 2 and bool(gap_items)
    seal_fouling_signature = (
        not compressor_like
        and gap_stable_for_friction
        and surge_active_type_count <= 1
        and gas_path_active_type_count <= 1
        and (strong_1x_count >= 1 or dominant_1x_count >= 1)
        and (
            # 有工艺量数据时：要求负荷联动
            (load_active_type_count > 0 and (disp_change_count > 0 or one_x_recent_rise_count > 0 or one_x_long_rise_count > 0
             or friction_evidence_strong))
            # 无工艺量数据时：摩擦证据充分 + 波动 + 不规则轨迹 也支持油封结垢
            # 但有强低频证据时除外（非压缩机+强低频更可能是气流扰动）
            or (load_active_type_count == 0 and process_anomaly_count == 0
                and friction_evidence_strong and volatile_vib_count >= 2
                and (irregular_orbit_count > 0 or shape_inconsistent_count > 0)
                and not strong_low_freq_signature)
        )
    )
    seal_coking_signature = (
        not compressor_like
        and disp_change_count > 0
        and load_active_type_count > 0
        and surge_active_type_count == 0
        and gas_path_active_type_count <= 1
        and strong_1x_count >= 1
        and gap_stable_count >= 1
        and high_kurtosis_count == 0
        and reverse_precession_count == 0
    )
    # 轴电流在单设备上的特征组合（跨设备联动需在更上层实现）
    shaft_current_signature = (
        (glitch_count > 1 or high_glitch_ratio_count > 0)
        and (high_kurtosis_count > 0 or outlier_kurtosis_count > 0)
        and volatile_vib_count > 0
        and rapid_rising_vib_count == 0
        and post_step_high_vib_count == 0
    )
    # 极端峭度 + 波动：即使没有毛刺统计，也可能是轴电流放电（峭度>20 是非常强的脉冲特征）
    shaft_current_extreme_kurtosis = (
        outlier_kurtosis_count > 0
        and volatile_vib_count > 0
        and rapid_rising_vib_count == 0
        and post_step_high_vib_count == 0
    )
    aero_excitation_signature = (
        compressor_like
        and weak_1x_count >= 2
        and strong_1x_count == 0
        and shape_inconsistent_count > 0
        and (figure_eight_count > 0 or crescent_count > 0)
        and oil_whirl_count == 0
    )
    missing_strong_fluid_signature = (
        process_anomaly_count == 0
        and surge_process_count == 0
        and strong_low_freq_count == 0
        and strong_very_low_freq_count == 0
        and significant_sub_sync_case_count == 0
        and low_repeatability_count == 0
        and figure_eight_count == 0
        and crescent_count == 0
        and not aero_excitation_signature
    )
    # 无明确流体特征：仅凭泛化工艺量波动不能支撑流体扰动主结论
    weak_fluid_no_specific_evidence = (
        surge_active_type_count == 0
        and gas_path_active_type_count == 0
        and not strong_low_freq_signature
    )
    strong_process_sync_signature = (
        load_active_type_count > 0
        and process_anomaly_count > 0
        and gas_path_active_type_count <= 1
        and surge_active_type_count == 0
        and reverse_precession_count == 0
        and fractional_harmonic_count == 0
        and not (disp_change_count > 0 and (strong_1x_count >= 1 or gap_stable_count >= 2))
    )
    strong_fluid_signature = (
        (surge_hard_support and strong_low_freq_signature)
        or aero_excitation_signature
        or (
            compressor_like
            and gas_path_active_type_count > 0
            and (
                strong_low_freq_signature
                or figure_eight_count > 0
                or crescent_count > 0
            )
            and weak_1x_count >= 1
            and strong_1x_count == 0
        )
        or (
            # 无工艺量测点时，强低频频谱 + 振动波动 + 轨迹异常也支持流体扰动
            strong_low_freq_signature
            and volatile_vib_count >= 2
            and surge_active_type_count == 0
            and process_anomaly_count == 0
            and (irregular_orbit_count > 0 or shape_inconsistent_count > 0 or figure_eight_count > 0 or crescent_count > 0)
        )
    )
    fouling_priority_signature = (
        steam_fouling_like_signature
        or (
            compressor_fouling_signature
            and surge_active_type_count == 0
        )
        or (
            disp_change_count > 0
            and gap_stable_count >= 2
            and strong_1x_count >= 1
            and surge_active_type_count == 0
            and gas_path_active_type_count == 0
        )
    )
    impeller_fouling_signature = (
        compressor_like
        and (rising_vib_count >= 2 or high_deviation_vib_count >= 2 or one_x_recent_rise_count > 0)
        and (one_x_long_rise_count > 0 or one_x_high_deviation_count >= 1 or one_x_recent_rise_count > 0)
        and gap_stable_count >= 2
        and strong_1x_count >= 1
        and high_kurtosis_count == 0
        and not aero_excitation_signature
        and (
            not surge_hard_support
            # 强1X+近期上涨时，即使有喘振联动也允许叶轮结垢（喘振可能是结垢的后果）
            or (one_x_recent_rise_count > 0 and strong_1x_count >= 2)
        )
    )
    shaft_current_priority_signature = (
        (shaft_current_signature or shaft_current_extreme_kurtosis)
        and (glitch_count > 0 or high_glitch_ratio_count > 0 or outlier_kurtosis_count > 0)
    )
    rotor_dominant_signature = (
        strong_1x_count >= 2
        and (one_x_long_rise_count > 0 or one_x_high_deviation_count >= 2 or sustained_high_1x_signature)
        and gap_stable_count >= 1
        and surge_active_type_count == 0
        and gas_path_active_type_count == 0
    )
    clean_rotor_nonfriction_signature = (
        strong_1x_count >= 2
        and high_repeatability_count >= 1
        and symmetric_count >= 1
        and reverse_precession_count == 0
        and fractional_harmonic_count == 0
        and irregular_orbit_count == 0
        and (forward_precession_count > 0 or orbit_case_count == 0)
        # 排除汽封摩擦模式：汽轮机 + 波动或1X上涨（间歇性规律波动+1X同步变化是汽封漆膜摩擦典型特征）
        and not (not compressor_like and (volatile_vib_count > 0 or one_x_recent_rise_count > 0 or one_x_long_rise_count > 0))
    )
    rotor_runout_signature = (
        (strong_1x_count >= 2 or (strong_1x_count >= 1 and dominant_1x_count >= 2))
        and orbit_pattern_ready
        and (ellipse_like_count >= 1 or elongated_orbit_count > 0)
        and high_repeatability_count >= 1
        and symmetric_count >= 1
        and reverse_precession_count == 0
        and fractional_harmonic_count == 0
        and strong_low_freq_count == 0
        and process_anomaly_count == 0
        and (disp_change_count > 0 or gap_change_count > 0 or high_deviation_vib_count >= 1)
    )
    bearing_wear_priority_signature = (
        bearing_wear_strong
        and bearing_wear_multisource_signature
        and (gap_change_count > 0 or rising_temp_count > 0 or high_temp_count > 0 or support_temp_stable_high_count > 0)
        and surge_active_type_count == 0
        and gas_path_active_type_count == 0
    )
    shaft_current_conflict_signature = (
        (fouling_priority_signature and not shaft_current_extreme_kurtosis)
        or (rotor_dominant_signature and not shaft_current_extreme_kurtosis)
        or (
            strong_1x_count >= 2
            and gap_stable_count >= 2
            and (rising_vib_count >= 2 or high_deviation_vib_count >= 2)
            and not shaft_current_extreme_kurtosis
        )
    )
    oil_whirl_conflict_signature = (
        strong_fluid_signature
        or multiple_low_freq_count > 0
        or (gas_path_active_type_count > 0 and surge_active_type_count == 0)
        or (load_active_type_count > 0 and process_anomaly_count > 0 and strong_1x_count >= 1)
    )
    impact_sudden_rotor_signature = (
        (jump_vib_count >= 2 or rapid_rising_vib_count > 0 or post_step_high_vib_count > 0)
        and strong_1x_count >= 1
        and (glitch_count > 0 or high_kurtosis_count > 0 or asymmetric_count > 0 or jump_vib_count >= 3 or rapid_rising_vib_count > 0)
        and not strong_fluid_signature
    )
    screw_ingestion_signature = (
        screw_like
        and (jump_vib_count >= 2 or rapid_rising_vib_count > 0 or post_step_high_vib_count > 0)
        and (strong_2x_count > 0 or two_x_activity_count > 0 or high_kurtosis_count > 0 or glitch_count > 0)
        and strong_1x_count >= 1
        and not strong_fluid_signature
    )

    candidates: list[CandidateFault] = []

    def add(rule_id: str, score: float, matched: list[str], missing: list[str], contradictions: list[str]) -> None:
        candidate = _build_candidate(rule_id, _device_mapping(device_type, rule_id, config), score, matched, missing, contradictions)
        if candidate:
            candidates.append(candidate)

    add(
        "sensor_anomaly",
        _clip_score(
            0.22 * (1.0 if medium_vib_count <= 1 and volatile_vib_count <= 1 else 0.0)
            + 0.18 * (1.0 if glitch_count > 0 or clipping_count > 0 or drift_count > 0 else 0.0)
            + 0.13 * (1.0 if process_anomaly_count == 0 and high_temp_count <= 1 else 0.0)
            + 0.13 * (1.0 if strong_1x_count == 0 and high_vib_count <= 1 else 0.0)
            + 0.10 * (1.0 if sensor_kurtosis_count > 0 or sensor_crest_count > 0 else 0.0)
            + 0.10 * (1.0 if outlier_kurtosis_count > 0 else 0.0)
            + 0.07 * (1.0 if low_repeatability_count > 0 else 0.0)
            + 0.07 * (1.0 if large_drift_count > 0 or high_glitch_ratio_count > 0 else 0.0)
            - 0.12 * (1.0 if one_x_recent_rise_count + one_x_long_rise_count + one_x_high_deviation_count >= 2 else 0.0)
            - 0.08 * (1.0 if post_step_high_vib_count > 0 or over_limit_vib_count > 0 else 0.0)
        ),
        ["异常更偏单通道或少量通道，且波形带毛刺/削波/漂移。"],
        ["更多同类通道同步异常证据不足。"] if medium_vib_count <= 1 else [],
        (["多通道机械证据较强，传感器异常优先级下降。"] if high_vib_count >= 2 and dominant_1x_count >= 2 else [])
        + (["趋势中 1X 或台阶上升证据一致，更像真实机械变化。"] if one_x_recent_rise_count + one_x_long_rise_count + post_step_high_vib_count >= 2 else []),
    )

    add(
        "process_sync",
        _clip_score(
            0.30 * (1.0 if process_anomaly_count > 0 else 0.0)
            + 0.18 * process_sync_support
            + 0.08 * min(1.0, process_active_type_count / 2.0)
            + 0.15 * (1.0 if strong_1x_count == 0 and weak_1x_count >= 2 else 0.0)
            + 0.20 * (1.0 if volatile_vib_count >= 2 and low_freq_count == 0 and oil_whirl_count == 0 else 0.0)
            + 0.10 * (1.0 if one_x_recent_rise_count == 0 and one_x_high_deviation_count == 0 else 0.0)
            # 轴位移有明显持续变化时，更可能是结垢/磨损而非正常负荷跟随
            - 0.30 * (1.0 if disp_change_count >= 1 else 0.0)
            - 0.12 * (1.0 if steam_fouling_like_signature or rotor_dominant_signature else 0.0)
            # 存在反进动或分数谐波时，更像机械故障
            - 0.12 * (1.0 if reverse_precession_count > 0 or fractional_harmonic_count > 0 else 0.0)
            - 0.12 * (1.0 if compressor_like and surge_active_type_count > 0 and fluid_process_support >= 0.5 else 0.0)
            # 轨道高度不规则时，说明有机机械故障，不可能是纯工艺同步
            - 0.10 * (1.0 if irregular_orbit_count >= 3 else 0.0)
        ),
        ["工艺量或负荷相关测点存在同步变化。"]
        + ([f"同步异常已覆盖 {process_active_type_count} 类工艺参数。"] if process_active_type_count > 1 else [])
        + (["其他工艺参数/负荷类测点活跃，更像负荷跟随。"] if load_active_type_count > 0 else [])
        if process_anomaly_count > 0
        else [],
        ["负荷/工艺同步证据不足。"] if process_anomaly_count == 0 else [],
        (["机械 1X 证据较强，更像机械本体问题。"] if strong_1x_count >= 2 and ellipse_like_count >= 1 else [])
        + (["趋势中 1X 分量也在同步增强，不能简单归因为工艺同步。"] if one_x_recent_rise_count + one_x_high_deviation_count >= 2 else [])
        + (["波形存在摩擦/冲击特征，工艺同步可能是伴随现象。"] if (asymmetric_count > 0 or high_kurtosis_count > 0) and volatile_vib_count >= 2 else [])
        + (["轴位移存在持续变化，更像结垢或磨损而非正常负荷跟随。"] if disp_change_count >= 1 else [])
        + (["存在防喘振阀/入口流量联动，更像流体扰动而非纯负荷跟随。"] if compressor_like and surge_active_type_count > 0 and fluid_process_support >= 0.5 else [])
        + (["存在反进动或分数谐波，更像机械故障而非纯工艺同步。"] if reverse_precession_count > 0 or fractional_harmonic_count > 0 else []),
    )

    # 半频/residual 的趋势活跃度：仅在有效频谱证据时给全分，否则降权（纯趋势噪声）
    # 文档要求"低频成分通频幅值较高"——单个波形不够，需要多个波形确认
    _has_spectral_low_freq = strong_low_freq_count >= 2 or strong_very_low_freq_count >= 2 or significant_sub_sync_case_count >= 2
    _half_remain_activity_bonus = 0.10 if _has_spectral_low_freq else 0.06

    fluid_base_score = (
        0.20 * (1.0 if volatile_vib_count >= 2 else 0.0)
        + 0.10 * (1.0 if process_anomaly_count > 0 else 0.0)
        + 0.10 * fluid_process_support
        + 0.18 * (1.0 if strong_low_freq_count >= 2 or strong_very_low_freq_count >= 2 else 0.0)
        + 0.08 * (1.0 if strong_low_freq_signature and strong_low_freq_count < 2 and strong_very_low_freq_count < 2 else 0.0)
        + 0.10 * (1.0 if irregular_orbit_count > 0 else 0.0)
        + 0.10 * (1.0 if low_repeatability_count > 0 else 0.0)
        + 0.10 * (1.0 if shape_inconsistent_count > 0 else 0.0)
        + 0.10 * (1.0 if significant_sub_sync_case_count > 0 or fractional_harmonic_count > 0 else 0.0)
        + 0.10 * (1.0 if surge_process_count > 0 else 0.0)
        + _half_remain_activity_bonus * (1.0 if half_freq_activity_count > 0 or remain_freq_activity_count > 0 else 0.0)
        + 0.08 * (1.0 if weak_1x_count >= 2 and strong_1x_count == 0 else 0.0)
        + 0.08 * (1.0 if figure_eight_count > 0 or crescent_count > 0 else 0.0)
        + 0.08 * (1.0 if multiple_low_freq_count > 0 else 0.0)
        + 0.06 * (1.0 if high_cv_vib_count >= 2 else 0.0)
        + 0.05 * (1.0 if high_ellipse_residual_count > 0 and orbit_case_count > 0 else 0.0)
        # 反进动是机械故障特征（摩擦/碰摩），但仅在缺乏低频证据时才压低流体
        - 0.08 * (1.0 if reverse_precession_count > 0 and strong_low_freq_count < 2 else 0.0)
        - 0.12 * (1.0 if load_only_process_signature else 0.0)
        - 0.12 * (1.0 if bearing_wear_strong else 0.0)
        - 0.10 * (1.0 if strong_1x_count >= 2 and high_repeatability_count >= 1 else 0.0)
        - 0.12 * (1.0 if seal_fouling_signature or seal_coking_signature or impeller_fouling_signature or compressor_fouling_signature else 0.0)
        - 0.08 * (1.0 if rotor_runout_signature else 0.0)
        - 0.12 * (1.0 if mechanical_1x_bias_signature else 0.0)
        - 0.18 * (1.0 if weak_fluid_without_process_signature else 0.0)
        - 0.15 * (1.0 if missing_strong_fluid_signature else 0.0)
    )
    # 喘振/失速：防喘振阀或流量联动 + 振动波动 → 优先判 fluid_excitation
    is_surge = (
        volatile_vib_count >= 2
        and strong_low_freq_signature
        and (
            surge_active_type_count >= 2
            or (surge_active_type_count >= 1 and gas_path_active_type_count >= 1)
            or (
                # 无工艺量测点时：强低频频谱 + 高波动 + 非1X主导 也支持喘振/失速
                surge_active_type_count == 0 and process_anomaly_count == 0
                and (weak_1x_count >= 2 or figure_eight_count > 0 or crescent_count > 0)
            )
        )
    )
    fluid_rule_id = "fluid_excitation" if (is_surge or aero_excitation_signature) else "fluid_disturbance"
    add(
        fluid_rule_id,
        _clip_score(fluid_base_score
            + 0.25 * (1.0 if is_surge or aero_excitation_signature else 0.0)
        ),
        ["振动趋势呈明显波动，且低频或非稳定轨迹特征存在。"]
        + (["防喘振阀/入口流量存在联动波动，支持喘振/失速判断。"] if surge_process_count > 0 else [])
        + (["进气/出口工艺量同步异常，支持气路扰动。"] if gas_path_active_type_count > 0 else [])
        + ([f"工艺扰动覆盖 {process_active_type_count} 类参数，支持流体/工况异常。"] if process_active_type_count > 1 else [])
        + (["1X 不占优且轨迹呈“8”字/月牙或形状不稳定，支持压缩机气动激振。"] if aero_excitation_signature else []),
        ["缺少明显流量、阀位或其他工艺同步证据。"] if process_anomaly_count == 0 and surge_process_count == 0 else [],
        (["稳定 1X 主导且轨迹重复性高，不像流体扰动。"] if strong_1x_count >= 2 and ellipse_like_count >= 1 else [])
        + (["细分工艺量主要落在负荷/泛化工艺量，缺少关键喘振联动。"] if load_only_process_signature else [])
        + (["温度/GAP/同轴承多通道特征更强，更像轴承磨损。"] if bearing_wear_strong else []),
    )

    add(
        "seal_fouling",
        _clip_score(
            0.22 * (1.0 if gap_stable_for_friction else 0.0)
            + 0.18 * (1.0 if load_active_type_count > 0 else 0.0)
            + 0.16 * (1.0 if disp_change_count > 0 else 0.0)
            + 0.12 * (1.0 if strong_1x_count >= 1 else (0.5 if dominant_1x_count >= 1 else 0.0))
            + 0.08 * (1.0 if volatile_vib_count > 0 else 0.0)
            + 0.10 * (1.0 if one_x_recent_rise_count > 0 else 0.0)
            + 0.10 * (1.0 if seal_fouling_signature else 0.0)
            + 0.08 * (1.0 if one_x_long_rise_count > 0 else 0.0)
            # 汽轮机+波动+1X近期上涨是汽封漆膜摩擦典型特征
            + 0.15 * (1.0 if not compressor_like and volatile_vib_count >= 2 and one_x_recent_rise_count > 0 else 0.0)
            # 摩擦证据充分 + 不规则轨迹 + 工艺联动：即使无1X上涨也支持油封结垢
            + 0.18 * (1.0 if friction_evidence_strong and irregular_orbit_count > 0 and load_active_type_count > 0 else 0.0)
            - 0.14 * (1.0 if surge_active_type_count > 0 or gas_path_active_type_count > 0 else 0.0)
            - 0.12 * (1.0 if strong_fluid_signature else 0.0)
            - 0.08 * (1.0 if gap_change_count > 0 else 0.0)
        ),
        ["油封相关通道更像渐进积垢/结垢引发的密封摩擦，伴随 GAP 稳定与 1X 演化。"] if seal_fouling_signature else [],
        ["缺少稳定 GAP 或负荷侧结垢累积证据。"] if not seal_fouling_signature else [],
        (["存在明显气路/喘振联动，更像流体扰动而非油封积垢。"] if surge_active_type_count > 0 or gas_path_active_type_count > 0 else [])
        + (["GAP 存在持续变化，更像轴承磨损而非油封积垢。"] if gap_change_count > 0 else []),
    )

    add(
        "seal_coking",
        _clip_score(
            0.26 * (1.0 if disp_change_count > 0 else 0.0)
            + 0.18 * (1.0 if load_active_type_count > 0 else 0.0)
            + 0.14 * (1.0 if strong_1x_count >= 1 else (0.5 if dominant_1x_count >= 1 else 0.0))
            + 0.12 * (1.0 if gap_stable_count >= 1 else 0.0)
            + 0.10 * (1.0 if one_x_long_rise_count > 0 or rising_vib_count >= 2 else 0.0)
            + 0.10 * (1.0 if seal_coking_signature else 0.0)
            + 0.08 * (1.0 if steam_fouling_like_signature else 0.0)
            - 0.16 * (1.0 if surge_active_type_count > 0 or gas_path_active_type_count > 0 else 0.0)
            - 0.10 * (1.0 if reverse_precession_count > 0 or high_kurtosis_count > 0 else 0.0)
        ),
        ["轴位移与负荷侧工艺量同步演化，且缺少喘振联动，更像油封结垢/结焦累积。"] if seal_coking_signature else [],
        ["缺少轴位移持续变化或负荷侧累积证据。"] if not seal_coking_signature else [],
        (["存在反进动或冲击特征，更像摩擦而非纯结焦累积。"] if reverse_precession_count > 0 or high_kurtosis_count > 0 else [])
        + (["存在气路/喘振联动，更像流体扰动。"] if surge_active_type_count > 0 or gas_path_active_type_count > 0 else []),
    )

    add(
        "friction",
        _clip_score(
            0.18 * (1.0 if friction_impact_signature else 0.0)
            + 0.15 * (1.0 if rapid_rising_vib_count > 0 or volatile_vib_count > 0 else 0.0)
            + 0.12 * (1.0 if strong_2x_count > 0 else 0.0)
            + 0.15 * (1.0 if irregular_orbit_count > 0 or max(straight_values or [0.0]) > 0.6 or max(concavity_values or [0.0]) > 0.6 else 0.0)
            + 0.10 * (1.0 if asymmetric_count > 0 or high_skewness_count > 0 else 0.0)
            + 0.08 * (1.0 if reverse_precession_count > 0 else 0.0)
            + 0.10 * (1.0 if fractional_harmonic_count > 0 else 0.0)
            + 0.10 * (1.0 if high_kurtosis_count > 0 else 0.0)
            + 0.08 * (1.0 if two_x_activity_count > 0 or half_freq_activity_count > 0 or remain_freq_activity_count > 0 else 0.0)
            + 0.08 * (1.0 if one_x_long_rise_count > 0 else 0.0)
            + 0.06 * (1.0 if high_ellipse_residual_count > 0 and orbit_case_count > 0 else 0.0)
            + 0.06 * (1.0 if low_cycle_size_similarity_count > 0 and orbit_case_count > 0 else 0.0)
            + 0.07 * (1.0 if post_step_high_vib_count > 0 else 0.0)
            + 0.06 * (1.0 if soft_rub_signature else 0.0)
            + 0.20 * (1.0 if not compressor_like and volatile_vib_count >= 2 and one_x_recent_rise_count > 0 else 0.0)
            + 0.08 * (1.0 if steam_fouling_like_signature and gap_stable_for_friction else 0.0)
            - 0.12 * (1.0 if smooth_repeatable_waveform and not friction_nonlinear_signature and not (not compressor_like and volatile_vib_count >= 2 and one_x_recent_rise_count > 0) else 0.0)
            - 0.10 * (1.0 if clean_gradual_rotor_signature else 0.0)
            - 0.12 * (1.0 if soft_rub_signature_missing else 0.0)
            - 0.10 * (1.0 if not friction_evidence_strong else 0.0)
            - 0.05 * (1.0 if not gap_stable_for_friction and not (not compressor_like and volatile_vib_count >= 2 and one_x_recent_rise_count > 0) else 0.0)
            - 0.08 * (1.0 if gap_change_count > 0 and not (not compressor_like and volatile_vib_count >= 2 and one_x_recent_rise_count > 0) else 0.0)
            - 0.16 * (1.0 if clean_rotor_nonfriction_signature else 0.0)
            - 0.10 * (1.0 if bearing_wear_strong else 0.0)
            - 0.10 * (1.0 if strong_fluid_signature else 0.0)
            - 0.08 * (1.0 if shaft_current_priority_signature else 0.0)
        ),
        ["波形存在削波/毛刺/不对称，且振动快速上涨或明显波动，进动方向或分数谐波支持摩擦。"]
        + (["GAP 电压无明显持续变化，排除轴承磨损。"] if gap_stable_for_friction else []),
        (["轨迹异常或谐波证据不足。"] if irregular_orbit_count == 0 and strong_2x_count == 0 and asymmetric_count == 0 else [])
        + (["细分工艺量更像负荷/蒸汽跟随，偏结垢/结焦而非直接摩擦。"] if steam_fouling_like_signature else [])
        + (["摩擦证据充分度不足，仅靠弱证据难以确认。"] if not friction_evidence_strong else []),
        (["低频非同步特征更强，不像典型摩擦。"] if weak_1x_count >= 2 and low_freq_count > 0 else [])
        + (["峭度极端异常，更像传感器放电脉冲而非机械摩擦。"] if outlier_kurtosis_count > 0 else [])
        + (["GAP 电压存在持续变化，更像轴承磨损而非密封摩擦。"] if gap_change_count > 0 else [])
        + (["当前更像稳定 1X 主导的转子类故障，而非摩擦。"] if clean_rotor_nonfriction_signature else []),
    )

    oil_whirl_score = _clip_score(
        0.40 * (1.0 if oil_whirl_hard_support else 0.0)
        + 0.10 * (1.0 if strong_oil_whirl_count > 0 else 0.0)
        + 0.20 * (1.0 if volatile_vib_count > 0 else 0.0)
        + 0.20 * (1.0 if irregular_orbit_count > 0 else 0.0)
        + 0.10 * (1.0 if reverse_precession_count > 0 else 0.0)
        + 0.10 * (1.0 if shape_inconsistent_count > 0 else 0.0)
        + 0.10 * (1.0 if half_freq_activity_count > 0 or remain_freq_activity_count > 0 else 0.0)
        - 0.08 * (1.0 if aero_excitation_signature else 0.0)
        - 0.10 * (1.0 if multiple_low_freq_count > 0 else 0.0)
        # 压缩机 + 工艺波动/喘振证据 → 更可能是气动故障而非油膜涡动
        - 0.15 * (1.0 if compressor_like and (surge_process_count > 0 or process_anomaly_count > 0) else 0.0)
        # 1X 占比极低（<0.2）时，主频完全在低频区，压缩机场景更偏气动
        - 0.10 * (1.0 if compressor_like and strong_1x_count == 0 and weak_1x_count >= 2 else 0.0)
        - 0.18 * (1.0 if oil_whirl_conflict_signature else 0.0)
    )
    if oil_whirl_count == 0:
        oil_whirl_score = min(oil_whirl_score, 0.45)

    add(
        "oil_whirl",
        oil_whirl_score,
        ["频谱主特征落在 0.3X~0.52X 附近，且轨迹重复性差。"] if oil_whirl_count > 0 else [],
        ["缺少典型低频油膜涡动证据。"] if oil_whirl_count == 0 else [],
        (["主特征更偏稳定 1X，油膜涡动优先级下降。"] if strong_1x_count >= 2 else [])
        + (["更像压缩机气动激振而非典型 0.3X~0.52X 油膜涡动。"] if aero_excitation_signature else [])
        + (["频谱中存在多个低频峰值，更像气流扰动而非单一频率的油膜涡动。"] if multiple_low_freq_count > 0 else [])
        + (["压缩机 + 工艺波动/喘振证据，更可能是气动故障而非油膜涡动。"] if compressor_like and (surge_process_count > 0 or process_anomaly_count > 0) else []),
    )

    add(
        "unbalance_stable",
        _clip_score(
            0.20 * (1.0 if high_vib_count >= 2 else 0.0)
            + 0.20 * (1.0 if strong_1x_count >= 2 else (0.7 if dominant_1x_count >= 2 else 0.0))
            + 0.15 * (1.0 if sine_like_count >= 1 else 0.0)
            + 0.15 * (1.0 if ellipse_like_count >= 1 or orbit_case_count == 0 else 0.0)
            + 0.05 * (1.0 if volatile_vib_count == 0 else 0.0)
            # 波动大不可能是纯不平衡——摩擦/流体/轴承故障才会波动
            - 0.15 * (1.0 if volatile_vib_count >= 2 else 0.0)
            + 0.05 * (1.0 if sine_crest_count >= 1 and normal_kurtosis_count >= 1 else 0.0)
            + 0.05 * (1.0 if high_repeatability_count >= 1 or waveform_case_count == 0 else 0.0)
            + 0.05 * (1.0 if forward_precession_count > 0 or orbit_case_count == 0 else 0.0)
            + 0.05 * (1.0 if symmetric_count >= 1 or waveform_case_count == 0 else 0.0)
            + 0.05 * (1.0 if shape_consistent_count > 0 or orbit_case_count == 0 else 0.0)
            + 0.08 * one_x_clean_support
            + 0.05 * (1.0 if stable_high_vib_count >= 2 else 0.0)
            + 0.06 * (1.0 if low_ellipse_residual_count > 0 and high_cycle_size_similarity_count > 0 and orbit_case_count > 0 else 0.0)
            + 0.05 * (1.0 if true_1x_dominant_count >= 6 else 0.0)
            - 0.06 * (1.0 if half_freq_activity_count > 0 or remain_freq_activity_count > 0 else 0.0)
            # 汽轮机+波动+1X近期上涨是汽封漆膜摩擦典型特征，应降低稳定不平衡得分
            - 0.15 * (1.0 if not compressor_like and volatile_vib_count >= 2 and one_x_recent_rise_count > 0 else 0.0)
        ),
        ["多通道振动偏高，且以稳定 1X 和规则椭圆轨迹为主，波形对称正弦、正进动。"],
        ["缺少长周期平稳高振证据。"] if high_vib_count < 2 else [],
        ["存在明显低频波动或工艺同步，更像流体/工况问题。"] if volatile_vib_count > 0 and process_anomaly_count > 0 else [],
    )

    add(
        "unbalance_gradual",
        _clip_score(
            0.20 * (1.0 if rising_vib_count >= 2 else 0.0)
            + 0.15 * (1.0 if high_deviation_vib_count >= 2 else 0.0)
            + 0.15 * (1.0 if strong_1x_count >= 2 else (0.7 if dominant_1x_count >= 2 else 0.0))
            + 0.10 * (1.0 if ellipse_like_count >= 1 or orbit_case_count == 0 else 0.0)
            + 0.10 * (1.0 if gap_stable_count >= 2 else 0.0)
            + 0.05 * (1.0 if volatile_vib_count <= 1 else 0.0)
            # 波动大不可能是纯不平衡——摩擦/流体/轴承故障才会波动
            - 0.15 * (1.0 if volatile_vib_count >= 2 else 0.0)
            + 0.05 * (1.0 if sine_crest_count >= 1 and normal_kurtosis_count >= 1 else 0.0)
            + 0.05 * (1.0 if high_repeatability_count >= 1 or waveform_case_count == 0 else 0.0)
            + 0.05 * (1.0 if forward_precession_count > 0 or orbit_case_count == 0 else 0.0)
            + 0.05 * (1.0 if symmetric_count >= 1 or waveform_case_count == 0 else 0.0)
            + 0.05 * (1.0 if shape_consistent_count > 0 or orbit_case_count == 0 else 0.0)
            + 0.08 * (1.0 if one_x_long_rise_count > 0 or one_x_high_deviation_count >= 2 else 0.0)
            + 0.08 * (1.0 if clean_gradual_rotor_signature else 0.0)
            + 0.08 * (1.0 if gradual_unbalance_bias else 0.0)
            + 0.12 * (1.0 if sustained_high_1x_signature else 0.0)
            + 0.06 * (1.0 if stable_high_vib_count >= 2 or high_vib_count >= 2 else 0.0)
            + 0.08 * (1.0 if gradual_unbalance_bias and strong_1x_count >= 1 and symmetric_count >= 1 else 0.0)
            + 0.06 * (1.0 if low_ellipse_residual_count > 0 and high_cycle_size_similarity_count > 0 and orbit_case_count > 0 else 0.0)
            + 0.05 * (1.0 if true_1x_dominant_count >= 6 else 0.0)
            - 0.05 * (1.0 if two_x_activity_count > 0 or half_freq_activity_count > 0 else 0.0)
            # 存在突变/跳变证据时，降低渐变不平衡得分（更像断叶片/进异物）
            - 0.12 * (1.0 if jump_vib_count >= 2 or rapid_rising_vib_count > 0 or post_step_high_vib_count > 0 else 0.0)
            # 存在摩擦非线性特征（反进动/分数谐波/不规则轨迹）时，降低渐变不平衡得分
            - 0.10 * (1.0 if friction_nonlinear_signature else 0.0)
            # 存在油封积垢特征时，降低渐变不平衡得分
            - 0.10 * (1.0 if seal_fouling_signature else 0.0)
            # 汽轮机+波动+1X近期上涨是汽封漆膜摩擦典型特征，应降低渐变不平衡得分
            - 0.15 * (1.0 if not compressor_like and volatile_vib_count >= 2 and one_x_recent_rise_count > 0 else 0.0)
        ),
        ["振动呈渐变上涨或长期偏高，波形和轨迹总体仍保持不平衡型特征，正进动、对称正弦。"],
        ["上涨证据不足。"] if rising_vib_count < 2 and high_deviation_vib_count < 2 else [],
        ["存在明显毛刺/冲击/不对称，更像摩擦或测量异常。"] if glitch_count > 0 or asymmetric_count > 0 or high_kurtosis_count > 0 else [],
    )

    add(
        "unbalance_sudden",
        _clip_score(
            0.22 * (1.0 if rapid_rising_vib_count > 0 or jump_vib_count >= 2 else 0.0)
            + 0.20 * (1.0 if strong_1x_count >= 1 else (0.7 if dominant_1x_count >= 1 else 0.0))
            + 0.15 * (1.0 if ellipse_like_count >= 1 or orbit_case_count == 0 else 0.0)
            + 0.13 * (1.0 if high_vib_count >= 1 else 0.0)
            + 0.10 * (1.0 if volatile_vib_count <= 1 else 0.0)
            + 0.10 * (1.0 if normal_kurtosis_count >= 1 and sine_crest_count >= 1 else (0.5 if waveform_case_count == 0 else 0.0))
            + 0.10 * (1.0 if forward_precession_count > 0 or orbit_case_count == 0 else 0.0)
            + 0.08 * (1.0 if post_step_high_vib_count > 0 or one_x_recent_rise_count > 0 else 0.0)
            - 0.05 * (1.0 if half_freq_activity_count > 0 or remain_freq_activity_count > 0 else 0.0)
            - 0.12 * (1.0 if not critical_fast_change_signature and strong_1x_count >= 1 and high_repeatability_count >= 1 else 0.0)
            # 波动大不可能是纯突变不平衡——摩擦/流体/轴承故障才会波动
            - 0.15 * (1.0 if volatile_vib_count >= 2 else 0.0)
            # 汽轮机+波动+1X近期上涨是汽封漆膜摩擦典型特征，应降低突变不平衡得分
            - 0.15 * (1.0 if not compressor_like and volatile_vib_count >= 2 and one_x_recent_rise_count > 0 else 0.0)
        ),
        ["振动在短时间内快速跳变，随后仍表现为不平衡型 1X 特征，正进动。"],
        ["缺少明显快速跳变证据。"] if rapid_rising_vib_count == 0 and jump_vib_count < 2 else [],
        ["波形长期失稳，更像流体扰动。"] if volatile_vib_count > 1 and low_freq_count > 0 else [],
    )

    add(
        "critical_response",
        _clip_score(
            0.10 * (1.0 if jump_vib_count >= 2 else 0.0)
            + 0.18 * (1.0 if strong_1x_count >= 1 else 0.0)
            + 0.17 * (1.0 if sine_like_count >= 1 else 0.0)
            + 0.10 * (1.0 if ellipse_like_count >= 1 or orbit_case_count == 0 else 0.0)
            + 0.10 * (1.0 if high_vib_count >= 2 else 0.0)
            + 0.08 * (1.0 if circle_like_count > 0 else 0.0)
            + 0.07 * (1.0 if high_repeatability_count >= 1 or waveform_case_count == 0 else 0.0)
            + 0.18 * (1.0 if critical_fast_change_signature and not (not compressor_like and volatile_vib_count >= 2 and one_x_recent_rise_count > 0) else 0.0)
            - 0.14 * (1.0 if clean_gradual_rotor_signature else 0.0)
            - 0.16 * (1.0 if sustained_high_1x_signature else 0.0)
            - 0.10 * (1.0 if not critical_fast_change_signature and circle_like_count == 0 else 0.0)
            - 0.12 * (1.0 if gradual_unbalance_bias and post_step_high_vib_count == 0 and rapid_rising_vib_count == 0 and one_x_recent_rise_count == 0 else 0.0)
            - 0.08 * (1.0 if reverse_precession_count > 0 and circle_like_count == 0 and elongated_orbit_count > 0 else 0.0)
            # 存在摩擦非线性特征时，降低临界响应得分
            - 0.10 * (1.0 if friction_nonlinear_signature else 0.0)
            # 汽轮机+波动+1X近期上涨是汽封漆膜摩擦典型特征，应降低临界响应得分
            - 0.12 * (1.0 if not compressor_like and volatile_vib_count >= 2 and one_x_recent_rise_count > 0 else 0.0)
        ),
        ["振动在特定时段快速放大，图谱仍以同步 1X 特征为主，轨迹接近圆形。"],
        ["缺少明显快速放大或共振区高振证据。"] if jump_vib_count < 2 and post_step_high_vib_count == 0 and rapid_rising_vib_count == 0 else [],
        ["当前更像长期渐变不平衡，而不是短时穿越临界导致的放大。"] if clean_gradual_rotor_signature else [],
    )

    misalign_penalty = (
        0.05 * (1.0 if asymmetric_count > 0 or high_skewness_count > 0 else 0.0)
        + 0.08 * (1.0 if reverse_precession_count > 0 else 0.0)
        + 0.05 * (1.0 if low_repeatability_count > 0 else 0.0)
        + 0.10 * (1.0 if weak_1x_count >= 2 and strong_1x_count == 0 and (figure_eight_count > 0 or shape_inconsistent_count > 0) else 0.0)
        # 文档要求趋势平稳，波动大时更像流体扰动
        + 0.10 * (1.0 if volatile_vib_count >= 2 else 0.0)
        # 存在工艺量/喘振联动时，更像流体扰动而非不对中
        + 0.08 * (1.0 if process_anomaly_count > 0 or surge_active_type_count > 0 else 0.0)
        # 温度/GAP/同轴承多通道证据更强时，更像轴承磨损而非不对中
        + 0.08 * (1.0 if bearing_wear_strong else 0.0)
    )
    add(
        "misalignment",
        _clip_score(
            0.25 * (1.0 if coupling_side_high >= 2 else (0.6 if coupling_side_high >= 1 else 0.0))
            + 0.20 * (1.0 if strong_1x_count >= 1 else (0.5 if dominant_1x_count >= 1 else 0.0))
            + 0.15 * (1.0 if strong_2x_count > 0 else 0.0)
            + 0.10 * (1.0 if elongated_orbit_count > 0 else 0.0)
            + 0.10 * (1.0 if process_anomaly_count == 0 else 0.0)
            + 0.05 * (1.0 if figure_eight_count > 0 else 0.0)
            + 0.05 * (1.0 if high_repeatability_count >= 1 or waveform_case_count == 0 else 0.0)
            + 0.05 * (1.0 if forward_precession_count > 0 or orbit_case_count == 0 else 0.0)
            + 0.05 * (1.0 if symmetric_count >= 1 or waveform_case_count == 0 else 0.0)
            + 0.08 * (1.0 if two_x_activity_count > 0 else 0.0)
            + 0.06 * (1.0 if low_ellipse_residual_count > 0 and orbit_case_count > 0 else 0.0)
            - misalign_penalty
        ),
        ["联端相关通道振动偏高，伴随 1X/2X 和细长椭圆轨迹特征，正进动、波形对称。"],
        ["联端侧支撑证据不足。"] if coupling_side_high == 0 else [],
        ["波形不对称或反进动或重复性差，更像摩擦/流体扰动。"] if misalign_penalty > 0 else [],
    )

    add(
        "coupling_damage",
        _clip_score(
            0.30 * (1.0 if coupling_side_high > 0 else 0.0)
            + 0.18 * (1.0 if jump_vib_count >= 2 or rapid_rising_vib_count > 0 else 0.0)
            + 0.17 * (1.0 if strong_1x_count >= 1 else 0.0)
            + 0.15 * (1.0 if strong_2x_count > 0 else 0.0)
            + 0.10 * (1.0 if gap_change_count == 0 and bool(gap_items) else 0.0)
            + 0.10 * (1.0 if high_kurtosis_count > 0 or asymmetric_count > 0 else 0.0)
            + 0.08 * (1.0 if post_step_high_vib_count > 0 or two_x_activity_count > 0 else 0.0)
        ),
        ["联轴器两端相关通道同步变化，且 GAP 无明显持续变化。"],
        ["缺少联端同步快速变化证据。"] if coupling_side_high == 0 else [],
        [],
    )

    add(
        "bearing_wear",
        _clip_score(
            0.16 * (1.0 if bearing_pair_high > 0 else 0.0)
            + 0.14 * (1.0 if bearing_pair_medium > 0 else 0.0)
            + 0.20 * (1.0 if rising_temp_count > 0 or high_temp_count > 0 or support_temp_stable_high_count > 0 else 0.0)
            + 0.15 * (1.0 if gap_change_count > 0 else 0.0)
            + 0.10 * (1.0 if irregular_orbit_count > 0 else 0.0)
            + 0.10 * (1.0 if strong_1x_count >= 1 else 0.0)
            + 0.10 * (1.0 if moderate_kurtosis_count > 0 else 0.0)
            + 0.10 * (1.0 if crescent_count > 0 else 0.0)
            + 0.08 * (1.0 if temp_step_high_count > 0 or post_step_high_vib_count > 0 else 0.0)
            + 0.08 * (1.0 if wear_smooth_support else 0.0)
            + 0.12 * (1.0 if clearance_wear_signature else 0.0)
            + 0.12 * (1.0 if bearing_wear_strong else 0.0)
            + 0.15 * (1.0 if bearing_wear_strong and not strong_fluid_signature else 0.0)
            + 0.12 * (1.0 if bearing_wear_priority_signature else 0.0)
            + 0.10 * (1.0 if bearing_pair_high > 0 and oil_whirl_count == 0 else 0.0)
            + 0.08 * (1.0 if (rising_temp_count > 0 or high_temp_count > 0) and oil_whirl_count == 0 and not strong_fluid_signature else 0.0)
            # 无温度+少量GAP变化(<3)但有同轴承多通道+峭度/轨迹异常时给保底分
            + 0.30 * (1.0 if (bearing_pair_high > 0 or bearing_pair_medium > 0)
                      and rising_temp_count == 0 and high_temp_count == 0 and support_temp_stable_high_count == 0
                      and gap_change_count < 3
                      and (moderate_kurtosis_count > 0 or irregular_orbit_count > 0 or shape_inconsistent_count > 0)
                      else 0.0)
            - 0.14 * (1.0 if not bearing_wear_multisource_signature else 0.0)
            - 0.10 * (1.0 if not waveform_pattern_ready and orbit_case_count == 0 and gap_change_count == 0 else 0.0)
            - 0.06 * (1.0 if support_temp_stable_high_count >= 2 and gap_change_count == 0 else 0.0)
        ),
        ["同一支撑轴承相关通道同步异常，且伴随温度或 GAP 变化，峭度中等偏高。"]
        + (["振动持续变化 + 温度同步异常，即使 GAP 暂未变化也符合轴承磨损特征。"] if bearing_wear_strong and gap_change_count == 0 else []),
        ["温度或 GAP 同步证据不足。"] if rising_temp_count == 0 and high_temp_count == 0 and support_temp_stable_high_count == 0 and gap_change_count == 0 else [],
        [],
    )

    add(
        "bearing_assembly",
        _clip_score(
            0.28 * (1.0 if bearing_pair_diff > 0 or bearing_pair_high > 0 else 0.0)
            + 0.17 * (1.0 if elongated_orbit_count > 0 else 0.0)
            + 0.15 * (1.0 if strong_1x_count >= 1 else 0.0)
            + 0.10 * (1.0 if volatile_vib_count <= 1 else 0.0)
            + 0.10 * (1.0 if high_temp_count > 0 else 0.0)
            + 0.10 * (1.0 if crescent_count > 0 else 0.0)
            + 0.10 * (1.0 if low_repeatability_count > 0 and high_repeatability_count == 0 else 0.0)
            + 0.10 * (1.0 if support_temp_stable_high_count >= 2 else 0.0)
            - 0.06 * (1.0 if gap_change_count > 0 or temp_step_high_count > 0 else 0.0)
        ),
        ["单端支撑轴承两个通道偏高或差异明显，伴随细长椭圆或月牙形轨迹，重复性稍差。"],
        ["同端差异证据不足。"] if bearing_pair_diff == 0 and bearing_pair_high == 0 else [],
        [],
    )

    add(
        "bearing_coating",
        _clip_score(
            0.28 * (1.0 if high_temp_count > 0 else 0.0)
            + 0.22 * (1.0 if gap_change_count > 0 else 0.0)
            + 0.15 * (1.0 if volatile_vib_count > 0 else 0.0)
            + 0.15 * (1.0 if strong_1x_count >= 1 else 0.0)
            + 0.10 * (1.0 if low_repeatability_count > 0 and high_repeatability_count == 0 else 0.0)
            + 0.10 * (1.0 if rising_temp_count > 0 else 0.0)
            + 0.08 * (1.0 if temp_step_high_count > 0 else 0.0)
        ),
        ["轴承温度与振动/GAP 存在联动变化，波形重复性稍差。"],
        ["缺少温度高位或持续变化证据。"] if high_temp_count == 0 and rising_temp_count == 0 else [],
        [],
    )

    add(
        "shaft_current",
        _clip_score(
            0.20 * (1.0 if glitch_count > 1 or high_glitch_ratio_count > 0 else 0.0)
            + 0.15 * (1.0 if volatile_vib_count > 0 else 0.0)
            + 0.18 * (1.0 if high_temp_count > 0 else 0.0)
            + 0.12 * (1.0 if medium_vib_count >= 2 else 0.0)
            + 0.15 * (1.0 if high_kurtosis_count > 0 else 0.0)
            + 0.10 * (1.0 if high_crest_count > 0 else 0.0)
            + 0.10 * (1.0 if outlier_kurtosis_count > 0 else 0.0)
            # 极端峭度+波动：强轴电流特征，额外加分
            + 0.12 * (1.0 if shaft_current_extreme_kurtosis else 0.0)
            + 0.10 * (1.0 if shaft_current_priority_signature else 0.0)
            # 波形缺失时降权：轴电流诊断强依赖波形特征
            - 0.20 * (1.0 if waveform_case_count == 0 else 0.0)
            # 不符合轴电流特征组合时适度降分（极端峭度可豁免）
            - 0.12 * (1.0 if not shaft_current_signature and not shaft_current_extreme_kurtosis else 0.0)
            # 存在持续上涨或台阶变化时更像机械故障而非轴电流
            - 0.10 * (1.0 if rapid_rising_vib_count > 0 or post_step_high_vib_count > 0 else 0.0)
            - 0.18 * (1.0 if shaft_current_conflict_signature else 0.0)
        ),
        ["多通道存在脉冲/毛刺样异常，且伴随温度或振动波动，峭度偏高。"]
        + (["波动后快速回落，无持续上涨或台阶变化，符合轴电流短时放电特征。"] if shaft_current_signature else [])
        + (["峭度极端异常（>20），结合波动特征，强烈指向轴电流放电。"] if shaft_current_extreme_kurtosis else []),
        (["缺少明显放电脉冲型特征。"] if glitch_count <= 1 and high_kurtosis_count == 0 and outlier_kurtosis_count == 0 else [])
        + (["特征组合不满足轴电流典型模式，可能为其他故障。"] if not shaft_current_signature and not shaft_current_extreme_kurtosis else []),
        (["存在持续上涨或台阶变化，更像机械故障而非轴电流。"] if rapid_rising_vib_count > 0 or post_step_high_vib_count > 0 else [])
        + (["当前存在结垢或渐变 1X 证据，轴电流应降级为备选。"] if shaft_current_conflict_signature else []),
    )

    add(
        "thrust_wear",
        _clip_score(
            0.45 * (1.0 if disp_change_count >= 2 else 0.0)
            + 0.25 * (1.0 if rising_temp_count > 0 or high_temp_count > 0 else 0.0)
            + 0.20 * (1.0 if glitch_count > 0 else 0.0)
            + 0.10 * (1.0 if thrust_temp_stable_high_count > 0 else 0.0)
            - 0.18 * (1.0 if thrust_friction_conflict else 0.0)
            - 0.08 * (1.0 if thrust_temp_stable_high_count >= 2 and disp_change_count == 0 else 0.0)
        ),
        ["多通道轴位移存在同步持续变化，并伴随推力相关温度变化。"],
        ["轴位移同步变化证据不足。"] if disp_change_count < 2 else [],
        ["存在反进动/谐波/非线性轨迹，更像汽封摩擦而非纯推力磨损。"] if thrust_friction_conflict else [],
    )

    add(
        "thrust_assembly",
        _clip_score(
            0.40 * (1.0 if thrust_temp_stable_high_count >= 2 else 0.0)
            + 0.20 * (1.0 if high_temp_count > 0 else 0.0)
            + 0.15 * (1.0 if rising_temp_count == 0 else 0.0)
            + 0.15 * (1.0 if disp_change_count <= 1 else 0.0)
            + 0.10 * (1.0 if volatile_vib_count <= 1 else 0.0)
        ),
        ["推力轴承温度长期高位且整体平稳，更像装配或设计偏差。"],
        ["缺少推力轴承双通道高位平稳证据。"] if thrust_temp_stable_high_count < 2 else [],
        ["轴位移持续变化更强，更像推力轴承磨损。"] if disp_change_count >= 2 else [],
    )

    add(
        "medium_fouling",
        _clip_score(
            0.35 * (1.0 if disp_change_count >= 1 else 0.0)
            + 0.25 * (1.0 if high_deviation_vib_count >= 1 or rising_vib_count > 0 else 0.0)
            + 0.20 * (1.0 if strong_1x_count >= 1 else (0.7 if dominant_1x_count >= 1 else 0.0))
            + 0.12 * (1.0 if process_anomaly_count > 0 else 0.0)
            + 0.08 * (1.0 if one_x_long_rise_count > 0 else 0.0)
            + 0.12 * (1.0 if compressor_fouling_signature else 0.0)
            + 0.08 * (1.0 if gap_stable_count >= 2 else 0.0)
            + 0.08 * (1.0 if steam_fouling_like_signature else 0.0)
            + 0.10 * (1.0 if fouling_priority_signature else 0.0)
            + 0.08 * (1.0 if not compressor_like and gas_path_active_type_count > 0 and surge_active_type_count == 0 else 0.0)
            - 0.10 * (1.0 if surge_active_type_count > 0 else 0.0)
            - 0.10 * (1.0 if gap_change_count > 0 else 0.0)
            - 0.10 * (1.0 if irregular_orbit_count > 0 or fractional_harmonic_count > 0 else 0.0)
            - 0.30 * (1.0 if volatile_vib_count >= 2 and one_x_recent_rise_count > 0 else 0.0)
        ),
        ["轴位移变化与渐变不平衡证据同时存在。"]
        + (["轴位移与负荷/蒸汽类工艺量同步，且缺少喘振联动，更像结垢/结焦累积。"] if steam_fouling_like_signature else [])
        + (["振动持续上涨 + GAP 平稳 + 1X 为主，符合压缩机叶轮结垢特征。"] if compressor_fouling_signature else []),
        ["轴位移或结垢渐变证据不足。"] if disp_change_count == 0 and not compressor_fouling_signature else [],
        (["GAP 电压存在持续变化，更像轴承磨损而非结垢。"] if gap_change_count > 0 else [])
        + (["存在防喘振阀/入口流量联动，更像流体扰动而非结垢累积。"] if surge_active_type_count > 0 else [])
        + (["存在不规则轨迹或分数谐波，更像摩擦而非纯介质结垢。"] if irregular_orbit_count > 0 or fractional_harmonic_count > 0 else [])
        + (["振动波动伴随 1X 近期上涨，更像汽封漆膜摩擦而非介质结垢。"] if volatile_vib_count >= 2 and one_x_recent_rise_count > 0 else []),
    )

    add(
        "impeller_fouling",
        _clip_score(
            0.30 * (1.0 if rising_vib_count >= 2 else 0.0)
            + 0.18 * (1.0 if high_deviation_vib_count >= 1 else 0.0)
            + 0.16 * (1.0 if strong_1x_count >= 1 else (0.7 if dominant_1x_count >= 1 else 0.0))
            + 0.14 * (1.0 if gap_stable_count >= 2 else 0.0)
            + 0.12 * (1.0 if one_x_long_rise_count > 0 or one_x_high_deviation_count >= 1 else 0.0)
            + 0.18 * (1.0 if impeller_fouling_signature else 0.0)
            + 0.08 * (1.0 if high_repeatability_count >= 1 or waveform_case_count == 0 else 0.0)
            - 0.16 * (1.0 if strong_fluid_signature else 0.0)
            - 0.12 * (1.0 if surge_active_type_count > 0 else 0.0)
            - 0.10 * (1.0 if gap_change_count > 0 or high_kurtosis_count > 0 else 0.0)
        ),
        ["压缩机振动呈渐变上涨，GAP 稳定且 1X 持续增强，更像叶轮结垢累积。"] if impeller_fouling_signature else [],
        ["缺少 1X 渐变上涨与 GAP 稳定的叶轮结垢特征。"] if not impeller_fouling_signature else [],
        (["存在明确喘振/气路联动，更像流体扰动而非叶轮结垢。"] if strong_fluid_signature or surge_active_type_count > 0 else [])
        + (["GAP 持续变化或高峭度冲击，不像典型叶轮结垢。"] if gap_change_count > 0 or high_kurtosis_count > 0 else []),
    )

    add(
        "gear_mesh",
        _clip_score(
            0.28 * (1.0 if very_strong_2x_count > 0 else 0.0)
            + 0.10 * (1.0 if dominant_1x_count == 0 else 0.0)
            + 0.15 * (1.0 if volatile_vib_count > 0 or jump_vib_count > 0 else 0.0)
            + 0.10 * (1.0 if fractional_harmonic_count > 0 else 0.0)
            + 0.10 * (1.0 if high_kurtosis_count > 0 else 0.0)
            + 0.08 * (1.0 if two_x_activity_count > 0 else 0.0)
        ),
        ["频谱存在明显非纯 1X 的啮合/谐波特征，伴随分数谐波或峭度偏高。"],
        ["缺少明显啮合相关频率与谐波证据。"] if very_strong_2x_count == 0 else [],
        [],
    )

    add(
        "gear_damage",
        _clip_score(
            0.25 * (1.0 if glitch_count > 0 or jump_vib_count > 0 else 0.0)
            + 0.20 * (1.0 if strong_2x_count > 0 else 0.0)
            + 0.10 * (1.0 if volatile_vib_count > 0 else 0.0)
            + 0.15 * (1.0 if high_kurtosis_count > 0 else 0.0)
            + 0.10 * (1.0 if high_crest_count > 0 else 0.0)
            + 0.08 * (1.0 if two_x_activity_count > 0 or remain_freq_activity_count > 0 else 0.0)
        ),
        ["存在冲击/跳变和谐波增强，峭度偏高，需关注轮齿损伤。"],
        ["缺少明显冲击或啮合损伤证据。"] if glitch_count == 0 and jump_vib_count == 0 and high_kurtosis_count == 0 else [],
        [],
    )

    add(
        "screw_ingestion",
        _clip_score(
            0.26 * (1.0 if jump_vib_count >= 2 or rapid_rising_vib_count > 0 or post_step_high_vib_count > 0 else 0.0)
            + 0.18 * (1.0 if strong_2x_count > 0 or two_x_activity_count > 0 else 0.0)
            + 0.16 * (1.0 if high_kurtosis_count > 0 or glitch_count > 0 else 0.0)
            + 0.14 * (1.0 if strong_1x_count >= 1 else 0.0)
            + 0.12 * (1.0 if screw_ingestion_signature else 0.0)
            + 0.10 * (1.0 if fractional_harmonic_count > 0 or remain_freq_activity_count > 0 else 0.0)
            - 0.14 * (1.0 if strong_fluid_signature else 0.0)
            - 0.10 * (1.0 if bearing_wear_strong else 0.0)
        ),
        ["螺杆机存在突变、冲击与啮合谐波特征，更像进异物导致的啮合偏差。"] if screw_ingestion_signature else [],
        ["缺少明显突变冲击或啮合谐波证据。"] if not screw_ingestion_signature else [],
        (["存在明确气路/流体联动，更像流体扰动。"] if strong_fluid_signature else [])
        + (["温度/GAP 与同轴承多通道证据更强，更像轴承类故障。"] if bearing_wear_strong else []),
    )

    add(
        "rotor_runout",
        _clip_score(
            0.24 * (1.0 if strong_1x_count >= 2 else (0.7 if dominant_1x_count >= 2 else 0.0))
            + 0.18 * (1.0 if ellipse_like_count >= 1 or elongated_orbit_count > 0 else 0.0)
            + 0.14 * (1.0 if high_repeatability_count >= 1 else 0.0)
            + 0.10 * (1.0 if symmetric_count >= 1 else 0.0)
            + 0.10 * (1.0 if forward_precession_count > 0 else 0.0)
            + 0.10 * (1.0 if rotor_runout_signature else 0.0)
            + 0.08 * (1.0 if disp_change_count > 0 or gap_change_count > 0 else 0.0)
            - 0.12 * (1.0 if reverse_precession_count > 0 or fractional_harmonic_count > 0 else 0.0)
            - 0.10 * (1.0 if low_freq_count > 0 or process_anomaly_count > 0 else 0.0)
        ),
        ["稳定 1X、规则轨迹与较高重复性同时出现，更像测振区晃度或转子偏心。"] if rotor_runout_signature else [],
        ["缺少稳定 1X、规则轨迹与重复性支撑证据。"] if not rotor_runout_signature else [],
        (["存在反进动、分数谐波或低频工艺联动，更像摩擦/流体扰动。"] if reverse_precession_count > 0 or fractional_harmonic_count > 0 or low_freq_count > 0 or process_anomaly_count > 0 else []),
    )

    add(
        "bent_rotor",
        _clip_score(
            0.28 * (1.0 if high_vib_count >= 2 else 0.0)
            + 0.22 * (1.0 if strong_1x_count >= 1 else (0.7 if dominant_1x_count >= 1 else 0.0))
            + 0.15 * (1.0 if disp_change_count > 0 else 0.0)
            + 0.15 * (1.0 if sine_like_count >= 1 else 0.0)
            + 0.10 * (1.0 if forward_precession_count > 0 or orbit_case_count == 0 else 0.0)
            + 0.10 * (1.0 if normal_kurtosis_count >= 1 and sine_crest_count >= 1 else (0.5 if waveform_case_count == 0 else 0.0))
            + 0.08 * (1.0 if one_x_high_deviation_count > 0 or one_x_long_rise_count > 0 else 0.0)
            - 0.06 * (1.0 if half_freq_activity_count > 0 or remain_freq_activity_count > 0 else 0.0)
            # 存在快速跳变/台阶变化时更像断叶片/进异物而非弯曲
            - 0.15 * (1.0 if jump_vib_count >= 2 or rapid_rising_vib_count > 0 or post_step_high_vib_count > 0 else 0.0)
            # 存在反进动时更像摩擦而非纯弯曲
            - 0.08 * (1.0 if reverse_precession_count > 0 else 0.0)
            # 波动大不可能是纯弯曲——摩擦/流体/轴承故障才会波动
            - 0.10 * (1.0 if volatile_vib_count >= 2 else 0.0)
            # 汽轮机+波动+1X近期上涨是汽封漆膜摩擦典型特征，应降低弯曲得分
            - 0.10 * (1.0 if not compressor_like and volatile_vib_count >= 2 and one_x_recent_rise_count > 0 else 0.0)
        ),
        ["高振同步 1X 特征明显，且伴随转子几何偏移迹象，正进动。"],
        ["缺少轴位移或几何偏差支撑证据。"] if disp_change_count == 0 else [],
        (["存在快速跳变或台阶变化，更像断叶片/进异物等突变故障而非弯曲。"] if jump_vib_count >= 2 or rapid_rising_vib_count > 0 or post_step_high_vib_count > 0 else []),
    )

    def _adjust_candidate_scores(rule_ids: set[str], delta: float, reason: str, *, positive: bool) -> None:
        for item in candidates:
            if item.rule_id not in rule_ids:
                continue
            item.score = round(_clip_score(item.score + delta), 4)
            target = item.matched_conditions if positive else item.contradictions
            if reason not in target:
                target.append(reason)

    def _cap_candidate_scores(rule_ids: set[str], max_score: float, reason: str) -> None:
        for item in candidates:
            if item.rule_id not in rule_ids or item.score <= max_score:
                continue
            item.score = round(max_score, 4)
            if reason not in item.contradictions:
                item.contradictions.append(reason)

    if not strong_process_sync_signature:
        _adjust_candidate_scores(
            {"process_sync"},
            -0.12,
            "缺少明确负荷类测点主导或存在机械反证，负荷同步优先级下调。",
            positive=False,
        )
    if soft_rub_signature:
        _adjust_candidate_scores(
            {"friction", "seal_fouling"},
            0.08,
            "存在反进动、轨迹异常与 1X 演化，符合软摩擦模式。",
            positive=True,
        )
        # 有强低频证据时不罚流体——喘振/失速常伴随反进动
        _soft_rub_fluid_penalty = 0.0 if (strong_low_freq_count >= 2 or strong_very_low_freq_count >= 2 or strong_low_freq_signature) else -0.12
        _adjust_candidate_scores(
            {"fluid_disturbance", "fluid_excitation"},
            _soft_rub_fluid_penalty,
            "存在反进动与轨迹异常，更像摩擦或结垢而非直接流体扰动。" if _soft_rub_fluid_penalty < 0 else "",
            positive=False,
        )
        _adjust_candidate_scores(
            {"process_sync", "medium_fouling"},
            -0.12,
            "存在反进动与轨迹异常，更像摩擦或结垢而非直接工艺同步或介质结垢。",
            positive=False,
        )
    # 有强低频证据时，流体扰动优先于摩擦（即使没有工艺量异常，频谱已足够）
    if strong_low_freq_count >= 2 or strong_very_low_freq_count >= 2 or strong_low_freq_signature:
        _adjust_candidate_scores(
            {"fluid_disturbance", "fluid_excitation"},
            0.10,
            "频谱存在明确强低频证据，流体扰动/喘振优先级上调。",
            positive=True,
        )
        _adjust_candidate_scores(
            {"friction"},
            -0.08,
            "频谱存在明确强低频证据，更可能是流体扰动而非机械摩擦。",
            positive=False,
        )
    if seal_fouling_signature or seal_coking_signature:
        _adjust_candidate_scores(
            {"seal_fouling", "seal_coking"},
            0.18,
            "存在油封积垢/结焦累积特征，优先抬升密封积垢相关候选。",
            positive=True,
        )
        # 有强低频证据时，不限制流体扰动（非压缩机 + 低频可能是气流扰动而非油封问题）
        _seal_fluid_cap = 0.78 if (strong_low_freq_signature and not compressor_like) else 0.58
        _cap_candidate_scores(
            {"fluid_disturbance", "fluid_excitation", "process_sync", "medium_fouling"},
            _seal_fluid_cap,
            "存在油封积垢/结焦累积证据，限制流体扰动、工艺同步和介质结垢类过高得分。",
        )
    if fouling_priority_signature:
        _adjust_candidate_scores(
            {"medium_fouling", "unbalance_gradual", "seal_coking", "impeller_fouling"},
            0.10,
            "存在轴位移演化、GAP 稳定与 1X 渐变，支持结垢/结焦累积故障。",
            positive=True,
        )
        _adjust_candidate_scores(
            {"fluid_disturbance", "fluid_excitation", "process_sync"},
            -0.12,
            "当前更像结垢/结焦累积而非直接流体扰动或负荷跟随。",
            positive=False,
        )
    if impeller_fouling_signature:
        _adjust_candidate_scores(
            {"impeller_fouling", "unbalance_gradual", "medium_fouling"},
            0.10,
            "存在压缩机叶轮结垢特征，优先抬升叶轮结垢相关候选。",
            positive=True,
        )
        _cap_candidate_scores(
            {"fluid_disturbance", "fluid_excitation", "shaft_current"},
            0.68,
            "存在叶轮结垢累积特征，限制流体扰动和轴电流类过高得分。",
        )
    if compressor_fouling_signature:
        _cap_candidate_scores(
            {"fluid_disturbance", "fluid_excitation"},
            0.72,
            "存在压缩机结垢渐变特征，限制流体扰动类过高得分。",
        )
    if mechanical_1x_bias_signature:
        _adjust_candidate_scores(
            {"unbalance_gradual", "medium_fouling", "impeller_fouling", "rotor_runout"},
            0.08,
            "稳定 1X、重复性与渐变证据同时存在，更像机械渐变类故障而非纯流体激振。",
            positive=True,
        )
        _cap_candidate_scores(
            {"fluid_disturbance", "fluid_excitation"},
            0.76,
            "存在稳定 1X 与机械渐变证据，限制流体扰动类过高得分。",
        )
    if shaft_current_priority_signature:
        _adjust_candidate_scores(
            {"shaft_current"},
            0.14,
            "存在放电脉冲与极端峭度，轴电流优先级大幅上调。",
            positive=True,
        )
        _adjust_candidate_scores(
            {"fluid_disturbance", "fluid_excitation", "friction", "unbalance_sudden"},
            -0.12,
            "脉冲放电特征极强，大幅压低流体扰动、摩擦和突变不平衡优先级。",
            positive=False,
        )
    if bearing_wear_strong:
        _adjust_candidate_scores(
            {"bearing_wear"},
            0.08,
            "同轴承多通道与温度/GAP 证据一致，支撑轴承磨损优先级上调。",
            positive=True,
        )
        _adjust_candidate_scores(
            {"fluid_disturbance", "fluid_excitation", "oil_whirl"},
            -0.08,
            "温度、GAP 与同轴承多通道证据更强，流体扰动/油膜涡动优先级下调。",
            positive=False,
        )
    if bearing_wear_priority_signature:
        _adjust_candidate_scores(
            {"bearing_wear", "bearing_assembly"},
            0.08,
            "温度、GAP 与同轴承多通道证据同时成立，轴承类候选继续上调。",
            positive=True,
        )
        _cap_candidate_scores(
            {"fluid_disturbance", "fluid_excitation", "oil_whirl", "bent_rotor"},
            0.72,
            "温度/GAP 与同轴承多通道证据更强，限制非轴承类候选过高得分。",
        )
    if not bearing_wear_multisource_signature:
        # 无温度但有同轴承多通道+轨迹异常时，允许更高上限
        _bw_cap = 0.72 if ((bearing_pair_high > 0 or bearing_pair_medium > 0)
                           and rising_temp_count == 0 and high_temp_count == 0 and support_temp_stable_high_count == 0
                           and (moderate_kurtosis_count > 0 or irregular_orbit_count > 0 or shape_inconsistent_count > 0)) else 0.62
        _cap_candidate_scores(
            {"bearing_wear"},
            _bw_cap,
            "轴承磨损缺少多源独立证据，限制其作为主结论。",
        )
    if rotor_dominant_signature:
        _adjust_candidate_scores(
            {"unbalance_stable", "unbalance_gradual", "critical_response"},
            0.06,
            "稳定 1X 与渐变高振占优，更像转子类故障。",
            positive=True,
        )
        _adjust_candidate_scores(
            {"fluid_disturbance", "fluid_excitation", "process_sync"},
            -0.08,
            "稳定 1X 与渐变高振占优，流体扰动/工艺同步优先级下调。",
            positive=False,
        )
    if clean_rotor_nonfriction_signature:
        _adjust_candidate_scores(
            {"unbalance_stable", "unbalance_gradual", "critical_response", "rotor_runout", "bent_rotor"},
            0.08,
            "稳定 1X、对称与正进动明显，更像转子不平衡/临界响应而非摩擦。",
            positive=True,
        )
        _cap_candidate_scores(
            {"friction"},
            0.72,
            "稳定 1X、对称与正进动占优，限制摩擦类过高得分。",
        )
    # 汽轮机 + 波动 + 1X 近期上涨：汽封漆膜摩擦典型模式，抬升摩擦并压低不平衡/弯曲/介质结垢
    if not compressor_like and volatile_vib_count >= 2 and one_x_recent_rise_count > 0:
        _adjust_candidate_scores(
            {"friction", "seal_fouling"},
            0.15,
            "汽轮机存在波动与 1X 同步上涨，符合汽封漆膜摩擦典型模式。",
            positive=True,
        )
        _adjust_candidate_scores(
            {"unbalance_sudden", "unbalance_stable", "unbalance_gradual", "bent_rotor", "critical_response", "medium_fouling"},
            -0.10,
            "汽轮机存在波动与 1X 同步上涨，更像汽封漆膜摩擦而非不平衡/弯曲/介质结垢类故障。",
            positive=False,
        )
        _cap_candidate_scores(
            {"medium_fouling"},
            0.60,
            "汽轮机存在波动与 1X 同步上涨，限制介质结垢类过高得分，优先考虑汽封摩擦。",
        )
    if strong_fluid_signature:
        _adjust_candidate_scores(
            {"oil_whirl", "bearing_wear"},
            -0.10,
            "关键气路/喘振联动明确，优先压低轴承类候选。",
            positive=False,
        )
        _adjust_candidate_scores(
            {"fluid_disturbance", "fluid_excitation"},
            0.10,
            "关键气路/喘振联动明确，流体扰动类候选优先级上调。",
            positive=True,
        )
    if oil_whirl_conflict_signature:
        _cap_candidate_scores(
            {"oil_whirl"},
            0.68,
            "存在明显工艺/气路联动或机械反证，限制油膜涡动类过高得分。",
        )
    if rotor_runout_signature:
        _adjust_candidate_scores(
            {"rotor_runout", "bent_rotor"},
            0.10,
            "存在稳定 1X、规则轨迹与重复性，更像晃度/转子几何偏差。",
            positive=True,
        )
        _cap_candidate_scores(
            {"friction", "fluid_disturbance", "fluid_excitation", "process_sync"},
            0.70,
            "存在明显晃度/转子几何偏差证据，限制摩擦与流体扰动类过高得分。",
        )
    if not strong_fluid_signature and missing_strong_fluid_signature:
        _cap_candidate_scores(
            {"fluid_disturbance", "fluid_excitation"},
            0.66,
            "缺少关键气路/低频/非稳定轨迹证据，限制流体扰动类过高得分。",
        )
    if weak_fluid_no_specific_evidence and waveform_case_count > 0:
        _cap_candidate_scores(
            {"fluid_disturbance", "fluid_excitation"},
            0.80,
            "缺少喘振/气路联动且无强低频特征，仅凭泛化工艺量波动不足以支撑流体扰动为主结论。",
        )
    if weak_fluid_without_process_signature:
        # aero_excitation 基于波形/轨迹证据，即使无工艺量也应允许更高得分
        _wf_cap = 0.78 if aero_excitation_signature else (0.68 if waveform_case_count == 0 else 0.60)
        _cap_candidate_scores(
            {"fluid_disturbance", "fluid_excitation"},
            _wf_cap,
            "缺少工艺联动且低频支撑不足，限制流体扰动类作为主结论。",
        )
    if not strong_process_sync_signature and (steam_fouling_like_signature or rotor_dominant_signature):
        _cap_candidate_scores(
            {"process_sync"},
            0.54,
            "存在结垢或转子类机械反证，限制 process_sync 作为主结论。",
        )
    # process_sync 全局绝对上限
    _cap_candidate_scores(
        {"process_sync"},
        0.75,
        "process_sync 全局上限，防止工艺同步得分过高掩盖真实机械故障。",
    )
    # 2X 极强 + 1X 不主导：更像齿轮啮合/不对中而非流体扰动
    two_x_dominant_mechanical = (
        strong_2x_count > 0
        and very_strong_2x_count > 0
        and strong_1x_count == 0
    )
    if two_x_dominant_mechanical:
        _adjust_candidate_scores(
            {"fluid_disturbance", "fluid_excitation"},
            -0.10,
            "2X 和强谐波主导、1X 不占优，更像齿轮啮合或不对中而非流体扰动。",
            positive=False,
        )
        _adjust_candidate_scores(
            {"misalignment", "gear_mesh", "gear_damage", "coupling_damage"},
            0.06,
            "2X 和强谐波主导、1X 不占优，抬升啮合/不对中类候选。",
            positive=True,
        )
    if shaft_current_conflict_signature:
        _cap_candidate_scores(
            {"shaft_current"},
            0.70,
            "存在结垢或渐变 1X 机械反证，限制轴电流类过高得分。",
        )
    if impact_sudden_rotor_signature:
        _adjust_candidate_scores(
            {"unbalance_sudden", "gear_damage", "friction", "seal_fouling"},
            0.15,
            "存在突变、冲击和同步 1X 组合，更像进异物/断叶片/密封摩擦类突变转子故障。",
            positive=True,
        )
        _adjust_candidate_scores(
            {"bearing_wear"},
            -0.20,
            "存在突变冲击特征，压低平滑渐变型轴承磨损优先级。",
            positive=False,
        )
    if screw_ingestion_signature:
        _adjust_candidate_scores(
            {"screw_ingestion", "unbalance_sudden", "gear_damage", "gear_mesh"},
            0.10,
            "存在螺杆机突变冲击与啮合特征，优先抬升进异物/啮合偏差相关候选。",
            positive=True,
        )
        _cap_candidate_scores(
            {"fluid_disturbance", "fluid_excitation", "bearing_wear"},
            0.70,
            "存在螺杆机突变啮合证据，限制流体扰动和轴承磨损类过高得分。",
        )
    if waveform_case_count == 0 and orbit_case_count == 0:
        _cap_candidate_scores(
            {"bearing_wear", "rotor_runout", "oil_whirl", "fluid_disturbance", "fluid_excitation", "friction"},
            0.60,
            "波形与轨迹数据缺失，限制强依赖图谱的规则作为主结论。",
        )
    elif not waveform_pattern_ready:
        _cap_candidate_scores(
            {"fluid_disturbance", "fluid_excitation", "oil_whirl", "shaft_current", "friction"},
            0.70,
            "波形样本不足，限制强依赖频谱规则的过高得分。",
        )
    if not orbit_pattern_ready:
        _cap_candidate_scores(
            {"oil_whirl", "rotor_runout", "misalignment", "friction"},
            0.68,
            "轴心轨迹样本不足，限制强依赖轨迹规则的过高得分。",
        )

    # 工艺量数据全部静默时，无法验证流体/工艺类规则，应限制其得分
    all_process_silent = (
        process_anomaly_count == 0
        and surge_process_count == 0
        and gas_path_process_count == 0
        and load_process_count == 0
    )
    if all_process_silent:
        # is_surge/aero_excitation 基于频谱证据，即使工艺量静默也应允许更高得分
        _fluid_cap = 0.78 if (is_surge or aero_excitation_signature) else 0.62
        _cap_candidate_scores(
            {"fluid_disturbance", "fluid_excitation", "process_sync"},
            _fluid_cap,
            "工艺量数据全部静默，缺少验证流体扰动/工艺同步的外部证据。",
        )

    candidate_min_score = _safe_float(thresholds.get("candidate_min_score")) or 0.25
    filtered = [item for item in candidates if item.score >= candidate_min_score]
    filtered.sort(key=lambda item: (item.score, len(item.matched_conditions), -len(item.contradictions)), reverse=True)

    # ---- debug info ----
    def _b(v: Any) -> bool:
        return bool(v)

    debug_info: dict[str, Any] = {
        "feature_counts": {
            # vibration trend
            "high_vib_count": high_vib_count,
            "medium_vib_count": medium_vib_count,
            "jump_vib_count": jump_vib_count,
            "rapid_rising_vib_count": rapid_rising_vib_count,
            "volatile_vib_count": volatile_vib_count,
            "rising_vib_count": rising_vib_count,
            "high_deviation_vib_count": high_deviation_vib_count,
            "post_step_high_vib_count": post_step_high_vib_count,
            "over_limit_vib_count": over_limit_vib_count,
            "stable_high_vib_count": stable_high_vib_count,
            "high_alarm_vib_count": high_alarm_vib_count,
            # 1X / 2X / sub-sync（新度量：peak-based，旧度量作为对比）
            "strong_1x_count": strong_1x_count,
            "dominant_1x_count": dominant_1x_count,
            "weak_1x_count": weak_1x_count,
            "old_strong_1x_count": _old_strong_1x,
            "old_dominant_1x_count": _old_dominant_1x,
            "true_1x_dominant_count": true_1x_dominant_count,
            "strong_2x_count": strong_2x_count,
            "very_strong_2x_count": very_strong_2x_count,
            "one_x_recent_rise_count": one_x_recent_rise_count,
            "one_x_long_rise_count": one_x_long_rise_count,
            "one_x_high_deviation_count": one_x_high_deviation_count,
            "one_x_volatile_count": one_x_volatile_count,
            "two_x_activity_count": two_x_activity_count,
            "half_freq_activity_count": half_freq_activity_count,
            "remain_freq_activity_count": remain_freq_activity_count,
            # waveform features
            "waveform_case_count": waveform_case_count,
            "sine_like_count": sine_like_count,
            "clipping_count": clipping_count,
            "drift_count": drift_count,
            "glitch_count": glitch_count,
            "high_kurtosis_count": high_kurtosis_count,
            "moderate_kurtosis_count": moderate_kurtosis_count,
            "normal_kurtosis_count": normal_kurtosis_count,
            "sensor_kurtosis_count": sensor_kurtosis_count,
            "outlier_kurtosis_count": outlier_kurtosis_count,
            "sine_crest_count": sine_crest_count,
            "high_crest_count": high_crest_count,
            "sensor_crest_count": sensor_crest_count,
            "asymmetric_count": asymmetric_count,
            "symmetric_count": symmetric_count,
            "high_skewness_count": high_skewness_count,
            "high_repeatability_count": high_repeatability_count,
            "low_repeatability_count": low_repeatability_count,
            "high_glitch_ratio_count": high_glitch_ratio_count,
            "large_drift_count": large_drift_count,
            # frequency features
            "low_freq_count": low_freq_count,
            "strong_low_freq_count": strong_low_freq_count,
            "very_low_freq_count": very_low_freq_count,
            "strong_very_low_freq_count": strong_very_low_freq_count,
            "oil_whirl_count": oil_whirl_count,
            "strong_oil_whirl_count": strong_oil_whirl_count,
            "multiple_low_freq_count": multiple_low_freq_count,
            "significant_low_freq_case_count": significant_low_freq_case_count,
            "fractional_harmonic_count": fractional_harmonic_count,
            "sub_sync_peak_count": sub_sync_peak_count,
            "significant_sub_sync_case_count": significant_sub_sync_case_count,
            # orbit features
            "orbit_case_count": orbit_case_count,
            "ellipse_like_count": ellipse_like_count,
            "irregular_orbit_count": irregular_orbit_count,
            "elongated_orbit_count": elongated_orbit_count,
            "figure_eight_count": figure_eight_count,
            "crescent_count": crescent_count,
            "circle_like_count": circle_like_count,
            "shape_consistent_count": shape_consistent_count,
            "shape_inconsistent_count": shape_inconsistent_count,
            "high_ellipse_residual_count": high_ellipse_residual_count,
            "low_ellipse_residual_count": low_ellipse_residual_count,
            "high_cycle_size_similarity_count": high_cycle_size_similarity_count,
            "low_cycle_size_similarity_count": low_cycle_size_similarity_count,
            "high_cv_vib_count": high_cv_vib_count,
            "forward_precession_count": forward_precession_count,
            "reverse_precession_count": reverse_precession_count,
            # temperature / gap / displacement
            "high_temp_count": high_temp_count,
            "rising_temp_count": rising_temp_count,
            "support_temp_stable_high_count": support_temp_stable_high_count,
            "thrust_temp_stable_high_count": thrust_temp_stable_high_count,
            "temp_step_high_count": temp_step_high_count,
            "gap_change_count": gap_change_count,
            "gap_stable_count": gap_stable_count,
            "disp_change_count": disp_change_count,
            # bearing pair
            "bearing_pair_high": bearing_pair_high,
            "bearing_pair_medium": bearing_pair_medium,
            "bearing_pair_diff": bearing_pair_diff,
            "coupling_side_high": coupling_side_high,
            # process
            "process_anomaly_count": process_anomaly_count,
            "process_active_type_count": process_active_type_count,
            "surge_process_count": surge_process_count,
            "surge_active_type_count": surge_active_type_count,
            "gas_path_process_count": gas_path_process_count,
            "gas_path_active_type_count": gas_path_active_type_count,
            "load_process_count": load_process_count,
            "load_active_type_count": load_active_type_count,
            "fluid_process_support": round(fluid_process_support, 4),
            "process_sync_support": round(process_sync_support, 4),
        },
        "signature_flags": {
            "smooth_repeatable_waveform": _b(smooth_repeatable_waveform),
            "gradual_unbalance_bias": _b(gradual_unbalance_bias),
            "sustained_high_1x_signature": _b(sustained_high_1x_signature),
            "critical_fast_change_signature": _b(critical_fast_change_signature),
            "clean_gradual_rotor_signature": _b(clean_gradual_rotor_signature),
            "friction_impact_signature": _b(friction_impact_signature),
            "friction_nonlinear_signature": _b(friction_nonlinear_signature),
            "wear_smooth_support": _b(wear_smooth_support),
            "clearance_wear_signature": _b(clearance_wear_signature),
            "strong_low_freq_signature": _b(strong_low_freq_signature),
            "weak_fluid_without_process_signature": _b(weak_fluid_without_process_signature),
            "weak_fluid_no_specific_evidence": _b(weak_fluid_no_specific_evidence),
            "mechanical_1x_bias_signature": _b(mechanical_1x_bias_signature),
            "bearing_wear_multisource_signature": _b(bearing_wear_multisource_signature),
            "bearing_wear_strong": _b(bearing_wear_strong),
            "oil_whirl_hard_support": _b(oil_whirl_hard_support),
            "soft_rub_signature_missing": _b(soft_rub_signature_missing),
            "compressor_like": _b(compressor_like),
            "compressor_fouling_signature": _b(compressor_fouling_signature),
            "soft_rub_signature": _b(soft_rub_signature),
            "screw_like": _b(screw_like),
            "surge_hard_support": _b(surge_hard_support),
            "steam_fouling_like_signature": _b(steam_fouling_like_signature),
            "thrust_friction_conflict": _b(thrust_friction_conflict),
            "friction_evidence_strong": _b(friction_evidence_strong),
            "gap_stable_for_friction": _b(gap_stable_for_friction),
            "seal_fouling_signature": _b(seal_fouling_signature),
            "seal_coking_signature": _b(seal_coking_signature),
            "shaft_current_signature": _b(shaft_current_signature),
            "shaft_current_extreme_kurtosis": _b(shaft_current_extreme_kurtosis),
            "aero_excitation_signature": _b(aero_excitation_signature),
            "missing_strong_fluid_signature": _b(missing_strong_fluid_signature),
            "strong_process_sync_signature": _b(strong_process_sync_signature),
            "strong_fluid_signature": _b(strong_fluid_signature),
            "fouling_priority_signature": _b(fouling_priority_signature),
            "impeller_fouling_signature": _b(impeller_fouling_signature),
            "shaft_current_priority_signature": _b(shaft_current_priority_signature),
            "rotor_dominant_signature": _b(rotor_dominant_signature),
            "clean_rotor_nonfriction_signature": _b(clean_rotor_nonfriction_signature),
            "rotor_runout_signature": _b(rotor_runout_signature),
            "bearing_wear_priority_signature": _b(bearing_wear_priority_signature),
            "shaft_current_conflict_signature": _b(shaft_current_conflict_signature),
            "oil_whirl_conflict_signature": _b(oil_whirl_conflict_signature),
            "impact_sudden_rotor_signature": _b(impact_sudden_rotor_signature),
            "screw_ingestion_signature": _b(screw_ingestion_signature),
            "load_only_process_signature": _b(load_only_process_signature),
            "is_surge": _b(is_surge),
            "waveform_pattern_ready": _b(waveform_pattern_ready),
            "orbit_pattern_ready": _b(orbit_pattern_ready),
            "pattern_data_sparse": _b(pattern_data_sparse),
            "all_process_silent": _b(all_process_silent),
        },
        "candidate_score_breakdown": [
            {
                "rule_id": item.rule_id,
                "score": round(item.score, 4),
                "fault_type": item.fault_type,
                "fault_subtype": item.fault_subtype,
                "matched_count": len(item.matched_conditions),
                "missing_count": len(item.missing_evidence),
                "contradictions_count": len(item.contradictions),
                "capped": _candidate_has_score_cap(item),
            }
            for item in filtered
        ],
    }
    return filtered, debug_info


def _candidate_has_score_cap(candidate: CandidateFault) -> bool:
    return any("限制" in str(item) for item in candidate.contradictions)


def _confidence_from_score(
    score: float,
    config: dict[str, Any],
    matched_evidence_count: int = 0,
    contradictions_count: int = 0,
    score_gap: float | None = None,
    capped: bool = False,
) -> str:
    thresholds = config.get("thresholds") or {}
    high = _safe_float(thresholds.get("high_confidence_score")) or 0.75
    medium = _safe_float(thresholds.get("medium_confidence_score")) or 0.5
    # 证据充分度：至少 4 个独立证据才接近满配，避免仅凭高分直接给高置信。
    evidence_factor = min(1.0, matched_evidence_count / 4.0)
    adjusted_score = score * (0.58 + 0.42 * evidence_factor)
    adjusted_score -= min(0.18, contradictions_count * 0.04)
    if score_gap is not None:
        if score_gap < 0.06:
            adjusted_score -= 0.14
        elif score_gap < 0.10:
            adjusted_score -= 0.08
        elif score_gap < 0.16:
            adjusted_score -= 0.03
    if capped:
        adjusted_score -= 0.10
    adjusted_score = _clip_score(adjusted_score)
    if adjusted_score >= high:
        return "high"
    if adjusted_score >= medium:
        return "medium"
    return "low"


def _build_actions(fault_type: str, fault_subtype: str, config: dict[str, Any]) -> tuple[list[str], list[str]]:
    action_map = config.get("actions") or {}
    item = action_map.get(f"{fault_type}/{fault_subtype}") or {}
    running = item.get("running") if isinstance(item, dict) else None
    maintenance = item.get("maintenance") if isinstance(item, dict) else None
    return (
        [str(v) for v in running] if isinstance(running, list) else [],
        [str(v) for v in maintenance] if isinstance(maintenance, list) else [],
    )


def _build_evidence_summary(
    trends: list[TrendSnapshot],
    waveform_results: list[dict[str, Any]],
    orbit_results: list[dict[str, Any]],
    best_candidate: CandidateFault,
) -> list[str]:
    summaries: list[str] = []
    vib_items = _trend_filter(trends, point_type="轴振", feature="pp_value") or _trend_filter(trends, point_type="轴振")
    one_x_items = [item for item in trends if item.point_type == "轴振" and item.feature in {"one_freq_x", "one_freq_y"}]
    two_x_items = [item for item in trends if item.point_type == "轴振" and item.feature in {"two_freq_x", "two_freq_y"}]
    process_items_by_type = _group_process_items_by_type(trends)
    process_items = [
        item
        for point_type in PROCESS_PARAMETER_POINT_TYPES
        if point_type in GENERIC_PROCESS_SYNC_POINT_TYPES
        for item in process_items_by_type.get(point_type) or []
    ]

    rising_count = _count_rising(vib_items, 0.1)
    volatile_count = _count_volatile(vib_items, 1.0)
    high_alarm_count = _count_alarm(vib_items)
    post_step_count = _count_dominant_state(vib_items, {"post_step_high", "rapid_rising"}) + _count_step_change(vib_items, 0.10, {"level_shift", "slope_shift"})
    over_limit_count = _count_over_threshold_ratio(vib_items, 0.03)
    if rising_count or volatile_count or high_alarm_count or post_step_count or over_limit_count:
        summaries.append(
            f"振动趋势证据：上涨通道 {rising_count} 个，波动通道 {volatile_count} 个，报警通道 {high_alarm_count} 个，"
            f"台阶/快速上升 {post_step_count} 个，越限持续 {over_limit_count} 个。"
        )

    one_x_rise = _count_rising(one_x_items, 0.08)
    two_x_activity = _count_rising(two_x_items, 0.08) + _count_volatile(two_x_items, 0.8)
    if one_x_rise or two_x_activity:
        summaries.append(f"分频趋势证据：1X 上涨通道 {one_x_rise} 个，2X 活跃通道 {two_x_activity} 个。")

    amp_1x_values = _waveform_metric(waveform_results, "amp_1x_ratio")
    kurtosis_vals = _waveform_metric(waveform_results, "kurtosis_factor")
    asymmetry_vals = _waveform_metric(waveform_results, "peak_valley_asymmetry_ratio")
    repeat_vals = _waveform_metric(waveform_results, "cycle_repeatability_score")
    if amp_1x_values:
        parts = [f"1X 占比最高 {round(max(amp_1x_values), 3)}"]
        if kurtosis_vals:
            parts.append(f"峭度最高 {round(max(kurtosis_vals), 2)}")
        if asymmetry_vals:
            parts.append(f"不对称比最高 {round(max(asymmetry_vals), 2)}")
        if repeat_vals:
            parts.append(f"周期重复性最高 {round(max(repeat_vals), 2)}")
        summaries.append(f"波形频谱证据：{'，'.join(parts)}。")
    elif waveform_results is not None:
        summaries.append("波形数据获取失败，频谱证据缺失，诊断仅依赖趋势和轨迹。")

    repetition_values = _orbit_metric(orbit_results, "raw_repetition_score")
    axis_ratio_values = _orbit_metric(orbit_results, "first_cycle_axis_ratio")
    if repetition_values:
        orbit_parts = [f"重复性最高 {round(max(repetition_values), 3)}，长短轴比最高 {round(max(axis_ratio_values or [0.0]), 3)}"]
        precession_dirs = []
        for item in orbit_results:
            d = str((item.get("feature_details") or {}).get("one_x_precession_direction") or "")
            if d:
                precession_dirs.append(d)
        if precession_dirs:
            orbit_parts.append(f"进动方向 {'/'.join(set(precession_dirs))}")
        summaries.append(f"轴心轨迹证据：{'，'.join(orbit_parts)}。")

    if process_items:
        process_type_summary = _summarize_process_items_by_type(process_items_by_type, 0.1, 1.0)
        active_parts: list[str] = []
        for point_type in PROCESS_PARAMETER_POINT_TYPES:
            rise_count = process_type_summary[point_type]["rise_count"]
            volatility_count = process_type_summary[point_type]["volatility_count"]
            if rise_count == 0 and volatility_count == 0:
                continue
            active_parts.append(f"{point_type} 上涨 {rise_count} 个、波动 {volatility_count} 个")
        surge_sig = int(process_type_summary["防喘振阀开度"]["anomaly_count"]) + int(process_type_summary["入口流量"]["anomaly_count"])
        if active_parts:
            summaries.append(f"工艺量证据：{'；'.join(active_parts)}。")
        if surge_sig > 0:
            summaries.append(f"喘振联动证据：防喘振阀/入口流量异常通道 {surge_sig} 个，支持旋转失速/喘振判断。")

    if "传感器" not in best_candidate.fault_type:
        summaries.append("已排除优先判为纯传感器异常的主因：当前存在机械或流体侧的同步支撑证据。")
    else:
        summaries.append("机械侧同步支撑不足，异常更像单通道测量链路或探头问题。")

    return summaries[:6]


def _build_rule_optimization_conclusion(
    primary: CandidateFault,
    selected: list[CandidateFault],
    process_type_summary: dict[str, dict[str, Any]],
    process_profile: dict[str, Any],
) -> list[str]:
    conclusions: list[str] = []
    active_types = [
        point_type
        for point_type in PROCESS_PARAMETER_POINT_TYPES
        if int((process_type_summary.get(point_type) or {}).get("anomaly_count") or 0) > 0
    ]
    surge_active_type_count = int(process_profile.get("surge_active_type_count") or 0)
    gas_path_active_type_count = int(process_profile.get("gas_path_active_type_count") or 0)
    load_active_type_count = int(process_profile.get("load_active_type_count") or 0)

    if active_types:
        conclusions.append(f"细分工艺量活跃类型：{'、'.join(active_types)}。")
    else:
        conclusions.append("细分工艺量未提供有效支撑，本轮主结论主要依赖机械趋势和图谱证据。")

    if primary.rule_id in {"fluid_excitation", "fluid_disturbance"}:
        if load_active_type_count > 0 and surge_active_type_count == 0 and gas_path_active_type_count == 0:
            conclusions.append("当前流体扰动结论仍容易被泛化负荷/其他工艺参数抬高，下一轮应继续压低其直接加分。")
        if surge_active_type_count < 2:
            conclusions.append("喘振/失速类结论的关键工艺量还不够完整，建议要求防喘振阀开度与入口流量或进气参数形成联动后再优先上升为主结论。")

    if primary.rule_id == "process_sync":
        if load_active_type_count == 0:
            conclusions.append("当前 process_sync 缺少明确负荷类测点支撑，后续应避免仅凭泛化工艺量计数触发。")
        if surge_active_type_count > 0:
            conclusions.append("当前同时存在喘振相关工艺量，需继续区分负荷跟随与流体扰动。")

    if primary.rule_id == "friction":
        conclusions.append("摩擦规则后续应继续要求反进动、分数谐波、明显不对称或冲击特征中的至少一项强证据。")
        if load_active_type_count > 0 and surge_active_type_count == 0:
            conclusions.append("当前还存在负荷/蒸汽类工艺量影响，需继续区分结垢/结焦累积与直接摩擦。")

    if primary.rule_id == "thrust_wear":
        conclusions.append("推力轴承磨损后续应继续要求轴位移持续变化与推力温度同时满足，避免与汽封摩擦混淆。")

    if primary.rule_id == "bearing_wear" and surge_active_type_count > 0:
        conclusions.append("当前支撑轴承磨损与流体扰动易竞争，建议继续抬高温度/GAP/同轴承多通道证据的优先级。")

    secondary = selected[1] if len(selected) > 1 else None
    if secondary is not None and (primary.score - secondary.score) < 0.12:
        conclusions.append(
            f"主次规则分差仅 {round(primary.score - secondary.score, 3)}，建议继续优化 `{primary.rule_id}` 与 `{secondary.rule_id}` 的边界条件。"
        )

    if not primary.matched_conditions:
        conclusions.append("主规则显式匹配条件偏少，后续应补充更可解释的触发条件与反证。")

    return conclusions[:4]


async def run_diagnosis(device_id: str, sub_device_id: str, time: str) -> DiagnosisResult:
    config = load_config()
    time_ms = datetime_input_to_ms(str(time))
    context = await build_rule_device_context(device_id, sub_device_id=sub_device_id)
    diagnosis_target = _resolve_target(context, sub_device_id, device_id, config)
    target_info = diagnosis_target.target_info

    trend_collection = await _collect_trend_snapshots(context, target_info, time_ms, config, sub_device_id=sub_device_id)
    trends = trend_collection.snapshots
    trend_failures = trend_collection.failures
    raw_30d_data = trend_collection.raw_30d_data
    waveform_probe_ids = [str(item) for item in (target_info.get("waveform_probe_ids") or [])]

    # 从已有 30d 趋势数据中内存搜索峰值时间戳（零 API 调用）
    waveform_results: list[dict[str, Any]] = []
    all_waveform_times: list[str] = []
    waveform_failures: list[dict[str, str]] = []

    # 每个探头从趋势数据中解析波形时间戳（纯内存操作，零 API 调用）
    for probe_id in waveform_probe_ids:
        if raw_30d_data:
            times = _resolve_waveform_times_from_trend([probe_id], raw_30d_data, trends, time_ms)
        else:
            # Fallback: 如果 30d 数据不可用，使用原来的 API 调用方式
            times = await _resolve_waveform_times([probe_id], trends, time_ms, config)
        for t in times:
            if t not in all_waveform_times:
                all_waveform_times.append(t)

    # 第二步：并行提取所有 (probe_id, time) 组合的波形特征
    extraction_tasks = []
    for probe_id in waveform_probe_ids:
        for t in all_waveform_times:
            extraction_tasks.append((probe_id, t, _extract_spectral_waveform_features_impl(component_id=probe_id, time_ms=t)))

    all_waveform_times.sort(key=lambda t: int(t), reverse=True)

    # 第三步：波形提取 + 轴心轨迹提取 全部并行（单一 asyncio.gather）
    # 这消除了原来的串行依赖，将 2 个 API 轮次合并为 1 个
    orbit_tasks = []
    orbit_task_metadata = []
    bearing_ids = [str(item) for item in (target_info.get("bearing_ids") or [])]
    max_orbit_points = int(_safe_float(config.get("max_orbit_points")) or 2)
    for bearing_id in bearing_ids[:max_orbit_points]:
        probe_ids_for_orbit = _bearing_waveform_probe_ids(context, bearing_id)
        for t in all_waveform_times[:2]:
            orbit_tasks.append(
                cached_extract_orbit(
                    root_device_id=diagnosis_target.root_device_id,
                    bearing_id=bearing_id,
                    time_ms=t,
                    probe_ids=probe_ids_for_orbit,
                )
            )
            orbit_task_metadata.append((bearing_id, t, probe_ids_for_orbit))

    # 合并所有任务: 波形提取 + 轴心轨迹提取 → 一次 gather
    all_tasks = []
    task_type = []  # "waveform" or "orbit"
    for _, _, coro in extraction_tasks:
        all_tasks.append(coro)
        task_type.append("waveform")
    for orbit_coro in orbit_tasks:
        all_tasks.append(orbit_coro)
        task_type.append("orbit")

    orbit_results: list[dict[str, Any]] = []
    orbit_failures: list[dict[str, str]] = []

    if all_tasks:
        all_results = await asyncio.gather(*all_tasks, return_exceptions=True)
        for task_result, kind, idx in zip(all_results, task_type, range(len(all_results))):
            if kind == "waveform":
                probe_id, t, _ = extraction_tasks[idx]
                if isinstance(task_result, Exception):
                    waveform_failures.append({"component_id": probe_id, "time_ms": t, "error": str(task_result)})
                    print(f"[waveform.fail] component_id={probe_id} time_ms={t} error={task_result}")
                else:
                    waveform_results.append(task_result)
            else:  # orbit
                orbit_idx = idx - len(extraction_tasks)
                bearing_id, t, probe_ids = orbit_task_metadata[orbit_idx]
                if isinstance(task_result, Exception):
                    orbit_failures.append({
                        "bearing_id": bearing_id, "time_ms": t,
                        "probe_ids": ",".join(probe_ids), "error": str(task_result),
                    })
                    print(f"[orbit.fail] bearing_id={bearing_id} time_ms={t} error={task_result}")
                else:
                    orbit_results.append(task_result)
    candidates, score_debug_info = _score_candidates(diagnosis_target, trends, waveform_results, orbit_results, config)

    if not candidates:
        fallback = CandidateFault(
            rule_id="fallback",
            fault_type="传感器异常及测量因素类",
            fault_subtype="测温传感器自身因素",
            score=0.3,
            matched_conditions=["当前证据不足以稳定支持具体机械故障。"],
            missing_evidence=["缺少足够强的机械或流体故障特征。"],
            contradictions=[],
        )
        candidates = [fallback]
        score_debug_info = {
            "feature_counts": {},
            "signature_flags": {},
            "candidate_score_breakdown": [],
        }

    max_final_faults = int(_safe_float(config.get("max_final_faults")) or 2)
    selected = candidates[:max_final_faults]
    primary = selected[0]
    primary_score_gap = (selected[0].score - selected[1].score) if len(selected) >= 2 else None
    confidence = _confidence_from_score(
        primary.score,
        config,
        matched_evidence_count=len(primary.matched_conditions),
        contradictions_count=len(primary.contradictions),
        score_gap=primary_score_gap,
        capped=_candidate_has_score_cap(primary),
    )
    final_faults = [
        FinalFault(
            fault_type=item.fault_type,
            fault_subtype=item.fault_subtype,
            confidence=_confidence_from_score(
                item.score,
                config,
                matched_evidence_count=len(item.matched_conditions),
                contradictions_count=len(item.contradictions),
                score_gap=(item.score - selected[index + 1].score) if index + 1 < len(selected) else None,
                capped=_candidate_has_score_cap(item),
            ),
            score=round(item.score, 4),
        )
        for index, item in enumerate(selected)
    ]
    running_actions, maintenance_actions = _build_actions(primary.fault_type, primary.fault_subtype, config)
    evidence_summary = _build_evidence_summary(trends, waveform_results, orbit_results, primary)
    process_items_by_type = _group_process_items_by_type(trends)
    process_type_summary = _summarize_process_items_by_type(process_items_by_type, 0.1, 1.0)
    process_profile = _build_process_signal_profile(process_type_summary)
    active_process_types = [
        point_type
        for point_type in PROCESS_PARAMETER_POINT_TYPES
        if process_type_summary[point_type]["anomaly_count"] > 0
    ]
    rule_optimization_conclusion = _build_rule_optimization_conclusion(
        primary=primary,
        selected=selected,
        process_type_summary=process_type_summary,
        process_profile=process_profile,
    )

    return DiagnosisResult(
        device_id=device_id,
        sub_device_id=sub_device_id,
        time_ms=time_ms,
        stage="running",
        fault_type=primary.fault_type,
        fault_subtype=primary.fault_subtype,
        confidence=confidence,
        score=round(primary.score, 4),
        final_faults=final_faults,
        evidence_summary=evidence_summary,
        running_actions=running_actions,
        maintenance_actions=maintenance_actions,
        alternative_faults=selected[1:],
        primary_rule_detail=primary,
        process_signal_summary={
            "by_type": process_type_summary,
            "profile": process_profile,
            "active_types": active_process_types,
        },
        rule_optimization_conclusion=rule_optimization_conclusion,
        debug={
            "reasoning_summary": [
                f"device_type={context.device_type}",
                f"target_device_type={diagnosis_target.target_device_type}",
                f"target_kind={target_info.get('target_kind')}",
                f"trend_points=1d:{sum(1 for s in trends if s.window=='1d')} 3d:{sum(1 for s in trends if s.window=='3d')} 30d:{sum(1 for s in trends if s.window=='30d')}",
                f"trend_failures={len(trend_failures)}",
                f"waveform_cases={len(waveform_results)} orbit_cases={len(orbit_results)}",
                f"waveform_probes={len(waveform_probe_ids)} bearing_ids={len([str(item) for item in (target_info.get('bearing_ids') or [])])} waveform_times={all_waveform_times}",
                f"waveform_failures={len(waveform_failures)} orbit_failures={len(orbit_failures)}",
                f"active_process_types={active_process_types}",
                f"top_rules={[item.rule_id for item in selected]}",
            ],
            "target_info": target_info,
            "trend_failures": trend_failures,
            "waveform_failures": waveform_failures,
            "orbit_failures": orbit_failures,
            "process_type_summary": process_type_summary,
            "process_profile": process_profile,
            "feature_counts": score_debug_info.get("feature_counts", {}),
            "signature_flags": score_debug_info.get("signature_flags", {}),
            "candidate_score_breakdown": score_debug_info.get("candidate_score_breakdown", []),
        },
    )


async def close_all_clients() -> None:
    await close_shared_http_client()
