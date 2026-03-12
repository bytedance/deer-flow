"""
AI Graphs Dashboard Generator.

Generates TipTap-compatible JSON dashboards with ECharts visualizations
from uploaded CSV/Excel files using DuckDB for data analysis.

Usage:
    # Inspect uploaded data (schema, samples)
    python generate.py --files data.csv --action inspect

    # Generate a dashboard from a plan (JSON with chart specs)
    python generate.py --files data.csv --action generate --plan '<json>'

    # Run a SQL query and return results as JSON array-of-arrays
    python generate.py --files data.csv --action query --sql "SELECT ..."

    # Update an existing dashboard (read, merge, write)
    python generate.py --files data.csv --action update --plan '<json>' --dashboard /path/to/dashboard.json
"""

import argparse
import hashlib
import json
import logging
import os
import re
import sys
import tempfile
import uuid

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

try:
    import duckdb
except ImportError:
    logger.error("duckdb is not installed. Installing...")
    os.system(f"{sys.executable} -m pip install duckdb openpyxl -q")
    import duckdb

try:
    import openpyxl  # noqa: F401
except ImportError:
    os.system(f"{sys.executable} -m pip install openpyxl -q")

# Cache directory for persistent DuckDB databases
CACHE_DIR = os.path.join(tempfile.gettempdir(), ".data-analysis-cache")
TABLE_MAP_SUFFIX = ".table_map.json"


# ---------------------------------------------------------------------------
# DuckDB helpers (shared with data-analysis skill)
# ---------------------------------------------------------------------------

def compute_files_hash(files: list[str]) -> str:
    hasher = hashlib.sha256()
    for file_path in sorted(files):
        try:
            with open(file_path, "rb") as f:
                while chunk := f.read(8192):
                    hasher.update(chunk)
        except OSError:
            hasher.update(file_path.encode())
    return hasher.hexdigest()


def get_cache_db_path(files_hash: str) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, f"{files_hash}.duckdb")


def get_table_map_path(files_hash: str) -> str:
    return os.path.join(CACHE_DIR, f"{files_hash}{TABLE_MAP_SUFFIX}")


def save_table_map(files_hash: str, table_map: dict[str, str]) -> None:
    path = get_table_map_path(files_hash)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(table_map, f, ensure_ascii=False)


def load_table_map(files_hash: str) -> dict[str, str] | None:
    path = get_table_map_path(files_hash)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def sanitize_table_name(name: str) -> str:
    sanitized = re.sub(r"[^\w]", "_", name)
    if sanitized and sanitized[0].isdigit():
        sanitized = f"t_{sanitized}"
    return sanitized


def load_files(con: duckdb.DuckDBPyConnection, files: list[str]) -> dict[str, str]:
    con.execute("INSTALL spatial; LOAD spatial;")
    table_map: dict[str, str] = {}
    for file_path in files:
        if not os.path.exists(file_path):
            logger.error(f"File not found: {file_path}")
            continue
        ext = os.path.splitext(file_path)[1].lower()
        if ext in (".xlsx", ".xls"):
            _load_excel(con, file_path, table_map)
        elif ext == ".csv":
            _load_csv(con, file_path, table_map)
        else:
            logger.warning(f"Unsupported file format: {ext} ({file_path})")
    return table_map


def _load_excel(con, file_path, table_map):
    import openpyxl
    wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
    sheet_names = wb.sheetnames
    wb.close()
    for sheet_name in sheet_names:
        table_name = sanitize_table_name(sheet_name)
        original = table_name
        counter = 1
        while table_name in table_map.values():
            table_name = f"{original}_{counter}"
            counter += 1
        try:
            con.execute(f"""
                CREATE TABLE "{table_name}" AS
                SELECT * FROM st_read('{file_path}', layer='{sheet_name}',
                    open_options=['HEADERS=FORCE','FIELD_TYPES=AUTO'])
            """)
            table_map[sheet_name] = table_name
            row_count = con.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0]
            logger.info(f"  Loaded sheet '{sheet_name}' -> '{table_name}' ({row_count} rows)")
        except Exception as e:
            logger.warning(f"  Failed to load sheet '{sheet_name}': {e}")


def _load_csv(con, file_path, table_map):
    base_name = os.path.splitext(os.path.basename(file_path))[0]
    table_name = sanitize_table_name(base_name)
    original = table_name
    counter = 1
    while table_name in table_map.values():
        table_name = f"{original}_{counter}"
        counter += 1
    try:
        con.execute(f"""
            CREATE TABLE "{table_name}" AS
            SELECT * FROM read_csv_auto('{file_path}')
        """)
        table_map[base_name] = table_name
        row_count = con.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0]
        logger.info(f"  Loaded CSV '{base_name}' -> '{table_name}' ({row_count} rows)")
    except Exception as e:
        logger.warning(f"  Failed to load CSV '{base_name}': {e}")


def get_connection(files: list[str]):
    """Get a DuckDB connection, using cache if available."""
    files_hash = compute_files_hash(files)
    db_path = get_cache_db_path(files_hash)
    cached_map = load_table_map(files_hash)

    if cached_map and os.path.exists(db_path):
        logger.info(f"Cache hit: {db_path}")
        con = duckdb.connect(db_path, read_only=True)
        return con, cached_map

    logger.info("Loading files (first time, will cache)...")
    con = duckdb.connect(db_path)
    table_map = load_files(con, files)
    if not table_map:
        logger.error("No tables loaded. Check file paths.")
        con.close()
        if os.path.exists(db_path):
            os.remove(db_path)
        sys.exit(1)
    save_table_map(files_hash, table_map)
    logger.info(f"Loaded {len(table_map)} table(s), cached at {db_path}")
    return con, table_map


def run_query(con, sql: str, table_map: dict[str, str]):
    """Run SQL and return (columns, rows). Raises on error."""
    modified_sql = sql
    for orig, tbl in sorted(table_map.items(), key=lambda x: len(x[0]), reverse=True):
        if orig != tbl:
            modified_sql = re.sub(rf"\b{re.escape(orig)}\b", f'"{tbl}"', modified_sql)
    result = con.execute(modified_sql)
    columns = [desc[0] for desc in result.description]
    rows = result.fetchall()
    return columns, rows


def to_json_safe(val):
    """Convert a value to JSON-safe type."""
    if val is None:
        return None
    if isinstance(val, (int, float, str, bool)):
        return val
    if hasattr(val, "isoformat"):
        return val.isoformat()
    return str(val)


# ---------------------------------------------------------------------------
# Action: inspect
# ---------------------------------------------------------------------------

def action_inspect(con, table_map):
    """Print schema and sample data for all tables."""
    output = []
    for orig, tbl in table_map.items():
        row_count = con.execute(f'SELECT COUNT(*) FROM "{tbl}"').fetchone()[0]
        columns = con.execute(f'DESCRIBE "{tbl}"').fetchall()

        output.append(f"\n{'='*60}")
        output.append(f'Table: {orig} (SQL name: "{tbl}")')
        output.append(f"Rows: {row_count}")
        output.append(f"\nColumns ({len(columns)}):")
        output.append(f"{'Name':<30} {'Type':<15}")
        output.append(f"{'-'*30} {'-'*15}")
        for col in columns:
            output.append(f"{col[0]:<30} {col[1]:<15}")

        # Sample
        output.append(f"\nSample (first 5 rows):")
        sample = con.execute(f'SELECT * FROM "{tbl}" LIMIT 5').fetchall()
        header = [c[0] for c in columns]
        output.append("  " + " | ".join(header))
        for row in sample:
            output.append("  " + " | ".join(str(v) for v in row))

    result = "\n".join(output)
    print(result)
    return result


# ---------------------------------------------------------------------------
# Action: query — run SQL, return as JSON array-of-arrays (for dataset.source)
# ---------------------------------------------------------------------------

def action_query(con, sql, table_map, output_file=None):
    """Run SQL and print results as JSON array-of-arrays (dataset.source format)."""
    try:
        columns, rows = run_query(con, sql, table_map)
    except Exception as e:
        available = ", ".join(f'"{t}" ({o})' for o, t in table_map.items())
        error_msg = f"SQL Error: {e}\nAvailable tables: {available}"
        print(error_msg)
        return error_msg

    # Build array-of-arrays: [[col1, col2, ...], [val1, val2, ...], ...]
    source = [columns]
    for row in rows:
        source.append([to_json_safe(v) for v in row])

    result = json.dumps(source, ensure_ascii=False, default=str)

    if output_file:
        os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(result)
        print(f"Results written to {output_file} ({len(rows)} rows)")
    else:
        print(result)

    return result


# ---------------------------------------------------------------------------
# Action: generate — build a TipTap dashboard from a plan
# ---------------------------------------------------------------------------

def action_generate(con, table_map, plan: dict, output_file: str):
    """
    Generate a TipTap dashboard JSON from a plan.

    Plan format:
    {
      "title": "Dashboard Title",
      "metrics": [
        {"label": "Total Revenue", "sql": "SELECT ...", "format": "$", "change_sql": "SELECT ..."}
      ],
      "charts": [
        {
          "title": "Chart Title",
          "type": "line",  // line, bar, pie, scatter, area, heatmap, radar, funnel, gauge, etc.
          "sql": "SELECT category, value FROM ...",
          "options": {}  // optional extra ECharts options to merge
        }
      ]
    }
    """
    content = []

    # --- Metrics row ---
    if plan.get("metrics"):
        metrics = []
        for m in plan["metrics"]:
            value = ""
            change = None
            if m.get("sql"):
                try:
                    _, rows = run_query(con, m["sql"], table_map)
                    if rows and rows[0]:
                        raw = rows[0][0]
                        value = format_metric_value(raw, m.get("format", ""))
                except Exception as e:
                    value = f"Error: {e}"

            if m.get("change_sql"):
                try:
                    _, rows = run_query(con, m["change_sql"], table_map)
                    if rows and rows[0] and rows[0][0] is not None:
                        raw = float(rows[0][0])
                        sign = "+" if raw >= 0 else ""
                        change = f"{sign}{raw:.1f}%"
                except Exception:
                    pass

            metrics.append({
                "metricId": str(uuid.uuid4())[:8],
                "label": m.get("label", "Metric"),
                "value": value,
                "change": change,
            })

        content.append({
            "type": "metricRowNode",
            "attrs": {"metrics": metrics},
        })

    # --- Charts ---
    for chart_spec in plan.get("charts", []):
        chart_title = chart_spec.get("title", "Chart")
        chart_type = chart_spec.get("type", "bar")
        sql = chart_spec.get("sql", "")

        if not sql:
            continue

        # Add heading
        content.append({
            "type": "heading",
            "attrs": {"level": 3},
            "content": [{"type": "text", "text": chart_title}],
        })

        # Run query to get data
        try:
            columns, rows = run_query(con, sql, table_map)
        except Exception as e:
            content.append({
                "type": "paragraph",
                "content": [{"type": "text", "text": f"Error loading data: {e}"}],
            })
            continue

        # Build dataset.source
        source = [columns]
        for row in rows:
            source.append([to_json_safe(v) for v in row])

        # Build ECharts option
        option = build_echart_option(chart_type, columns, source, chart_spec.get("options"))

        content.append({
            "type": "chartNode",
            "attrs": {
                "chartId": str(uuid.uuid4())[:8],
                "title": chart_title,
                "option": option,
            },
        })

    # Add trailing empty paragraph
    content.append({"type": "paragraph"})

    # Build TipTap doc
    doc = {"type": "doc", "content": content}

    # Write output
    os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False, default=str)

    print(json.dumps(doc, indent=2, ensure_ascii=False, default=str))
    logger.info(f"\nDashboard written to {output_file}")
    return doc


# ---------------------------------------------------------------------------
# Action: update — read existing dashboard, apply changes, write back
# ---------------------------------------------------------------------------

def action_update(con, table_map, plan: dict, dashboard_path: str):
    """Read existing dashboard, apply plan updates, write back."""
    existing = {"type": "doc", "content": []}
    if os.path.exists(dashboard_path):
        with open(dashboard_path, "r", encoding="utf-8") as f:
            existing = json.load(f)

    # Generate new content from plan
    new_doc = action_generate(con, table_map, plan, dashboard_path)
    return new_doc


# ---------------------------------------------------------------------------
# ECharts option builder
# ---------------------------------------------------------------------------

DEFAULT_PALETTE = ["#2563eb", "#3b82f6", "#60a5fa", "#93c5fd", "#bfdbfe", "#dbeafe"]


def build_echart_option(chart_type: str, columns: list[str], source: list, extra_options: dict | None = None) -> dict:
    """Build a complete ECharts option for the given chart type."""
    option = {
        "tooltip": {},
        "dataset": {"source": source},
        "color": DEFAULT_PALETTE,
    }

    if chart_type in ("line", "area"):
        option["tooltip"]["trigger"] = "axis"
        option["grid"] = {"containLabel": True, "left": 12, "right": 12, "bottom": 32, "top": 16}
        option["xAxis"] = {"type": "category"}
        option["yAxis"] = {"type": "value"}
        series = []
        for col in columns[1:]:
            s = {"type": "line", "smooth": True, "encode": {"x": columns[0], "y": col}}
            if chart_type == "area":
                s["areaStyle"] = {"opacity": 0.15}
            series.append(s)
        option["series"] = series

    elif chart_type in ("bar", "column"):
        option["tooltip"]["trigger"] = "axis"
        option["grid"] = {"containLabel": True, "left": 12, "right": 12, "bottom": 32, "top": 16}
        option["xAxis"] = {"type": "category"}
        option["yAxis"] = {"type": "value"}
        option["series"] = [
            {"type": "bar", "encode": {"x": columns[0], "y": col}, "itemStyle": {"borderRadius": 4}}
            for col in columns[1:]
        ]

    elif chart_type == "horizontal_bar":
        option["tooltip"]["trigger"] = "axis"
        option["grid"] = {"containLabel": True, "left": 12, "right": 12, "bottom": 32, "top": 16}
        option["xAxis"] = {"type": "value"}
        option["yAxis"] = {"type": "category"}
        option["series"] = [
            {"type": "bar", "encode": {"y": columns[0], "x": col}, "itemStyle": {"borderRadius": 4}}
            for col in columns[1:]
        ]

    elif chart_type in ("pie", "donut"):
        option["tooltip"]["trigger"] = "item"
        s = {"type": "pie", "encode": {"itemName": columns[0], "value": columns[1]}}
        if chart_type == "donut":
            s["radius"] = ["40%", "70%"]
        option["series"] = [s]

    elif chart_type == "scatter":
        option["tooltip"]["trigger"] = "item"
        option["grid"] = {"containLabel": True}
        option["xAxis"] = {"type": "value", "name": columns[0] if columns else ""}
        option["yAxis"] = {"type": "value", "name": columns[1] if len(columns) > 1 else ""}
        option["series"] = [{"type": "scatter", "encode": {"x": columns[0], "y": columns[1]} if len(columns) > 1 else {}}]

    elif chart_type == "radar":
        option["tooltip"]["trigger"] = "item"
        # Radar needs indicator from column names (skip first = label column)
        indicators = [{"name": col} for col in columns[1:]]
        option["radar"] = {"indicator": indicators}
        # Build series data from rows
        series_data = []
        for row in source[1:]:
            series_data.append({"name": to_json_safe(row[0]), "value": [to_json_safe(v) for v in row[1:]]})
        option["series"] = [{"type": "radar", "data": series_data}]
        # Remove dataset for radar (uses series.data directly)
        del option["dataset"]

    elif chart_type == "funnel":
        option["tooltip"]["trigger"] = "item"
        option["series"] = [{"type": "funnel", "encode": {"itemName": columns[0], "value": columns[1]}}]

    elif chart_type == "heatmap":
        option["tooltip"]["trigger"] = "item"
        option["grid"] = {"containLabel": True}
        option["xAxis"] = {"type": "category"}
        option["yAxis"] = {"type": "category"}
        option["visualMap"] = {"min": 0, "max": 100, "calculable": True}
        option["series"] = [{"type": "heatmap", "encode": {"x": columns[0], "y": columns[1], "value": columns[2]} if len(columns) > 2 else {}}]

    elif chart_type == "gauge":
        option["tooltip"]["trigger"] = "item"
        # Gauge uses first row, first value column
        val = to_json_safe(source[1][1]) if len(source) > 1 and len(source[1]) > 1 else 0
        option["series"] = [{"type": "gauge", "data": [{"value": val, "name": columns[1] if len(columns) > 1 else "Value"}]}]
        del option["dataset"]

    elif chart_type == "stacked_bar":
        option["tooltip"]["trigger"] = "axis"
        option["grid"] = {"containLabel": True, "left": 12, "right": 12, "bottom": 32, "top": 16}
        option["xAxis"] = {"type": "category"}
        option["yAxis"] = {"type": "value"}
        option["series"] = [
            {"type": "bar", "stack": "total", "encode": {"x": columns[0], "y": col}, "itemStyle": {"borderRadius": 0}}
            for col in columns[1:]
        ]

    elif chart_type == "treemap":
        option["tooltip"]["trigger"] = "item"
        # Build tree data from source
        tree_data = []
        for row in source[1:]:
            tree_data.append({"name": to_json_safe(row[0]), "value": to_json_safe(row[1]) if len(row) > 1 else 0})
        option["series"] = [{"type": "treemap", "data": tree_data}]
        del option["dataset"]

    elif chart_type == "sankey":
        option["tooltip"]["trigger"] = "item"
        # Expect columns: source, target, value
        nodes_set = set()
        links = []
        for row in source[1:]:
            src, tgt = to_json_safe(row[0]), to_json_safe(row[1])
            val = to_json_safe(row[2]) if len(row) > 2 else 1
            nodes_set.add(src)
            nodes_set.add(tgt)
            links.append({"source": src, "target": tgt, "value": val})
        nodes = [{"name": n} for n in nodes_set]
        option["series"] = [{"type": "sankey", "data": nodes, "links": links}]
        del option["dataset"]

    else:
        # Default: bar chart
        option["tooltip"]["trigger"] = "axis"
        option["grid"] = {"containLabel": True}
        option["xAxis"] = {"type": "category"}
        option["yAxis"] = {"type": "value"}
        option["series"] = [
            {"type": "bar", "encode": {"x": columns[0], "y": col}, "itemStyle": {"borderRadius": 4}}
            for col in columns[1:]
        ]

    # Merge extra options if provided
    if extra_options:
        option = deep_merge(option, extra_options)

    return option


def deep_merge(base: dict, override: dict) -> dict:
    """Deep merge override into base."""
    result = base.copy()
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = deep_merge(result[key], val)
        else:
            result[key] = val
    return result


def format_metric_value(raw, fmt: str = "") -> str:
    """Format a raw numeric value for display in a metric card."""
    if raw is None:
        return "N/A"
    try:
        num = float(raw)
    except (TypeError, ValueError):
        return str(raw)

    if fmt == "%":
        return f"{num:.1f}%"

    prefix = ""
    if "$" in fmt:
        prefix = "$"

    abs_num = abs(num)
    if abs_num >= 1_000_000_000:
        formatted = f"{num / 1_000_000_000:.1f}B"
    elif abs_num >= 1_000_000:
        formatted = f"{num / 1_000_000:.1f}M"
    elif abs_num >= 1_000:
        formatted = f"{num / 1_000:.1f}K"
    else:
        formatted = f"{num:,.2f}" if isinstance(raw, float) else f"{num:,.0f}"

    return f"{prefix}{formatted}"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="AI Graphs Dashboard Generator")
    parser.add_argument("--files", nargs="+", required=True, help="CSV/Excel file paths")
    parser.add_argument("--action", required=True, choices=["inspect", "query", "generate", "update"],
                        help="Action: inspect, query, generate, update")
    parser.add_argument("--sql", type=str, default=None, help="SQL query (for 'query' action)")
    parser.add_argument("--plan", type=str, default=None,
                        help="JSON plan for dashboard generation (for 'generate'/'update' actions)")
    parser.add_argument("--output", type=str, default="/mnt/user-data/outputs/dashboard.json",
                        help="Output file path (default: /mnt/user-data/outputs/dashboard.json)")
    parser.add_argument("--dashboard", type=str, default=None,
                        help="Existing dashboard path (for 'update' action)")
    args = parser.parse_args()

    if args.action == "query" and not args.sql:
        parser.error("--sql is required for 'query' action")
    if args.action in ("generate", "update") and not args.plan:
        parser.error("--plan is required for 'generate'/'update' actions")

    con, table_map = get_connection(args.files)

    try:
        if args.action == "inspect":
            action_inspect(con, table_map)
        elif args.action == "query":
            action_query(con, args.sql, table_map)
        elif args.action == "generate":
            plan = json.loads(args.plan)
            action_generate(con, table_map, plan, args.output)
        elif args.action == "update":
            plan = json.loads(args.plan)
            dashboard = args.dashboard or args.output
            action_update(con, table_map, plan, dashboard)
    finally:
        con.close()


if __name__ == "__main__":
    main()
