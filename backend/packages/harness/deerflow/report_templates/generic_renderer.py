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
    # Also accept the common DSL pattern where ``columns`` is author-supplied
    # ``[{key, label}]`` and the source resolves to ``rows: [dict, ...]``.
    columns = props.get("columns")
    data = props.get("data")
    rows = props.get("rows")

    if columns is None and isinstance(rows, list):
        # Pure rows-only path — infer columns from first row's keys.
        if not rows:
            return ["_(empty table)_"]
        columns = list(rows[0].keys())
        data = [list(r.get(c, "") for c in columns) for r in rows]
    elif isinstance(columns, list) and data is None and isinstance(rows, list):
        # Author-supplied columns + rows: project each row into a list using
        # column ``key`` (when columns is a list of label dicts) or the column
        # name (when columns is a list of strings).
        if not rows:
            return ["_(empty table)_"]
        column_keys = [
            c.get("key", c.get("label", "")) if isinstance(c, dict) else str(c)
            for c in columns
        ]
        column_labels = [
            c.get("label", c.get("key", "")) if isinstance(c, dict) else str(c)
            for c in columns
        ]
        data = [[r.get(k, "") for k in column_keys] for r in rows]
        columns = column_labels  # use labels for the rendered header

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
    # Banner-style card (§13.2 human_review_required / data-quality warnings):
    # when props.style is one of {warning, danger, info} we emit a Markdown
    # quote block instead of a bullet so the banner stands out from regular cards.
    if not group and props.get("style") in ("warning", "danger", "info"):
        return _render_banner_card(props)

    # Confidence badge — when the source resolved to a single low/medium/high
    # string (DSL renders confidence with component=card), turn the value into
    # a coloured badge for readability.
    if not group and _looks_like_confidence(props):
        return _render_confidence_badge(props)

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


_BANNER_PREFIX = {"warning": "⚠", "danger": "🛑", "info": "ℹ"}


def _render_banner_card(props: dict[str, Any]) -> list[str]:
    """Render a card with a ``style`` hint as a Markdown quote-block banner.

    Lookup order for banner text:
      1. ``template`` (DSL author-provided literal)
      2. ``value`` (when the source resolved to a single string)
      3. ``title`` (fallback)
    """
    style = props.get("style", "info")
    icon = _BANNER_PREFIX.get(style, "ℹ")
    template = props.get("template")
    if isinstance(template, str) and template.strip():
        text = template
    else:
        value = props.get("value")
        if isinstance(value, str) and value.strip():
            text = value
        else:
            text = props.get("title") or ""
    safe = _safe_str(text)
    return [f"> {icon} {safe}"]


_CONFIDENCE_LEVELS = {"low", "medium", "high"}
_CONFIDENCE_BADGE = {
    "low": "🔴 Low",
    "medium": "🟡 Medium",
    "high": "🟢 High",
}


def _looks_like_confidence(props: dict[str, Any]) -> bool:
    value = props.get("value")
    return isinstance(value, str) and value.lower() in _CONFIDENCE_LEVELS


def _render_confidence_badge(props: dict[str, Any]) -> list[str]:
    value = str(props.get("value", "")).lower()
    badge = _CONFIDENCE_BADGE.get(value, value)
    title = _safe_str(props.get("title", ""))
    if title:
        return [f"- **{title}**: {badge}"]
    return [f"- {badge}"]


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
