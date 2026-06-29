from __future__ import annotations

import logging
from collections import defaultdict
from decimal import Decimal
from typing import Any

import duckdb

from ai_report.models import SENTINEL_VALUE

_log = logging.getLogger(__name__)


def _fetch_metric_pivot(
    con: duckdb.DuckDBPyConnection,
    run_id: str,
    table_id: str,
) -> tuple[dict[tuple[str, str, str], Decimal | None], dict[str, str]]:
    """Return (pivot, short_name_by_branch) for ok/parse_failed rows only.

    - pivot: {(idx_id, period_alias, branch_num) -> numeric_value or None}
    - short_name_by_branch: {branch_num -> branch_short_name} for the template
    """
    rows = con.execute("""
        SELECT idx_id, period_alias, branch_num, branch_short_name, numeric_value, status
        FROM metric_facts
        WHERE run_id = ? AND table_id = ? AND status IN ('ok', 'parse_failed')
    """, [run_id, table_id]).fetchall()
    pivot: dict[tuple[str, str, str], Decimal | None] = {}
    short_name_by_branch: dict[str, str] = {}
    for idx_id, period_alias, branch_num, short_name, numeric_value, _status in rows:
        pivot[(idx_id, period_alias, branch_num)] = numeric_value
        if short_name and branch_num not in short_name_by_branch:
            short_name_by_branch[branch_num] = short_name
    return pivot, short_name_by_branch


def _fetch_computed_pivot(con: duckdb.DuckDBPyConnection, run_id: str, table_id: str) -> dict[tuple[str, str], Decimal | None]:
    rows = con.execute("""
        SELECT branch_num, compute_name, numeric_value, status
        FROM computed_facts
        WHERE run_id = ? AND table_id = ? AND status IN ('ok', 'null_input', 'parse_failed')
    """, [run_id, table_id]).fetchall()
    pivot: dict[tuple[str, str], Decimal | None] = {}
    for branch_num, compute_name, numeric_value, _status in rows:
        pivot[(branch_num, compute_name)] = numeric_value
    return pivot


def _render_template(
    table_title: str,
    metric_pivot: dict[tuple[str, str, str], Decimal | None],
    computed_pivot: dict[tuple[str, str], Decimal | None],
    short_name_by_branch: dict[str, str],
) -> str:
    """Build a one-paragraph summary grouped by branch.

    Raises ValueError when the table has no usable data, so the orchestrator
    can apply the failure policy (return SENTINEL_VALUE for continue_with_sentinel,
    propagate for stop_on_failure).
    """
    by_branch: dict[str, list[tuple[str, str, Decimal | None]]] = defaultdict(list)
    for (idx_id, period_alias, branch_num), value in metric_pivot.items():
        by_branch[branch_num].append(("metric", f"{idx_id}@{period_alias}", value))
    for (branch_num, compute_name), value in computed_pivot.items():
        by_branch[branch_num].append(("compute", compute_name, value))

    if not by_branch:
        raise ValueError(f"no usable data for table {table_title!r}")

    lines = [f"{table_title}:"]
    for branch_num in sorted(by_branch.keys()):
        items = by_branch[branch_num]
        ok_values = [v for _, _, v in items if v is not None]
        range_str = (
            f"数值范围 {min(ok_values)}~{max(ok_values)}"
            if ok_values
            else "无有效数值"
        )
        short_name = short_name_by_branch.get(branch_num, "")
        label = f"{short_name}({branch_num})" if short_name else branch_num
        lines.append(f"- 机构 {label}:{range_str}")
        for kind, item_label, value in items:
            if value is None:
                lines.append(f"  - {kind} {item_label}:无值")
            else:
                lines.append(f"  - {kind} {item_label}={value}")
    return "\n".join(lines)


def generate_descriptions(
    con: duckdb.DuckDBPyConnection,
    run_id: str,
    table_failure_policy: dict[str, str] | None = None,
) -> dict[str, str]:
    """Generate description text per table. Failed tables get SENTINEL_VALUE
    unless their description_failure_policy is "stop_on_failure", in which
    case the exception propagates."""
    table_failure_policy = table_failure_policy or {}
    tables = con.execute("""
        SELECT table_id, table_title, description_failure_policy
        FROM run_tables
        WHERE run_id = ?
        ORDER BY section_id, table_order, table_id
    """, [run_id]).fetchall()
    descriptions: dict[str, str] = {}
    for table_id, table_title, policy in tables:
        try:
            metric_pivot, short_name_by_branch = _fetch_metric_pivot(con, run_id, table_id)
            computed_pivot = _fetch_computed_pivot(con, run_id, table_id)
            descriptions[table_id] = _render_template(
                table_title, metric_pivot, computed_pivot, short_name_by_branch
            )
        except Exception as exc:
            effective_policy = policy or table_failure_policy.get(table_id, "continue_with_sentinel")
            if effective_policy == "stop_on_failure":
                _log.exception("Description generation failed for %s", table_id)
                raise RuntimeError(f"description generation failed for table {table_id}: {exc}") from exc
            _log.warning("Description generation failed for %s; using sentinel", table_id)
            descriptions[table_id] = SENTINEL_VALUE
    return descriptions
