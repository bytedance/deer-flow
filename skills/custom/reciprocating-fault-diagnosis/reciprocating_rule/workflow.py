"""Reciprocating machine diagnosis workflow orchestrator.

Three-layer pipeline:
  ① Channel rules (per measurement point)
  ② Cylinder rules (per keyphasor)
  ③ Machine rules (cross-cylinder)
"""

from __future__ import annotations

import json
import os
import platform
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .assembler import assemble
from .config import HL_A, HL_NAMES, SS_NAMES
from .models import ChannelResult, DiagnosisResult
from .provider import (
    InsReciprocatingDataProvider,
    JsonFixtureReciprocatingDataProvider,
    ReciprocatingDataProvider,
)
from .rules import run_ch_rules, run_cylinder_rules, run_machine_rules


_PROVIDERS: list[ReciprocatingDataProvider] = []


def _artifact_root() -> Path:
    root = Path(os.environ.get("DIAGNOSIS_OUTPUT_DIR", "/mnt/user-data/outputs"))
    path = root / "reciprocating_rule_cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_cache(prefix: str, name: str, payload: Any) -> str:
    safe_name = "".join(ch if ch.isalnum() or ch in {"_", "-", "."} else "_" for ch in name)
    path = _artifact_root() / f"{prefix}_{safe_name}.json"
    if isinstance(payload, (dict, list)):
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        path.write_text(str(payload), encoding="utf-8")
    return str(path)


def _provider_from_env() -> ReciprocatingDataProvider:
    fixture = os.environ.get("RECIPROCATING_RULE_FIXTURE")
    if fixture:
        provider = JsonFixtureReciprocatingDataProvider(fixture)
    else:
        provider = InsReciprocatingDataProvider()
    _PROVIDERS.append(provider)
    return provider


def self_check() -> dict[str, Any]:
    return {
        "python_version": platform.python_version(),
        "ins_access_token": bool(os.environ.get("INS_ACCESS_TOKEN")),
        "ins_base_url": os.environ.get("INS_BASE_URL"),
    }


async def close_all_clients() -> None:
    providers = list(_PROVIDERS)
    _PROVIDERS.clear()
    for provider in providers:
        await provider.close()


def _collect_gpids(config: dict[str, Any]) -> list[str]:
    """Extract all measurement point IDs from config."""
    gpids: list[str] = []
    device_points = config.get("devicePoints") or []
    for dp in device_points:
        gpid = str(dp.get("id") or dp.get("gpid") or "")
        if gpid:
            gpids.append(gpid)
    return gpids


def _collect_channel_results(machine: Any) -> list[ChannelResult]:
    """Flatten all channels from all keys + JSZD into ChannelResult list."""
    results: list[ChannelResult] = []
    for key in machine.keys:
        for ch in key.channels:
            seg_health_str: dict[str, str] = {}
            for seg_name, seg_hl in ch.health_segs.items():
                if seg_hl > HL_A:
                    seg_health_str[seg_name] = HL_NAMES.get(seg_hl, "?")
            results.append(ChannelResult(
                name=ch.name,
                position_type=ch.position_type,
                health=HL_NAMES.get(ch.health_all, "?"),
                health_value=ch.health_all,
                main_feature=ch.main_feature,
                main_value=ch.main_value,
                seg_health=seg_health_str,
                thresholds=ch.thresholds,
                seg_thresholds=ch.seg_thresholds,
            ))
    # JSZD channels (machine-level)
    for ch in machine.jszd_channels:
        seg_health_str: dict[str, str] = {}
        for seg_name, seg_hl in ch.health_segs.items():
            if seg_hl > HL_A:
                seg_health_str[seg_name] = HL_NAMES.get(seg_hl, "?")
        results.append(ChannelResult(
            name=ch.name,
            position_type=ch.position_type,
            health=HL_NAMES.get(ch.health_all, "?"),
            health_value=ch.health_all,
            main_feature=ch.main_feature,
            main_value=ch.main_value,
            seg_health=seg_health_str,
            thresholds=ch.thresholds,
            seg_thresholds=ch.seg_thresholds,
        ))
    return results


async def run_diagnosis(
    machine_id: str,
    timestamp_ms: int,
    *,
    component_id: str | None = None,
    provider: ReciprocatingDataProvider | None = None,
) -> DiagnosisResult:
    """Execute the full 3-layer diagnosis pipeline.

    Parameters
    ----------
    machine_id : str
        Machine / equipment ID.
    timestamp_ms : int
        Diagnosis time (milliseconds epoch).
    component_id : str, optional
        Restrict to a specific component / sub-device.
    provider : ReciprocatingDataProvider, optional
        Data source. Defaults to InS API or fixture (from env).

    Returns
    -------
    DiagnosisResult
    """
    provider = provider or _provider_from_env()
    warnings: list[str] = []

    # ① Fetch samplerId first, then config
    device_id = ""
    try:
        device_id = await provider.fetch_sampler_id(machine_id)
        if not device_id:
            warnings.append("未获取到 samplerId，D901 配置可能不完整")
    except Exception as exc:
        warnings.append(f"samplerId 获取失败: {exc}")

    try:
        config = await provider.fetch_config(machine_id, device_id=device_id)
    except Exception as exc:
        warnings.append(f"配置获取失败: {exc}")
        config = {}
    _write_cache("config", machine_id, config)

    if not config:
        return DiagnosisResult(
            timestamp=timestamp_ms,
            machine_id=machine_id,
            machine_name=machine_id,
            speed=0.0,
            ss_state="UNKNOWN",
            warnings=warnings + ["未获取到设备配置，无法执行诊断"],
        )

    # ② Collect measurement point IDs and fetch data
    gpids = _collect_gpids(config)
    _write_cache("gpids", machine_id, gpids)

    try:
        data = await provider.fetch_trend_data(gpids, timestamp_ms)
    except Exception as exc:
        warnings.append(f"趋势数据获取失败: {exc}")
        data = []
    _write_cache("trend_data", f"{machine_id}_{timestamp_ms}", data)

    if not data:
        warnings.append("未获取到趋势数据，诊断结果可能不完整")

    # ③ Assemble model
    machine = assemble(config, data, timestamp_ms, component_id)

    # ④ Channel rules (layer 1)
    # Determine global machine state for JSZD gate
    any_key_running = any(k.ss_state == 1 for k in machine.keys)  # SS_NORMAL = 1

    for key in machine.keys:
        for ch in key.channels:
            if key.ss_state not in (1,):
                ch.health_all = HL_A
                continue
            run_ch_rules(ch)

    # JSZD channels (machine-level): gate by global machine state
    for ch in machine.jszd_channels:
        if not any_key_running:
            ch.health_all = HL_A
            continue
        run_ch_rules(ch)

    # ⑤ Cylinder rules (layer 2)
    for key in machine.keys:
        run_cylinder_rules(key, machine)

    # ⑥ Machine rules (layer 3)
    run_machine_rules(machine)

    # ⑦ Collect results
    channel_results = _collect_channel_results(machine)

    from .models import DiagnosisItem

    cyl_items: list[DiagnosisItem] = []
    for key in machine.keys:
        for detail in key.diag_details:
            if isinstance(detail, dict):
                cyl_items.append(DiagnosisItem(**detail))

    mac_items: list[DiagnosisItem] = []
    for detail in machine.diag_details:
        if isinstance(detail, dict):
            mac_items.append(DiagnosisItem(**detail))

    # Determine overall speed and state
    speed = 0.0
    ss_state = "UNKNOWN"
    for key in machine.keys:
        speed = max(speed, key.speed)
        ss_state = SS_NAMES.get(key.ss_state, "UNKNOWN")

    return DiagnosisResult(
        timestamp=timestamp_ms,
        machine_id=machine_id,
        machine_name=machine.name,
        speed=speed,
        ss_state=ss_state,
        channels=channel_results,
        cylinder_diagnosis=cyl_items,
        machine_diagnosis=mac_items,
        warnings=warnings,
    )
