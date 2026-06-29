from __future__ import annotations

import json
from typing import Any

import duckdb


def _rows(con: duckdb.DuckDBPyConnection, query: str, params: list[Any]) -> list[dict[str, Any]]:
    result = con.execute(query, params)
    names = [d[0] for d in result.description]
    return [dict(zip(names, row)) for row in result.fetchall()]


def _json_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def build_render_payload(con: duckdb.DuckDBPyConnection, run_id: str, descriptions: dict[str, str] | None = None) -> dict[str, Any]:
    descriptions = descriptions or {}
    run_meta = _rows(con, "SELECT * FROM run_meta WHERE run_id = ?", [run_id])[0]
    sections = _rows(con, """
        SELECT * FROM run_sections
        WHERE run_id = ? AND enabled = true
        ORDER BY section_order, section_id
    """, [run_id])
    tables = _rows(con, """
        SELECT * FROM run_tables
        WHERE run_id = ?
        ORDER BY section_id, table_order, table_id
    """, [run_id])
    metric_facts = _rows(con, "SELECT * FROM metric_facts WHERE run_id = ? ORDER BY table_id, branch_num", [run_id])
    computed_facts = _rows(con, "SELECT * FROM computed_facts WHERE run_id = ? ORDER BY table_id, branch_num", [run_id])

    metric_by_table_branch: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for fact in metric_facts:
        metric_by_table_branch.setdefault((fact["table_id"], fact["branch_num"]), []).append(fact)

    computed_by_table_branch: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for fact in computed_facts:
        computed_by_table_branch.setdefault((fact["table_id"], fact["branch_num"]), []).append(fact)

    tables_by_section: dict[str, list[dict[str, Any]]] = {}
    for table in tables:
        tables_by_section.setdefault(table["section_id"], []).append(table)

    payload_sections: list[dict[str, Any]] = []
    for section in sections:
        payload_tables: list[dict[str, Any]] = []
        for table in tables_by_section.get(section["section_id"], []):
            branch_nums = sorted({
                branch for table_id, branch in metric_by_table_branch
                if table_id == table["table_id"]
            } | {
                branch for table_id, branch in computed_by_table_branch
                if table_id == table["table_id"]
            })
            rows: list[dict[str, Any]] = []
            for branch_num in branch_nums:
                cells: dict[str, str] = {}
                cell_status: dict[str, str] = {}
                branch_short_name = ""
                for fact in metric_by_table_branch.get((table["table_id"], branch_num), []):
                    key = f"{fact['idx_id']}@{fact['period_alias']}"
                    cells[key] = fact["raw_value"]
                    cell_status[key] = fact["status"]
                    branch_short_name = fact["branch_short_name"]
                for fact in computed_by_table_branch.get((table["table_id"], branch_num), []):
                    cells[fact["compute_name"]] = fact["value"]
                    cell_status[fact["compute_name"]] = fact["status"]
                rows.append({
                    "branch_num": branch_num,
                    "branch_short_name": branch_short_name,
                    "cells": cells,
                    "cell_status": cell_status,
                })
            payload_tables.append({
                "table_id": table["table_id"],
                "table_title": table["table_title"],
                "table_order": table["table_order"],
                "headers": _json_value(table.get("headers")) or [],
                "rows": rows,
                "description_text": descriptions.get(table["table_id"], ""),
            })
        payload_sections.append({
            "section_id": section["section_id"],
            "section_title": section["section_title"],
            "section_order": section["section_order"],
            "tables": payload_tables,
        })

    return {
        "report": {
            "report_id": run_meta["report_id"],
            "report_title": run_meta.get("report_title") or run_meta["report_id"],
            "run_id": run_id,
        },
        "sections": payload_sections,
    }
