"""ai-report unit conversion: generate DuckDB UPDATE SQL + Python-side apply_units (新写, 硬编码单位字典).

Phase 1: apply_units uses layout-aware col_sources so multi-row headers with
colspan'd data_unit labels correctly propagate the unit to all leaf columns.
generate_update_sql is kept for external callers but unused by the design
pipeline (it has the same propagate-bug for non-leaf cells; use apply_units).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

# SQL operator strings (for generate_update_sql, kept for back-compat with any external caller)
BASIC_FACTORS = {"万元": "/ 10000", "亿元": "/ 100000000"}
COMPUTED_FACTORS = {"%": "* 100"}

# Numeric factors (for apply_units Python path, preserves Decimal precision — no float)
BASIC_FACTORS_NUMERIC: dict[str, Decimal] = {
    "万元": Decimal("0.0001"),
    "亿元": Decimal("0.00000001"),
}
COMPUTED_FACTORS_NUMERIC: dict[str, Decimal] = {
    "%": Decimal("100"),
}


def _as_dict(th: Any) -> dict:
    if isinstance(th, dict):
        return th
    return {"text": str(th)}


def _span(th: Any, attr: str) -> int:
    th = _as_dict(th)
    n = th.get(attr) or 1
    try:
        return max(1, int(n))
    except (ValueError, TypeError):
        return 1


def _leaf_col_units(headers: list[list[dict]]) -> list[dict | None]:
    """Resolve each logical data column to its source th (with data_unit inherited).

    Same layout pass as render_docx._build_header_layout / render_markdown._build_col_sources:
    col_sources[col_idx] is the th that OWNS that data column (may be a parent
    colspan'd cell carrying the data_unit label). Returns one entry per logical
    column; None entries mean no header covers that column (skip).
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


def _propagate_units(headers: list[list[dict]]) -> list[list[dict]]:
    """Mutate headers_2d in place so every leaf cell with idx_id + period also
    carries the data_unit from the owning parent (colspan'd or sibling) cell.

    Example: header `[Th(BAS_001, colspan=2, data_unit='万元'), Th(BAS_001, period=202602), Th(BAS_001, period=202603)]`
    becomes `[Th(BAS_001, colspan=2, data_unit='万元'), Th(BAS_001, period=202602, data_unit='万元'), Th(BAS_001, period=202603, data_unit='万元')]`
    so apply_units' simple iteration can find the right col_key + unit without
    needing layout state.

    Propagation order:
    1. Same-row sibling with the same idx_id and a data_unit.
    2. Any other row's cell with the same idx_id and a data_unit.
    """
    for header_row in headers:
        for th in header_row:
            if not isinstance(th, dict):
                continue
            idx = th.get("idx_id")
            period = th.get("period")
            unit = th.get("data_unit")
            if not idx or not period or unit:
                continue
            # 1. Same-row sibling with same idx_id + data_unit (covers colspan layouts)
            for sibling in header_row:
                if sibling is th or not isinstance(sibling, dict):
                    continue
                if (
                    sibling.get("idx_id") == idx
                    and sibling.get("data_unit")
                ):
                    th["data_unit"] = sibling["data_unit"]
                    break
            # 2. Walk any other row's cell with same idx_id + data_unit (covers
            #    the wangyi pattern: parent in row 0 with colspan=2 + data_unit,
            #    leaves in row 1 with idx_id + period + no data_unit)
            if not th.get("data_unit"):
                for parent_row in headers:
                    for parent in parent_row:
                        if parent is th or not isinstance(parent, dict):
                            continue
                        if (
                            parent.get("idx_id") == idx
                            and parent.get("data_unit")
                        ):
                            th["data_unit"] = parent["data_unit"]
                            break
                    if th.get("data_unit"):
                        break
    return headers


def generate_update_sql(headers: list[list], target_table: str = "wide") -> list[str]:
    """Generate DuckDB UPDATE statements that normalize `headers` units to target.

    Basic columns (is_computed=False): 元 is identity (no-op), 万元 → / 10000, 亿元 → / 100000000.
    Computed columns (is_computed=True): % → * 100 (基础列的 % 不换算, 见 Phase 1 政策).

    Column key: for basic, `{idx_id}@{period}` (or just `idx_id` if no period);
    for computed, the column's own `text` name.

    Dedup by column key. Unknown units are silently skipped.

    Note: this path does NOT propagate data_unit from colspan'd parent cells
    to leaf cells. For multi-row headers, use apply_units (the Phase 1 path).
    """
    seen: set[str] = set()
    statements: list[str] = []
    for row in headers:
        for th in row:
            unit = getattr(th, "data_unit", None)
            if not unit:
                continue
            if getattr(th, "is_computed", False):
                col_key = th.text
                factor_expr = COMPUTED_FACTORS.get(unit)
            else:
                idx = getattr(th, "idx_id", None)
                period = getattr(th, "period", None)
                if not idx:
                    continue
                col_key = f"{idx}@{period}" if period else idx
                factor_expr = BASIC_FACTORS.get(unit)
            if not factor_expr or col_key in seen:
                continue
            seen.add(col_key)
            statements.append(
                f'UPDATE {target_table} SET "{col_key}" = "{col_key}" {factor_expr};'
            )
    return statements


def apply_units(wide: list[dict], headers: list[list[dict]]) -> list[dict]:
    """Apply unit conversion in Python (Phase 1 path). Pure: returns a new list.

    Why Python-side (not DuckDB UPDATE):
    - Decimal / Decimal preserves banking precision (no float round-trip).
    - No shared-conn / write_lock concerns.
    - headers_2d is dict (from asdict(Th)) — DuckDB UPDATE path uses getattr
      which silently returns None for dicts, so the SQL path was a no-op.

    Layout-aware: for multi-row headers where data_unit sits on a colspan'd
    parent cell (e.g. `<th colspan="2" data-idx="BAS_001" data-unit="万元">`),
    `_propagate_units` first copies the unit down to every leaf cell with the
    same idx_id + period under that parent. The leaf iteration then finds the
    unit on each leaf directly.

    Same conversion rules as generate_update_sql:
    - Basic (is_computed=False): 万元 → /10000, 亿元 → /1e8, 元 → identity (skipped).
    - Computed (is_computed=True): % → *100.
    - Unknown units, non-Decimal cells → silently skipped.

    Returns a new list with converted cells (input unchanged). `headers` is
    NOT mutated — `_propagate_units` operates on a deep-copied structure.
    """
    import copy as _copy
    propagated = _copy.deepcopy(headers)
    propagated = _propagate_units(propagated)
    out: list[dict] = []
    for row in wide:
        new_row = dict(row)
        for header_row in propagated:
            for th in header_row:
                unit = th.get("data_unit")
                if not unit:
                    continue
                if th.get("is_computed"):
                    col_key = th.get("text")
                    factor = COMPUTED_FACTORS_NUMERIC.get(unit)
                else:
                    idx = th.get("idx_id")
                    period = th.get("period")
                    if not idx or not period:
                        # Parent cell (no period) carrying the unit — its leaf
                        # children inherit via _propagate_units and will be
                        # converted there.
                        continue
                    col_key = f"{idx}@{period}"
                    factor = BASIC_FACTORS_NUMERIC.get(unit)
                if not factor:
                    continue
                v = new_row.get(col_key)
                if isinstance(v, Decimal):
                    new_row[col_key] = v * factor
        out.append(new_row)
    return out
