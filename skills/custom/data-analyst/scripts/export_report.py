#!/usr/bin/env python
"""Export daily KPI payload to a downloadable report file.

Reads ``$DAILY_REPORT_OUTPUT_DIR/daily_kpi.json`` (or ``--input``) and
writes ``$DAILY_REPORT_OUTPUT_DIR/daily_report.{md,pdf}``.

Supports two modes:
- **detail**: per-device listing (original behavior)
- **grouped**: aggregated display with device count and top_anomalies table

Export formats:
- **md**: Markdown (always available)
- **pdf**: HTML→PDF via weasyprint (raises ``ImportError`` when weasyprint
  is not installed)
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
INPUT_FILENAME = "daily_kpi.json"
WEEKLY_INPUT_FILENAME = "weekly_kpi.json"
MONTHLY_INPUT_FILENAME = "monthly_kpi.json"
DIAGNOSIS_INPUT_FILENAME = "diagnosis_features.json"
MONITORING_INPUT_FILENAME = "monitoring_features.json"
SUPPORTED_FORMATS = {"md", "pdf"}
SUPPORTED_REPORT_TYPES = {"daily", "weekly", "monthly", "diagnosis", "monitoring"}


TYPE_DISPLAY = {
    "static_equipment": "静设备",
    "rotating_machinery": "旋转机组",
    "pump": "机泵",
    "reciprocating_machinery": "往复机组",
    "all": "设备",
}


def _output_dir(report_type: str = "daily") -> Path:
    """Resolve output dir.

    Daily reports keep their original env contract (``DAILY_REPORT_OUTPUT_DIR``).
    Weekly reports prefer ``WEEKLY_REPORT_OUTPUT_DIR`` but fall back to the
    daily var so a single sandbox configuration covers both. Monthly extends
    the chain to ``MONTHLY_REPORT_OUTPUT_DIR`` → weekly → daily.
    Diagnosis prefers ``DIAGNOSIS_OUTPUT_DIR`` (matches query_diagnosis.py /
    diagnosis_features.py) and falls back to the daily var.
    """
    if report_type == "monthly":
        return Path(
            os.environ.get(
                "MONTHLY_REPORT_OUTPUT_DIR",
                os.environ.get(
                    "WEEKLY_REPORT_OUTPUT_DIR",
                    os.environ.get("DAILY_REPORT_OUTPUT_DIR", DEFAULT_OUTPUT_DIR),
                ),
            )
        )
    if report_type == "weekly":
        return Path(
            os.environ.get(
                "WEEKLY_REPORT_OUTPUT_DIR",
                os.environ.get("DAILY_REPORT_OUTPUT_DIR", DEFAULT_OUTPUT_DIR),
            )
        )
    if report_type == "diagnosis":
        return Path(
            os.environ.get(
                "DIAGNOSIS_OUTPUT_DIR",
                os.environ.get("DAILY_REPORT_OUTPUT_DIR", DEFAULT_OUTPUT_DIR),
            )
        )
    if report_type == "monitoring":
        return Path(
            os.environ.get(
                "MONITORING_REPORT_OUTPUT_DIR",
                os.environ.get("DAILY_REPORT_OUTPUT_DIR", DEFAULT_OUTPUT_DIR),
            )
        )
    return Path(os.environ.get("DAILY_REPORT_OUTPUT_DIR", DEFAULT_OUTPUT_DIR))


_SERIES_COLORS = ["#5470c6", "#91cc75", "#fac858", "#ee6666", "#73c0de", "#3ba272"]


def _svg_segments(data: list) -> list[list[tuple[int, float]]]:
    """Split data into contiguous non-None segments for polyline rendering."""
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
    """Convert an ECharts line-chart option dict into an SVG string.

    theme: 'light' | 'dark' | 'transparent' (default). 'transparent' uses
    currentColor and opacity so the SVG adapts to both color modes via CSS.

    Returns an empty string if chart has no renderable series data.
    """
    all_series = chart.get("series") or []
    if not all_series:
        return ""

    x_labels = (chart.get("xAxis") or {}).get("data") or [f"{h:02d}:00" for h in range(24)]
    title_text = (chart.get("title") or {}).get("text", "")
    y_axis_raw = chart.get("yAxis")
    if isinstance(y_axis_raw, list):
        # Multi-axis charts (e.g. weekly daily_trend_chart) — pick first axis name
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

    # Theme colours
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
    """Return SVG opacity attributes for the transparent theme.

    In transparent mode, secondary elements use reduced opacity so they don't
    visually compete with primary content.  Light/dark themes use explicit
    muted/grid colours instead and don't need opacity.
    """
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


def _format_delta(item: dict) -> str:
    delta = item.get("delta")
    if delta is None:
        return "—"
    arrow = "↑" if delta > 0 else ("↓" if delta < 0 else "→")
    return f"{arrow} {_format_number(abs(delta) if isinstance(delta, (int, float)) else delta)}"


def _table_cell(value) -> str:
    return _format_number(value).replace("|", "\\|").replace("\n", " ")


def _read_image_as_data_uri(img_path: str) -> str | None:
    """Read an image file and return a base64 data URI, or None if unreadable."""
    p = Path(img_path)
    if not p.is_file():
        return None
    suffix = p.suffix.lower()
    mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"}.get(
        suffix.lstrip("."), "image/png"
    )
    try:
        data = p.read_bytes()
        b64 = base64.b64encode(data).decode("ascii")
        return f"data:{mime};base64,{b64}"
    except OSError:
        return None


def _embed_chart_image(svg_str: str, alt: str, thread_id: str | None = None) -> str:
    """Embed a chart SVG as Markdown image syntax.

    For SVGs ≤50KB, returns an inline base64 data URI.
    For SVGs >50KB, writes the file and returns an artifact URL reference.
    """
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


def render_markdown(payload: dict, chart_images: list[str] | None = None, thread_id: str | None = None) -> str:
    """Render KPI payload as a Markdown report string."""
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
        equipment_names = payload.get("equipment_names") or {}
        if equipment:
            labels = [equipment_names.get(eid, eid) for eid in equipment]
            lines.append(f"- 设备：{', '.join(labels)}")

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

    if chart_images:
        embedded = False
        for i, img_path in enumerate(chart_images):
            data_uri = _read_image_as_data_uri(img_path)
            if data_uri:
                if not embedded:
                    lines.append("## 运行趋势")
                    lines.append("")
                    embedded = True
                lines.append(f'![趋势图{i + 1}]({data_uri})')
                lines.append("")
        if not embedded:
            trend_chart = payload.get("trend_chart")
            if trend_chart and trend_chart.get("series"):
                svg_str = trend_chart_to_svg(trend_chart)
                if svg_str:
                    lines.append("## 运行趋势")
                    lines.append("")
                    lines.append(_embed_chart_image(svg_str, "运行趋势图", thread_id))
                    lines.append("")
    else:
        trend_chart = payload.get("trend_chart")
        if trend_chart and trend_chart.get("series"):
            svg_str = trend_chart_to_svg(trend_chart)
            if svg_str:
                lines.append("## 运行趋势")
                lines.append("")
                lines.append(_embed_chart_image(svg_str, "运行趋势图", thread_id))
                lines.append("")

    top_anomalies = payload.get("top_anomalies") or []
    if top_anomalies:
        lines.append("## 异常设备排行")
        lines.append("")
        lines.append("| 排名 | 设备名称 | 区域 | 异常描述 | 严重性 |")
        lines.append("| --- | --- | --- | --- | --- |")
        for item in top_anomalies:
            lines.append(
                "| {rank} | {name} | {area} | {issue} | {severity} |".format(
                    rank=_table_cell(item.get("rank", "")),
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


def render_html(payload: dict, chart_images: list[str] | None = None) -> str:
    """Render payload as a standalone HTML document with embedded CSS."""
    md = render_markdown(payload, chart_images)
    return _markdown_to_html(md, payload=payload, chart_images=chart_images)


COMPARE_LABEL_WEEKLY = {
    "previous_week": "对比上一周",
    "previous_year": "对比去年同期",
    "none": "无对比",
}


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


def render_weekly_markdown(payload: dict, thread_id: str | None = None) -> str:
    """Render weekly KPI payload as a Markdown report string.

    The output is intentionally distinct from ``render_markdown`` (daily) so
    user-facing reports never blur the two:
    - KPI table headers say "本周均值/峰值/低谷/波动率" instead of "当前/上一周期".
    - Trend section embeds an SVG built from ``daily_trend_chart`` (7-day x-axis).
    - Anomaly table is the TopN aggregation from ``weekly_kpi.anomaly_top_n``.
    - Alarm flow table follows. Next-week focus closes the report.
    """
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


def render_weekly_html(payload: dict) -> str:
    """Render weekly payload as a standalone HTML document."""
    md = render_weekly_markdown(payload)
    return _markdown_to_html(md, payload=None, chart_images=None)


# ---------------------------------------------------------------------------
# Monthly rendering (single entry — see design doc §4.3 "render_monthly_markdown
# is the sole renderer; monthly_kpi.py does NOT emit summary_markdown").
# ---------------------------------------------------------------------------

COMPARE_LABEL_MONTHLY = {
    "previous_month": "上月（环比 MoM）",
    "previous_year_month": "去年同月（同比 YoY）",
    "none": "无对比",
}


def _format_monthly_pct(pct: float | None) -> str:
    """Render a delta_pct value as ``+3.2%`` / ``—`` (None → dash)."""
    if pct is None:
        return "—"
    return f"{pct * 100:+.1f}%"


def _format_monthly_value(value, unit: str) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.2f}{unit}" if unit else f"{value:.2f}"
    return f"{value}{unit}" if unit else str(value)


def render_monthly_markdown(payload: dict, thread_id: str | None = None) -> str:
    """Render monthly KPI payload as a Markdown report string.

    This is the ONLY full-markdown renderer for monthly reports — see design
    doc §4.3 and §6.2 rendering-layer contract: ``monthly_kpi.py`` outputs
    structured fields only, and the artifact-quality 8-section Markdown is
    assembled exclusively here. The function deliberately ignores any
    ``summary_markdown`` key the payload may carry (kept for forward-compat
    if a future revision re-introduces it; sprint plan M7 has a regression
    test asserting the field is NOT consulted).

    Eight sections, in order:
      1. 月度总览
      2. 月 KPI 表（含 MTBF/MTTR/达标率 + 小节尾"口径说明"引用块）
      3. 周维度趋势（PDF 时嵌入 SVG）
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

    # Header bullets
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
    # Section 1: 月度总览
    lines.append("## 1. 月度总览")
    lines.append("")
    lines.append(f"- 状态：{overall.get('level', 'good')}")
    lines.append(f"- 总结：{overall.get('summary', '')}")
    lines.append("")

    # Section 2: 月 KPI
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

    # Section 3: 周维度趋势
    trend_chart = payload.get("weekly_trend_chart")
    if trend_chart and trend_chart.get("series"):
        svg_str = trend_chart_to_svg(trend_chart)
        if svg_str:
            lines.append("## 3. 周维度趋势")
            lines.append("")
            lines.append(_embed_chart_image(svg_str, "本月周维度趋势图", thread_id))
            lines.append("")

    # Section 4: 异常 TopN
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

    # Section 5: 重大事件回顾 — skip table when empty (sprint plan M3 acceptance)
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

    # Section 6: 月环比 + 同比 (compact textual digest derived from kpi_summary)
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

    # Section 7: 改进措施跟踪 — skip table when empty (sprint plan M3 acceptance)
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

    # Section 8: 下月计划
    lines.append("## 8. 下月计划")
    lines.append("")
    next_month_plan = payload.get("next_month_plan") or []
    if next_month_plan:
        for plan_item in next_month_plan:
            lines.append(f"- {plan_item}")
    else:
        lines.append("- 本月无显著异常，下月保持当前预防性维护节奏。")
    lines.append("")

    # Trailing 月度复盘 (multi-paragraph, lives below the 8 numbered sections to
    # keep section indexing stable; the 8-section structure refers to the
    # numbered chapters above).
    monthly_review = payload.get("monthly_review")
    if monthly_review:
        lines.append("---")
        lines.append("")
        lines.append("### 月度复盘")
        lines.append("")
        lines.append(monthly_review)
        lines.append("")

    return "\n".join(lines)


def render_monthly_html(payload: dict) -> str:
    """Render monthly payload as a standalone HTML document."""
    md = render_monthly_markdown(payload)
    return _markdown_to_html(md, payload=None, chart_images=None)


def _markdown_to_html(md: str, payload: dict | None = None, chart_images: list[str] | None = None) -> str:
    """Shared Markdown → HTML wrapper.

    Daily callers pass ``payload`` + optional ``chart_images`` to keep the
    legacy chart-fallback behaviour. Weekly callers pass ``payload=None`` and
    rely on the SVG already being inlined inside ``md`` by
    ``render_weekly_markdown``.
    """
    try:
        import markdown as md_lib
        body = md_lib.markdown(md, extensions=["tables"])
    except ImportError:
        body = "<pre>" + md.replace("&", "&amp;").replace("<", "&lt;") + "</pre>"
        if payload is not None:
            chart_html = ""
            if chart_images:
                for i, img_path in enumerate(chart_images):
                    data_uri = _read_image_as_data_uri(img_path)
                    if data_uri:
                        chart_html += f'\n<img src="{data_uri}" alt="趋势图{i + 1}" style="max-width:100%">\n'
            if chart_html:
                body += f"\n<h2>运行趋势</h2>\n{chart_html}"
            else:
                trend_chart = payload.get("trend_chart")
                if trend_chart and trend_chart.get("series"):
                    svg_str = trend_chart_to_svg(trend_chart)
                    if svg_str:
                        body += f"\n<h2>运行趋势</h2>\n{svg_str}\n"

    return (
        "<!DOCTYPE html>\n<html lang='zh'>\n<head>\n<meta charset='utf-8'>\n"
        "<style>\n"
        "body { font-family: 'SimSun','Noto Sans SC',sans-serif; margin: 2cm; font-size: 12pt; }\n"
        "h1 { font-size: 18pt; border-bottom: 2px solid #333; padding-bottom: 6pt; }\n"
        "h2 { font-size: 14pt; margin-top: 16pt; }\n"
        "table { border-collapse: collapse; width: 100%; margin: 8pt 0; }\n"
        "th, td { border: 1px solid #ccc; padding: 6pt 8pt; text-align: left; }\n"
        "th { background: #f5f5f5; }\n"
        "img { max-width: 100%; }\n"
        "</style>\n</head>\n<body>\n"
        + body
        + "\n</body>\n</html>"
    )


def _monitoring_html(payload: dict) -> str:
    """Minimal HTML wrapper for monitoring PDF export."""
    md = render_monitoring_markdown(payload)
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>监测分析报告</title>
<style>
body {{ font-family: "Microsoft YaHei", "PingFang SC", sans-serif; max-width: 900px; margin: 40px auto; padding: 0 20px; color: #333; }}
h1 {{ border-bottom: 2px solid #5470C6; padding-bottom: 8px; }}
h2 {{ color: #5470C6; margin-top: 24px; }}
table {{ border-collapse: collapse; width: 100%; margin: 12px 0; }}
th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; font-size: 14px; }}
th {{ background: #f5f5f5; }}
</style></head>
<body>{md.replace(chr(10), "<br>")}</body></html>"""


def _write_pdf(html: str, out_path: Path) -> None:
    """Write HTML string to PDF. Requires weasyprint."""
    try:
        from weasyprint import HTML as WeasyprintHTML
    except ImportError:
        raise ImportError(
            "PDF export requires the 'weasyprint' package. "
            "Install it with: pip install weasyprint"
        ) from None
    WeasyprintHTML(string=html).write_pdf(str(out_path))


def render_monitoring_markdown(payload: dict, thread_id: str | None = None) -> str:
    """Render monitoring analysis report as Markdown.

    Covers all four analysis types: trend, anomaly, kpi_dashboard, correlation.
    """
    analysis_type = payload.get("analysis_type", "trend")
    type_labels = {
        "trend": "趋势分析",
        "anomaly": "异常检测",
        "kpi_dashboard": "KPI 健康看板",
        "correlation": "关联分析",
    }
    type_label = type_labels.get(analysis_type, analysis_type)

    lines: list[str] = []
    lines.append(f"# 监测分析报告 — {type_label}")
    lines.append("")

    # Scope
    time_range = payload.get("time_range", {})
    equipment_summary = payload.get("equipment_summary", [])
    eq_names = ", ".join(e.get("equipment_name", e.get("equipment_id", "?")) for e in equipment_summary[:5])
    if len(equipment_summary) > 5:
        eq_names += f" 等 {len(equipment_summary)} 台"
    lines.append(f"**分析类型**：{type_label}　|　**时间范围**：{time_range.get('start', '?')} ~ {time_range.get('end', '?')}　|　**设备**：{eq_names}")
    lines.append("")

    # Key Findings
    findings = payload.get("findings", [])
    lines.append("## 关键发现")
    lines.append("")
    if findings:
        for i, f in enumerate(findings[:5], 1):
            severity = f.get("severity", "info")
            sev_icon = {"critical": "🔴", "warning": "🟡", "high": "🟠", "info": "🔵"}.get(severity, "⚪")
            desc = f.get("description", "")
            lines.append(f"{i}. {sev_icon} **{f.get('metric', '')}**：{desc}")
    else:
        lines.append("监测期间未发现显著异常。")
    lines.append("")

    # Evidence / Detail
    evidence = payload.get("evidence", [])
    if evidence and isinstance(evidence, list) and len(evidence) > 0:
        lines.append("## 分析详情")
        lines.append("")
        if analysis_type == "anomaly":
            lines.append("| 时间 | 指标 | 测量值 | 阈值 | 偏差(%) | 严重等级 | 检测方法 | 异常模式 |")
            lines.append("|------|------|--------|------|---------|----------|----------|----------|")
            for a in evidence[:20]:
                lines.append(
                    f"| {a.get('timestamp', '')} | {a.get('metric_name', '')} | "
                    f"{a.get('value', '')}{a.get('unit', '')} | {a.get('threshold_upper', '-')} | "
                    f"{a.get('deviation_pct', '')}% | {a.get('severity', '')} | "
                    f"{', '.join(a.get('methods', []))} | {a.get('pattern', '')} |"
                )
        elif analysis_type == "trend":
            lines.append("| 指标 | 方向 | 变化率/天 | 波动率 | 置信度 |")
            lines.append("|------|------|-----------|--------|--------|")
            for f_item in findings[:10]:
                lines.append(
                    f"| {f_item.get('metric', '')} | {f_item.get('direction', '')} | "
                    f"{f_item.get('slope', '')} | {f_item.get('volatility', '')} | "
                    f"{f_item.get('confidence', '')} |"
                )
        elif analysis_type == "kpi_dashboard":
            lines.append("| 设备 | 指标 | 当前值 | 目标范围 | 达标 |")
            lines.append("|------|------|--------|----------|------|")
            for k in evidence[:30]:
                compliant = "✅" if k.get("compliant") else "❌"
                lines.append(
                    f"| {k.get('equipment_name', '')} | {k.get('metric_name', '')} | "
                    f"{k.get('value', '')}{k.get('unit', '')} | "
                    f"{k.get('target_min', '')}-{k.get('target_max', '')} | {compliant} |"
                )
        elif analysis_type == "correlation":
            for s in evidence[:5]:
                lines.append(f"- **{s.get('name_a', '')} ↔ {s.get('name_b', '')}**：{s.get('direction', '')} r={s.get('r', '')}（{s.get('strength', '')}相关）")
    lines.append("")

    # Data Quality
    data_quality = payload.get("data_quality", [])
    if data_quality:
        lines.append("## 数据质量说明")
        lines.append("")
        for dq in data_quality:
            lines.append(f"- {dq}")
        lines.append("")

    # Recommendations
    recommendations = payload.get("recommendations", [])
    if recommendations:
        lines.append("## 处置建议")
        lines.append("")
        for i, rec in enumerate(recommendations[:5], 1):
            priority = rec.get("priority", "normal")
            pri_label = {"urgent": "紧急", "important": "重要", "normal": "一般", "observe": "观察"}.get(priority, priority)
            lines.append(f"{i}. [{pri_label}] {rec.get('action', '')}")
        lines.append("")

    return "\n".join(lines)


def write_report(
    payload: dict,
    fmt: str,
    path: Path | None = None,
    chart_images: list[str] | None = None,
    report_type: str = "daily",
) -> Path:
    if fmt not in SUPPORTED_FORMATS:
        raise ValueError(f"Unsupported export format: {fmt}")
    if report_type not in SUPPORTED_REPORT_TYPES:
        raise ValueError(f"Unsupported report type: {report_type}")
    filename = f"{report_type}_report.{fmt}"
    out_path = path or (_output_dir(report_type) / filename)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if report_type == "diagnosis":
        # Lazy import to avoid module-load-time circular dependency
        from export_diagnosis_report import (  # type: ignore[import-not-found]
            render_diagnosis_html,
            render_diagnosis_markdown,
        )

        if fmt == "pdf":
            html = render_diagnosis_html(payload)
            _write_pdf(html, out_path)
        else:
            content = render_diagnosis_markdown(payload)
            out_path.write_text(content, encoding="utf-8")
    elif report_type == "monitoring":
        if fmt == "pdf":
            html = _monitoring_html(payload)
            _write_pdf(html, out_path)
        else:
            content = render_monitoring_markdown(payload)
            out_path.write_text(content, encoding="utf-8")
    elif report_type == "monthly":
        if fmt == "pdf":
            html = render_monthly_html(payload)
            _write_pdf(html, out_path)
        else:
            content = render_monthly_markdown(payload)
            out_path.write_text(content, encoding="utf-8")
    elif report_type == "weekly":
        if fmt == "pdf":
            html = render_weekly_html(payload)
            _write_pdf(html, out_path)
        else:
            content = render_weekly_markdown(payload)
            out_path.write_text(content, encoding="utf-8")
    else:
        if fmt == "pdf":
            html = render_html(payload, chart_images)
            _write_pdf(html, out_path)
        else:
            content = render_markdown(payload, chart_images)
            out_path.write_text(content, encoding="utf-8")
    return out_path


def build_export_result(
    payload: dict,
    fmt: str,
    path: Path | None = None,
    chart_images: list[str] | None = None,
    report_type: str = "daily",
) -> dict:
    out_path = write_report(payload, fmt, path=path, chart_images=chart_images, report_type=report_type)
    filename = out_path.name
    virtual_path = f"/mnt/user-data/outputs/{filename}"
    return {
        "format": fmt,
        "filename": filename,
        "path": str(out_path),
        "artifact_path": str(out_path),
        "present_files_hint": [virtual_path],
    }


def load_payload(path: Path | None = None, report_type: str = "daily") -> dict:
    if path is not None:
        target = path
    else:
        if report_type == "monthly":
            filename = MONTHLY_INPUT_FILENAME
        elif report_type == "weekly":
            filename = WEEKLY_INPUT_FILENAME
        elif report_type == "diagnosis":
            filename = DIAGNOSIS_INPUT_FILENAME
        elif report_type == "monitoring":
            filename = MONITORING_INPUT_FILENAME
        else:
            filename = INPUT_FILENAME
        target = _output_dir(report_type) / filename
    return json.loads(target.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Export report (daily / weekly / monthly)")
    parser.add_argument("--input", default=None, help="Input KPI JSON path")
    parser.add_argument("--format", default="md", choices=sorted(SUPPORTED_FORMATS))
    parser.add_argument("--output", default=None, help="Output file path")
    parser.add_argument("--chart-images", default="", help="JSON array of chart image paths (daily only)")
    parser.add_argument(
        "--report-type",
        default="daily",
        choices=sorted(SUPPORTED_REPORT_TYPES),
        help="Report type (default: daily, preserves legacy behaviour)",
    )
    args = parser.parse_args()

    try:
        payload = (
            load_payload(Path(args.input), report_type=args.report_type)
            if args.input
            else load_payload(report_type=args.report_type)
        )
    except FileNotFoundError as exc:
        print(json.dumps({"error": f"input not found: {exc}"}, ensure_ascii=False))
        return 0
    except json.JSONDecodeError as exc:
        print(json.dumps({"error": f"invalid input JSON: {exc}"}, ensure_ascii=False))
        return 0

    chart_images: list[str] = []
    if args.chart_images and args.report_type == "daily":
        try:
            parsed = json.loads(args.chart_images)
            if isinstance(parsed, list):
                chart_images = [str(p) for p in parsed]
        except json.JSONDecodeError:
            pass

    try:
        result = build_export_result(
            payload,
            args.format,
            path=Path(args.output) if args.output else None,
            chart_images=chart_images or None,
            report_type=args.report_type,
        )
    except ImportError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 0
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 0
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
