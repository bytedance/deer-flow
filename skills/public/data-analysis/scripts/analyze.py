"""
Data Analysis Script using DuckDB.

Analyzes Excel (.xlsx/.xls) and CSV files using DuckDB's in-process SQL engine.
Supports schema inspection, SQL queries, statistical summaries, and result export.
"""

import argparse
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import tempfile

LOG_DIR = os.path.join(tempfile.gettempdir(), ".data-analysis-logs")
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(f"{LOG_DIR}/analyze.log"),
    ],
)
logger = logging.getLogger(__name__)

try:
    import duckdb
except ImportError:
    logger.error("❌ duckdb 未安装，正在安装...")
    subprocess.run([sys.executable, "-m", "pip", "install", "duckdb", "openpyxl", "-q"], check=True)
    import duckdb

try:
    import openpyxl  # noqa: F401
except ImportError:
    subprocess.run([sys.executable, "-m", "pip", "install", "openpyxl", "-q"], check=True)

try:
    from header_processor import flatten_excel_headers  # noqa: F401
except ImportError:
    # header_processor.py should be in same scripts/ directory
    flatten_excel_headers = None

# Cache directory for persistent DuckDB databases
CACHE_DIR = os.path.join(tempfile.gettempdir(), ".data-analysis-cache")
TABLE_MAP_SUFFIX = ".table_map.json"

# Flat CSV naming pattern from header_processor: {file_hash}_flat_{version}_{sheet_name}.csv
FLATTEN_VERSION = "v1"


def compute_files_hash(files: list[str]) -> str:
    """Compute a combined SHA256 hash of all input files for cache key."""
    hasher = hashlib.sha256()
    for file_path in sorted(files):
        try:
            with open(file_path, "rb") as f:
                while chunk := f.read(8192):
                    hasher.update(chunk)
        except OSError:
            # Include path as fallback if file can't be read
            hasher.update(file_path.encode())
    return hasher.hexdigest()


def get_cache_db_path(files_hash: str) -> str:
    """Get the path to the cached DuckDB database file."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, f"{files_hash}.duckdb")


def get_table_map_path(files_hash: str) -> str:
    """Get the path to the cached table map JSON file."""
    return os.path.join(CACHE_DIR, f"{files_hash}{TABLE_MAP_SUFFIX}")


def save_table_map(files_hash: str, table_map: dict[str, str]) -> None:
    """Save table map to a JSON file alongside the cached DB."""
    path = get_table_map_path(files_hash)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(table_map, f, ensure_ascii=False)


def load_table_map(files_hash: str) -> dict[str, str] | None:
    """Load table map from cache. Returns None if not found."""
    path = get_table_map_path(files_hash)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _compute_file_hash(file_path: str) -> str:
    """Compute file SHA256 hash (first 12 hex chars) — matches header_processor logic."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(8192):
            hasher.update(chunk)
    return hasher.hexdigest()[:12]


def find_flat_csvs(excel_path: str) -> dict[str, str]:
    """Find pre-processed flattened CSVs for an Excel file. Returns {sheet_name: csv_path}."""
    if not os.path.exists(excel_path):
        return {}

    file_hash = _compute_file_hash(excel_path)
    pattern = f"{file_hash}_flat_{FLATTEN_VERSION}_"
    results: dict[str, str] = {}

    if not os.path.isdir(CACHE_DIR):
        return results

    for fname in os.listdir(CACHE_DIR):
        if fname.startswith(pattern) and fname.endswith(".csv"):
            # Extract sheet name: {hash}_flat_{version}_{sheet_name}.csv
            sheet_name = fname[len(pattern):-4]  # strip pattern and .csv
            csv_path = os.path.join(CACHE_DIR, fname)
            results[sheet_name] = csv_path

    return results


def sanitize_table_name(name: str) -> str:
    """Sanitize a sheet/file name into a valid SQL table name."""
    sanitized = re.sub(r"[^\w]", "_", name)
    if sanitized and sanitized[0].isdigit():
        sanitized = f"t_{sanitized}"
    return sanitized


def load_files(con: duckdb.DuckDBPyConnection, files: list[str], use_flat_csv: bool = True) -> dict[str, str]:
    """
    Load Excel/CSV files into DuckDB tables.

    Returns a mapping of original_name -> sanitized_table_name.
    use_flat_csv: If True, prefer pre-processed flattened CSVs (L1 cache) when available.
    """
    con.execute("INSTALL spatial; LOAD spatial;")
    table_map: dict[str, str] = {}

    for file_path in files:
        if not os.path.exists(file_path):
            logger.error(f"❌ 文件未找到: {file_path}")
            continue

        ext = os.path.splitext(file_path)[1].lower()

        if ext in (".xlsx", ".xls"):
            # Try to use pre-processed flattened CSVs (L1 cache) first
            if use_flat_csv:
                flat_csvs = find_flat_csvs(file_path)
                if flat_csvs:
                    # Load flat CSVs as separate tables
                    for sheet_name, csv_path in flat_csvs.items():
                        table_name = sanitize_table_name(sheet_name)
                        # Handle duplicate table names
                        original_table_name = table_name
                        counter = 1
                        while table_name in table_map.values():
                            table_name = f"{original_table_name}_{counter}"
                            counter += 1
                        try:
                            con.execute(
                                f'CREATE TABLE "{table_name}" AS SELECT * FROM read_csv_auto(\'{csv_path}\')'
                            )
                            table_map[sheet_name] = table_name
                            row_count = con.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0]
                            logger.info(
                                f"  ✅ 已加载（展平CSV）工作表 '{sheet_name}' -> 表 '{table_name}' ({row_count} 行)"
                            )
                            print(f"  ✅ 已加载工作表: {sheet_name}")
                        except Exception as e:
                            logger.warning(f"  ⚠️ 加载工作表 '{sheet_name}' 失败: {e}")
                    continue

            # Fall back: try header flattening
            if flatten_excel_headers:
                flat_csvs = flatten_excel_headers(file_path, CACHE_DIR)
                if flat_csvs:
                    # Load flat CSVs as separate tables
                    for sheet_name, csv_path in flat_csvs.items():
                        table_name = sanitize_table_name(sheet_name)
                        # Handle duplicate table names
                        original_table_name = table_name
                        counter = 1
                        while table_name in table_map.values():
                            table_name = f"{original_table_name}_{counter}"
                            counter += 1
                        try:
                            con.execute(
                                f'CREATE TABLE "{table_name}" AS SELECT * FROM read_csv_auto(\'{csv_path}\')'
                            )
                            table_map[sheet_name] = table_name
                            row_count = con.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0]
                            logger.info(
                                f"  ✅ 已加载（展平）工作表 '{sheet_name}' -> 表 '{table_name}' ({row_count} 行)"
                            )
                            print(f"  ✅ 已加载工作表: {sheet_name}")
                        except Exception as e:
                            logger.warning(f"  ⚠️ 加载工作表 '{sheet_name}' 失败: {e}")
                    continue
            # Fall back to GDAL方式
            _load_excel(con, file_path, table_map)
        elif ext == ".csv":
            _load_csv(con, file_path, table_map)
        else:
            logger.warning(f"❌ 不支持的文件格式: {ext} ({file_path})")

    return table_map


def _load_excel(
    con: duckdb.DuckDBPyConnection, file_path: str, table_map: dict[str, str]
) -> None:
    """Load all sheets from an Excel file into DuckDB tables."""
    import openpyxl

    wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
    sheet_names = wb.sheetnames
    wb.close()

    for sheet_name in sheet_names:
        table_name = sanitize_table_name(sheet_name)

        # Handle duplicate table names
        original_table_name = table_name
        counter = 1
        while table_name in table_map.values():
            table_name = f"{original_table_name}_{counter}"
            counter += 1

        try:
            con.execute(
                f"""
                CREATE TABLE "{table_name}" AS
                SELECT * FROM st_read(
                    '{file_path}',
                    layer = '{sheet_name}',
                    open_options = ['HEADERS=FORCE', 'FIELD_TYPES=AUTO']
                )
            """
            )
            table_map[sheet_name] = table_name
            row_count = con.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[
                0
            ]
            logger.info(
                f"  Loaded sheet '{sheet_name}' -> table '{table_name}' ({row_count} rows)"
            )
        except Exception as e:
            logger.warning(f"  Failed to load sheet '{sheet_name}': {e}")


def _load_csv(
    con: duckdb.DuckDBPyConnection, file_path: str, table_map: dict[str, str]
) -> None:
    """Load a CSV file into a DuckDB table."""
    base_name = os.path.splitext(os.path.basename(file_path))[0]
    table_name = sanitize_table_name(base_name)

    # Handle duplicate table names
    original_table_name = table_name
    counter = 1
    while table_name in table_map.values():
        table_name = f"{original_table_name}_{counter}"
        counter += 1

    try:
        con.execute(
            f"""
            CREATE TABLE "{table_name}" AS
            SELECT * FROM read_csv_auto('{file_path}')
        """
        )
        table_map[base_name] = table_name
        row_count = con.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0]
        logger.info(
            f"  ✅ 已加载 CSV '{base_name}' -> 表 '{table_name}' ({row_count} 行)"
        )
        print(f"  ✅ 已加载 CSV: {base_name}")
    except Exception as e:
        logger.warning(f"  ⚠️ 加载 CSV '{base_name}' 失败: {e}")


def action_inspect(con: duckdb.DuckDBPyConnection, table_map: dict[str, str]) -> str:
    """Inspect the schema of all loaded tables."""
    output_parts = []

    for original_name, table_name in table_map.items():
        output_parts.append(f"\n{'=' * 60}")
        output_parts.append(f'Table: {original_name} (SQL name: "{table_name}")')
        output_parts.append(f"{'=' * 60}")

        # Get row count
        row_count = con.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0]
        output_parts.append(f"Rows: {row_count}")

        # Get column info
        columns = con.execute(f'DESCRIBE "{table_name}"').fetchall()
        output_parts.append(f"\nColumns ({len(columns)}):")
        output_parts.append(f"{'Name':<30} {'Type':<15} {'Nullable'}")
        output_parts.append(f"{'-' * 30} {'-' * 15} {'-' * 8}")
        for col in columns:
            col_name, col_type, nullable = col[0], col[1], col[2]
            output_parts.append(f"{col_name:<30} {col_type:<15} {nullable}")

        # Get non-null counts per column
        col_names = [col[0] for col in columns]
        non_null_parts = []
        for c in col_names:
            non_null_parts.append(f'COUNT("{c}") as "{c}"')
        non_null_sql = f'SELECT {", ".join(non_null_parts)} FROM "{table_name}"'
        try:
            non_null_counts = con.execute(non_null_sql).fetchone()
            output_parts.append("\nNon-null counts:")
            for i, c in enumerate(col_names):
                output_parts.append(f"  {c}: {non_null_counts[i]} / {row_count}")
        except Exception:
            pass

        # Sample data (first 5 rows)
        output_parts.append("\nSample data (first 5 rows):")
        try:
            sample = con.execute(f'SELECT * FROM "{table_name}" LIMIT 5').fetchdf()
            output_parts.append(sample.to_string(index=False))
        except Exception:
            sample = con.execute(f'SELECT * FROM "{table_name}" LIMIT 5').fetchall()
            header = [col[0] for col in columns]
            output_parts.append("  " + " | ".join(header))
            for row in sample:
                output_parts.append("  " + " | ".join(str(v) for v in row))

    result = "\n".join(output_parts)
    print(result)
    return result


def action_query(
    con: duckdb.DuckDBPyConnection,
    sql: str,
    table_map: dict[str, str],
    output_file: str | None = None,
) -> str:
    """Execute a SQL query and return/export results."""
    # Replace original sheet/file names with sanitized table names in SQL
    modified_sql = sql
    for original_name, table_name in sorted(
        table_map.items(), key=lambda x: len(x[0]), reverse=True
    ):
        if original_name != table_name:
            # Replace occurrences not already quoted
            modified_sql = re.sub(
                rf"\b{re.escape(original_name)}\b",
                f'"{table_name}"',
                modified_sql,
            )

    try:
        result = con.execute(modified_sql)
        columns = [desc[0] for desc in result.description]
        rows = result.fetchall()
    except Exception as e:
        error_msg = f"SQL Error: {e}\n\nAvailable tables:\n"
        for orig, tbl in table_map.items():
            cols = con.execute(f'DESCRIBE "{tbl}"').fetchall()
            col_names = [c[0] for c in cols]
            error_msg += f'  "{tbl}" ({orig}): {", ".join(col_names)}\n'
        print(error_msg)
        return error_msg

    # Format output
    if output_file:
        return _export_results(columns, rows, output_file)

    # Print as table
    return _format_table(columns, rows)


def _format_table(columns: list[str], rows: list[tuple]) -> str:
    """Format query results as a readable table."""
    if not rows:
        msg = "Query returned 0 rows."
        print(msg)
        return msg

    # Calculate column widths
    col_widths = [len(str(c)) for c in columns]
    for row in rows:
        for i, val in enumerate(row):
            col_widths[i] = max(col_widths[i], len(str(val)))

    # Cap column width
    max_width = 40
    col_widths = [min(w, max_width) for w in col_widths]

    # Build table
    parts = []
    header = " | ".join(str(c).ljust(col_widths[i]) for i, c in enumerate(columns))
    separator = "-+-".join("-" * col_widths[i] for i in range(len(columns)))
    parts.append(header)
    parts.append(separator)
    for row in rows:
        row_str = " | ".join(
            str(v)[:max_width].ljust(col_widths[i]) for i, v in enumerate(row)
        )
        parts.append(row_str)

    parts.append(f"\n({len(rows)} rows)")
    result = "\n".join(parts)
    print(result)
    return result


def _export_results(columns: list[str], rows: list[tuple], output_file: str) -> str:
    """Export query results to a file (CSV, JSON, or Markdown)."""
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    ext = os.path.splitext(output_file)[1].lower()

    if ext == ".csv":
        import csv

        with open(output_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(columns)
            writer.writerows(rows)

    elif ext == ".json":
        records = []
        for row in rows:
            record = {}
            for i, col in enumerate(columns):
                val = row[i]
                # Handle non-JSON-serializable types
                if hasattr(val, "isoformat"):
                    val = val.isoformat()
                elif isinstance(val, (bytes, bytearray)):
                    val = val.hex()
                record[col] = val
            records.append(record)
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2, ensure_ascii=False, default=str)

    elif ext == ".md":
        with open(output_file, "w", encoding="utf-8") as f:
            # Header
            f.write("| " + " | ".join(columns) + " |\n")
            f.write("| " + " | ".join("---" for _ in columns) + " |\n")
            # Rows
            for row in rows:
                f.write(
                    "| " + " | ".join(str(v).replace("|", "\\|") for v in row) + " |\n"
                )
    else:
        msg = f"❌ 不支持的输出格式: {ext}，请使用 .csv、.json 或 .md"
        print(msg)
        return msg

    msg = f"✅ 结果已导出到 {output_file}（{len(rows)} 行）"
    print(msg)
    return msg


def action_summary(
    con: duckdb.DuckDBPyConnection,
    table_name: str,
    table_map: dict[str, str],
) -> str:
    """Generate statistical summary for a table."""
    # Resolve table name
    resolved = table_map.get(table_name, table_name)

    try:
        columns = con.execute(f'DESCRIBE "{resolved}"').fetchall()
    except Exception:
        available = ", ".join(f'"{t}" ({o})' for o, t in table_map.items())
        msg = f"Table '{table_name}' not found. Available tables: {available}"
        print(msg)
        return msg

    row_count = con.execute(f'SELECT COUNT(*) FROM "{resolved}"').fetchone()[0]

    output_parts = []
    output_parts.append(f"\nStatistical Summary: {table_name}")
    output_parts.append(f"Total rows: {row_count}")
    output_parts.append(f"{'=' * 70}")

    numeric_types = {
        "BIGINT",
        "INTEGER",
        "SMALLINT",
        "TINYINT",
        "DOUBLE",
        "FLOAT",
        "DECIMAL",
        "HUGEINT",
        "REAL",
        "NUMERIC",
    }

    for col in columns:
        col_name, col_type = col[0], col[1].upper()
        output_parts.append(f"\n--- {col_name} ({col[1]}) ---")

        # Check base type (strip parameterized parts)
        base_type = re.sub(r"\(.*\)", "", col_type).strip()

        if base_type in numeric_types:
            try:
                stats = con.execute(f"""
                    SELECT
                        COUNT("{col_name}") as count,
                        AVG("{col_name}")::DOUBLE as mean,
                        STDDEV("{col_name}")::DOUBLE as std,
                        MIN("{col_name}") as min,
                        QUANTILE_CONT("{col_name}", 0.25) as q25,
                        MEDIAN("{col_name}") as median,
                        QUANTILE_CONT("{col_name}", 0.75) as q75,
                        MAX("{col_name}") as max,
                        COUNT(*) - COUNT("{col_name}") as null_count
                    FROM "{resolved}"
                """).fetchone()
                labels = [
                    "count",
                    "mean",
                    "std",
                    "min",
                    "25%",
                    "50%",
                    "75%",
                    "max",
                    "nulls",
                ]
                for label, val in zip(labels, stats):
                    if isinstance(val, float):
                        output_parts.append(f"  {label:<8}: {val:,.4f}")
                    else:
                        output_parts.append(f"  {label:<8}: {val}")
            except Exception as e:
                output_parts.append(f"  Error computing stats: {e}")
        else:
            try:
                stats = con.execute(f"""
                    SELECT
                        COUNT("{col_name}") as count,
                        COUNT(DISTINCT "{col_name}") as unique_count,
                        MODE("{col_name}") as mode_val,
                        COUNT(*) - COUNT("{col_name}") as null_count
                    FROM "{resolved}"
                """).fetchone()
                output_parts.append(f"  count   : {stats[0]}")
                output_parts.append(f"  unique  : {stats[1]}")
                output_parts.append(f"  top     : {stats[2]}")
                output_parts.append(f"  nulls   : {stats[3]}")

                # Show top 5 values
                top_vals = con.execute(f"""
                    SELECT "{col_name}", COUNT(*) as freq
                    FROM "{resolved}"
                    WHERE "{col_name}" IS NOT NULL
                    GROUP BY "{col_name}"
                    ORDER BY freq DESC
                    LIMIT 5
                """).fetchall()
                if top_vals:
                    output_parts.append("  top values:")
                    for val, freq in top_vals:
                        pct = (freq / row_count * 100) if row_count > 0 else 0
                        output_parts.append(f"    {val}: {freq} ({pct:.1f}%)")
            except Exception as e:
                output_parts.append(f"  Error computing stats: {e}")

    result = "\n".join(output_parts)
    print(result)
    return result


def _col_quote(col_name: str) -> str:
    """Return double-quoted column name if it contains spaces or special chars."""
    if any(c in col_name for c in (' ', '-', '（', '）', '_', '/', '\\')):
        return f'"{col_name}"'
    return col_name


def action_overview(con: duckdb.DuckDBPyConnection, table_map: dict[str, str]) -> str:
    """
    Single-pass overview: table structure + column quick-ref + stats summary + sample rows.
    Designed to provide everything needed to write a query in one call.
    """
    output_parts = []

    for original_name, table_name in table_map.items():
        output_parts.append(f"\n{'=' * 60}")
        output_parts.append(f"  Table: {original_name}  (SQL: \"{table_name}\")")
        output_parts.append(f"{'=' * 60}")

        row_count = con.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0]
        columns = con.execute(f'DESCRIBE "{table_name}"').fetchall()
        col_names = [c[0] for c in columns]

        # Section 1: Quick column reference with auto-quoting hints
        output_parts.append(f"\n--- Column Quick-Ref ---")
        output_parts.append(f"Rows: {row_count}  |  Columns: {len(columns)}")
        output_parts.append(f"\n{'Name':<32} {'Type':<12} Nullable")
        output_parts.append(f"{'-' * 32} {'-' * 12} {'-' * 8}")
        for col in columns:
            col_name, col_type, nullable = col[0], col[1], col[2]
            quoted = _col_quote(col_name)
            hint = f"  -> use {quoted}" if quoted != col_name else ""
            output_parts.append(f"{col_name:<32} {col_type:<12} {nullable}{hint}")

        # Section 2: Compact stats for numeric columns
        numeric_types = {"BIGINT", "INTEGER", "SMALLINT", "TINYINT", "DOUBLE", "FLOAT", "DECIMAL", "HUGEINT", "REAL", "NUMERIC"}
        numeric_cols = [(c[0], re.sub(r"\(.*\)", "", c[1]).strip().upper()) for c in columns
                        if re.sub(r"\(.*\)", "", c[1]).strip().upper() in numeric_types]

        if numeric_cols:
            output_parts.append(f"\n--- Numeric Columns Summary ---")
            for col_name, col_type in numeric_cols:
                try:
                    stats = con.execute(f"""
                        SELECT
                            COUNT("{col_name}"),
                            AVG("{col_name}")::DOUBLE,
                            MIN("{col_name}"),
                            MAX("{col_name}")
                        FROM "{table_name}"
                    """).fetchone()
                    cnt, avg, mn, mx = stats
                    output_parts.append(f"  {col_name}: count={cnt:,}  avg={avg:,.2f}  min={mn}  max={mx}")
                except Exception:
                    pass

        # Section 3: String column top values
        string_cols = [(c[0], re.sub(r"\(.*\)", "", c[1]).strip().upper()) for c in columns
                       if re.sub(r"\(.*\)", "", c[1]).strip().upper() not in numeric_types]
        if string_cols:
            output_parts.append(f"\n--- String Columns (top 3 values each) ---")
            for col_name, col_type in string_cols[:5]:  # limit to 5 string cols
                try:
                    top_vals = con.execute(f"""
                        SELECT "{col_name}", COUNT(*) as freq
                        FROM "{table_name}"
                        WHERE "{col_name}" IS NOT NULL
                        GROUP BY "{col_name}"
                        ORDER BY freq DESC LIMIT 3
                    """).fetchall()
                    vals_str = "  |  ".join(f"{v} ({n})" for v, n in top_vals) if top_vals else "(no data)"
                    output_parts.append(f"  {col_name}: {vals_str}")
                except Exception:
                    pass

        # Section 4: Sample rows
        output_parts.append(f"\n--- Sample Rows (3) ---")
        try:
            sample = con.execute(f'SELECT * FROM "{table_name}" LIMIT 3').fetchdf()
            output_parts.append(sample.to_string(index=False))
        except Exception:
            sample = con.execute(f'SELECT * FROM "{table_name}" LIMIT 3').fetchall()
            header = [c[0] for c in columns]
            output_parts.append("  " + " | ".join(header))
            for row in sample:
                output_parts.append("  " + " | ".join(str(v) for v in row))

    result = "\n".join(output_parts)
    print(result)
    return result


def main():
    parser = argparse.ArgumentParser(description="Analyze Excel/CSV files using DuckDB")
    parser.add_argument(
        "--files",
        nargs="+",
        required=True,
        help="Paths to Excel (.xlsx/.xls) or CSV files",
    )
    parser.add_argument(
        "--action",
        required=True,
        choices=["inspect", "query", "summary", "overview"],
        help="Action to perform: inspect, query, summary, or overview (inspect+summary in one)",
    )
    parser.add_argument(
        "--no-flat-csv",
        action="store_true",
        help="Disable auto-use of pre-processed flattened CSVs (force re-parse Excel files)",
    )
    parser.add_argument(
        "--sql",
        type=str,
        default=None,
        help="SQL query to execute (required for 'query' action)",
    )
    parser.add_argument(
        "--table",
        type=str,
        default=None,
        help="Table name for summary (required for 'summary' action)",
    )
    parser.add_argument(
        "--output-file",
        type=str,
        default=None,
        help="Path to export results (CSV/JSON/MD)",
    )
    args = parser.parse_args()

    # Validate arguments
    if args.action == "query" and not args.sql:
        parser.error("--sql is required for 'query' action")
    if args.action == "summary" and not args.table:
        parser.error("--table is required for 'summary' action")

    # Compute file hash for caching
    files_hash = compute_files_hash(args.files)
    db_path = get_cache_db_path(files_hash)
    cached_table_map = load_table_map(files_hash)

    if cached_table_map and os.path.exists(db_path):
        # Cache hit: connect to existing DB
        print("✅ 缓存命中 — 使用已有缓存数据库")
        con = duckdb.connect(db_path, read_only=True)
        table_map = cached_table_map
        print(f"✅ 已加载 {len(table_map)} 个表")
    else:
        # Cache miss: load files and persist to DB
        logger.info("⏳ 首次加载 — 正在解析文件并建立缓存...")
        print("⏳ 正在解析文件...")
        con = duckdb.connect(db_path)
        use_flat_csv = not args.no_flat_csv
        table_map = load_files(con, args.files, use_flat_csv=use_flat_csv)

        if not table_map:
            logger.error("❌ 未加载任何表，请检查文件路径和格式。")
            print("❌ 文件加载失败")
            # Clean up empty DB file
            con.close()
            if os.path.exists(db_path):
                os.remove(db_path)
            sys.exit(1)

        # Save table map for future cache lookups
        save_table_map(files_hash, table_map)
        print(f"✅ 数据已缓存 ({len(table_map)} 个表)")
        print(f"✅ 缓存已保存")

    # Perform action
    if args.action == "inspect":
        action_inspect(con, table_map)
    elif args.action == "query":
        action_query(con, args.sql, table_map, args.output_file)
    elif args.action == "summary":
        action_summary(con, args.table, table_map)
    elif args.action == "overview":
        action_overview(con, table_map)

    con.close()


if __name__ == "__main__":
    main()
