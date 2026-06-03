#!/usr/bin/env python
"""为 ai-report--daily agent 查询日报数据。

输出合约：写入 JSON 到 ``$DAILY_REPORT_OUTPUT_DIR/daily_data.json``
（默认 ``/mnt/user-data/outputs/daily_data.json``），结构为::

    {
      "report_date": "2026-05-13",
      "equipment_ids": ["E001"],
      "kpi_keys": ["runtime_rate", ...],
      "compare_type": "previous_day" | "previous_week" | "none",
      "compare_date": "2026-05-12" | null,
      "current": {
        "kpis": {<key>: <value>},
        "kpi_units": {<key>: <unit>},
        "hourly_runtime_rate": [24 个浮点数],
        "alarms": [{time, equipment, level, message}],
        "per_equipment": {<id>: {kpis, hourly_runtime_rate}} (仅 >20 台设备时)
      },
      "compare": <同 current 结构> | null,
      "data_source": "ins",
      "data_notes": [],
    }

数据通过注册的平台提供者获取。任何失败（HttpProviderError / KPI 映射缺失 /
空趋势 / 认证失败）以 ``{"error": ...}`` 格式输出到 stdout。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

_SCRIPT_DIR = str(Path(__file__).resolve().parent)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from _report_common import (
    KPI_UNITS,
    VALID_SCOPES,
    VALID_TYPES,
    _ARGPARSE_DEFAULT_KPIS,
    _EQUIPMENT_TYPE_DEFAULT_KPIS,
    dedupe_preserve_order,
    detect_equipment_type,
    error_output,
    load_sibling_module,
    parse_csv,
    resolve_equipment_by_scope,
    validate_equipment_ids,
    validate_kpi_keys,
)

DEFAULT_OUTPUT_DIR = "/mnt/user-data/outputs"
OUTPUT_FILENAME = "daily_data.json"


def _output_dir() -> Path:
    """获取日报输出目录路径。"""
    return Path(os.environ.get("DAILY_REPORT_OUTPUT_DIR", DEFAULT_OUTPUT_DIR))


def _runtime_data_dir(output_dir: str | None) -> Path | None:
    """将运行时 ``--output-dir`` 根路径映射到平台的 ``data/`` 子目录。"""
    if not output_dir:
        return None
    return Path(output_dir) / "data"


def fetch_day(
    date_str: str,
    equipment_ids: list[str],
    kpi_keys: list[str],
    eq_type: str = "all",
    include_per_equipment: bool = False,
    equipment_meta: dict[str, dict] | None = None,
) -> dict:
    """通过注册的平台提供者获取单日数据。

    如需同时获取数据来源和备注，请使用 ``fetch_day_with_provenance``。
    """
    data, _, _ = fetch_day_with_provenance(
        date_str, equipment_ids, kpi_keys, eq_type, include_per_equipment, equipment_meta
    )
    return data


def fetch_day_with_provenance(
    date_str: str,
    equipment_ids: list[str],
    kpi_keys: list[str],
    eq_type: str = "all",
    include_per_equipment: bool = False,
    equipment_meta: dict[str, dict] | None = None,
) -> tuple[dict, str, list[str]]:
    """带数据来源追踪的单日数据获取。

    直接调用已注册的 ``daily`` 提供者（``PlatformDailyProvider``）。
    ``HttpProviderError`` 向上传播，CLI 层将其转为
    ``{"error": "HttpProviderError: ..."}``，而非静默回退到 demo 数据。

    Returns:
        (数据字典, 数据来源标签, 备注列表)
    """
    dp = load_sibling_module("_data_providers")

    provider = dp.get_provider("daily")
    result = provider.fetch(
        date_str=date_str,
        equipment_ids=equipment_ids,
        kpi_keys=kpi_keys,
        eq_type=eq_type,
        include_per_equipment=include_per_equipment,
        equipment_meta=equipment_meta,
    )
    if not isinstance(result, dp.ProviderResult):
        raise TypeError(f"daily provider returned non-ProviderResult: {type(result)}")
    return result.data, result.data_source, list(result.notes)


def _compare_date(date_str: str, compare: str) -> str | None:
    """根据对比模式计算对比日期。"""
    if compare == "previous_day":
        return (datetime.strptime(date_str, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    if compare == "previous_week":
        return (datetime.strptime(date_str, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")
    return None


def build_result(
    date_str: str,
    equipment_ids: list[str],
    kpi_keys: list[str],
    compare: str,
    eq_type: str = "all",
    include_per_equipment: bool = False,
    is_scope_mode: bool = False,
    equipment_meta: dict[str, dict] | None = None,
) -> dict:
    """构建完整的日报数据字典（current + compare 双块结构）。"""
    compare = compare or "none"
    current, current_src, current_notes = fetch_day_with_provenance(
        date_str, equipment_ids, kpi_keys, eq_type, include_per_equipment, equipment_meta
    )
    compare_date_str = _compare_date(date_str, compare)
    if compare_date_str:
        compare_block, compare_src, compare_notes = fetch_day_with_provenance(
            compare_date_str, equipment_ids, kpi_keys, eq_type, include_per_equipment, equipment_meta
        )
    else:
        compare_block, compare_src, compare_notes = None, None, []

    notes: list[str] = list(current_notes)
    if compare_src is not None:
        notes.extend(compare_notes)
    data_source = current_src

    equipment_names: dict[str, str] = {}
    if equipment_meta:
        equipment_names = {eid: meta.get("name", eid) for eid, meta in equipment_meta.items() if meta}
    result: dict = {
        "report_date": date_str,
        "equipment_ids": equipment_ids,
        "equipment_names": equipment_names,
        "kpi_keys": kpi_keys,
        "compare_type": compare,
        "compare_date": compare_date_str,
        "current": current,
        "compare": compare_block,
        "data_source": data_source,
        "data_notes": notes,
    }
    if is_scope_mode:
        result["equipment_type"] = eq_type
        result["equipment_count"] = len(equipment_ids)
    return result


def write_payload(result: dict, output_dir: Path | None = None) -> Path:
    """将日报数据写入 JSON 文件，返回输出路径。"""
    out_dir = output_dir or _output_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / OUTPUT_FILENAME
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def main() -> int:
    """CLI 入口：解析参数、获取数据、写入 daily_data.json。"""
    parser = argparse.ArgumentParser(description="Query daily report data")
    parser.add_argument("--date", required=True, help="Report date YYYY-MM-DD")
    parser.add_argument("--equipment", default="", help="Comma-separated equipment ids")
    parser.add_argument(
        "--equipment-names",
        dest="equipment_names",
        default="",
        help="Comma-separated equipment names aligned with --equipment (optional)",
    )
    parser.add_argument(
        "--kpis",
        default="runtime_rate,downtime_count,alarm_count",
        help="Comma-separated KPI keys",
    )
    parser.add_argument(
        "--compare",
        default="previous_day",
        choices=["previous_day", "previous_week", "none"],
    )
    parser.add_argument("--type", default="all", help="Equipment type filter")
    parser.add_argument("--scope", default=None, help="Scope: all/area/specific")
    parser.add_argument("--scope-filter", default="", help="Area names or equipment IDs for scope")
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Optional runtime output root; payload is written under <output-dir>/data/",
    )
    args = parser.parse_args()

    try:
        try:
            datetime.strptime(args.date, "%Y-%m-%d")
        except ValueError as exc:
            return error_output(f"invalid --date: {exc}")

        eq_type = getattr(args, "type")
        if eq_type not in VALID_TYPES:
            return error_output(f"--type must be one of {sorted(VALID_TYPES)}, got: {eq_type}")

        scope = args.scope

        if scope is not None:
            if scope not in VALID_SCOPES:
                return error_output(f"--scope must be one of {sorted(VALID_SCOPES)}, got: {scope}")
            equipment_records = resolve_equipment_by_scope(eq_type, scope, getattr(args, "scope_filter", ""))
            if not equipment_records:
                return error_output("no equipment matched for the given --type/--scope/--scope-filter")
            equipment_ids = [e["id"] for e in equipment_records]
            equipment_meta = {e["id"]: e for e in equipment_records}
            include_per_equipment = len(equipment_ids) > 20
            is_scope_mode = True
            # 当 --type=all 时，从实际设备中推导统一类型，确保逐类型 KPI 映射生效
            if eq_type == "all" and equipment_records:
                org_types = {e.get("org_type") for e in equipment_records if e.get("org_type")}
                if len(org_types) == 1:
                    eq_type = org_types.pop()
        else:
            equipment_ids = dedupe_preserve_order(parse_csv(args.equipment))
            equipment_error = validate_equipment_ids(equipment_ids)
            if equipment_error:
                return error_output(equipment_error)
            equipment_names = parse_csv(args.equipment_names)
            equipment_meta = None
            if equipment_names:
                equipment_meta = {
                    eid: {"id": eid, "name": (equipment_names[i] if i < len(equipment_names) else eid)}
                    for i, eid in enumerate(equipment_ids)
                }
            include_per_equipment = False
            is_scope_mode = False
            # 当 --type 未显式覆盖时，从 Organize Tree 推导设备类型
            if getattr(args, "type") == "all":
                detected = _detect_equipment_type(equipment_ids)
                if detected != "all":
                    eq_type = detected

        kpi_keys = dedupe_preserve_order(parse_csv(args.kpis) or ["runtime_rate", "downtime_count", "alarm_count"])
        # 当 --kpis 保持默认值且 eq_type 为具体类型时，替换为类型对应的默认 KPI。
        # 这对泵类型至关重要：默认 KPI（runtime_rate/downtime_count/alarm_count）
        # 只匹配 8K/9K 测点类型，2K 泵数据若无此替换将返回空。
        if kpi_keys == _ARGPARSE_DEFAULT_KPIS and eq_type != "all" and eq_type in _EQUIPMENT_TYPE_DEFAULT_KPIS:
            kpi_keys = list(_EQUIPMENT_TYPE_DEFAULT_KPIS[eq_type])
        kpi_error = validate_kpi_keys(kpi_keys, KPI_UNITS)
        if kpi_error:
            return error_output(kpi_error)

        result = build_result(args.date, equipment_ids, kpi_keys, args.compare, eq_type, include_per_equipment, is_scope_mode, equipment_meta)
        out_path = write_payload(result, _runtime_data_dir(args.output_dir))
        print(json.dumps({"output": str(out_path), "report_date": result["report_date"]}, ensure_ascii=False))
        return 0
    except Exception as exc:  # noqa: BLE001 - 按 Skill 约定输出到 stdout
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 0


# 旧测试 monkeypatch 兼容别名
_detect_equipment_type = detect_equipment_type


if __name__ == "__main__":
    sys.exit(main())
