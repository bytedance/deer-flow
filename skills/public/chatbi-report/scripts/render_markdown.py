"""Render the backfilled Markdown report (`report.md`).

- 输出 HTML `<table>`，保留多级表头的 `rowspan`/`colspan` 与 data-* 属性。
- 表头显示中文名与单位，不追加 SQLBot idx_id。
- 若 report 挂载 `description_text`，在 report heading 与 table 之间渲染描述段。
"""
from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path
from typing import Any

from parse_md import ChartSpec, ComputedSpec, OrgContext, Report, ReportDoc, Section, Th
from unit_conversion import convert_unit

COMPUTE_FAILURE_STATUSES = {
    "compute_smoke_failed",
    "compute_validation_failed",
    "compute_codegen_failed",
    "compute_base_missing",
}


def doc_from_dict(d: dict[str, Any]) -> ReportDoc:
    sections: list[Section] = []
    for sec in d.get("sections", []):
        reports: list[Report] = []
        for rep in sec.get("reports", []):
            headers = [
                [
                    Th(
                        text=c["text"],
                        is_indicator=c["is_indicator"],
                        is_computed=c["is_computed"],
                        idx_id=c.get("idx_id"),
                        data_unit=c.get("data_unit"),
                        period=c.get("period"),
                        rowspan=c.get("rowspan"),
                        colspan=c.get("colspan"),
                    )
                    for c in row
                ]
                for row in rep.get("headers", [])
            ]
            reports.append(Report(
                title=rep["title"],
                org_contexts=[OrgContext(**o) for o in rep.get("org_contexts", [])],
                time_info=rep.get("time_info", []),
                headers=headers,
                data_rows=rep.get("data_rows", []),
                computed_specs=[
                    ComputedSpec(name=s["name"], prompt=s["prompt"], examples=s.get("examples", []))
                    for s in rep.get("computed_specs", [])
                ],
                description_prompt=rep.get("description_prompt"),
                chart_specs=[
                    ChartSpec(
                        标题=s["标题"],
                        类型=s["类型"],
                        x轴=s["x轴"],
                        y轴=s.get("y轴"),
                        y轴左=s.get("y轴左"),
                        y轴右=s.get("y轴右"),
                        系列=s.get("系列"),
                        单位=s.get("单位"),
                        左轴单位=s.get("左轴单位"),
                        右轴单位=s.get("右轴单位"),
                        条形配色=s.get("条形配色"),
                        折线配色=s.get("折线配色"),
                        输出=s.get("输出"),
                    )
                    for s in rep.get("chart_specs", [])
                ],
            ))
        sections.append(Section(title=sec.get("title", ""), reports=reports))
    return ReportDoc(title=d.get("title", ""), sections=sections, all_idx_ids=set(d.get("all_idx_ids", [])))


def normalize_wide_by_report(doc: ReportDoc, payload: Any) -> list[list[dict]]:
    if not isinstance(payload, list):
        return []
    if not payload:
        return [[]]
    if isinstance(payload[0], list):
        return payload
    org_names: dict[str, str] = {}
    first_report = next((rep for sec in doc.sections for rep in sec.reports), None)
    if first_report:
        org_names = {o.branch_num: o.branch_short_name for o in first_report.org_contexts}
        data_dt = "-".join(first_report.time_info)
    else:
        data_dt = ""
    rows: list[dict] = []
    for raw in payload:
        if not isinstance(raw, dict):
            continue
        cells = {k: v for k, v in raw.items() if k not in {"branch_num", "org_ecd", "data_dt", "cells", "raw_cells"}}
        if isinstance(raw.get("cells"), dict):
            cells.update(raw["cells"])
        branch_num = str(raw.get("branch_num", ""))
        rows.append({
            "data_dt": str(raw.get("data_dt", data_dt)),
            "org_ecd": str(raw.get("org_ecd") or org_names.get(branch_num, branch_num)),
            "branch_num": branch_num,
            "cells": cells,
            "raw_cells": raw.get("raw_cells", cells),
        })
    return [rows]


def attach_description_files(doc: ReportDoc, descriptions_dir: str | None, stem: str | None = None) -> None:
    if not descriptions_dir:
        return
    base = Path(descriptions_dir)
    report_idx = 0
    for section in doc.sections:
        for report in section.reports:
            candidates = []
            if stem:
                candidates.append(base / f"{stem}.description.report-{report_idx}.txt")
            candidates.append(base / f"description.report-{report_idx}.txt")
            for path in candidates:
                if path.exists():
                    text = path.read_text(encoding="utf-8").strip()
                    report.description_text = text if text else "⚠️DESCRIPTION_FAILED"
                    break
            report_idx += 1


def _value_key(th: Th) -> str | None:
    if th.is_computed:
        return th.text.strip("{}") if th.text.startswith("{{") else th.text
    if th.idx_id:
        return f"{th.idx_id}@{th.period}" if th.period else th.idx_id
    return None


def _html_attrs(th: Th) -> str:
    attrs: list[tuple[str, str]] = []
    if th.rowspan is not None:
        attrs.append(("rowspan", str(th.rowspan)))
    if th.colspan is not None:
        attrs.append(("colspan", str(th.colspan)))
    if th.idx_id:
        attrs.append(("data-idx", th.idx_id))
    if th.data_unit is not None:
        attrs.append(("data-unit", th.data_unit))
    if th.period is not None:
        attrs.append(("data-period", th.period))
    return "".join(f' {name}="{html.escape(value, quote=True)}"' for name, value in attrs)


def _header_text(th: Th, compute_status: dict[str, str], wide_rows: list[dict]) -> str:
    if th.is_computed:
        name = th.text.strip("{}") if th.text.startswith("{{") else th.text
        label = f"{name}"
        if compute_status.get(name) in COMPUTE_FAILURE_STATUSES:
            label = f"{label} ⚠️COMPUTE_FAILED"
        if th.data_unit:
            label = f"{label} ({th.data_unit})"
        return label
    label = th.text
    if th.data_unit:
        label = f"{label} ({th.data_unit})"
    key = _value_key(th)
    if key and any(row.get("cells", {}).get(key) == "⚠️QUERY_FAILED" for row in wide_rows):
        label = f"{label} ⚠️QUERY_FAILED"
    return label


def _header_grid(headers: list[list[Th]]) -> list[list[Th | None]]:
    grid: list[list[Th | None]] = []
    for r_idx, row in enumerate(headers):
        while len(grid) <= r_idx:
            grid.append([])
        c_idx = 0
        for th in row:
            while c_idx < len(grid[r_idx]) and grid[r_idx][c_idx] is not None:
                c_idx += 1
            rowspan = th.rowspan or 1
            colspan = th.colspan or 1
            for rr in range(r_idx, r_idx + rowspan):
                while len(grid) <= rr:
                    grid.append([])
                while len(grid[rr]) < c_idx + colspan:
                    grid[rr].append(None)
            for rr in range(r_idx, r_idx + rowspan):
                for cc in range(c_idx, c_idx + colspan):
                    grid[rr][cc] = th
            c_idx += colspan
    width = max((len(row) for row in grid), default=0)
    for row in grid:
        while len(row) < width:
            row.append(None)
    return grid


def _leaf_columns(headers: list[list[Th]]) -> list[Th]:
    grid = _header_grid(headers)
    return [th for th in grid[-1] if th is not None] if grid else []


def _cell_value(th: Th, row: dict) -> str:
    key = _value_key(th)
    if key:
        raw = str(row.get("cells", {}).get(key, "—"))
        if raw == "—":
            return raw
        # Apply unit conversion and formatting
        data_unit = th.data_unit
        if data_unit == "%":
            try:
                v = convert_unit(raw, "%")
                return f"{v:.2f}%"
            except Exception:
                return raw
        elif data_unit in ("万元", "亿元", "元"):
            # Phase 1: raw data is already in the display unit, just format
            try:
                from decimal import Decimal, InvalidOperation
                v = Decimal(raw.replace(",", "").strip())
                if data_unit == "万元":
                    return f"{v:,.2f}"
                elif data_unit == "亿元":
                    return f"{v:,.4f}"
                else:
                    return f"{v:,.2f}"
            except Exception:
                return raw
        return raw
    label = (th.text or "").strip()
    if label in {"季度", "时期", "日期", "period"}:
        return str(row.get("data_dt", ""))
    if label in {"机构", "行社", "分行", "网点", "org"}:
        return str(row.get("org_ecd", ""))
    return ""


def _render_table(report: Report, wide_rows: list[dict], compute_status: dict[str, str]) -> list[str]:
    lines = ["<table>", "  <thead>"]
    for header_row in report.headers:
        lines.append("    <tr>")
        for th in header_row:
            label = _header_text(th, compute_status, wide_rows)
            lines.append(f"      <th{_html_attrs(th)}>{html.escape(label)}</th>")
        lines.append("    </tr>")
    lines.extend(["  </thead>", "  <tbody>"])
    leaves = _leaf_columns(report.headers)
    for row in wide_rows:
        lines.append("    <tr>")
        for th in leaves:
            lines.append(f"      <td>{html.escape(_cell_value(th, row))}</td>")
        lines.append("    </tr>")
    lines.extend(["  </tbody>", "</table>"])
    return lines


def render_markdown(
    doc: ReportDoc,
    wide_by_report: list[list[dict]],
    compute_status: dict,
) -> str:
    lines: list[str] = [f"# {doc.title}", ""]
    ridx = 0
    for section in doc.sections:
        lines.extend([f"## {section.title}", ""])
        for report in section.reports:
            wide_rows = wide_by_report[ridx] if ridx < len(wide_by_report) else []
            ridx += 1
            lines.extend([f"### {report.title}", ""])
            description_text = getattr(report, "description_text", None)
            if description_text:
                lines.extend([str(description_text).strip(), ""])
            if not wide_rows:
                lines.extend(["_(no data rows in this report)_", ""])
                continue
            lines.extend(_render_table(report, wide_rows, compute_status))
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="render_markdown", description=__doc__.splitlines()[0])
    parser.add_argument("--parsed", required=True)
    parser.add_argument("--wide", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--compute-status", default=None)
    parser.add_argument("--descriptions-dir", default=None)
    parser.add_argument("--stem", default=None)
    args = parser.parse_args(argv)

    try:
        parsed = json.loads(Path(args.parsed).read_text(encoding="utf-8"))
        doc = doc_from_dict(parsed)
        wide = normalize_wide_by_report(doc, json.loads(Path(args.wide).read_text(encoding="utf-8")))
        compute_status = json.loads(Path(args.compute_status).read_text(encoding="utf-8")) if args.compute_status else {}
        attach_description_files(doc, args.descriptions_dir, args.stem or Path(args.parsed).name.removesuffix(".parsed.json"))
        Path(args.out).write_text(render_markdown(doc, wide, compute_status), encoding="utf-8")
    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(f"OK: rendered markdown -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
