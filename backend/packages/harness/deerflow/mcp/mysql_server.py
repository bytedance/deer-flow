"""MCP server providing MySQL database query tools (read-only).

Run as a stdio MCP server:
    uv run python -m deerflow.mcp.mysql_server

Required environment variables:
    MYSQL_HOST     - MySQL host (default: host.docker.internal)
    MYSQL_PORT     - MySQL port (default: 3306)
    MYSQL_DATABASE - Database name (default: ragflow_mcp)
    MYSQL_USER     - MySQL user (default: root)
    MYSQL_PASSWORD - MySQL password
"""

import logging
import os
import re

import pymysql
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────

def _load_config() -> dict:
    """Load MySQL configuration from environment variables."""
    config = {
        "host": os.environ.get("MYSQL_HOST", "host.docker.internal"),
        "port": int(os.environ.get("MYSQL_PORT", "3306")),
        "database": os.environ.get("MYSQL_DATABASE", "ragflow_mcp"),
        "user": os.environ.get("MYSQL_USER", "root"),
        "password": os.environ.get("MYSQL_PASSWORD", ""),
        "charset": "utf8mb4",
        "cursorclass": pymysql.cursors.DictCursor,
    }
    logger.info(
        "[MySQL MCP] Config loaded: host=%s, port=%d, db=%s, user=%s",
        config["host"], config["port"], config["database"], config["user"],
    )
    return config


# ── Safety Guardrails ────────────────────────────────────────────────────────

_FORBIDDEN_PATTERNS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|REPLACE|GRANT|REVOKE|LOAD|CALL)\b",
    re.IGNORECASE,
)

_MAX_ROWS = 200


def _validate_query(sql: str) -> str | None:
    """Return an error message if the query violates read-only policy, else None."""
    if _FORBIDDEN_PATTERNS.search(sql):
        return (
            "Error: This query contains write operations (INSERT/UPDATE/DELETE/DROP/etc.). "
            "Only SELECT queries are allowed."
        )
    return None


# ── Result Formatting ────────────────────────────────────────────────────────

def _format_as_markdown_table(rows: list[dict], truncated: bool = False) -> str:
    """Format query results as a Markdown table with a header row."""
    if not rows:
        return "Query executed successfully. No results returned."

    columns = list(rows[0].keys())
    lines = []

    # Header
    lines.append("| " + " | ".join(str(c) for c in columns) + " |")
    lines.append("| " + " | ".join("---" for _ in columns) + " |")

    # Data rows
    display_rows = rows[:_MAX_ROWS]
    for row in display_rows:
        values = [str(row.get(c, ""))[:200] for c in columns]
        lines.append("| " + " | ".join(values) + " |")

    if truncated and len(rows) > _MAX_ROWS:
        lines.append("")
        lines.append(f"*Result truncated to {_MAX_ROWS} rows (total: {len(rows)} rows).*")

    return "\n".join(lines)


# ── MCP Server ───────────────────────────────────────────────────────────────

mcp = FastMCP(
    name="mysql",
    instructions=(
        "MySQL database read-only query tools. "
        "Use list_tables to discover tables, describe_table to understand schema, "
        "and execute_query to run SELECT queries."
    ),
)


@mcp.tool()
def list_tables() -> str:
    """List all tables in the current database.

    Returns a formatted list of table names. Use this to discover
    available tables before querying or describing specific tables.
    """
    logger.info("[MySQL MCP] list_tables: called")
    try:
        cfg = _load_config()
        conn = pymysql.connect(**cfg)
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT TABLE_NAME, TABLE_COMMENT "
                "FROM information_schema.TABLES "
                "WHERE TABLE_SCHEMA = %s AND TABLE_TYPE = 'BASE TABLE' "
                "ORDER BY TABLE_NAME",
                (cfg["database"],),
            )
            tables = cursor.fetchall()
        conn.close()

        if not tables:
            return f"No tables found in database '{cfg['database']}'."

        lines = [f"## Tables in database '{cfg['database']}'\n"]
        for t in tables:
            comment = t.get("TABLE_COMMENT", "") or "No comment"
            lines.append(f"- **{t['TABLE_NAME']}** - {comment}")
        result = "\n".join(lines)
        logger.info("[MySQL MCP] list_tables: Found %d tables", len(tables))
        return result

    except pymysql.MySQLError as e:
        return f"MySQL Error: {e}"
    except Exception as e:
        return f"Error listing tables: {type(e).__name__}: {e}"


@mcp.tool()
def describe_table(table_name: str) -> str:
    """Get the schema (columns, types, nullable, keys) of a specific table.

    Args:
        table_name: Name of the table to describe (required).

    Returns a formatted description of table columns including column name,
    data type, whether it is nullable, key information, and default values.
    """
    logger.info("[MySQL MCP] describe_table: table=%s", table_name)
    try:
        cfg = _load_config()
        conn = pymysql.connect(**cfg)
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, COLUMN_KEY, "
                "COLUMN_DEFAULT, EXTRA, COLUMN_COMMENT "
                "FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s "
                "ORDER BY ORDINAL_POSITION",
                (cfg["database"], table_name),
            )
            columns = cursor.fetchall()
        conn.close()

        if not columns:
            return f"Table '{table_name}' not found in database '{cfg['database']}'."

        lines = [f"## Schema for table '{table_name}'\n"]
        lines.append("| Column | Type | Nullable | Key | Default | Extra |")
        lines.append("|---|---|---|---|---|---|")
        for c in columns:
            lines.append(
                f"| {c['COLUMN_NAME']} "
                f"| {c['DATA_TYPE']} "
                f"| {c['IS_NULLABLE']} "
                f"| {c['COLUMN_KEY']} "
                f"| {c['COLUMN_DEFAULT'] or 'NULL'} "
                f"| {c.get('EXTRA', '')} "
                f"|"
            )
        result = "\n".join(lines)
        logger.info("[MySQL MCP] describe_table: %d columns", len(columns))
        return result

    except pymysql.MySQLError as e:
        return f"MySQL Error: {e}"
    except Exception as e:
        return f"Error describing table: {type(e).__name__}: {e}"


@mcp.tool()
def execute_query(sql: str, limit: int = 100) -> str:
    """Execute a read-only SQL SELECT query against the database.

    Args:
        sql: The SELECT SQL query to execute (required).
        limit: Maximum number of rows to return (default: 100, max: 500).

    Only SELECT queries are allowed. Write operations (INSERT, UPDATE,
    DELETE, DROP, etc.) will be rejected. Results are returned as a
    Markdown table. Large results are truncated to 200 rows.
    """
    logger.info("[MySQL MCP] execute_query: sql='%s', limit=%d", sql.strip()[:100], limit)

    error = _validate_query(sql)
    if error:
        logger.warning("[MySQL MCP] execute_query: blocked - %s", error)
        return error

    limit = min(max(limit, 1), 500)

    try:
        cfg = _load_config()
        conn = pymysql.connect(**cfg)
        with conn.cursor() as cursor:
            try:
                cursor.execute("SET SESSION sql_read_only = 1")
            except pymysql.MySQLError:
                pass

        with conn.cursor() as cursor:
            cursor.execute(sql)
            rows = cursor.fetchall()
        conn.close()

        logger.info("[MySQL MCP] execute_query: %d rows returned", len(rows))
        return _format_as_markdown_table(rows, truncated=len(rows) > _MAX_ROWS)

    except pymysql.MySQLError as e:
        return f"MySQL Error: {e}"
    except Exception as e:
        return f"Error executing query: {type(e).__name__}: {e}"


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=__import__("sys").stderr,
    )
    mcp.run(transport="stdio")
