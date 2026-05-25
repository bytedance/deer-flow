"""Assemble raw API responses into Channel / Key / Machine model objects.

Equivalent to the Java ``DataAssembler`` — merges config API (queryD901Config)
and data API (getTrendDataHis) results into the domain model tree.
"""

from __future__ import annotations

import math
from typing import Any

from .config import (
    HL_A,
    POSITION_SEG_NUM,
    SS_NORMAL,
    SS_STOP,
    SS_UNKNOWN,
)
from .models import Channel, Key, Machine


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value is None or isinstance(value, bool):
        return default
    try:
        numeric = float(value)
        return numeric if math.isfinite(numeric) else default
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    if value is None or isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return int(value) == 1
    if isinstance(value, str):
        return value.strip() in {"1", "true", "True", "yes"}
    return False


def _pick_nearest_data(
    data_arr: list[dict[str, Any]],
    timestamp: int,
) -> dict[str, Any] | None:
    """Find the data record whose ``datatime`` is closest to *timestamp*."""
    if not data_arr:
        return None
    return min(data_arr, key=lambda rec: abs(_safe_int(rec.get("datatime")) - timestamp))


def _inject_features(channel: Channel, record: dict[str, Any]) -> None:
    """Inject main_value and seg_values from a data record into a Channel."""
    # Main feature value
    mf = channel.main_feature
    if mf in ("rms", "pp", "pp_value", "avg"):
        key = "pp_value" if mf == "pp" else mf
        channel.main_value = _safe_float(record.get(key))

    # Segment feature values
    sf = channel.seg_feature
    channel.seg_values = []
    for i in range(channel.seg_num):
        seg_key = f"seg_{i}_{sf}"
        channel.seg_values.append(_safe_float(record.get(seg_key)))


def _build_channel(
    device_point: dict[str, Any],
    config: dict[str, Any],
    data_map: dict[str, list[dict[str, Any]]],
    timestamp: int,
) -> Channel | None:
    """Build a single Channel from a devicePoint + config maps + data."""
    gpid = str(device_point.get("id") or device_point.get("gpid") or "")
    if not gpid:
        return None

    point_config = device_point.get("configInfo") or device_point

    # Analyse config
    analyse_id = str(point_config.get("analyseId") or "")
    analyse_cfg = (config.get("analyseConfig") or {}).get(analyse_id) or {}

    position_type = str(analyse_cfg.get("position_type") or "")
    if not position_type:
        return None

    seg_num = _safe_int(analyse_cfg.get("seg_num"), POSITION_SEG_NUM.get(position_type, 1))
    seg_feature = str(analyse_cfg.get("seg_feature") or "max")
    main_feature = str(analyse_cfg.get("main_feature") or "rms")
    alarm_model = str(analyse_cfg.get("alarm_model") or "")
    is_seg = _safe_bool(analyse_cfg.get("is_seg"))

    # Channel config (thresholds)
    is_alarm = _safe_bool(point_config.get("isAlarm") or point_config.get("is_alarm"))
    is_def_alarm = _safe_bool(point_config.get("isDefAlarm") or point_config.get("is_def_alarm"))

    thresholds = {
        "hh": _safe_float(point_config.get("alarmHH") or point_config.get("hh")),
        "h": _safe_float(point_config.get("alarmH") or point_config.get("h")),
        "ll": _safe_float(point_config.get("alarmLL") or point_config.get("ll")),
        "l": _safe_float(point_config.get("alarmL") or point_config.get("l")),
    }

    # Channel-level config (hysteresis)
    key_channel_num = str(point_config.get("keyChannelNum") or "")
    ch_cfg = (config.get("channelConfig") or {}).get(key_channel_num) or {}
    hysteresis = _safe_float(ch_cfg.get("hysteresis"))

    # Fallback thresholds from channelConfig if not in devicePoint
    if not thresholds["hh"]:
        thresholds["hh"] = _safe_float(ch_cfg.get("hh"))
    if not thresholds["h"]:
        thresholds["h"] = _safe_float(ch_cfg.get("h"))
    if not thresholds["ll"]:
        thresholds["ll"] = _safe_float(ch_cfg.get("ll"))
    if not thresholds["l"]:
        thresholds["l"] = _safe_float(ch_cfg.get("l"))

    # Segment thresholds (from segConfig, keyed by keyChannelNum — same key as channelConfig)
    seg_cfg = (config.get("segConfig") or {}).get(key_channel_num) or {}
    seg_thresholds: dict[str, list[float]] = {}
    if is_seg and seg_cfg:
        for level in ("hh", "h", "ll", "l"):
            raw_arr = seg_cfg.get(level)
            if isinstance(raw_arr, list):
                seg_thresholds[level] = [_safe_float(v) for v in raw_arr]

    # Inject data
    data_arr = data_map.get(gpid) or []
    record = _pick_nearest_data(data_arr, timestamp)

    # Store keyId for JSZD per-key lookup in cylinder_rules
    key_id = str(point_config.get("keyId") or "")

    channel = Channel(
        name=str(point_config.get("name") or device_point.get("name") or gpid),
        gpid=gpid,
        position_type=position_type,
        seg_num=seg_num if is_seg else 0,
        seg_feature=seg_feature,
        main_feature=main_feature,
        alarm_model=alarm_model,
        is_alarm=is_alarm,
        is_def_alarm=is_def_alarm,
        thresholds=thresholds,
        seg_thresholds=seg_thresholds,
        hysteresis=hysteresis,
        key_id=key_id,
    )

    if record is not None:
        _inject_features(channel, record)

    return channel


def _build_key(
    key_id: str,
    key_cfg: dict[str, Any],
    channels: list[Channel],
    data_map: dict[str, list[dict[str, Any]]],
    timestamp: int,
    mac_cfg: dict[str, Any],
) -> Key:
    """Build a Key (keyphasor / cylinder) from keyConfig + its channels."""
    low_run_speed = _safe_float(mac_cfg.get("low_run_speed"), 100.0)

    # Determine speed: prefer KEY-type channel, fallback to any channel's data
    speed = 0.0
    ss_state = SS_UNKNOWN

    # Try KEY-type channels first
    for ch in channels:
        if ch.position_type == "KEY":
            key_data = data_map.get(ch.gpid) or []
            record = _pick_nearest_data(key_data, timestamp)
            if record is not None:
                speed = _safe_float(record.get("speed"))
            break

    # Fallback: extract speed from any channel's trend data
    if speed == 0.0:
        for ch in channels:
            ch_data = data_map.get(ch.gpid) or []
            record = _pick_nearest_data(ch_data, timestamp)
            if record is not None:
                s = _safe_float(record.get("speed"))
                if s > 0:
                    speed = s
                    break

    # Simplified start/stop judgment
    if speed >= low_run_speed:
        ss_state = SS_NORMAL
    elif speed > 0:
        ss_state = SS_STOP  # below running speed
    else:
        ss_state = SS_STOP

    # Filter non-KEY channels (those belong to this keyphasor)
    key_channels = [ch for ch in channels if ch.position_type != "KEY"]

    return Key(
        id=_safe_int(key_id),
        name=str(key_cfg.get("name") or f"键相{key_id}"),
        start_phase=_safe_int(key_cfg.get("start_phase")),
        real_rev=_safe_float(key_cfg.get("real_rev"), 1.0),
        component_id=str(key_cfg.get("parentId") or ""),
        speed=speed,
        ss_state=ss_state,
        channels=key_channels,
    )


def assemble(
    config: dict[str, Any],
    data: list[dict[str, Any]],
    timestamp: int,
    component_id: str | None = None,
) -> Machine:
    """Main assembly function.

    Parameters
    ----------
    config : dict
        Raw response from ``queryD901Config`` (the ``data`` object).
    data : list[dict]
        Raw response from ``getTrendDataHis`` (the ``data`` array).
    timestamp : int
        Target diagnosis time (milliseconds).
    component_id : str, optional
        If set, only assemble this specific component.

    Returns
    -------
    Machine
        Fully populated domain model tree.
    """
    # Extract config sections
    device_info = config.get("deviceInfo") or {}
    raw_config = device_info.get("configInfo") or config

    mac_configs = raw_config.get("macConfig") or {}
    key_configs = raw_config.get("keyConfig") or {}
    analyse_configs = raw_config.get("analyseConfig") or {}
    channel_configs = raw_config.get("channelConfig") or {}
    seg_configs = raw_config.get("segConfig") or {}

    # Machine config (should be exactly one)
    mac_id = ""
    mac_cfg: dict[str, Any] = {}
    for mid, mcfg in mac_configs.items():
        mac_id = mid
        mac_cfg = mcfg
        break

    # Build data lookup: gpid → dataArr
    data_map: dict[str, list[dict[str, Any]]] = {}
    for item in data:
        gpid = str(item.get("gpid") or "")
        if gpid:
            data_map[gpid] = item.get("dataArr") or []

    # Collect device points
    device_points = config.get("devicePoints") or []

    # Group device points by keyId
    # JSZD goes to jszd_points (machine-level), others to points_by_key
    points_by_key: dict[str, list[dict[str, Any]]] = {}
    jszd_points: list[dict[str, Any]] = []

    for dp in device_points:
        dp_config = dp.get("configInfo") or dp
        key_id = str(dp_config.get("keyId") or "")
        if not key_id:
            continue

        analyse_id = str(dp_config.get("analyseId") or "")
        analyse_cfg = analyse_configs.get(analyse_id) or {}
        pos_type = str(analyse_cfg.get("position_type") or "")

        if pos_type == "JSZD":
            # JSZD: machine-level channels (used by machine_rules + cylinder_rules per-key)
            jszd_points.append(dp)
        elif pos_type == "KEY":
            # KEY points stored separately for speed extraction
            points_by_key.setdefault(f"_key_{key_id}", []).append(dp)
        else:
            # SZT, GTZD, PBY, PBX grouped by keyId
            points_by_key.setdefault(key_id, []).append(dp)

    # Build config bundle for channel construction
    config_bundle = {
        "analyseConfig": analyse_configs,
        "channelConfig": channel_configs,
        "segConfig": seg_configs,
    }

    # Build keys
    keys: list[Key] = []
    for key_id, key_cfg in key_configs.items():
        if _safe_bool(key_cfg.get("disable")):
            continue

        # Gather channels for this key (excludes JSZD — those are machine-level)
        key_dp_list = points_by_key.get(key_id) or []

        channels: list[Channel] = []
        for dp in key_dp_list:
            ch = _build_channel(dp, config_bundle, data_map, timestamp)
            if ch is not None:
                channels.append(ch)

        # Also add KEY-type data points (for speed extraction)
        for dp in points_by_key.get(f"_key_{key_id}") or []:
            ch = _build_channel(dp, config_bundle, data_map, timestamp)
            if ch is not None:
                channels.append(ch)

        key = _build_key(key_id, key_cfg, channels, data_map, timestamp, mac_cfg)

        # Filter by component_id if specified
        if component_id and key.component_id and key.component_id != component_id:
            continue

        keys.append(key)

    # Build JSZD channels (machine-level, per design doc §4.4)
    # Filter by component_id: only include JSZD whose keyId maps to an accepted key
    accepted_key_ids = {str(k.id) for k in keys}
    jszd_channels: list[Channel] = []
    for dp in jszd_points:
        dp_config = dp.get("configInfo") or dp
        key_id = str(dp_config.get("keyId") or "")
        # If component_id is set, only include JSZD belonging to accepted keys
        if component_id and key_id not in accepted_key_ids:
            continue
        ch = _build_channel(dp, config_bundle, data_map, timestamp)
        if ch is not None:
            jszd_channels.append(ch)

    # If no keys found from keyConfig, try to build from device points directly
    if not keys and device_points:
        all_channels: list[Channel] = []
        for dp in device_points:
            ch = _build_channel(dp, config_bundle, data_map, timestamp)
            if ch is not None:
                all_channels.append(ch)
        if all_channels:
            key = Key(
                id=0,
                name="默认",
                speed=0.0,
                ss_state=SS_UNKNOWN,
                channels=[ch for ch in all_channels if ch.position_type != "KEY"],
            )
            # Try to get speed from any channel's data
            for ch in all_channels:
                record = _pick_nearest_data(data_map.get(ch.gpid) or [], timestamp)
                if record is not None:
                    speed = _safe_float(record.get("speed"))
                    if speed > 0:
                        key.speed = speed
                        break
            if key.speed >= _safe_float(mac_cfg.get("low_run_speed"), 100.0):
                key.ss_state = SS_NORMAL
            else:
                key.ss_state = SS_STOP
            keys.append(key)

    return Machine(
        id=mac_id,
        name=str(mac_cfg.get("name") or mac_id),
        low_run_speed=_safe_float(mac_cfg.get("low_run_speed"), 100.0),
        hysteresis_speed=_safe_float(mac_cfg.get("hysteresis_speed"), 10.0),
        jitter=_safe_float(mac_cfg.get("jitter"), 10.0),
        keys=keys,
        jszd_channels=jszd_channels,
    )
