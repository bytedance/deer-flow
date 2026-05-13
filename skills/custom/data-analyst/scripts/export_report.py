#!/usr/bin/env python
"""Export daily KPI payload to a downloadable Markdown file.

Reads ``$DAILY_REPORT_OUTPUT_DIR/daily_kpi.json`` (or ``--input``) and
writes ``$DAILY_REPORT_OUTPUT_DIR/daily_report.md``.

Supports two modes:
- **detail**: per-device listing (original behavior)
- **grouped**: aggregated display with device count and top_anomalies table

PDF support is intentionally deferred (see Sprint plan Story 6) and
raises ``ValueError`` when requested.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

DEFAULT_OUTPUT_DIR = "/mnt/user-data/outputs"
INPUT_FILENAME = "daily_kpi.json"
SUPPORTED_FORMATS = {"md"}

TYPE_DISPLAY = {
    "static_equipment": "静设备",
    "rotating_machinery": "旋转机组",
    "pump": "机泵",
    "reciprocating_machinery": "往复机组",
    "all": "设备",
}


def _output_dir() -> Path:
    return Path(os.environ.get("DAILY_REPORT_OUTPUT_DIR", DEFAULT_OUTPUT_DIR))


def _format_number(value) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def _format_delta(item: dict) -> str:
    delta = item.get("delta")
    if delta is None:
        return "—"
    arrow = "↑" if delta > 0 else ("↓" if delta < 0 else "→")
    return f"{arrow} {_format_number(abs(delta) if isinstance(delta, (int, float)) else delta)}"


def _table_cell(value) -> str:
    return _format_number(value).replace("|", "\\|").replace("\n", " ")


def render_markdown(payload: dict) -> str:
    aggregation_mode = payload.get("aggregation_mode", "detail")
    equipment_type = payload.get("equipment_type", "all")
    equipment_count = payload.get("equipment_count")
    type_label = TYPE_DISPLAY.get(equipment_type, "设备")

    lines: list[str] = []

    if aggregation_mode == "grouped" and equipment_type != "all":
        lines.append(f"# {type_label}运行日报")
    else:
        lines.append("# 设备运行日报")
    lines.append("")
    lines.append(f"- 日期：{payload.get('report_date', '')}")

    if aggregation_mode == "grouped" and equipment_count:
        lines.append(f"- 设备：共 {equipment_count} 台")
    else:
        equipment = payload.get("equipment_ids") or []
        if equipment:
            lines.append(f"- 设备：{', '.join(equipment)}")

    compare_type = payload.get("compare_type", "none")
    compare_label = {
        "previous_day": "对比前一日",
        "previous_week": "对比上周同日",
        "none": "无对比",
    }.get(compare_type, compare_type)
    lines.append(f"- 对比基准：{compare_label}")
    lines.append("")

    overall = payload.get("overall_status") or {}
    lines.append("## 概览")
    lines.append("")
    lines.append(f"- 状态：{overall.get('level', 'ok')}")
    lines.append(f"- 总结：{overall.get('summary', '')}")
    lines.append("")

    lines.append("## KPI 指标")
    lines.append("")
    if aggregation_mode == "grouped":
        lines.append("| 指标 | 当前（均值） | 最小 | 最大 | 上一周期 | 变化 | 单位 |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- |")
        for item in payload.get("kpi_summary") or []:
            lines.append(
                "| {name} | {current} | {min_val} | {max_val} | {previous} | {delta} | {unit} |".format(
                    name=_table_cell(item.get("name", item.get("key", ""))),
                    current=_table_cell(item.get("current")),
                    min_val=_table_cell(item.get("min")),
                    max_val=_table_cell(item.get("max")),
                    previous=_table_cell(item.get("previous")),
                    delta=_table_cell(_format_delta(item)),
                    unit=_table_cell(item.get("unit", "")),
                )
            )
    else:
        lines.append("| 指标 | 当前 | 上一周期 | 变化 | 单位 |")
        lines.append("| --- | --- | --- | --- | --- |")
        for item in payload.get("kpi_summary") or []:
            lines.append(
                "| {name} | {current} | {previous} | {delta} | {unit} |".format(
                    name=_table_cell(item.get("name", item.get("key", ""))),
                    current=_table_cell(item.get("current")),
                    previous=_table_cell(item.get("previous")),
                    delta=_table_cell(_format_delta(item)),
                    unit=_table_cell(item.get("unit", "")),
                )
            )
    lines.append("")

    top_anomalies = payload.get("top_anomalies") or []
    if top_anomalies:
        lines.append("## 异常设备排行")
        lines.append("")
        lines.append("| 排名 | 设备ID | 名称 | 区域 | 异常描述 | 严重性 |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for item in top_anomalies:
            lines.append(
                "| {rank} | {equipment_id} | {name} | {area} | {issue} | {severity} |".format(
                    rank=_table_cell(item.get("rank", "")),
                    equipment_id=_table_cell(item.get("equipment_id", "")),
                    name=_table_cell(item.get("name", "")),
                    area=_table_cell(item.get("area", "")),
                    issue=_table_cell(item.get("issue", "")),
                    severity=_table_cell(item.get("severity", "")),
                )
            )
        lines.append("")

    lines.append("## 异常事件")
    lines.append("")
    alarms = payload.get("alarm_table") or []
    if alarms:
        lines.append("| 时间 | 设备 | 级别 | 描述 |")
        lines.append("| --- | --- | --- | --- |")
        for alarm in alarms:
            lines.append(
                "| {time} | {equipment} | {level} | {message} |".format(
                    time=_table_cell(alarm.get("time", "")),
                    equipment=_table_cell(alarm.get("equipment", "")),
                    level=_table_cell(alarm.get("level", "")),
                    message=_table_cell(alarm.get("message", "")),
                )
            )
    else:
        lines.append("今日无异常事件。")
    lines.append("")

    lines.append("## 建议")
    lines.append("")
    for rec in payload.get("recommendations") or []:
        lines.append(f"- {rec}")
    lines.append("")
    return "\n".join(lines)


def write_report(payload: dict, fmt: str, path: Path | None = None) -> Path:
    if fmt not in SUPPORTED_FORMATS:
        raise ValueError(f"Unsupported export format: {fmt}")
    out_path = path or (_output_dir() / f"daily_report.{fmt}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    content = render_markdown(payload)
    out_path.write_text(content, encoding="utf-8")
    return out_path


def build_export_result(payload: dict, fmt: str, path: Path | None = None) -> dict:
    out_path = write_report(payload, fmt, path=path)
    filename = out_path.name
    return {
        "format": fmt,
        "filename": filename,
        "path": str(out_path),
        "artifact_path": str(out_path),
    }


def load_payload(path: Path | None = None) -> dict:
    target = path or (_output_dir() / INPUT_FILENAME)
    return json.loads(target.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Export daily report")
    parser.add_argument("--input", default=None, help="Input KPI JSON path")
    parser.add_argument("--format", default="md", choices=sorted(SUPPORTED_FORMATS))
    parser.add_argument("--output", default=None, help="Output file path")
    args = parser.parse_args()

    try:
        payload = load_payload(Path(args.input)) if args.input else load_payload()
    except FileNotFoundError as exc:
        print(json.dumps({"error": f"input not found: {exc}"}, ensure_ascii=False))
        return 0
    except json.JSONDecodeError as exc:
        print(json.dumps({"error": f"invalid input JSON: {exc}"}, ensure_ascii=False))
        return 0

    try:
        result = build_export_result(payload, args.format, path=Path(args.output) if args.output else None)
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 0
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
