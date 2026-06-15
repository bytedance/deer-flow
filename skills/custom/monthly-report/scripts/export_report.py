#!/usr/bin/env python
"""Export monthly KPI payload to a downloadable report file (Markdown only).

Reads monthly_kpi.json and writes monthly_report.md.
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

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from _perf import get_tracer

DEFAULT_OUTPUT_DIR = "/mnt/user-data/outputs"
INPUT_FILENAME = "monthly_kpi.json"

_SERIES_COLORS = ["#5470c6", "#91cc75", "#fac858", "#ee6666", "#73c0de", "#3ba272"]

COMPARE_LABEL_MONTHLY = {
    "previous_month": "上月（环比 MoM）",
    "previous_year_month": "去年同月（同比 YoY）",
    "none": "无对比",
}


def _output_dir() -> Path:
    return Path(
        os.environ.get(
            "MONTHLY_REPORT_OUTPUT_DIR",
            os.environ.get(
                "WEEKLY_REPORT_OUTPUT_DIR",
                os.environ.get("DAILY_REPORT_OUTPUT_DIR", DEFAULT_OUTPUT_DIR),
            ),
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


def _format_monthly_pct(pct: float | None) -> str:
    if pct is None:
        return "—"
    return f"{pct * 100:+.1f}%"


def _format_monthly_value(value, unit: str) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.2f}{unit}" if unit else f"{value:.2f}"
    return f"{value}{unit}" if unit else str(value)


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
    """Render monthly KPI payload as a Markdown report string.

    Eight sections, in order:
      1. 月度总览
      2. 月 KPI 表
      3. 周维度趋势
      4. 异常 TopN
      5. 重大事件回顾
      6. 月环比 + 同比
      7. 改进措施跟踪
      8. 下月计划
    """
    period = payload.get("report_period") or {}
    month_label = period.get("report_month") or ""
    month_start = period.get("month_start", "")
    month_end = period.get("month_end", "")
    compare_types = payload.get("compare_types") or []
    compare_periods = payload.get("compare_periods") or {}

    lines: list[str] = []
    lines.append(f"# 设备运行月报：{month_label}")
    lines.append("")
    if payload.get("compare_warning"):
        lines.append(f"> ⚠ {payload['compare_warning']}。")
        lines.append("")

    lines.append(f"- 报告月份：{month_label}（{month_start} 至 {month_end}）")
    if compare_types:
        compare_lines = []
        for basis in compare_types:
            label = COMPARE_LABEL_MONTHLY.get(basis, basis)
            cp = compare_periods.get(basis) or {}
            if cp.get("start") and cp.get("end"):
                compare_lines.append(f"{label}（{cp['start']} 至 {cp['end']}）")
            else:
                compare_lines.append(label)
        lines.append(f"- 对比基准：{'; '.join(compare_lines)}")
    else:
        lines.append("- 对比基准：无对比")
    lines.append("")

    overall = payload.get("overall_status") or {}
    lines.append("## 1. 月度总览")
    lines.append("")
    lines.append(f"- 状态：{overall.get('level', 'good')}")
    lines.append(f"- 总结：{overall.get('summary', '')}")
    lines.append("")

    lines.append("## 2. 月 KPI")
    lines.append("")
    lines.append(
        "| 指标 | 月均值 | 月峰值 | 月低谷 | 波动率 | 达标率 | 上月均值 | 月环比 | 去年同月 | 同比 |"
    )
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for item in payload.get("kpi_summary") or []:
        unit = item.get("unit", "")
        volatility = item.get("current_volatility")
        vol_str = (
            f"{volatility * 100:.1f}%" if isinstance(volatility, (int, float)) else "—"
        )
        ratio = item.get("current_in_target_ratio")
        ratio_str = (
            f"{ratio * 100:.1f}%" if isinstance(ratio, (int, float)) else "—"
        )
        lines.append(
            "| {name} | {mean} | {peak} | {trough} | {vol} | {ratio} | {pmo} | {dmo} | {pyr} | {dyr} |".format(
                name=_table_cell(item.get("name", item.get("key", ""))),
                mean=_table_cell(_format_monthly_value(item.get("current_mean"), unit)),
                peak=_table_cell(_format_monthly_value(item.get("current_peak"), unit)),
                trough=_table_cell(_format_monthly_value(item.get("current_trough"), unit)),
                vol=_table_cell(vol_str),
                ratio=_table_cell(ratio_str),
                pmo=_table_cell(_format_monthly_value(item.get("previous_month_mean"), unit)),
                dmo=_table_cell(_format_monthly_pct(item.get("delta_mom_pct"))),
                pyr=_table_cell(_format_monthly_value(item.get("previous_year_month_mean"), unit)),
                dyr=_table_cell(_format_monthly_pct(item.get("delta_yoy_pct"))),
            )
        )
    lines.extend(
        [
            "",
            "> 口径说明：月均值按 7 日桶 ``day_count`` 加权平均（区别于周报 7 日简单平均、日报单日值）；"
            "MTBF=`total_uptime_hours / max(total_failures, 1)`；"
            "MTTR=`total_repair_minutes / max(total_failures, 1) / 60`；"
            "零故障月 MTBF/MTTR 输出 `—`。",
            "",
        ]
    )

    trend_chart = payload.get("weekly_trend_chart")
    if trend_chart and trend_chart.get("series"):
        svg_str = trend_chart_to_svg(trend_chart)
        if svg_str:
            lines.append("## 3. 周维度趋势")
            lines.append("")
            lines.append(_embed_chart_image(svg_str, "本月周维度趋势图", thread_id))
            lines.append("")

    anomaly_top_n = payload.get("anomaly_top_n") or []
    if anomaly_top_n:
        lines.append("## 4. 异常 TopN")
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

    critical_events = payload.get("critical_events") or []
    if critical_events:
        lines.append("## 5. 重大事件回顾")
        lines.append("")
        lines.append("| 时间 | 设备 | 级别 | 描述 | 处置时长(分钟) | 已处置 |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for e in critical_events:
            lines.append(
                "| {t} | {eq} | {lv} | {msg} | {dur} | {res} |".format(
                    t=_table_cell(e.get("time", "")),
                    eq=_table_cell(e.get("equipment", "")),
                    lv=_table_cell(e.get("level", "")),
                    msg=_table_cell(e.get("message", "")),
                    dur=_table_cell(e.get("duration_minutes", "—")),
                    res=_table_cell("是" if e.get("resolved") else "否"),
                )
            )
        lines.append("")

    # SMS 异常事件 — section 5.5 between 重大事件回顾 (5) and 月环比+同比 (6)
    sms_table = payload.get("sms_abnormal_table") or []
    if sms_table:
        lines.append("## 5.5 SMS 异常事件")
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

    if compare_types:
        lines.append("## 6. 月环比 + 同比")
        lines.append("")
        lines.append("| 指标 | 月环比 (MoM) | 同比 (YoY) |")
        lines.append("| --- | --- | --- |")
        for item in payload.get("kpi_summary") or []:
            lines.append(
                "| {name} | {mo} | {yr} |".format(
                    name=_table_cell(item.get("name", item.get("key", ""))),
                    mo=_table_cell(_format_monthly_pct(item.get("delta_mom_pct"))),
                    yr=_table_cell(_format_monthly_pct(item.get("delta_yoy_pct"))),
                )
            )
        lines.append("")

    improvement_tracking = payload.get("improvement_tracking") or []
    if improvement_tracking:
        lines.append("## 7. 改进措施跟踪")
        lines.append("")
        lines.append("| 编号 | 负责人 | 计划 | 截止 | 状态 | 完成度 | 备注 |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- |")
        for r in improvement_tracking:
            completion = r.get("completion_rate")
            completion_str = (
                f"{completion}%" if isinstance(completion, (int, float)) else "—"
            )
            lines.append(
                "| {id} | {owner} | {plan} | {due} | {status} | {comp} | {note} |".format(
                    id=_table_cell(r.get("id", "")),
                    owner=_table_cell(r.get("owner", "")),
                    plan=_table_cell(r.get("plan", "")),
                    due=_table_cell(r.get("due_date", "")),
                    status=_table_cell(r.get("status", "")),
                    comp=_table_cell(completion_str),
                    note=_table_cell(r.get("note", "")),
                )
            )
        lines.append("")

    lines.append("## 8. 下月计划")
    lines.append("")
    next_month_plan = payload.get("next_month_plan") or []
    if next_month_plan:
        for plan_item in next_month_plan:
            lines.append(f"- {plan_item}")
    else:
        lines.append("- 本月无显著异常，下月保持当前预防性维护节奏。")
    lines.append("")

    monthly_review = payload.get("monthly_review")
    if monthly_review:
        lines.append("---")
        lines.append("")
        lines.append("### 月度复盘")
        lines.append("")
        lines.append(monthly_review)
        lines.append("")

    return "\n".join(lines)


def write_report(payload: dict, path: Path | None = None, thread_id: str | None = None) -> Path:
    filename = "monthly_report.md"
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
    tracer = get_tracer("export_report")
    parser = argparse.ArgumentParser(description="Export monthly report")
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

    tracer.start_span("export")
    try:
        result = build_export_result(payload, path=Path(args.output) if args.output else None)
    except ValueError as exc:
        tracer.end_span(error=str(exc))
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 0
    tracer.end_span()
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
