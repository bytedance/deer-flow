"""
History Viewer Module.

Provides functions to view import history, table structures, and table relationships
in markdown table format.
"""

import json
import os
import sys
from typing import Optional

import structlog

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import DatabaseRepository
from validators import quote_identifier, validate_table_name

logger = structlog.get_logger(__name__)


def format_markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    """Format headers and rows as an aligned markdown table.

    Args:
        headers: Column header strings.
        rows: List of row data, each row is a list of strings.

    Returns:
        A properly formatted markdown table string.
    """
    if not headers:
        return ""

    # Calculate column widths
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            if i < len(col_widths):
                col_widths[i] = max(col_widths[i], len(str(cell)))

    def format_row(cells: list[str]) -> str:
        padded = []
        for i, cell in enumerate(cells):
            width = col_widths[i] if i < len(col_widths) else len(str(cell))
            padded.append(str(cell).ljust(width))
        return "| " + " | ".join(padded) + " |"

    # Build table
    lines = [
        format_row(headers),
        format_row(["-" * w for w in col_widths]),
    ]
    for row in rows:
        lines.append(format_row(row))

    return "\n".join(lines)


def view_import_history(db_path: str = "workspace.duckdb", limit: int = 20) -> str:
    """View recent import history as a markdown table.

    Args:
        db_path: Path to the DuckDB database file.
        limit: Maximum number of records to return.

    Returns:
        Markdown formatted table of import history.
    """
    if not os.path.exists(db_path):
        return "暂无导入历史记录。数据库文件不存在。"

    repo = DatabaseRepository(db_path)

    try:
        with repo.connection() as conn:
            # Check if _data_skill_meta exists
            tables = conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_name = '_data_skill_meta'"
            ).fetchall()
            if not tables:
                return "暂无导入历史记录。"

            # Check if parent_tables column exists (for merge tracking)
            columns = conn.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = '_data_skill_meta'"
            ).fetchall()
            column_names = {row[0] for row in columns}
            has_parent_tables = "parent_tables" in column_names
            has_row_count = "row_count" in column_names
            has_file_path = "file_path" in column_names

            # Build query
            select_cols = [
                "file_name",
                "table_name",
                "COALESCE(row_count, 0) as row_count" if has_row_count else "0 as row_count",
                "strftime(import_time, '%Y-%m-%d %H:%M') as import_time",
            ]
            if has_file_path:
                select_cols.append("file_path")
            if has_parent_tables:
                select_cols.append("parent_tables")

            query = f"SELECT {', '.join(select_cols)} FROM _data_skill_meta ORDER BY import_time DESC LIMIT ?"
            rows = conn.execute(query, (limit,)).fetchall()

            if not rows:
                return "暂无导入历史记录。"

            # Build headers and data
            if has_parent_tables and has_file_path:
                headers = ["文件名", "表名", "行数", "导入时间", "文件路径", "来源"]
            elif has_parent_tables:
                headers = ["文件名", "表名", "行数", "导入时间", "来源"]
            elif has_file_path:
                headers = ["文件名", "表名", "行数", "导入时间", "文件路径"]
            else:
                headers = ["文件名", "表名", "行数", "导入时间"]

            data_rows = []
            for row in rows:
                idx = 0
                file_name = str(row[idx]); idx += 1
                table_name = str(row[idx]); idx += 1
                row_count = str(row[idx]); idx += 1
                import_time = str(row[idx]); idx += 1

                record = [file_name, table_name, row_count, import_time]

                if has_file_path:
                    file_path = str(row[idx]) if row[idx] else ""
                    idx += 1
                    # Truncate long paths
                    if len(file_path) > 60:
                        file_path = "..." + file_path[-57:]
                    record.append(file_path)

                if has_parent_tables:
                    parent_tables = row[idx] if idx < len(row) else None
                    if parent_tables:
                        try:
                            parents = json.loads(parent_tables)
                            record.append(", ".join(parents))
                        except (json.JSONDecodeError, TypeError):
                            record.append(parent_tables)
                    else:
                        record.append("")

                data_rows.append(record)

            markdown = "## 导入历史\n\n" + format_markdown_table(headers, data_rows)
            logger.info("导入历史查询完成", records=len(data_rows))
            return markdown

    except Exception as e:
        logger.error("导入历史查询失败", error=str(e))
        return f"查询导入历史时出错: {e}"


def view_table_structure(db_path: str = "workspace.duckdb", table_name: Optional[str] = None) -> str:
    """View table structure(s) as markdown tables.

    Args:
        db_path: Path to the DuckDB database file.
        table_name: Specific table name, or None to list all user tables.

    Returns:
        Markdown formatted table(s) of table structure(s).
    """
    if not os.path.exists(db_path):
        return "数据库文件不存在。"

    repo = DatabaseRepository(db_path)

    try:
        with repo.connection() as conn:
            if table_name:
                # Show structure for specific table
                return _show_single_table_structure(conn, table_name)
            else:
                # List all user tables and their structures
                return _show_all_table_structures(conn)

    except Exception as e:
        logger.error("表结构查询失败", error=str(e))
        return f"查询表结构时出错: {e}"


def _show_single_table_structure(conn, table_name: str) -> str:
    """Show structure for a single table."""
    table_name = validate_table_name(table_name)
    # Check if table exists
    exists = conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_name = ? AND table_schema = 'main'",
        (table_name,)
    ).fetchone()

    if not exists:
        return f"表 '{table_name}' 不存在。"

    # Get columns
    columns = conn.execute(
        """
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_name = ? AND table_schema = 'main'
        ORDER BY ordinal_position
        """,
        (table_name,)
    ).fetchall()

    # Get row count
    row_count = conn.execute(f"SELECT COUNT(*) FROM {quote_identifier(table_name)}").fetchone()[0]

    headers = ["列名", "类型", "可空"]
    data_rows = []
    for col in columns:
        col_name, data_type, is_nullable = col
        data_rows.append([col_name, data_type, is_nullable])

    markdown = f"## 表结构: {table_name}\n\n"
    markdown += f"**行数:** {row_count}\n\n"
    markdown += format_markdown_table(headers, data_rows)

    logger.info("表结构查询完成", table=table_name, columns=len(columns), rows=row_count)
    return markdown


def _show_all_table_structures(conn) -> str:
    """Show structures for all user tables."""
    # Get all user tables (exclude _data_skill_meta and tables starting with _)
    tables = conn.execute(
        """
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'main' AND table_name != '_data_skill_meta' AND table_name NOT LIKE '\\_%'
        ORDER BY table_name
        """
    ).fetchall()

    if not tables:
        return "暂无用户表。"

    sections = []
    for (table_name,) in tables:
        sections.append(_show_single_table_structure(conn, table_name))

    return "\n\n---\n\n".join(sections)


def view_table_relationships(db_path: str = "workspace.duckdb") -> str:
    """View table relationships (parent → child) as a markdown table.

    Args:
        db_path: Path to the DuckDB database file.

    Returns:
        Markdown formatted table of table relationships.
    """
    if not os.path.exists(db_path):
        return "数据库文件不存在。"

    repo = DatabaseRepository(db_path)

    try:
        with repo.connection() as conn:
            # Check if _data_skill_meta exists
            tables = conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_name = '_data_skill_meta'"
            ).fetchall()
            if not tables:
                return "暂无表关联记录。"

            # Check if parent_tables column exists
            columns = conn.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = '_data_skill_meta'"
            ).fetchall()
            column_names = {row[0] for row in columns}

            if "parent_tables" not in column_names:
                return "暂无表关联记录。"

            # Check if row_count column exists
            has_row_count = "row_count" in column_names

            # Query tables with parent_tables
            select_cols = ["table_name", "parent_tables"]
            if has_row_count:
                select_cols.insert(1, "COALESCE(row_count, 0) as row_count")
            else:
                select_cols.insert(1, "0 as row_count")
            select_cols.append("strftime(import_time, '%Y-%m-%d %H:%M') as import_time")

            query = f"""
                SELECT {', '.join(select_cols)}
                FROM _data_skill_meta
                WHERE parent_tables IS NOT NULL
                ORDER BY import_time DESC
            """
            rows = conn.execute(query).fetchall()

            if not rows:
                return "暂无表关联记录。"

            headers = ["目标表", "来源表", "行数", "创建时间"]
            data_rows = []
            for row in rows:
                target_table = str(row[0])
                row_count = str(row[1])
                parent_tables_json = row[2]
                import_time = str(row[3])

                # Parse parent tables JSON
                try:
                    parents = json.loads(parent_tables_json)
                    source_tables = ", ".join(parents)
                except (json.JSONDecodeError, TypeError):
                    source_tables = str(parent_tables_json)

                data_rows.append([target_table, source_tables, row_count, import_time])

            markdown = "## 表关联关系\n\n" + format_markdown_table(headers, data_rows)
            logger.info("表关联查询完成", relationships=len(data_rows))
            return markdown

    except Exception as e:
        logger.error("表关联查询失败", error=str(e))
        return f"查询表关联关系时出错: {e}"


def main():
    """CLI entry point for history viewer."""
    import argparse

    parser = argparse.ArgumentParser(
        description="查看导入历史、表结构和表关联关系"
    )
    subparsers = parser.add_subparsers(dest="command", help="查看命令")

    # History subparser
    history_parser = subparsers.add_parser("history", help="查看导入历史")
    history_parser.add_argument("--db", default="workspace.duckdb", help="数据库路径")
    history_parser.add_argument("--limit", type=int, default=20, help="显示记录数")

    # Structure subparser
    structure_parser = subparsers.add_parser("structure", help="查看表结构")
    structure_parser.add_argument("--db", default="workspace.duckdb", help="数据库路径")
    structure_parser.add_argument("--table", default=None, help="指定表名")

    # Relationships subparser
    rel_parser = subparsers.add_parser("relationships", help="查看表关联关系")
    rel_parser.add_argument("--db", default="workspace.duckdb", help="数据库路径")

    # Show all subparser
    show_parser = subparsers.add_parser("show", help="一键查看全部信息")
    show_parser.add_argument("--db", default="workspace.duckdb", help="数据库路径")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return

    if args.command == "history":
        print(view_import_history(args.db, args.limit))
    elif args.command == "structure":
        print(view_table_structure(args.db, args.table))
    elif args.command == "relationships":
        print(view_table_relationships(args.db))
    elif args.command == "show":
        output = []
        output.append(view_import_history(args.db))
        output.append("")
        output.append(view_table_structure(args.db))
        output.append("")
        output.append(view_table_relationships(args.db))
        print("\n".join(output))


if __name__ == "__main__":
    main()
