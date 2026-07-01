"""ai-report pure markdown renderer (新写, 借鉴 chatbi-report render_markdown 渲染规则)."""
from __future__ import annotations

import html
from typing import Any


def _as_dict(th: Any) -> dict:
    """Header cells may be plain strings (e.g. '机构') or dicts. Normalize to dict."""
    if isinstance(th, dict):
        return th
    return {"text": str(th)}


def _html_attrs(th: Any) -> str:
    th = _as_dict(th)
    attrs: list[tuple[str, str]] = []
    if th.get("rowspan"):
        attrs.append(("rowspan", str(th["rowspan"])))
    if th.get("colspan"):
        attrs.append(("colspan", str(th["colspan"])))
    if th.get("idx_id"):
        attrs.append(("data-idx", th["idx_id"]))
    if th.get("data_unit"):
        attrs.append(("data-unit", th["data_unit"]))
    if th.get("period"):
        attrs.append(("data-period", th["period"]))
    return "".join(f' {n}="{html.escape(v, quote=True)}"' for n, v in attrs)


def _header_label(th: Any, sentinels: list[str], computed_sentinels: dict) -> str:
    th = _as_dict(th)
    text = th.get("text", "")
    label = text
    if th.get("data_unit"):
        label = f"{label} ({th['data_unit']})"
    if th.get("is_computed"):
        if computed_sentinels.get(text) == "⚠️COMPUTE_FAILED":
            label = f"{label} ⚠️COMPUTE_FAILED"
    else:
        if th.get("idx_id") and th.get("period"):
            key = f"{th['idx_id']}@{th['period']}"
            if key in sentinels:
                label = f"{label} ⚠️QUERY_FAILED"
    return label


_ORG_LABELS = {"机构", "行社", "分行", "网点", "org"}


def _span(th: Any, attr: str) -> int:
    th = _as_dict(th)
    n = th.get(attr) or 1
    try:
        return max(1, int(n))
    except (ValueError, TypeError):
        return 1


def _build_col_sources(headers: list[list[Any]]) -> list[dict | None]:
    """Resolve each logical data column to its leaf th source.

    For multi-row headers (rowspan/colspan), the leaf cell that defines the
    idx_id@period lives on the LAST header row (or the deepest rowspan from
    above). Mirrors the layout logic in render_docx._build_header_layout so
    MD and DOCX render the same logical columns.
    """
    n_hdr_rows = len(headers)
    n_cols = max((sum(_span(th, "colspan") for th in row) for row in headers), default=1)
    occupied = [[False] * n_cols for _ in range(n_hdr_rows)]
    spans: list[tuple[int, int, int, int, dict]] = []
    for r, row in enumerate(headers):
        c = 0
        for th in row:
            while c < n_cols and occupied[r][c]:
                c += 1
            if c >= n_cols:
                break
            rs = _span(th, "rowspan")
            cs = _span(th, "colspan")
            spans.append((r, c, rs, cs, _as_dict(th)))
            for dr in range(rs):
                for dc in range(cs):
                    rr, cc = r + dr, c + dc
                    if rr < n_hdr_rows and cc < n_cols:
                        occupied[rr][cc] = True
            c += cs
    last_r = n_hdr_rows - 1
    col_sources: list[dict | None] = [None] * n_cols
    for col_idx in range(n_cols):
        for r, c, rs, cs, th_d in spans:
            if r == last_r and c <= col_idx < c + cs:
                col_sources[col_idx] = th_d
                break
        if col_sources[col_idx] is not None:
            continue
        for r, c, rs, _cs, th_d in spans:
            if r < last_r and c <= col_idx < c + rs:
                col_sources[col_idx] = th_d
                break
    return col_sources


def _cell_value(th: Any, row: dict) -> str:
    th = _as_dict(th)
    if th.get("is_computed"):
        return str(row.get(th.get("text", ""), "—"))
    if th.get("idx_id") and th.get("period"):
        return str(row.get(f"{th['idx_id']}@{th['period']}", "—"))
    if th.get("text") in _ORG_LABELS:
        return str(row.get("branch_num", ""))
    return ""


def _render_table(report: dict) -> list[str]:
    lines = ["<table>", "  <thead>"]
    sentinels = report.get("sentinels", [])
    computed_sentinels = report.get("computed_sentinels", {})
    header_rows = report.get("headers", [])
    for header_row in header_rows:
        lines.append("    <tr>")
        for th in header_row:
            label = _header_label(th, sentinels, computed_sentinels)
            lines.append(f"      <th{_html_attrs(th)}>{html.escape(label)}</th>")
        lines.append("    </tr>")
    lines.extend(["  </thead>", "  <tbody>"])
    col_sources = _build_col_sources(header_rows) if header_rows else []
    for row in report.get("rows", []):
        lines.append("    <tr>")
        for th_d in col_sources:
            if th_d is None:
                lines.append("      <td></td>")
                continue
            if _as_dict(th_d).get("text") in _ORG_LABELS and not _as_dict(th_d).get("idx_id"):
                lines.append(f"      <td>{html.escape(str(row.get('branch_num', '')))}</td>")
            else:
                lines.append(f"      <td>{html.escape(_cell_value(th_d, row))}</td>")
        lines.append("    </tr>")
    lines.extend(["  </tbody>", "</table>"])
    return lines


def render_markdown(payload: dict[str, Any]) -> str:
    lines: list[str] = [f"# {payload['title']}", ""]
    for section in payload.get("sections", []):
        lines.extend([f"## {section['title']}", ""])
        for report in section.get("reports", []):
            lines.extend([f"### {report['title']}", ""])
            if report.get("description"):
                lines.extend([str(report["description"]).strip(), ""])
            if not report.get("rows"):
                lines.extend(["_(no data rows in this report)_", ""])
                continue
            lines.extend(_render_table(report))
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"