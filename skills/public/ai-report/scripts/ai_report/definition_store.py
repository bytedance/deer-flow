from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb

from ai_report.models import ComputeRecord, MetricRecord, ReportRecord, SectionRecord, TableRecord


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def connect_definitions(db_path: str | Path) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(db_path))


def init_definition_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS reports(
          report_id TEXT PRIMARY KEY,
          report_name TEXT,
          report_title TEXT,
          status TEXT,
          version INTEGER,
          last_preview_run_id TEXT,
          activated_run_id TEXT,
          created_at TIMESTAMP DEFAULT current_timestamp,
          updated_at TIMESTAMP DEFAULT current_timestamp,
          metadata JSON
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS report_sections(
          section_id TEXT PRIMARY KEY,
          report_id TEXT,
          section_key TEXT,
          section_title TEXT,
          section_order INTEGER,
          description_prompt TEXT,
          enabled BOOLEAN,
          metadata JSON,
          created_at TIMESTAMP DEFAULT current_timestamp,
          updated_at TIMESTAMP DEFAULT current_timestamp
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS report_tables(
          table_id TEXT PRIMARY KEY,
          report_id TEXT,
          section_id TEXT,
          table_title TEXT,
          table_order INTEGER,
          source_md_path TEXT,
          source_md_hash TEXT,
          parsed_payload JSON,
          headers JSON,
          orgs JSON,
          time_info JSON,
          description_prompt TEXT,
          approval_status TEXT,
          query_failure_policy TEXT,
          compute_failure_policy TEXT,
          description_failure_policy TEXT,
          last_design_run_id TEXT,
          created_at TIMESTAMP DEFAULT current_timestamp,
          updated_at TIMESTAMP DEFAULT current_timestamp
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS table_metrics(
          table_id TEXT,
          idx_id TEXT,
          period_alias TEXT,
          data_unit TEXT,
          header_text TEXT,
          metric_order INTEGER,
          approval_status TEXT,
          last_design_run_id TEXT,
          metadata JSON,
          PRIMARY KEY(table_id, idx_id, period_alias)
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS table_computes(
          compute_id TEXT PRIMARY KEY,
          table_id TEXT,
          compute_name TEXT,
          formula_text TEXT,
          compute_sql TEXT,
          dependencies JSON,
          examples JSON,
          approval_status TEXT,
          last_design_run_id TEXT,
          created_at TIMESTAMP DEFAULT current_timestamp,
          updated_at TIMESTAMP DEFAULT current_timestamp
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS design_artifacts(
          artifact_id TEXT PRIMARY KEY,
          report_id TEXT,
          table_id TEXT,
          design_run_id TEXT,
          output_id TEXT,
          artifact_type TEXT,
          file_path TEXT,
          status TEXT,
          created_at TIMESTAMP DEFAULT current_timestamp
        )
    """)


def upsert_report(con: duckdb.DuckDBPyConnection, record: ReportRecord) -> None:
    con.execute("""
        INSERT OR REPLACE INTO reports(
          report_id, report_name, report_title, status, version,
          last_preview_run_id, activated_run_id, metadata, updated_at
        ) VALUES (?, ?, ?, ?, ?, NULL, NULL, ?::JSON, current_timestamp)
    """, [record.report_id, record.report_name, record.report_title, record.status, record.version, _json(record.metadata)])


def upsert_section(con: duckdb.DuckDBPyConnection, record: SectionRecord) -> None:
    con.execute("""
        INSERT OR REPLACE INTO report_sections(
          section_id, report_id, section_key, section_title, section_order,
          description_prompt, enabled, metadata, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?::JSON, current_timestamp)
    """, [
        record.section_id,
        record.report_id,
        record.section_key,
        record.section_title,
        record.section_order,
        record.description_prompt,
        record.enabled,
        _json(record.metadata),
    ])


def upsert_table(con: duckdb.DuckDBPyConnection, record: TableRecord) -> None:
    con.execute("""
        INSERT OR REPLACE INTO report_tables(
          table_id, report_id, section_id, table_title, table_order,
          source_md_path, source_md_hash, parsed_payload, headers, orgs,
          time_info, description_prompt, approval_status, query_failure_policy,
          compute_failure_policy, description_failure_policy, last_design_run_id, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?::JSON, ?::JSON, ?::JSON, ?::JSON, ?, ?, ?, ?, ?, ?, current_timestamp)
    """, [
        record.table_id,
        record.report_id,
        record.section_id,
        record.table_title,
        record.table_order,
        record.source_md_path,
        record.source_md_hash,
        _json(record.parsed_payload),
        _json(record.headers),
        _json(record.orgs),
        _json(record.time_info),
        record.description_prompt,
        record.approval_status,
        record.query_failure_policy,
        record.compute_failure_policy,
        record.description_failure_policy,
        record.last_design_run_id,
    ])


def upsert_metric(con: duckdb.DuckDBPyConnection, record: MetricRecord) -> None:
    con.execute("""
        INSERT OR REPLACE INTO table_metrics(
          table_id, idx_id, period_alias, data_unit, header_text,
          metric_order, approval_status, last_design_run_id, metadata
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?::JSON)
    """, [
        record.table_id,
        record.idx_id,
        record.period_alias,
        record.data_unit,
        record.header_text,
        record.metric_order,
        record.approval_status,
        record.last_design_run_id,
        _json(record.metadata),
    ])


def upsert_compute(con: duckdb.DuckDBPyConnection, record: ComputeRecord) -> None:
    con.execute("""
        INSERT OR REPLACE INTO table_computes(
          compute_id, table_id, compute_name, formula_text, compute_sql,
          dependencies, examples, approval_status, last_design_run_id, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?::JSON, ?::JSON, ?, ?, current_timestamp)
    """, [
        record.compute_id,
        record.table_id,
        record.compute_name,
        record.formula_text,
        record.compute_sql,
        _json(record.dependencies),
        _json(record.examples),
        record.approval_status,
        record.last_design_run_id,
    ])


def _rows(con: duckdb.DuckDBPyConnection, query: str, params: list[Any]) -> list[dict[str, Any]]:
    result = con.execute(query, params)
    names = [d[0] for d in result.description]
    return [dict(zip(names, row)) for row in result.fetchall()]


def load_active_report(con: duckdb.DuckDBPyConnection, report_id: str) -> dict[str, Any]:
    reports = _rows(con, "SELECT * FROM reports WHERE report_id = ? AND status = 'active'", [report_id])
    if not reports:
        raise ValueError(f"Active report not found: {report_id}")
    sections = _rows(con, """
        SELECT * FROM report_sections
        WHERE report_id = ? AND enabled = true
        ORDER BY section_order, section_id
    """, [report_id])
    tables = _rows(con, """
        SELECT * FROM report_tables
        WHERE report_id = ? AND approval_status = 'approved'
        ORDER BY section_id, table_order, table_id
    """, [report_id])
    table_ids = [row["table_id"] for row in tables]
    if table_ids:
        placeholders = ",".join(["?"] * len(table_ids))
        metrics = _rows(con, f"""
            SELECT * FROM table_metrics
            WHERE table_id IN ({placeholders}) AND approval_status = 'approved'
            ORDER BY table_id, metric_order, idx_id, period_alias
        """, table_ids)
        computes = _rows(con, f"""
            SELECT * FROM table_computes
            WHERE table_id IN ({placeholders}) AND approval_status = 'approved'
            ORDER BY table_id, compute_name
        """, table_ids)
    else:
        metrics = []
        computes = []
    return {
        "report": reports[0],
        "sections": sections,
        "tables": tables,
        "metrics": metrics,
        "computes": computes,
    }