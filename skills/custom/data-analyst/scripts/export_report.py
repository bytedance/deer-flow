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
from pathlib import Path

DEFAULT_OUTPUT_DIR = "/mnt/user-data/outputs"
INPUT_FILENAME = "daily_kpi.json"
SUPPORTED_FORMATS = {"md", "pdf"}

TYPE_DISPLAY = {
    "static_equipment": "静设备",
    "rotating_machinery": "旋转机组",
    "pump": "机泵",
    "reciprocating_machinery": "往复机组",
    "all": "设备",
}


def _output_dir() -> Path:
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


def trend_chart_to_svg(chart: dict) -> str:
    """Convert an ECharts line-chart option dict into an SVG string.

    Returns an empty string if chart has no renderable series data.
    """
    all_series = chart.get("series") or []
    if not all_series:
        return ""

    x_labels = (chart.get("xAxis") or {}).get("data") or [f"{h:02d}:00" for h in range(24)]
    title_text = (chart.get("title") or {}).get("text", "")
    y_name = (chart.get("yAxis") or {}).get("name", "")

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

    def px(i: int) -> float:
        return ML + (i / max(n_points - 1, 1)) * PW

    def py(v: float) -> float:
        return MT + PH * (1 - (v - y_min) / y_range)

    ticks = [y_min + i * y_range / 4 for i in range(5)]

    parts: list[str] = []
    parts.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {SVG_W} {SVG_H}" '
                 f'width="{SVG_W}" height="{SVG_H}" style="background:#fff">')
    parts.append(f'<rect width="{SVG_W}" height="{SVG_H}" fill="#fff"/>')

    if title_text:
        parts.append(f'<text x="{SVG_W / 2}" y="22" text-anchor="middle" '
                     f'font-size="13" font-family="SimSun,Noto Sans SC,sans-serif" fill="#333">'
                     f'{_svg_escape(title_text)}</text>')

    if y_name:
        rx = -(MT + PH // 2)
        parts.append(f'<text transform="rotate(-90)" x="{rx}" y="14" text-anchor="middle" '
                     f'font-size="10" font-family="SimSun,sans-serif" fill="#666">'
                     f'{_svg_escape(y_name)}</text>')

    for t in ticks:
        ty = py(t)
        parts.append(f'<line x1="{ML}" y1="{ty:.1f}" x2="{ML + PW}" y2="{ty:.1f}" '
                     f'stroke="#eee" stroke-width="1"/>')
        parts.append(f'<text x="{ML - 6}" y="{ty + 4:.1f}" text-anchor="end" '
                     f'font-size="10" fill="#666">{t:.2f}</text>')

    show_indices = list(range(0, n_points, max(n_points // 6, 1)))
    if n_points - 1 not in show_indices:
        show_indices.append(n_points - 1)
    for i in show_indices:
        if i < len(x_labels):
            parts.append(f'<text x="{px(i):.1f}" y="{MT + PH + 16}" text-anchor="middle" '
                         f'font-size="10" fill="#666">{_svg_escape(str(x_labels[i]))}</text>')

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
            parts.append(f'<text x="{lx + 24:.1f}" y="{legend_y}" font-size="10" fill="#666">'
                         f'{_svg_escape(name)}</text>')

    parts.append("</svg>")
    return "\n".join(parts)


def _svg_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


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


def render_markdown(payload: dict, chart_images: list[str] | None = None) -> str:
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

    if chart_images:
        embedded = False
        for i, img_path in enumerate(chart_images):
            data_uri = _read_image_as_data_uri(img_path)
            if data_uri:
                if not embedded:
                    lines.append("## 运行趋势")
                    lines.append("")
                    embedded = True
                lines.append(f'<img src="{data_uri}" alt="趋势图{i + 1}" width="760">')
                lines.append("")
        if not embedded:
            trend_chart = payload.get("trend_chart")
            if trend_chart and trend_chart.get("series"):
                svg_str = trend_chart_to_svg(trend_chart)
                if svg_str:
                    b64 = base64.b64encode(svg_str.encode("utf-8")).decode("ascii")
                    lines.append("## 运行趋势")
                    lines.append("")
                    lines.append(f'<img src="data:image/svg+xml;base64,{b64}" alt="运行趋势图" width="760">')
                    lines.append("")
    else:
        trend_chart = payload.get("trend_chart")
        if trend_chart and trend_chart.get("series"):
            svg_str = trend_chart_to_svg(trend_chart)
            if svg_str:
                b64 = base64.b64encode(svg_str.encode("utf-8")).decode("ascii")
                lines.append("## 运行趋势")
                lines.append("")
                lines.append(f'<img src="data:image/svg+xml;base64,{b64}" alt="运行趋势图" width="760">')
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


def render_html(payload: dict, chart_images: list[str] | None = None) -> str:
    """Render payload as a standalone HTML document with embedded CSS."""
    md = render_markdown(payload, chart_images)
    try:
        import markdown as md_lib
        body = md_lib.markdown(md, extensions=["tables"])
    except ImportError:
        body = "<pre>" + md.replace("&", "&amp;").replace("<", "&lt;") + "</pre>"
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


def write_report(payload: dict, fmt: str, path: Path | None = None, chart_images: list[str] | None = None) -> Path:
    if fmt not in SUPPORTED_FORMATS:
        raise ValueError(f"Unsupported export format: {fmt}")
    out_path = path or (_output_dir() / f"daily_report.{fmt}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "pdf":
        html = render_html(payload, chart_images)
        _write_pdf(html, out_path)
    else:
        content = render_markdown(payload, chart_images)
        out_path.write_text(content, encoding="utf-8")
    return out_path


def build_export_result(payload: dict, fmt: str, path: Path | None = None, chart_images: list[str] | None = None) -> dict:
    out_path = write_report(payload, fmt, path=path, chart_images=chart_images)
    filename = out_path.name
    virtual_path = f"/mnt/user-data/outputs/{filename}"
    return {
        "format": fmt,
        "filename": filename,
        "path": str(out_path),
        "artifact_path": str(out_path),
        "present_files_hint": [virtual_path],
    }


def load_payload(path: Path | None = None) -> dict:
    target = path or (_output_dir() / INPUT_FILENAME)
    return json.loads(target.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Export daily report")
    parser.add_argument("--input", default=None, help="Input KPI JSON path")
    parser.add_argument("--format", default="md", choices=sorted(SUPPORTED_FORMATS))
    parser.add_argument("--output", default=None, help="Output file path")
    parser.add_argument("--chart-images", default="", help="JSON array of chart image paths")
    args = parser.parse_args()

    try:
        payload = load_payload(Path(args.input)) if args.input else load_payload()
    except FileNotFoundError as exc:
        print(json.dumps({"error": f"input not found: {exc}"}, ensure_ascii=False))
        return 0
    except json.JSONDecodeError as exc:
        print(json.dumps({"error": f"invalid input JSON: {exc}"}, ensure_ascii=False))
        return 0

    chart_images: list[str] = []
    if args.chart_images:
        try:
            parsed = json.loads(args.chart_images)
            if isinstance(parsed, list):
                chart_images = [str(p) for p in parsed]
        except json.JSONDecodeError:
            pass

    try:
        result = build_export_result(payload, args.format, path=Path(args.output) if args.output else None, chart_images=chart_images or None)
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
