"""
Data Pipeline Script.

Executes a declarative ETL pipeline defined in a JSON spec file.
Uses DuckDB for all data operations: load → clean → transform → merge → export.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time

try:
    import duckdb
except ImportError:
    subprocess.run([sys.executable, "-m", "pip", "install", "duckdb", "-q"], check=True)
    import duckdb

try:
    import openpyxl  # noqa: F401
except ImportError:
    subprocess.run([sys.executable, "-m", "pip", "install", "openpyxl", "-q"], check=True)


# ---------------------------------------------------------------------------
# Pipeline action handlers
# ---------------------------------------------------------------------------


def action_load_csv(con: duckdb.DuckDBPyConnection, step: dict) -> str:
    """Load a CSV file into a DuckDB table."""
    file_path = step["file"]
    table_name = step["as"]
    con.execute(f"CREATE TABLE \"{table_name}\" AS SELECT * FROM read_csv_auto('{file_path}')")
    cnt = con.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0]
    return f"load_csv → {table_name} ({cnt:,} rows)"


def action_load_excel(con: duckdb.DuckDBPyConnection, step: dict) -> str:
    """Load an Excel file (all sheets) into DuckDB tables."""
    import openpyxl

    file_path = step["file"]
    base_name = step["as"]
    con.execute("INSTALL spatial; LOAD spatial;")

    wb = openpyxl.load_workbook(file_path, read_only=True)
    sheets = wb.sheetnames
    wb.close()

    loaded = []
    for sheet in sheets:
        safe_name = f"{base_name}_{re.sub(r'[^\\w]', '_', sheet)}"
        con.execute(f"CREATE TABLE \"{safe_name}\" AS SELECT * FROM st_read('{file_path}', layer = '{sheet}', open_options = ['HEADERS=FORCE', 'FIELD_TYPES=AUTO'])")
        cnt = con.execute(f'SELECT COUNT(*) FROM "{safe_name}"').fetchone()[0]
        loaded.append(f"{safe_name} ({cnt:,} rows)")

    return f"load_excel → {', '.join(loaded)}"


def action_load_json(con: duckdb.DuckDBPyConnection, step: dict) -> str:
    """Load a JSON file (array of objects) into a DuckDB table."""
    file_path = step["file"]
    table_name = step["as"]
    con.execute(f"CREATE TABLE \"{table_name}\" AS SELECT * FROM read_json_auto('{file_path}', format='array_of_objects')")
    cnt = con.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0]
    return f"load_json → {table_name} ({cnt:,} rows)"


def action_drop_nulls(con: duckdb.DuckDBPyConnection, step: dict) -> str:
    """Drop rows with null values in specified columns."""
    table = step["table"]
    columns = step["columns"]
    before = con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]

    null_checks = " AND ".join(f'"{c}" IS NOT NULL' for c in columns)
    con.execute(f'CREATE OR REPLACE TABLE "{table}" AS SELECT * FROM "{table}" WHERE {null_checks}')
    after = con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
    diff = before - after
    return f"drop_nulls on {table} ({before:,} → {after:,} rows, -{diff:,})"


def action_fill_nulls(con: duckdb.DuckDBPyConnection, step: dict) -> str:
    """Fill null values with specified defaults."""
    table = step["table"]
    columns: dict[str, str] = step["columns"]

    # Count nulls before
    null_counts: dict[str, int] = {}
    for col in columns:
        cnt = con.execute(f'SELECT COUNT(*) FROM "{table}" WHERE "{col}" IS NULL').fetchone()[0]
        null_counts[col] = cnt

    # Build COALESCE expressions
    coalesce_parts = []
    all_cols = con.execute(f"SELECT column_name FROM information_schema.columns WHERE table_name = '{table}'").fetchall()
    for (col_name,) in all_cols:
        if col_name in columns:
            default = columns[col_name]
            if isinstance(default, str):
                default = f"'{default}'"
            coalesce_parts.append(f'COALESCE("{col_name}", {default}) AS "{col_name}"')
        else:
            coalesce_parts.append(f'"{col_name}"')

    con.execute(f'CREATE OR REPLACE TABLE "{table}" AS SELECT {", ".join(coalesce_parts)} FROM "{table}"')

    filled_info = ", ".join(f"{c}: {null_counts[c]:,} filled" for c in columns)
    after = con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
    return f"fill_nulls on {table} ({after:,} rows, {filled_info})"


def action_drop_duplicates(con: duckdb.DuckDBPyConnection, step: dict) -> str:
    """Remove duplicate rows based on specified columns."""
    table = step["table"]
    columns = step["columns"]
    before = con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]

    partition_cols = ", ".join(f'"{c}"' for c in columns)
    all_cols = con.execute(f"SELECT column_name FROM information_schema.columns WHERE table_name = '{table}'").fetchall()
    select_cols = ", ".join(f'"{c[0]}"' for c in all_cols)

    con.execute(f'CREATE OR REPLACE TABLE "{table}" AS SELECT {select_cols} FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY {partition_cols}) as _rn FROM "{table}") sub WHERE _rn = 1')
    after = con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
    diff = before - after
    return f"drop_duplicates on {table} ({before:,} → {after:,} rows, -{diff:,})"


def action_trim_strings(con: duckdb.DuckDBPyConnection, step: dict) -> str:
    """Trim whitespace from string columns."""
    table = step["table"]
    columns = step.get("columns")

    all_cols = con.execute(f"SELECT column_name, data_type FROM information_schema.columns WHERE table_name = '{table}'").fetchall()

    if not columns:
        columns = [c[0] for c in all_cols if "VARCHAR" in c[1].upper() or "TEXT" in c[1].upper()]

    if not columns:
        cnt = con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        return f"trim_strings on {table} ({cnt:,} rows, no string columns found)"

    select_parts = []
    for col_name, _ in all_cols:
        if col_name in columns:
            select_parts.append(f'TRIM("{col_name}") AS "{col_name}"')
        else:
            select_parts.append(f'"{col_name}"')

    con.execute(f'CREATE OR REPLACE TABLE "{table}" AS SELECT {", ".join(select_parts)} FROM "{table}"')
    cnt = con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
    return f"trim_strings on {table} ({cnt:,} rows, {len(columns)} columns trimmed)"


def action_normalize_dates(con: duckdb.DuckDBPyConnection, step: dict) -> str:
    """Parse date columns into a standard format."""
    table = step["table"]
    columns = step["columns"]
    step.get("format", "%Y-%m-%d")  # date format hint

    all_cols = con.execute(f"SELECT column_name FROM information_schema.columns WHERE table_name = '{table}'").fetchall()

    select_parts = []
    for (col_name,) in all_cols:
        if col_name in columns:
            select_parts.append(f'TRY_CAST("{col_name}" AS DATE) AS "{col_name}"')
        else:
            select_parts.append(f'"{col_name}"')

    con.execute(f'CREATE OR REPLACE TABLE "{table}" AS SELECT {", ".join(select_parts)} FROM "{table}"')
    cnt = con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
    return f"normalize_dates on {table} ({cnt:,} rows, {len(columns)} columns)"


def action_cast_types(con: duckdb.DuckDBPyConnection, step: dict) -> str:
    """Cast columns to specified data types."""
    table = step["table"]
    columns: dict[str, str] = step["columns"]

    all_cols = con.execute(f"SELECT column_name FROM information_schema.columns WHERE table_name = '{table}'").fetchall()

    select_parts = []
    for (col_name,) in all_cols:
        if col_name in columns:
            target_type = columns[col_name]
            select_parts.append(f'TRY_CAST("{col_name}" AS {target_type}) AS "{col_name}"')
        else:
            select_parts.append(f'"{col_name}"')

    con.execute(f'CREATE OR REPLACE TABLE "{table}" AS SELECT {", ".join(select_parts)} FROM "{table}"')
    cnt = con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
    return f"cast_types on {table} ({cnt:,} rows, {len(columns)} columns cast)"


def action_rename_columns(con: duckdb.DuckDBPyConnection, step: dict) -> str:
    """Rename columns in a table."""
    table = step["table"]
    mapping: dict[str, str] = step["mapping"]

    all_cols = con.execute(f"SELECT column_name FROM information_schema.columns WHERE table_name = '{table}'").fetchall()

    select_parts = []
    for (col_name,) in all_cols:
        new_name = mapping.get(col_name, col_name)
        if new_name != col_name:
            select_parts.append(f'"{col_name}" AS "{new_name}"')
        else:
            select_parts.append(f'"{col_name}"')

    con.execute(f'CREATE OR REPLACE TABLE "{table}" AS SELECT {", ".join(select_parts)} FROM "{table}"')
    cnt = con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
    return f"rename_columns on {table} ({cnt:,} rows, {len(mapping)} columns renamed)"


def action_add_computed_column(con: duckdb.DuckDBPyConnection, step: dict) -> str:
    """Add a new column computed from a SQL expression."""
    table = step["table"]
    column = step["column"]
    expr = step["expr"]

    con.execute(f'CREATE OR REPLACE TABLE "{table}" AS SELECT *, ({expr}) AS "{column}" FROM "{table}"')
    cnt = con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
    return f"add_computed_column '{column}' on {table} ({cnt:,} rows)"


def action_group_by(con: duckdb.DuckDBPyConnection, step: dict) -> str:
    """Group and aggregate a table."""
    table = step["table"]
    by_cols = step["by"]
    aggregations: dict[str, str] = step["aggregations"]
    output_table = step.get("as", table)

    by_parts = ", ".join(f'"{c}"' for c in by_cols)
    agg_parts = [f'{expr} AS "{alias}"' for alias, expr in aggregations.items()]
    select = f"{by_parts}, {', '.join(agg_parts)}"

    con.execute(f'CREATE OR REPLACE TABLE "{output_table}" AS SELECT {select} FROM "{table}" GROUP BY {by_parts}')
    cnt = con.execute(f'SELECT COUNT(*) FROM "{output_table}"').fetchone()[0]
    return f"group_by on {table} → {output_table} ({cnt:,} rows)"


def action_join(con: duckdb.DuckDBPyConnection, step: dict) -> str:
    """Join two tables."""
    left = step["left"]
    right = step["right"]
    on_cols = step["on"]
    how = step.get("how", "inner")
    output_table = step["as"]

    on_clause = " AND ".join(f'"{left}"."{c}" = "{right}"."{c}"' for c in on_cols)

    left_cols = con.execute(f"SELECT column_name FROM information_schema.columns WHERE table_name = '{left}'").fetchall()
    right_cols = con.execute(f"SELECT column_name FROM information_schema.columns WHERE table_name = '{right}'").fetchall()

    left_select = ", ".join(f'"{left}"."{c[0]}" AS "{c[0]}"' for c in left_cols)
    right_select = ", ".join(f'"{right}"."{c[0]}" AS "{c[0]}_right"' for c in right_cols if c[0] not in [lc[0] for lc in left_cols])
    all_select = f"{left_select}, {right_select}" if right_select else left_select

    con.execute(f'CREATE TABLE "{output_table}" AS SELECT {all_select} FROM "{left}" {how.upper()} JOIN "{right}" ON {on_clause}')
    cnt = con.execute(f'SELECT COUNT(*) FROM "{output_table}"').fetchone()[0]
    return f"join {left} + {right} → {output_table} ({cnt:,} rows, {how})"


def action_union(con: duckdb.DuckDBPyConnection, step: dict) -> str:
    """Union (stack) multiple tables."""
    tables = step["tables"]
    output_table = step["as"]

    union_parts = [f'SELECT * FROM "{t}"' for t in tables]
    con.execute(f'CREATE TABLE "{output_table}" AS ' + " UNION ALL ".join(union_parts))
    cnt = con.execute(f'SELECT COUNT(*) FROM "{output_table}"').fetchone()[0]
    return f"union {', '.join(tables)} → {output_table} ({cnt:,} rows)"


def action_filter(con: duckdb.DuckDBPyConnection, step: dict) -> str:
    """Filter rows by a SQL WHERE condition."""
    table = step["table"]
    condition = step["condition"]
    before = con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]

    con.execute(f'CREATE OR REPLACE TABLE "{table}" AS SELECT * FROM "{table}" WHERE {condition}')
    after = con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
    diff = before - after
    return f"filter on {table} ({before:,} → {after:,} rows, -{diff:,})"


def action_sample(con: duckdb.DuckDBPyConnection, step: dict) -> str:
    """Take a random sample of rows."""
    table = step["table"]
    output_table = step.get("as", table)
    n = step.get("n")
    fraction = step.get("fraction")

    if n:
        con.execute(f'CREATE OR REPLACE TABLE "{output_table}" AS SELECT * FROM "{table}" USING SAMPLE {int(n)} ROWS')
    elif fraction:
        pct = float(fraction) * 100
        con.execute(f'CREATE OR REPLACE TABLE "{output_table}" AS SELECT * FROM "{table}" USING SAMPLE {pct}%')

    cnt = con.execute(f'SELECT COUNT(*) FROM "{output_table}"').fetchone()[0]
    return f"sample on {table} → {output_table} ({cnt:,} rows)"


def action_top_n(con: duckdb.DuckDBPyConnection, step: dict) -> str:
    """Get top N rows ordered by a column."""
    table = step["table"]
    order_by = step["order_by"]
    n = step.get("n", 10)
    direction = step.get("direction", "DESC")
    output_table = step.get("as", table)

    con.execute(f'CREATE OR REPLACE TABLE "{output_table}" AS SELECT * FROM "{table}" ORDER BY "{order_by}" {direction} LIMIT {int(n)}')
    cnt = con.execute(f'SELECT COUNT(*) FROM "{output_table}"').fetchone()[0]
    return f"top_n on {table} → {output_table} ({cnt:,} rows)"


def action_export_csv(con: duckdb.DuckDBPyConnection, step: dict) -> str:
    """Export a table to CSV."""
    table = step["table"]
    file_path = step["file"]
    os.makedirs(os.path.dirname(file_path) or ".", exist_ok=True)
    con.execute(f"COPY \"{table}\" TO '{file_path}' (HEADER, DELIMITER ',')")
    cnt = con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
    return f"export_csv → {file_path} ({cnt:,} rows)"


def action_export_json(con: duckdb.DuckDBPyConnection, step: dict) -> str:
    """Export a table to JSON."""
    table = step["table"]
    file_path = step["file"]
    os.makedirs(os.path.dirname(file_path) or ".", exist_ok=True)
    con.execute(f"COPY \"{table}\" TO '{file_path}' (FORMAT JSON, ARRAY true)")
    cnt = con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
    return f"export_json → {file_path} ({cnt:,} rows)"


def action_export_excel(con: duckdb.DuckDBPyConnection, step: dict) -> str:
    """Export a table to Excel via CSV intermediate."""
    table = step["table"]
    file_path = step["file"]
    os.makedirs(os.path.dirname(file_path) or ".", exist_ok=True)

    # Export to CSV first, then convert to Excel via openpyxl

    import openpyxl

    result = con.execute(f'SELECT * FROM "{table}"')
    columns = [desc[0] for desc in result.description]
    rows = result.fetchall()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = table[:31]
    ws.append(columns)
    for row in rows:
        ws.append(row)
    wb.save(file_path)

    return f"export_excel → {file_path} ({len(rows):,} rows)"


# ---------------------------------------------------------------------------
# Action dispatch
# ---------------------------------------------------------------------------

ACTION_MAP: dict[str, callable] = {
    "load_csv": action_load_csv,
    "load_excel": action_load_excel,
    "load_json": action_load_json,
    "drop_nulls": action_drop_nulls,
    "fill_nulls": action_fill_nulls,
    "drop_duplicates": action_drop_duplicates,
    "trim_strings": action_trim_strings,
    "normalize_dates": action_normalize_dates,
    "cast_types": action_cast_types,
    "rename_columns": action_rename_columns,
    "add_computed_column": action_add_computed_column,
    "group_by": action_group_by,
    "join": action_join,
    "union": action_union,
    "filter": action_filter,
    "sample": action_sample,
    "top_n": action_top_n,
    "export_csv": action_export_csv,
    "export_json": action_export_json,
    "export_excel": action_export_excel,
}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Execute a data pipeline defined in a JSON spec file")
    parser.add_argument(
        "--spec-file",
        required=True,
        help="Path to the pipeline spec JSON file",
    )
    args = parser.parse_args()

    with open(args.spec_file, encoding="utf-8") as f:
        spec = json.load(f)

    steps = spec.get("steps", [])
    if not steps:
        print("No steps defined in pipeline spec.")
        sys.exit(1)

    con = duckdb.connect()
    report_lines: list[str] = []
    report_lines.append("Pipeline Execution Report")
    report_lines.append("=" * 50)

    start_time = time.time()
    export_count = 0

    for i, step in enumerate(steps, 1):
        action = step.get("action", "")
        handler = ACTION_MAP.get(action)

        if not handler:
            msg = f"Step {i}: UNKNOWN action '{action}' — skipping"
            report_lines.append(msg)
            print(f"WARNING: {msg}")
            continue

        try:
            msg = handler(con, step)
            report_lines.append(f"Step {i}: {msg}")
            print(f"Step {i}: {msg}")
            if action.startswith("export_"):
                export_count += 1
        except Exception as e:
            msg = f"Step {i}: FAILED — {e}"
            report_lines.append(msg)
            print(f"ERROR: {msg}")
            con.close()
            sys.exit(1)

    elapsed = time.time() - start_time
    report_lines.append("=" * 50)
    report_lines.append(f"Done in {elapsed:.1f}s ({export_count} file(s) exported)")

    con.close()
    print("\n" + "\n".join(report_lines))


if __name__ == "__main__":
    main()
