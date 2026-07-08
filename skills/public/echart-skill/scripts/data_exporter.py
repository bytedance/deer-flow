import argparse
import pandas as pd
import os
import sys

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import get_repository
from validators import quote_identifier, validate_table_name
from logging_config import get_logger, configure_logging

# Initialize logging
configure_logging()
logger = get_logger(__name__)

def export_data(db_path, output_path, table_name=None, query=None):
    """
    Export data from DuckDB to a CSV or Excel file.
    Either table_name or query must be provided.
    """
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Database file not found: {db_path}")

    if not table_name and not query:
        raise ValueError("Either table_name or query must be provided.")

    repo = get_repository(db_path)

    try:
        with repo.connection() as conn:
            if query:
                logger.info("执行查询", query_summary=query[:100] if query else None)
                df = pd.read_sql_query(query, conn)
            else:
                # Validate table name to prevent SQL injection
                table_name = validate_table_name(table_name)
                logger.info("读取表", table_name=table_name)
                df = pd.read_sql_query(f"SELECT * FROM {quote_identifier(table_name)}", conn)

        # Determine export format based on file extension
        ext = os.path.splitext(output_path)[1].lower()

        # Ensure output directory exists
        out_dir = os.path.dirname(output_path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)

        if ext == '.csv':
            df.to_csv(output_path, index=False, encoding='utf-8-sig')
            logger.info("导出完成", rows=len(df), output_path=output_path, format="csv")
        elif ext in ['.xlsx', '.xls']:
            df.to_excel(output_path, index=False)
            logger.info("导出完成", rows=len(df), output_path=output_path, format="excel")
        else:
            raise ValueError(f"Unsupported output format: {ext}. Please use .csv or .xlsx")

    except ValueError:
        # Re-raise validation errors (e.g., invalid table name)
        raise
    except Exception as e:
        logger.error("导出失败", error=str(e), output_path=output_path)
        sys.exit(1)

if __name__ == "__main__":  # pragma: no cover
    parser = argparse.ArgumentParser(description="Export data from DuckDB to CSV or Excel")
    parser.add_argument("output_path", help="Path to save the output file (.csv or .xlsx)")
    parser.add_argument("--db", default="workspace.duckdb", help="Path to DuckDB database file")
    parser.add_argument("--table", help="Name of the table to export")
    parser.add_argument("--query", help="SQL query to execute and export")

    args = parser.parse_args()
    export_data(args.db, args.output_path, args.table, args.query)
