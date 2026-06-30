"""ai-report unit conversion: generate DuckDB UPDATE SQL (新写, 硬编码单位字典)."""

from __future__ import annotations

BASIC_FACTORS = {"万元": "/ 10000", "亿元": "/ 100000000"}
COMPUTED_FACTORS = {"%": "* 100"}


def generate_update_sql(headers: list[list], target_table: str = "wide") -> list[str]:
    """Generate DuckDB UPDATE statements that normalize `headers` units to target.

    Basic columns (is_computed=False): 元 is identity (no-op), 万元 → / 10000, 亿元 → / 100000000.
    Computed columns (is_computed=True): % → * 100 (基础列的 % 不换算, 见 Phase 1 政策).

    Column key: for basic, `{idx_id}@{period}` (or just `idx_id` if no period);
    for computed, the column's own `text` name.

    Dedup by column key. Unknown units are silently skipped.
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
