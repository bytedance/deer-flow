"""Phase 0.5 prototype — `render_markdown_generic(payload)`.

Converts a generic ``report_payload.json`` (schema §12.1 of the design) into a
Markdown document. The MVP target is section types ``markdown`` and ``table``;
``card`` / ``card_group`` / ``echart`` / ``image`` are stubbed so the
prototype can later evolve in Phase 4 without changing this surface.

This module is intentionally **independent** of
``skills/custom/data-analyst/scripts/export_report.py`` so that:

1. The Phase 0 spike does not touch the production daily-report renderer.
2. Phase 4 can either inline the production version or call back into this
   helper without forcing an upfront merge.

The output is sanitized at the leaves: every user-supplied string is HTML-escaped
before being emitted into Markdown, so a section with content like
``<script>...`` becomes ``&lt;script&gt;...``. We do **not** strip Markdown
syntax — authors are responsible for keeping section content safe.
"""

from __future__ import annotations

import html
from typing import Any

REPORT_PAYLOAD_SCHEMA_VERSION = "1"


class RenderError(ValueError):
    """Raised when the payload cannot be rendered."""


def render_markdown_generic(payload: dict[str, Any]) -> str:
    """Render a generic report payload as Markdown.

    Args:
        payload: Parsed ``report_payload.json`` matching the §12.1 schema.

    Returns:
        Markdown document as a single string. Always non-empty.

    Raises:
        RenderError: If ``payload`` is missing required keys or contains an
            unknown section component type.
    """
    if not isinstance(payload, dict):
        raise RenderError("payload must be a dict")

    schema_version = payload.get("schema_version")
    if schema_version != REPORT_PAYLOAD_SCHEMA_VERSION:
        raise RenderError(
            f"unsupported schema_version {schema_version!r}; expected {REPORT_PAYLOAD_SCHEMA_VERSION!r}"
        )

    title = _safe_str(payload.get("title", ""))
    sections = payload.get("sections")
    if not isinstance(sections, list):
        raise RenderError("payload.sections must be a list")

    out: list[str] = []
    if title:
        out.append(f"# {title}")
        out.append("")

    template = payload.get("template")
    run = payload.get("run")
    if isinstance(template, dict) and isinstance(run, dict):
        tpl_name = _safe_str(template.get("name", ""))
        tpl_version = template.get("version", "")
        generated_at = _safe_str(run.get("generated_at", ""))
        meta_parts = []
        if tpl_name:
            meta_parts.append(f"模板：`{tpl_name}` v{tpl_version}")
        if generated_at:
            meta_parts.append(f"生成时间：{generated_at}")
        if meta_parts:
            out.append("> " + " ｜ ".join(meta_parts))
            out.append("")

    for idx, section in enumerate(sections):
        if not isinstance(section, dict):
            raise RenderError(f"sections[{idx}] must be a dict")
        out.extend(_render_section(idx, section))
        out.append("")

    return "\n".join(out).rstrip() + "\n"


# ---------------------------------------------------------------------------
# Section dispatch
# ---------------------------------------------------------------------------


def _render_section(idx: int, section: dict[str, Any]) -> list[str]:
    component = section.get("component")
    title = _safe_str(section.get("title", ""))
    props = section.get("props") or {}
    if not isinstance(props, dict):
        raise RenderError(f"sections[{idx}].props must be a dict")

    lines: list[str] = []
    if title:
        lines.append(f"## {title}")
        lines.append("")

    if component == "markdown":
        lines.extend(_render_markdown(props))
    elif component == "table":
        lines.extend(_render_table(props))
    elif component in ("card", "card_group"):
        lines.extend(_render_cards(props, group=component == "card_group"))
    elif component == "echart":
        lines.extend(_render_echart_placeholder(props))
    elif component == "image":
        lines.extend(_render_image(props))
    else:
        raise RenderError(f"sections[{idx}].component={component!r} not supported")

    return lines


def _render_markdown(props: dict[str, Any]) -> list[str]:
    content = props.get("content", "")
    if isinstance(content, list):
        return [_safe_str(item) for item in content]
    return [_safe_str(content)]


def _render_table(props: dict[str, Any]) -> list[str]:
    # Accept either {columns: [...], data: [...]} or [rows...] (object[]).
    columns = props.get("columns")
    data = props.get("data")
    if columns is None and isinstance(props.get("rows"), list):
        rows = props["rows"]
        if not rows:
            return ["_(empty table)_"]
        columns = list(rows[0].keys())
        data = [list(r.get(c, "") for c in columns) for r in rows]
    if not isinstance(columns, list) or not isinstance(data, list):
        raise RenderError("table props must contain columns:list and data:list")
    if not columns:
        return ["_(empty table)_"]

    header_cells = " | ".join(_safe_str(c) for c in columns)
    separator = " | ".join(["---"] * len(columns))
    lines = [f"| {header_cells} |", f"| {separator} |"]
    for row in data:
        if not isinstance(row, list):
            raise RenderError("each table data row must be a list")
        cells = " | ".join(_safe_str(cell) for cell in row)
        lines.append(f"| {cells} |")
    return lines


def _render_cards(props: dict[str, Any], *, group: bool) -> list[str]:
    if group:
        items = props.get("items") or props.get("cards") or []
    else:
        items = [props]
    if not isinstance(items, list):
        raise RenderError("card_group items must be a list")
    lines: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            raise RenderError("card items must be dicts")
        item_title = _safe_str(item.get("title", ""))
        value = _safe_str(item.get("value", ""))
        description = _safe_str(item.get("description", ""))
        if item_title:
            lines.append(f"- **{item_title}**: {value}" if value else f"- **{item_title}**")
        elif value:
            lines.append(f"- {value}")
        if description:
            lines.append(f"  {description}")
    if not lines:
        lines.append("_(no cards)_")
    return lines


def _render_echart_placeholder(props: dict[str, Any]) -> list[str]:
    # Phase 0 prototype: do not invoke trend_chart_to_svg yet (lives in
    # data-analyst skill). Just record that the chart is present.
    chart_type = ""
    option = props.get("option")
    if isinstance(option, dict):
        series = option.get("series") or []
        if series and isinstance(series, list) and isinstance(series[0], dict):
            chart_type = _safe_str(series[0].get("type", ""))
    msg = f"_[echart chart: {chart_type}]_" if chart_type else "_[echart chart]_"
    return [msg]


def _render_image(props: dict[str, Any]) -> list[str]:
    alt = _safe_str(props.get("alt", "image"))
    src = _safe_str(props.get("src", ""))
    if not src:
        return ["_(image missing src)_"]
    return [f"![{alt}]({src})"]


# ---------------------------------------------------------------------------
# Sanitisation
# ---------------------------------------------------------------------------


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return html.escape(value, quote=False)
    return html.escape(str(value), quote=False)
