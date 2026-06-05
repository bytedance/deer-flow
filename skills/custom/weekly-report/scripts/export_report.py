#!/usr/bin/env python
"""Export weekly KPI payload to a downloadable report file (Markdown only).

Reads weekly_kpi.json and writes weekly_report.md.
"""

from __future__ import annotations

import argparse
import base64
import json
import math
import os
import sys
import uuid
from pathlib import Path

DEFAULT_OUTPUT_DIR = "/mnt/user-data/outputs"
INPUT_FILENAME = "weekly_kpi.json"

_SERIES_COLORS = ["#5470c6", "#91cc75", "#fac858", "#ee6666", "#73c0de", "#3ba272"]

COMPARE_LABEL_WEEKLY = {
    "previous_week": "对比上一周",
    "previous_year": "对比去年同期",
    "none": "无对比",
}


def _output_dir() -> Path:
    return Path(
        os.environ.get(
            "WEEKLY_REPORT_OUTPUT_DIR",
            os.environ.get("DAILY_REPORT_OUTPUT_DIR", DEFAULT_OUTPUT_DIR),
        )
    )


def _svg_segments(data: list) -> list[list[tuple[int, float]]]:
    segments: list[list[tuple[int, float]]] = []
    current: list[tuple[int, float]] = []
    for i, v in enumerate(data):
        if v is None or not isinstance(v, (int, float)):
            if current:
                segments.append(current)
                current = []
        else:
            current.append((i, float(v)))
    if current:
        segments.append(current)
    return segments


def trend_chart_to_svg(chart: dict, theme: str = "transparent") -> str:
    all_series = chart.get("series") or []
    if not all_series:
        return ""

    x_labels = (chart.get("xAxis") or {}).get("data") or [f"{h:02d}:00" for h in range(24)]
    title_text = (chart.get("title") or {}).get("text", "")
    y_axis_raw = chart.get("yAxis")
    if isinstance(y_axis_raw, list):
        y_name = (y_axis_raw[0] or {}).get("name", "") if y_axis_raw else ""
    elif isinstance(y_axis_raw, dict):
        y_name = y_axis_raw.get("name", "")
    else:
        y_name = ""

    all_values: list[float] = []
    for s in all_series:
        for v in (s.get("data") or []):
            if v is not None and isinstance(v, (int, float)):
                all_values.append(float(v))
    if not all_values:
        return ""

    SVG_W, SVG_H = 760, 300
    ML, MR, MT, MB = 60, 20, 36, 50
    PW = SVG_W - ML - MR
    PH = SVG_H - MT - MB

    raw_min, raw_max = min(all_values), max(all_values)
    y_min = math.floor(raw_min * 10) / 10
    y_max = math.ceil(raw_max * 10) / 10
    if y_min == y_max:
        y_min -= 0.1
        y_max += 0.1
    y_range = y_max - y_min

    n_points = max(len(x_labels), 1)

    if theme == "dark":
        bg, fg, grid, muted = "#161820", "#E8ECF1", "#2A2D36", "#8B919B"
    elif theme == "transparent":
        bg = "transparent"
        fg = "currentColor"
        grid = "currentColor"
        muted = "currentColor"
    else:
        bg, fg, grid, muted = "#fff", "#333", "#eee", "#666"

    def px(i: int) -> float:
        return ML + (i / max(n_points - 1, 1)) * PW

    def py(v: float) -> float:
        return MT + PH * (1 - (v - y_min) / y_range)

    ticks = [y_min + i * y_range / 4 for i in range(5)]

    parts: list[str] = []
    parts.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {SVG_W} {SVG_H}" '
                 f'width="{SVG_W}" height="{SVG_H}">')
    parts.append(f'<rect width="{SVG_W}" height="{SVG_H}" fill="{bg}"/>')

    if title_text:
        parts.append(f'<text x="{SVG_W / 2}" y="22" text-anchor="middle" '
                     f'font-size="13" font-family="SimSun,Noto Sans SC,sans-serif" fill="{fg}">'
                     f'{_svg_escape(title_text)}</text>')

    if y_name:
        rx = -(MT + PH // 2)
        parts.append(f'<text transform="rotate(-90)" x="{rx}" y="14" text-anchor="middle" '
                     f'font-size="10" font-family="SimSun,sans-serif" '
                     f'fill="{muted}"{_opacity_attr(theme, "text")}>'
                     f'{_svg_escape(y_name)}</text>')

    for t in ticks:
        ty = py(t)
        parts.append(f'<line x1="{ML}" y1="{ty:.1f}" x2="{ML + PW}" y2="{ty:.1f}" '
                     f'stroke="{grid}" stroke-width="1"'
                     f'{_opacity_attr(theme, "grid")}/>')
        parts.append(f'<text x="{ML - 6}" y="{ty + 4:.1f}" text-anchor="end" '
                     f'font-size="10" fill="{muted}"{_opacity_attr(theme, "text")}>{t:.2f}</text>')

    show_indices = list(range(0, n_points, max(n_points // 6, 1)))
    if n_points - 1 not in show_indices:
        show_indices.append(n_points - 1)
    for i in show_indices:
        if i < len(x_labels):
            parts.append(f'<text x="{px(i):.1f}" y="{MT + PH + 16}" text-anchor="middle" '
                         f'font-size="10" fill="{muted}"{_opacity_attr(theme, "text")}>'
                         f'{_svg_escape(str(x_labels[i]))}</text>')

    for si, s in enumerate(all_series):
        color = _SERIES_COLORS[si % len(_SERIES_COLORS)]
        data = s.get("data") or []
        is_dashed = (s.get("lineStyle") or {}).get("type") == "dashed"
        dash_attr = ' stroke-dasharray="6,3"' if is_dashed else ""
        for seg in _svg_segments(data):
            if len(seg) < 2:
                cx, cy = px(seg[0][0]), py(seg[0][1])
                parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="2" fill="{color}"/>')
                continue
            points_str = " ".join(f"{px(i):.1f},{py(v):.1f}" for i, v in seg)
            parts.append(f'<polyline points="{points_str}" fill="none" '
                         f'stroke="{color}" stroke-width="2"{dash_attr}/>')

    legend_y = SVG_H - 12
    legend_items: list[tuple[str, str]] = []
    for si, s in enumerate(all_series):
        name = str(s.get("name", f"Series {si + 1}"))
        if len(name) > 20:
            name = name[:18] + "…"
        color = _SERIES_COLORS[si % len(_SERIES_COLORS)]
        legend_items.append((name, color))

    if legend_items:
        item_w = 100
        total_w = len(legend_items) * item_w
        start_x = (SVG_W - total_w) / 2
        for li, (name, color) in enumerate(legend_items):
            lx = start_x + li * item_w
            parts.append(f'<rect x="{lx:.1f}" y="{legend_y - 3}" width="20" height="3" fill="{color}"/>')
            parts.append(f'<text x="{lx + 24:.1f}" y="{legend_y}" font-size="10" '
                         f'fill="{muted}"{_opacity_attr(theme, "text")}>'
                         f'{_svg_escape(name)}</text>')

    parts.append("</svg>")
    return "\n".join(parts)


def _svg_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _opacity_attr(theme: str, element: str) -> str:
    if theme == "transparent":
        if element == "text":
            return ' fill-opacity="0.55"'
        if element == "grid":
            return ' stroke-opacity="0.15"'
    return ""


def _format_number(value) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def _table_cell(value) -> str:
    return _format_number(value).replace("|", "\\|").replace("\n", " ")


def _format_weekly_kpi_value(value, unit: str) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.2f}{unit}" if unit else f"{value:.2f}"
    return f"{value}{unit}" if unit else str(value)


def _format_weekly_delta(item: dict) -> str:
    delta = item.get("delta_mean")
    pct = item.get("delta_pct")
    if delta is None:
        return "—"
    arrow = "↑" if delta > 0 else ("↓" if delta < 0 else "→")
    if pct is None:
        return f"{arrow} {_format_number(abs(delta))}"
    return f"{arrow} {_format_number(abs(delta))} ({pct * 100:+.1f}%)"


def _embed_chart_image(svg_str: str, alt: str, thread_id: str | None = None) -> str:
    b64 = base64.b64encode(svg_str.encode("utf-8")).decode("ascii")
    data_uri = f"data:image/svg+xml;base64,{b64}"

    if len(data_uri) <= 50 * 1024:
        return f"![{alt}]({data_uri})"

    output_dir = _output_dir()
    filename = f"chart_{uuid.uuid4().hex[:8]}.svg"
    filepath = output_dir / filename
    filepath.write_text(svg_str, encoding="utf-8")

    if thread_id:
        return f"![{alt}](/api/threads/{thread_id}/artifacts/mnt/user-data/outputs/{filename})"
    return f"![{alt}]({data_uri})"


def render_markdown(payload: dict, thread_id: str | None = None) -> str:
    """Render weekly KPI payload as a Markdown report string."""
    period = payload.get("report_period") or {}
    week_start = period.get("week_start", "")
    week_end = period.get("week_end", "")
    compare_type = payload.get("compare_type", "none")
    compare_period = payload.get("compare_period") or {}

    lines: list[str] = []
    lines.append("# 设备运行周报")
    lines.append("")
    if payload.get("week_start_warning"):
        lines.append(f"> ⚠ {payload['week_start_warning']}。")
        lines.append("")
    lines.append(f"- 报告周期：{week_start} 至 {week_end}")
    compare_label = COMPARE_LABEL_WEEKLY.get(compare_type, compare_type)
    if compare_type != "none" and compare_period.get("start") and compare_period.get("end"):
        compare_label = f"{compare_label}（{compare_period['start']} 至 {compare_period['end']}）"
    lines.append(f"- 对比基准：{compare_label}")
    if payload.get("compare_warning"):
        lines.append(f"- 对比说明：{payload['compare_warning']}")
    lines.append("")

    overall = payload.get("overall_status") or {}
    lines.append("## 本周概览")
    lines.append("")
    lines.append(f"- 状态：{overall.get('level', 'good')}")
    lines.append(f"- 总结：{overall.get('summary', '')}")
    lines.append("")

    lines.append("## 周 KPI")
    lines.append("")
    lines.append("> 口径说明：均值=7 日 daily KPI 简单平均；峰值/低谷=7 日 max/min；波动率=std÷mean。")
    lines.append("")
    lines.append("| 指标 | 周均值 | 周峰值 | 周低谷 | 波动率 | 上期均值 | 周环比 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for item in payload.get("kpi_summary") or []:
        unit = item.get("unit", "")
        volatility = item.get("current_volatility")
        volatility_str = f"{volatility * 100:.1f}%" if isinstance(volatility, (int, float)) else "—"
        lines.append(
            "| {name} | {mean} | {peak} | {trough} | {vol} | {prev} | {delta} |".format(
                name=_table_cell(item.get("name", item.get("key", ""))),
                mean=_table_cell(_format_weekly_kpi_value(item.get("current_mean"), unit)),
                peak=_table_cell(_format_weekly_kpi_value(item.get("current_peak"), unit)),
                trough=_table_cell(_format_weekly_kpi_value(item.get("current_trough"), unit)),
                vol=_table_cell(volatility_str),
                prev=_table_cell(_format_weekly_kpi_value(item.get("previous_mean"), unit)),
                delta=_table_cell(_format_weekly_delta(item)),
            )
        )
    lines.append("")

    trend_chart = payload.get("daily_trend_chart")
    if trend_chart and trend_chart.get("series"):
        svg_str = trend_chart_to_svg(trend_chart)
        if svg_str:
            lines.append("## 日趋势")
            lines.append("")
            lines.append(_embed_chart_image(svg_str, "本周日趋势图", thread_id))
            lines.append("")

    anomaly_top_n = payload.get("anomaly_top_n") or []
    if anomaly_top_n:
        lines.append("## 异常 TopN")
        lines.append("")
        lines.append("| 设备 | 级别 | 次数 | 最近一次 | 主导原因 |")
        lines.append("| --- | --- | --- | --- | --- |")
        for row in anomaly_top_n:
            lines.append(
                "| {eq} | {lv} | {cnt} | {latest} | {msg} |".format(
                    eq=_table_cell(row.get("equipment", "")),
                    lv=_table_cell(row.get("level", "")),
                    cnt=_table_cell(row.get("count", 0)),
                    latest=_table_cell(row.get("latest_time", "")),
                    msg=_table_cell(row.get("dominant_message", "")),
                )
            )
        lines.append("")

    # SMS 异常事件 section — between 异常 TopN and 告警流水
    sms_table = payload.get("sms_abnormal_table") or []
    if sms_table:
        lines.append("## SMS 异常事件")
        lines.append("")
        lines.append("| 排名 | 设备 | 部件 | 健康度 | 等级 | 严重性 | 事件数 | 处置状态 |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
        for row in sms_table:
            lines.append(
                "| {rank} | {eq} | {comp} | {health} | {level} | {sev} | {cnt} | {status} |".format(
                    rank=_table_cell(row.get("rank", "")),
                    eq=_table_cell(row.get("equipment", "")),
                    comp=_table_cell(row.get("component", "")),
                    health=_table_cell(row.get("health", "")),
                    level=_table_cell(row.get("level", "")),
                    sev=_table_cell(row.get("severity", "")),
                    cnt=_table_cell(row.get("event_count", 0)),
                    status=_table_cell(row.get("process_status", "")),
                )
            )
        lines.append("")

    lines.append("## 告警流水")
    lines.append("")
    alarm_table = payload.get("alarm_table") or []
    if alarm_table:
        lines.append("| 时间 | 设备 | 级别 | 描述 |")
        lines.append("| --- | --- | --- | --- |")
        for alarm in alarm_table:
            lines.append(
                "| {t} | {eq} | {lv} | {msg} |".format(
                    t=_table_cell(alarm.get("time", "")),
                    eq=_table_cell(alarm.get("equipment", "")),
                    lv=_table_cell(alarm.get("level", "")),
                    msg=_table_cell(alarm.get("message", "")),
                )
            )
    else:
        lines.append("本周无告警事件。")
    lines.append("")

    lines.append("## 下周关注")
    lines.append("")
    for focus in payload.get("next_week_focus") or []:
        lines.append(f"- {focus}")
    lines.append("")
    return "\n".join(lines)


def write_report(payload: dict, path: Path | None = None, thread_id: str | None = None) -> Path:
    filename = "weekly_report.md"
    out_path = path or (_output_dir() / filename)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    content = render_markdown(payload, thread_id=thread_id)
    out_path.write_text(content, encoding="utf-8")
    return out_path


def build_export_result(payload: dict, path: Path | None = None) -> dict:
    out_path = write_report(payload, path=path)
    filename = out_path.name
    virtual_path = f"/mnt/user-data/outputs/{filename}"
    return {
        "format": "md",
        "filename": filename,
        "path": str(out_path),
        "artifact_path": str(out_path),
        "present_files_hint": [virtual_path],
    }


def load_payload(path: Path | None = None) -> dict:
    if path is not None:
        target = path
    else:
        target = _output_dir() / INPUT_FILENAME
    return json.loads(target.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Export weekly report")
    parser.add_argument("--input", default=None, help="Input KPI JSON path")
    parser.add_argument("--output", default=None, help="Output file path")
    args = parser.parse_args()

    try:
        payload = load_payload(Path(args.input) if args.input else None)
    except FileNotFoundError as exc:
        print(json.dumps({"error": f"input not found: {exc}"}, ensure_ascii=False))
        return 0
    except json.JSONDecodeError as exc:
        print(json.dumps({"error": f"invalid input JSON: {exc}"}, ensure_ascii=False))
        return 0

    try:
        result = build_export_result(payload, path=Path(args.output) if args.output else None)
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 0
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
