from __future__ import annotations

import json
from typing import Any

import duckdb

from ai_report.definition_store import load_active_report


def _json_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def export_report_design_markdown(con: duckdb.DuckDBPyConnection, report_id: str) -> str:
    data = load_active_report(con, report_id)
    report = data["report"]
    sections = data["sections"]
    tables = data["tables"]
    metrics = data["metrics"]
    computes = data["computes"]

    metrics_by_table: dict[str, list[dict[str, Any]]] = {}
    for metric in metrics:
        metrics_by_table.setdefault(metric["table_id"], []).append(metric)

    computes_by_table: dict[str, list[dict[str, Any]]] = {}
    for compute in computes:
        computes_by_table.setdefault(compute["table_id"], []).append(compute)

    tables_by_section: dict[str, list[dict[str, Any]]] = {}
    for table in tables:
        tables_by_section.setdefault(table["section_id"], []).append(table)

    lines = [
        "---",
        f"report_id: {report['report_id']}",
        f"report_name: {report['report_name']}",
        f"report_title: {report['report_title']}",
        f"status: {report['status']}",
        f"version: {report['version']}",
        "---",
        "",
        f"# {report['report_title']}",
        "",
    ]

    for section in sections:
        lines.extend([
            f"## {section['section_title']}",
            "",
            f"<!-- section_key: {section['section_key']}; section_order: {section['section_order']} -->",
            "",
        ])
        for table in tables_by_section.get(section["section_id"], []):
            lines.extend([
                f"### {table['table_title']}",
                "",
                f"<!-- table_id: {table['table_id']}; table_order: {table['table_order']}; approval_status: {table['approval_status']} -->",
                "",
                f"> query_failure_policy: {table['query_failure_policy']}",
                f"> compute_failure_policy: {table['compute_failure_policy']}",
                f"> description_failure_policy: {table['description_failure_policy']}",
                "",
            ])
            orgs = _json_value(table.get("orgs")) or []
            if orgs:
                lines.append("> 机构:")
                for org in orgs:
                    lines.append(f">   branch_num={org.get('branch_num')}; branch_short_name={org.get('branch_short_name')}")
                lines.append("")
            time_info = _json_value(table.get("time_info")) or []
            if time_info:
                lines.extend(["> 时期:", f">   time_info={json.dumps(time_info, ensure_ascii=False)}", ""])
            table_metrics = metrics_by_table.get(table["table_id"], [])
            if table_metrics:
                lines.extend(["> 指标:"])
                for metric in table_metrics:
                    lines.append(
                        f">   idx_id: {metric['idx_id']}; period_alias: {metric['period_alias']}; "
                        f"data_unit: {metric['data_unit']}; header_text: {metric['header_text']}"
                    )
                lines.append("")
            prompt = table.get("description_prompt")
            if prompt:
                lines.extend(["> 描述:", f">   {prompt}", ""])
            table_computes = computes_by_table.get(table["table_id"], [])
            for compute in table_computes:
                lines.extend([
                    f"> 计算: {compute['compute_name']} = {compute['formula_text']}",
                    "",
                    f"```sql compute_sql:{compute['compute_name']}",
                    compute["compute_sql"],
                    "```",
                    "",
                ])

    return "\n".join(lines).rstrip() + "\n"