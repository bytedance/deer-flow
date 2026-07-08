"""
Data Merger Module.

Provides functionality to merge multiple DuckDB tables into one and export/import merged data.
"""

import argparse
import json
import sys
import os
from datetime import datetime
from typing import Optional

import pandas as pd
import structlog
from pydantic import BaseModel, Field, field_validator

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import get_repository
from scripts.data_importer import init_meta_table
from validators import quote_identifier, validate_table_name

logger = structlog.get_logger(__name__)

def record_merge(conn, source_tables: list[str], target_table: str, row_count: int):
    """Record merge operation metadata with parent table relationships."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute('''
        INSERT OR REPLACE INTO _data_skill_meta
        (file_name, table_name, import_time, last_used_time, parent_tables, row_count)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (
        f"merge: {', '.join(source_tables)}",
        target_table,
        now, now,
        json.dumps(source_tables),
        row_count
    ))
    conn.commit()


class MergeConfig(BaseModel):
    """Configuration for table merge operation."""

    source_tables: list[str] = Field(..., min_length=2, description="Tables to merge (at least 2)")
    target_table: str = Field(..., description="Name for merged table")
    db_path: str = Field(default="workspace.duckdb", description="Database path")
    export_file: Optional[str] = Field(default=None, description="Export to file (CSV/Excel)")

    @field_validator('source_tables')
    @classmethod
    def validate_source_tables(cls, v: list[str]) -> list[str]:
        """Validate source tables have at least 2 items and no duplicates."""
        if len(v) < 2:
            raise ValueError("source_tables must have at least 2 tables to merge")
        if len(set(v)) != len(v):
            raise ValueError("Duplicate table names in source_tables")
        return v

    @field_validator('source_tables')
    @classmethod
    def validate_table_names(cls, v: list[str]) -> list[str]:
        """Validate each table name is valid."""
        return [validate_table_name(table) for table in v]

    @field_validator('target_table')
    @classmethod
    def validate_target_table(cls, v: str) -> str:
        return validate_table_name(v)


class DataMerger:
    """Merge multiple DuckDB tables into one."""

    def __init__(self, config: MergeConfig):
        self.config = config
        self.repo = get_repository(config.db_path)

    def validate_source_tables(self) -> None:
        """Validate that all source tables exist in the database.

        Raises:
            ValueError: If any source table does not exist
        """
        with self.repo.connection() as conn:
            existing_tables_result = conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
            ).fetchall()
            existing_tables = {row[0] for row in existing_tables_result}

        missing = set(self.config.source_tables) - existing_tables
        if missing:
            raise ValueError(f"Source tables not found: {', '.join(missing)}")

    def merge_tables(self) -> pd.DataFrame:
        """Merge all source tables into one DataFrame.

        Returns:
            DataFrame with merged data and _source_table column

        Raises:
            ValueError: If any source table does not exist
        """
        self.validate_source_tables()

        dfs = []

        for table in self.config.source_tables:
            with self.repo.connection() as conn:
                df = pd.read_sql_query(f"SELECT * FROM {quote_identifier(table)}", conn)
                df['_source_table'] = table
                dfs.append(df)
                logger.info("读取源表", table=table, rows=len(df))

        # Concatenate all DataFrames
        merged = pd.concat(dfs, ignore_index=True)
        logger.info("合并完成", total_rows=len(merged), tables=len(dfs))

        return merged

    def save_to_database(self, df: pd.DataFrame) -> None:
        """Save merged DataFrame to DuckDB.

        Args:
            df: DataFrame to save
        """
        with self.repo.connection() as conn:
            target_table = quote_identifier(self.config.target_table)
            conn.register("_merged_df", df)
            try:
                conn.execute(f"CREATE OR REPLACE TABLE {target_table} AS SELECT * FROM _merged_df")
            finally:
                conn.unregister("_merged_df")
            init_meta_table(conn)
            record_merge(conn, self.config.source_tables, self.config.target_table, len(df))
            logger.info("保存到数据库", table=self.config.target_table, rows=len(df))

    def export_to_file(self, df: pd.DataFrame) -> None:
        """Export merged DataFrame to file.

        Args:
            df: DataFrame to export

        Raises:
            ValueError: If no export_file specified or unsupported format
        """
        if not self.config.export_file:
            raise ValueError("No export file specified")

        export_path = self.config.export_file

        if export_path.endswith('.xlsx'):
            df.to_excel(export_path, index=False)
        elif export_path.endswith('.csv'):
            df.to_csv(export_path, index=False)
        else:
            raise ValueError(f"Unsupported export format: {export_path}")

        logger.info("导出完成", file=export_path, rows=len(df))


def main():
    """CLI entry point for data merger."""
    parser = argparse.ArgumentParser(
        description="合并多个 DuckDB 表格"
    )
    parser.add_argument(
        "--tables", nargs="+", required=True,
        help="源表名列表 (至少2个)"
    )
    parser.add_argument(
        "--target", required=True,
        help="目标表名"
    )
    parser.add_argument(
        "--db", default="workspace.duckdb",
        help="数据库路径 (默认: workspace.duckdb)"
    )
    parser.add_argument(
        "--export",
        help="导出到文件 (支持 .csv, .xlsx)"
    )

    args = parser.parse_args()

    config = MergeConfig(
        source_tables=args.tables,
        target_table=args.target,
        db_path=args.db,
        export_file=args.export
    )

    merger = DataMerger(config)
    merged_df = merger.merge_tables()

    # Save to database
    merger.save_to_database(merged_df)

    # Export if requested
    if args.export:
        merger.export_to_file(merged_df)

    print(f"合并完成: {len(merged_df)} 行数据已保存到表 '{args.target}'")


if __name__ == "__main__":
    main()
