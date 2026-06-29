from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

import duckdb

from ai_report.models import SENTINEL_VALUE


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _quote_string(value: str) -> str:
    """SQL-safe single-quoted string literal."""
    return "'" + value.replace("'", "''") + "'"


def build_table_frame(con: duckdb.DuckDBPyConnection, run_id: str, table_id: str) -> None:
    pairs = con.execute("""
        SELECT DISTINCT idx_id, period_alias
        FROM metric_facts
        WHERE run_id = ? AND table_id = ?
        ORDER BY idx_id, period_alias
    """, [run_id, table_id]).fetchall()
    select_parts = ["branch_num", "max(branch_short_name) AS branch_short_name"]
    for idx_id, period_alias in pairs:
        col_name = f"{idx_id}@{period_alias}"
        select_parts.append(
            "max(CASE WHEN idx_id = {idx!r} AND period_alias = {period!r} THEN numeric_value END) AS {alias}".format(
                idx=idx_id,
                period=period_alias,
                alias=_quote(col_name),
            )
        )
    # DuckDB does not accept prepared parameters inside CREATE VIEW statements,
    # so run_id / table_id must be inlined as quoted string literals.
    sql = """
        CREATE OR REPLACE TEMP VIEW table_frame AS
        SELECT {select_list}
        FROM metric_facts
        WHERE run_id = {run_id_lit} AND table_id = {table_id_lit}
        GROUP BY branch_num
    """.format(
        select_list=", ".join(select_parts),
        run_id_lit=_quote_string(run_id),
        table_id_lit=_quote_string(table_id),
    )
    con.execute(sql)


def execute_computes(
    con: duckdb.DuckDBPyConnection,
    run_id: str,
    table_id: str,
    computes: list[dict[str, Any]],
    compute_failure_policy: str = "stop_on_failure",
) -> None:
    """Execute each approved compute_sql and write computed_facts.

    On compute_sql error:
    - "stop_on_failure" (default): raise and abort the run.
    - "continue_with_sentinel": write one computed_facts row per branch with
      raw_value=SENTINEL_VALUE ("—") and status="compute_failed" so downstream
      rendering still has cells to display.
    """
    for compute in computes:
        try:
            result = con.execute(compute["compute_sql"])
        except Exception as exc:
            if compute_failure_policy == "stop_on_failure":
                raise RuntimeError(
                    f"compute_sql failed for {compute['compute_name']} on table {table_id}: {exc}"
                ) from exc
            _write_compute_failure_for_all_branches(con, run_id, table_id, compute, str(exc))
            continue

        names = [d[0] for d in result.description]
        if "branch_num" not in names:
            raise ValueError(f"compute_sql must return branch_num for {compute['compute_name']}")
        rows = [dict(zip(names, row)) for row in result.fetchall()]
        for row in rows:
            for name, value in row.items():
                if name == "branch_num":
                    continue
                if value is None:
                    numeric_value = None
                    raw_value = SENTINEL_VALUE
                    status = "null_input"
                else:
                    try:
                        numeric_value = Decimal(str(value))
                        raw_value = str(value)
                        status = "ok"
                    except (InvalidOperation, ValueError):
                        numeric_value = None
                        raw_value = str(value)
                        status = "parse_failed"
                con.execute("""
                    INSERT OR REPLACE INTO computed_facts(
                      run_id, table_id, branch_num, compute_name, value,
                      numeric_value, status, error_message
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
                """, [
                    run_id,
                    table_id,
                    str(row["branch_num"]),
                    name,
                    raw_value,
                    numeric_value,
                    status,
                ])


def _write_compute_failure_for_all_branches(
    con: duckdb.DuckDBPyConnection,
    run_id: str,
    table_id: str,
    compute: dict[str, Any],
    error_message: str,
) -> None:
    """For continue_with_sentinel policy: write one compute_failed row per branch."""
    branch_rows = con.execute(
        "SELECT DISTINCT branch_num FROM metric_facts WHERE run_id = ? AND table_id = ?",
        [run_id, table_id],
    ).fetchall()
    for (branch_num,) in branch_rows:
        con.execute("""
            INSERT OR REPLACE INTO computed_facts(
              run_id, table_id, branch_num, compute_name, value,
              numeric_value, status, error_message
            ) VALUES (?, ?, ?, ?, ?, NULL, 'compute_failed', ?)
        """, [
            run_id,
            table_id,
            branch_num,
            compute["compute_name"],
            SENTINEL_VALUE,
            error_message,
        ])
