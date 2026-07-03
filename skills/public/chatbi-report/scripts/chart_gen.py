"""chart_gen.py — resolve chart specs against wide.json and (in later tasks) render PNGs.

Step 8c.5 chart generation pipeline:
  1. parse_md produces parsed.json with `chart_specs` per report.
  2. compute.py produces wide.json (flat rows with `{idx_id}@{period}` keys + computed cols).
  3. chart_gen resolves each spec's x/y axes against the parsed header leaves,
     extracts series from wide rows, and (Task 4) renders PNG via matplotlib.
  4. chart_gen writes <stem>.charts.json manifest (Task 5).

This module's public surface (Task 3): build_header_leaves, resolve_x_axis,
resolve_y_axis, extract_series. The matplotlib plotter (Task 4) and CLI
(Task 5) are added in subsequent commits.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any


# ---------- Header grid → leaf list ---------- #

def _header_grid(headers: list[list[dict]]) -> list[list[dict | None]]:
    """Expand a 2D thead (with rowspan/colspan) into a dense grid of cell refs.

    Each grid[r][c] is the dict (shared reference) that covers position (r, c),
    or None if the position is uncovered. Cells with rowspan/colspan are
    replicated across all positions they cover.
    """
    grid: list[list[dict | None]] = []
    for r_idx, row in enumerate(headers):
        while len(grid) <= r_idx:
            grid.append([])
        c_idx = 0
        for cell in row:
            while c_idx < len(grid[r_idx]) and grid[r_idx][c_idx] is not None:
                c_idx += 1
            rowspan = int(cell.get("rowspan", 1) or 1)
            colspan = int(cell.get("colspan", 1) or 1)
            for rr in range(r_idx, r_idx + rowspan):
                while len(grid) <= rr:
                    grid.append([])
                while len(grid[rr]) < c_idx + colspan:
                    grid[rr].append(None)
            for rr in range(r_idx, r_idx + rowspan):
                for cc in range(c_idx, c_idx + colspan):
                    grid[rr][cc] = cell
            c_idx += colspan
    width = max((len(row) for row in grid), default=0)
    for row in grid:
        while len(row) < width:
            row.append(None)
    return grid


@dataclass
class LeafHeader:
    path: list[str]
    labels: set[str]
    value_key: str | None
    period: str | None
    unit: str | None


def build_header_leaves(headers: list[list[dict]]) -> list[LeafHeader]:
    """Build leaf descriptors from a 2D thead. Last row = leaves.

    Each leaf inherits `data_unit` from its parent (colspan/rowspan) cells if
    the leaf itself has no `data_unit`. This matters for currency/percentage
    routing in the renderer — without inheritance, multi-row headers where
    only the parent carries `data-unit` would lose the unit.

    Cells with rowspan that span into the last row (e.g., a leftmost `行社`
    cell with rowspan=2) are NOT leaves — they're parent cells spanning from
    above. We detect them by object identity: if grid[-1][col] is the same
    dict as grid[-2][col], the cell was placed via rowspan, not originally
    in the last row, so skip it.

    C1 fix: computed columns (`{{name}}`) get their braces stripped so
    `y轴: 2024利润同比` (user-written, no braces) matches the leaf.
    """
    grid = _header_grid(headers)
    if not grid:
        return []
    last_row = grid[-1]
    parent_row = grid[-2] if len(grid) > 1 else []
    leaves: list[LeafHeader] = []
    for col_idx, leaf_cell in enumerate(last_row):
        if leaf_cell is None:
            continue
        # Skip rowspan parents: same cell object appears in the row above.
        if col_idx < len(parent_row) and parent_row[col_idx] is leaf_cell:
            continue
        path: list[str] = []
        seen: set[str] = set()
        parent_unit: str | None = None
        for row in grid[:-1]:
            cell = row[col_idx]
            if cell is None:
                continue
            text = (cell.get("text") or "").strip()
            if text and text not in seen:
                path.append(text)
                seen.add(text)
            if cell.get("data_unit"):
                parent_unit = cell.get("data_unit")
        leaf_text = (leaf_cell.get("text") or "").strip()
        is_computed = bool(leaf_cell.get("is_computed"))
        if is_computed and leaf_text.startswith("{{"):
            display_name = leaf_text.strip("{}")
        else:
            display_name = leaf_text
        if display_name:
            path.append(display_name)
            seen.add(display_name)
        value_key: str | None = None
        if is_computed:
            value_key = display_name
        elif leaf_cell.get("idx_id"):
            period = leaf_cell.get("period")
            value_key = f"{leaf_cell['idx_id']}@{period}" if period else leaf_cell["idx_id"]
        unit = leaf_cell.get("data_unit") or parent_unit
        leaves.append(LeafHeader(
            path=path,
            labels=seen,
            value_key=value_key,
            period=leaf_cell.get("period"),
            unit=unit,
        ))
    return leaves


# ---------- Axis resolvers ---------- #

def resolve_y_axis(y_label: str, leaves: list[LeafHeader]) -> list[LeafHeader]:
    """Resolve a y-axis Chinese label to 1..N leaves.

    Match priority:
      1. Exact unique match on labels (leaf text or stripped computed name).
      2. Parent header match (label appears in path[:-1]) — expands a colspan
         parent to all its leaf children.
      3. Ambiguous label match → raise.
      4. No match → raise.
    """
    y_label = y_label.strip()
    by_text = [l for l in leaves if y_label in l.labels]
    if len(by_text) == 1:
        return by_text
    by_path = [l for l in leaves if y_label in l.path[:-1]]
    if by_path:
        return by_path
    if len(by_text) > 1:
        raise ValueError(f"y axis `{y_label}` is ambiguous")
    raise ValueError(f"y axis `{y_label}` not found")


def resolve_x_axis(
    x_label: str,
    report: dict,
    leaves: list[LeafHeader],
    wide_rows: list[dict],
) -> list[str]:
    """Resolve x-axis label to the list of x positions.

    Supported labels:
      - `时期`: distinct periods from leaves, ordered by report.time_info.
      - `行社` / `机构`: org short names from wide rows (one per row).
    """
    x_label = x_label.strip()
    if x_label == "时期":
        periods = [l.period for l in leaves if l.period]
        time_info = report.get("time_info", [])
        return sorted(set(periods), key=lambda p: time_info.index(p) if p in time_info else -1)
    if x_label in {"行社", "机构"}:
        org_names = {o["branch_num"]: o["branch_short_name"] for o in report.get("org_contexts", [])}
        return [org_names.get(str(r.get("branch_num", "")), str(r.get("branch_num", ""))) for r in wide_rows]
    raise ValueError(f"x axis `{x_label}` not supported")


# ---------- Series extraction ---------- #

@dataclass
class Series:
    name: str
    x: list[str]
    y: list[Decimal | None]
    unit: str | None


@dataclass
class ResolvedChart:
    """C6 fix: explicit bar_count instead of inferring via len//2.

    For single-axis charts (line/bar/pie), bar_count=0.
    For bar_line, bar_count = number of bar series (the first bar_count of
    series_list are bars; the rest are lines).
    """
    series_list: list[Series]
    bar_count: int = 0


def _aggregate_mean(values: list[Decimal | None]) -> Decimal | None:
    """C4/C5 fix: aggregate multi-org values via mean instead of dropping."""
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    return sum(vals) / len(vals)


def extract_series(spec: dict, report: dict, wide_rows: list[dict]) -> ResolvedChart:
    """Extract series from a chart spec. Dispatches by chart type and series mode.

    Series modes:
      - "行社": one series per org row
      - "指标": one series per y-axis value (aggregates org data)
      - None: single aggregated series
    """
    leaves = build_header_leaves(report.get("headers", []))
    chart_type = spec.get("type")
    series_mode = spec.get("series")
    org_names = {o["branch_num"]: o["branch_short_name"] for o in report.get("org_contexts", [])}

    if chart_type == "bar_line":
        bar_series, line_series = _extract_bar_line_series(
            spec, report, leaves, wide_rows, series_mode, org_names)
        return ResolvedChart(series_list=bar_series + line_series, bar_count=len(bar_series))
    series = _extract_single_axis_series(spec, report, leaves, wide_rows, series_mode, org_names)
    return ResolvedChart(series_list=series, bar_count=0)


def _extract_single_axis_series(spec, report, leaves, wide_rows, series_mode, org_names):
    """Extract series for line/bar/pie charts."""
    y_leaves = resolve_y_axis(spec["y"], leaves)
    x_labels = resolve_x_axis(spec["x"], report, y_leaves, wide_rows)
    if series_mode == "行社":
        return _series_by_org(y_leaves, x_labels, wide_rows, org_names)
    if series_mode == "指标":
        return _series_by_metric(y_leaves, x_labels, wide_rows, spec["y"])
    return _series_single(y_leaves, x_labels, wide_rows, spec["y"])


def _extract_bar_line_series(spec, report, leaves, wide_rows, series_mode, org_names):
    """Extract dual-axis series for bar_line chart. Returns (bar_series, line_series)."""
    all_left_leaves: list[LeafHeader] = []
    for y_val in spec["y_left"]:
        all_left_leaves.extend(resolve_y_axis(y_val, leaves))
    all_right_leaves: list[LeafHeader] = []
    for y_val in spec["y_right"]:
        all_right_leaves.extend(resolve_y_axis(y_val, leaves))
    x_labels = resolve_x_axis(spec["x"], report, all_left_leaves, wide_rows)

    left_unit = spec.get("left_unit") or (all_left_leaves[0].unit if all_left_leaves else None)
    right_unit = spec.get("right_unit") or (all_right_leaves[0].unit if all_right_leaves else None)

    if series_mode == "行社":
        bar_series = _series_by_org(all_left_leaves, x_labels, wide_rows, org_names, unit=left_unit)
        line_series = _series_by_org(all_right_leaves, x_labels, wide_rows, org_names, unit=right_unit)
    elif series_mode == "指标":
        bar_series = _series_by_metric(all_left_leaves, x_labels, wide_rows, spec["y_left"], unit=left_unit)
        line_series = _series_by_metric(all_right_leaves, x_labels, wide_rows, spec["y_right"], unit=right_unit)
    else:
        bar_series = _series_single(all_left_leaves, x_labels, wide_rows, ", ".join(spec["y_left"]), unit=left_unit)
        line_series = _series_single(all_right_leaves, x_labels, wide_rows, ", ".join(spec["y_right"]), unit=right_unit)
    return bar_series, line_series


# ── Series builders (shared across chart types) ──

def _series_by_org(y_leaves, x_labels, wide_rows, org_names, *, unit=None):
    """One series per org row."""
    series_list: list[Series] = []
    for row in wide_rows:
        bn = str(row.get("branch_num", ""))
        name = org_names.get(bn, bn)
        y_values = [_to_decimal_or_none(row.get(lf.value_key)) if lf.value_key else None for lf in y_leaves]
        series_list.append(Series(
            name=name, x=x_labels, y=y_values,
            unit=unit or (y_leaves[0].unit if y_leaves else None),
        ))
    return series_list


def _series_by_metric(y_leaves, x_labels, wide_rows, y_labels, *, unit=None):
    """One series per y-axis value (aggregates org data into x positions).

    - Single leaf per metric (x=行社): y_values[i] = wide_rows[i][leaf.value_key]
    - Multiple leaves per metric (x=时期): y_values[i] = mean(org values for leaf_i)
    """
    series_list: list[Series] = []
    y_label_list = y_labels if isinstance(y_labels, list) else [y_labels]
    for label in y_label_list:
        metric_leaves = [lf for lf in y_leaves if label in lf.labels]
        if not metric_leaves:
            continue
        if len(metric_leaves) == 1:
            lf = metric_leaves[0]
            y_values = [_to_decimal_or_none(r.get(lf.value_key)) if lf.value_key else None for r in wide_rows]
        else:
            y_values = []
            for lf in metric_leaves:
                vals = [_to_decimal_or_none(r.get(lf.value_key)) if lf.value_key else None for r in wide_rows]
                y_values.append(_aggregate_mean(vals))
        series_list.append(Series(
            name=label, x=x_labels, y=y_values,
            unit=unit or (metric_leaves[0].unit if metric_leaves else None),
        ))
    return series_list


def _series_single(y_leaves, x_labels, wide_rows, name, *, unit=None):
    """Single aggregated series. Multi-org values aggregated via mean."""
    y_values: list[Decimal | None] = []
    for leaf in y_leaves:
        vals = [_to_decimal_or_none(row.get(leaf.value_key)) if leaf.value_key else None for row in wide_rows]
        y_values.append(_aggregate_mean(vals))
    return [Series(
        name=name, x=x_labels, y=y_values,
        unit=unit or (y_leaves[0].unit if y_leaves else None),
    )]


def _to_decimal_or_none(raw: Any) -> Decimal | None:
    if raw in (None, "", "⚠️QUERY_FAILED", "⚠️COMPUTE_FAILED"):
        return None
    if isinstance(raw, Decimal):
        return raw
    try:
        return Decimal(str(raw).replace(",", "").strip())
    except Exception:
        return None
