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

import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


_FONT_CANDIDATES = [
    "/mnt/skills/public/matplotlib/fonts/wqy-microhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
]


def _configure_font() -> None:
    """Register a CJK font so Chinese labels render correctly (no tofu boxes).

    Falls back silently if no candidate font exists; the caller's glyph-warning
    test (test_render_line_png) catches the missing-font case.
    """
    from matplotlib import font_manager

    font_path = None
    for candidate in _FONT_CANDIDATES:
        if os.path.exists(candidate):
            font_path = candidate
            break
    if font_path is None:
        return
    font_manager.fontManager.addfont(font_path)
    prop = font_manager.FontProperties(fname=font_path)
    plt.rcParams["font.family"] = prop.get_name()
    plt.rcParams["axes.unicode_minus"] = False


# ---------- Header grid → leaf list ---------- #

def _cell_get(cell: Any, key: str, default: Any = None) -> Any:
    """Read a field from either a dict or a dataclass-like Th cell.

    parse_md produces Th dataclass instances; tests construct plain dicts.
    Normalizing at this boundary keeps build_header_leaves simple.
    """
    if isinstance(cell, dict):
        return cell.get(key, default)
    return getattr(cell, key, default)


def _header_grid(headers: list[list[Any]]) -> list[list[Any | None]]:
    """Expand a 2D thead (with rowspan/colspan) into a dense grid of cell refs.

    Each grid[r][c] is the cell (shared reference) that covers position (r, c),
    or None if the position is uncovered. Cells with rowspan/colspan are
    replicated across all positions they cover.
    """
    grid: list[list[Any | None]] = []
    for r_idx, row in enumerate(headers):
        while len(grid) <= r_idx:
            grid.append([])
        c_idx = 0
        for cell in row:
            while c_idx < len(grid[r_idx]) and grid[r_idx][c_idx] is not None:
                c_idx += 1
            rowspan = int(_cell_get(cell, "rowspan", 1) or 1)
            colspan = int(_cell_get(cell, "colspan", 1) or 1)
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


def build_header_leaves(headers: list[list[Any]]) -> list[LeafHeader]:
    """Build leaf descriptors from a 2D thead. Last row = leaves.

    Each leaf inherits `data_unit` from its parent (colspan/rowspan) cells if
    the leaf itself has no `data_unit`. This matters for currency/percentage
    routing in the renderer — without inheritance, multi-row headers where
    only the parent carries `data-unit` would lose the unit.

    Cells with rowspan that span into the last row (e.g., a leftmost `行社`
    cell with rowspan=2) are NOT leaves — they're parent cells spanning from
    above. We detect them by object identity: if grid[-1][col] is the same
    object as grid[-2][col], the cell was placed via rowspan, not originally
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
            text = (_cell_get(cell, "text") or "").strip()
            if text and text not in seen:
                path.append(text)
                seen.add(text)
            if _cell_get(cell, "data_unit"):
                parent_unit = _cell_get(cell, "data_unit")
        leaf_text = (_cell_get(leaf_cell, "text") or "").strip()
        is_computed = bool(_cell_get(leaf_cell, "is_computed"))
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
        else:
            idx_id = _cell_get(leaf_cell, "idx_id")
            if idx_id:
                period = _cell_get(leaf_cell, "period")
                value_key = f"{idx_id}@{period}" if period else idx_id
        unit = _cell_get(leaf_cell, "data_unit") or parent_unit
        leaves.append(LeafHeader(
            path=path,
            labels=seen,
            value_key=value_key,
            period=_cell_get(leaf_cell, "period"),
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
    """Extract series for line/bar/pie charts.

    Pie must always have len(series.y) == len(series.x): with no series_mode,
    a single Series expects one y per x position. _series_by_metric routes
    this correctly for both x=行社 (1 leaf → per-row values) and x=时期
    (N leaves → aggregate per period, matching C5 behavior).
    """
    y_leaves = resolve_y_axis(spec["y"], leaves)
    x_labels = resolve_x_axis(spec["x"], report, y_leaves, wide_rows)
    if series_mode == "行社":
        return _series_by_org(y_leaves, x_labels, wide_rows, org_names)
    # Both "指标" and None use per-metric routing so pie/line/bar all share
    # the same x-alignment logic. The old _series_single produced 1 y per
    # leaf regardless of x shape — broke pie when x=行社 had 1 leaf.
    return _series_by_metric(y_leaves, x_labels, wide_rows, spec["y"])


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
    else:
        # Default (series="指标" or None): one series per y_left/y_right value.
        # _series_single would aggregate per-leaf and break x=行社 (1 leaf per
        # metric produces 1 y_value, mismatching N orgs on x). _series_by_metric
        # handles both x=行社 (1 leaf → y per org) and x=时期 (multiple leaves
        # → aggregate orgs per leaf).
        bar_series = _series_by_metric(all_left_leaves, x_labels, wide_rows, spec["y_left"], unit=left_unit)
        line_series = _series_by_metric(all_right_leaves, x_labels, wide_rows, spec["y_right"], unit=right_unit)
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


def _to_decimal_or_none(raw: Any) -> Decimal | None:
    if raw in (None, "", "⚠️QUERY_FAILED", "⚠️COMPUTE_FAILED"):
        return None
    if isinstance(raw, Decimal):
        return raw
    try:
        return Decimal(str(raw).replace(",", "").strip())
    except Exception:
        return None


# ---------- Matplotlib plotter (Task 4) ---------- #

def _to_float_or_nan(v: Decimal | None) -> float:
    if v is None:
        return float("nan")
    return float(v)


def render_chart(
    title: str,
    chart_type: str,
    series_list: list[Series],
    out_path: str,
    width: int = 8,
    height: int = 5,
    *,
    bar_count: int = 0,
    bar_colors: list[str] | None = None,
    line_colors: list[str] | None = None,
) -> None:
    """Render a chart to PNG. Dispatches by chart_type.

    - line: one line per series, all on left axis.
    - bar: grouped bars (one group per x position, one bar per series).
    - pie: single series, one slice per x label.
    - bar_line: first `bar_count` series are bars (left axis), the rest are
      lines (right axis). Requires bar_count > 0 (H7 fix).
    """
    _configure_font()
    fig, ax = plt.subplots(figsize=(width, height), constrained_layout=True)

    if chart_type == "line":
        for i, s in enumerate(series_list):
            kw: dict[str, Any] = {}
            if line_colors and i < len(line_colors):
                kw["color"] = line_colors[i]
            ax.plot(s.x, [_to_float_or_nan(y) for y in s.y], marker="o", label=s.name, **kw)
        ax.set_ylabel(series_list[0].unit or "" if series_list else "")
        ax.legend(loc="best")

    elif chart_type == "bar":
        x = series_list[0].x if series_list else []
        x_pos = list(range(len(x)))
        n = len(series_list)
        width_bar = 0.8 / max(n, 1)
        for i, s in enumerate(series_list):
            offset = (i - (n - 1) / 2) * width_bar
            kw = {}
            if bar_colors and i < len(bar_colors):
                kw["color"] = bar_colors[i]
            ax.bar(
                [xi + offset for xi in x_pos],
                [_to_float_or_nan(y) if y is not None else 0.0 for y in s.y],
                width=width_bar, label=s.name, **kw,
            )
        ax.set_xticks(x_pos)
        ax.set_xticklabels([str(v) for v in x])
        ax.set_ylabel(series_list[0].unit or "" if series_list else "")
        ax.legend(loc="best")

    elif chart_type == "bar_line":
        # H7 fix: fail fast if bar_count not provided or zero
        assert bar_count > 0, "bar_line requires bar_count > 0"
        bar_series = series_list[:bar_count]
        line_series = series_list[bar_count:]
        x = bar_series[0].x if bar_series else (line_series[0].x if line_series else [])
        x_pos = list(range(len(x)))
        ax2 = ax.twinx()
        n = len(bar_series)
        width_bar = 0.8 / max(n, 1)
        for i, s in enumerate(bar_series):
            offset = (i - (n - 1) / 2) * width_bar
            kw = {}
            if bar_colors and i < len(bar_colors):
                kw["color"] = bar_colors[i]
            ax.bar(
                [xi + offset for xi in x_pos],
                [_to_float_or_nan(y) if y is not None else 0.0 for y in s.y],
                width=width_bar, label=s.name, **kw,
            )
        ax.set_xticks(x_pos)
        ax.set_xticklabels([str(v) for v in x])
        for i, s in enumerate(line_series):
            kw = {}
            if line_colors and i < len(line_colors):
                kw["color"] = line_colors[i]
            ax2.plot(
                x_pos, [_to_float_or_nan(y) for y in s.y],
                marker="s", linestyle="--", label=s.name, **kw,
            )
        if bar_series and bar_series[0].unit:
            ax.set_ylabel(bar_series[0].unit)
        if line_series and line_series[0].unit:
            ax2.set_ylabel(line_series[0].unit)
        lines1, labels1 = ax.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax.legend(lines1 + lines2, labels1 + labels2, loc="best")

    elif chart_type == "pie":
        s = series_list[0]
        kw = {}
        if bar_colors:
            kw["colors"] = bar_colors
        ax.pie(
            [_to_float_or_nan(y) if y is not None else 0.0 for y in s.y],
            labels=s.x, autopct="%1.1f%%", **kw,
        )

    else:
        raise ValueError(f"unsupported chart type: {chart_type}")

    ax.set_title(title)

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
