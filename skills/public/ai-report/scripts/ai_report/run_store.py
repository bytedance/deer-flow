from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import duckdb

from ai_report.models import MetricFact


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def connect_run(db_path: str | Path) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(db_path))


def init_run_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS run_meta(
          run_id TEXT PRIMARY KEY,
          run_mode TEXT,
          report_id TEXT,
          report_title TEXT,
          table_id TEXT,
          report_version INTEGER,
          run_params JSON,
          checkpoint_policy TEXT,
          status TEXT,
          started_at TIMESTAMP DEFAULT current_timestamp,
          finished_at TIMESTAMP
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS run_sections(
          run_id TEXT,
          section_id TEXT,
          report_id TEXT,
          section_key TEXT,
          section_title TEXT,
          section_order INTEGER,
          description_prompt TEXT,
          enabled BOOLEAN,
          metadata JSON,
          PRIMARY KEY(run_id, section_id)
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS run_tables(
          run_id TEXT,
          table_id TEXT,
          report_id TEXT,
          section_id TEXT,
          table_title TEXT,
          table_order INTEGER,
          parsed_payload JSON,
          headers JSON,
          orgs JSON,
          time_info JSON,
          description_prompt TEXT,
          query_failure_policy TEXT,
          compute_failure_policy TEXT,
          description_failure_policy TEXT,
          source TEXT,
          PRIMARY KEY(run_id, table_id)
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS metric_facts(
          run_id TEXT,
          table_id TEXT,
          branch_num TEXT,
          branch_short_name TEXT,
          idx_id TEXT,
          period_alias TEXT,
          period_value TEXT,
          raw_value TEXT,
          numeric_value DECIMAL(38,10),
          data_unit TEXT,
          status TEXT,
          error_message TEXT,
          PRIMARY KEY(run_id, table_id, branch_num, idx_id, period_alias)
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS computed_facts(
          run_id TEXT,
          table_id TEXT,
          branch_num TEXT,
          compute_name TEXT,
          value TEXT,
          numeric_value DECIMAL(38,10),
          status TEXT,
          error_message TEXT,
          PRIMARY KEY(run_id, table_id, branch_num, compute_name)
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS run_events(
          event_id TEXT PRIMARY KEY,
          run_id TEXT,
          step TEXT,
          event_type TEXT,
          status TEXT,
          message TEXT,
          payload JSON,
          created_at TIMESTAMP DEFAULT current_timestamp
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS run_outputs(
          output_id TEXT PRIMARY KEY,
          run_id TEXT,
          table_id TEXT,
          output_type TEXT,
          file_path TEXT,
          content TEXT,
          status TEXT,
          payload JSON,
          created_at TIMESTAMP DEFAULT current_timestamp
        )
    """)


def create_run(con: duckdb.DuckDBPyConnection, run_id: str, plan: dict[str, Any], mode: str = "runtime") -> None:
    params = plan["run_params"]
    con.execute("""
        INSERT OR REPLACE INTO run_meta(
          run_id, run_mode, report_id, report_title, table_id, report_version,
          run_params, checkpoint_policy, status
        ) VALUES (?, ?, ?, ?, NULL, ?, ?::JSON, ?, ?)
    """, [
        run_id,
        mode,
        plan["report"]["report_id"],
        plan["report"].get("report_title") or plan["report"]["report_id"],
        plan["report"].get("version", 1),
        _json(asdict(params)),
        "auto" if mode == "runtime" else "interactive",
        "running",
    ])


def snapshot_runtime_plan(con: duckdb.DuckDBPyConnection, run_id: str, plan: dict[str, Any]) -> None:
    for section in plan["sections"]:
        con.execute("""
            INSERT OR REPLACE INTO run_sections(
              run_id, section_id, report_id, section_key, section_title,
              section_order, description_prompt, enabled, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?::JSON)
        """, [
            run_id,
            section["section_id"],
            section["report_id"],
            section["section_key"],
            section["section_title"],
            section["section_order"],
            section.get("description_prompt"),
            section.get("enabled", True),
            section.get("metadata") or "{}",
        ])
    for table in plan["tables"]:
        con.execute("""
            INSERT OR REPLACE INTO run_tables(
              run_id, table_id, report_id, section_id, table_title, table_order,
              parsed_payload, headers, orgs, time_info, description_prompt,
              query_failure_policy, compute_failure_policy, description_failure_policy, source
            ) VALUES (?, ?, ?, ?, ?, ?, ?::JSON, ?::JSON, ?::JSON, ?::JSON, ?, ?, ?, ?, ?)
        """, [
            run_id,
            table["table_id"],
            table["report_id"],
            table["section_id"],
            table["table_title"],
            table["table_order"],
            table.get("parsed_payload") or "{}",
            table.get("headers") or "[]",
            table.get("orgs") or "[]",
            table.get("time_info") or "[]",
            table.get("description_prompt"),
            table.get("query_failure_policy"),
            table.get("compute_failure_policy"),
            table.get("description_failure_policy"),
            "approved_definition",
        ])


def insert_metric_facts(con: duckdb.DuckDBPyConnection, facts: list[MetricFact]) -> None:
    for fact in facts:
        con.execute("""
            INSERT OR REPLACE INTO metric_facts(
              run_id, table_id, branch_num, branch_short_name, idx_id,
              period_alias, period_value, raw_value, numeric_value,
              data_unit, status, error_message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            fact.run_id,
            fact.table_id,
            fact.branch_num,
            fact.branch_short_name,
            fact.idx_id,
            fact.period_alias,
            fact.period_value,
            fact.raw_value,
            fact.numeric_value,
            fact.data_unit,
            fact.status,
            fact.error_message,
        ])


def fetch_metric_facts(con: duckdb.DuckDBPyConnection, run_id: str, table_id: str) -> list[dict[str, Any]]:
    result = con.execute("""
        SELECT * FROM metric_facts
        WHERE run_id = ? AND table_id = ?
        ORDER BY branch_num, idx_id, period_alias
    """, [run_id, table_id])
    names = [d[0] for d in result.description]
    return [dict(zip(names, row)) for row in result.fetchall()]
