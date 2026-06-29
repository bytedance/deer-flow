from __future__ import annotations

import re
from typing import Any

import duckdb

from ai_report.definition_store import (
    upsert_compute,
    upsert_metric,
    upsert_report,
    upsert_section,
    upsert_table,
)
from ai_report.models import ComputeRecord, MetricRecord, ReportRecord, SectionRecord, TableRecord

# Allows ASCII alphanumerics plus `_`, `-`, `@`, `.`, and CJK Unified Ideographs.
# CJK is needed for compute_name and period_alias values such as `贷款同比增速` and `本期`
# that the design spec uses as cell keys in render_payload.
_ID_RE = re.compile(r"^[A-Za-z0-9_\-@.一-鿿]+$")


def _validate_id(value: str, field: str) -> None:
    if not _ID_RE.match(value):
        raise ValueError(f"Invalid {field}: {value!r} (must match {_ID_RE.pattern})")


def import_design_json(
    con: duckdb.DuckDBPyConnection,
    design: dict[str, Any],
    *,
    replace: bool = False,
) -> None:
    """Import a parsed design dict into definitions.duckdb.

    Wraps all upserts in a single transaction so a partial import never
    leaves the database in an inconsistent state. Validates idx_id and
    compute_name identifiers to prevent SQL-keyword injection at runtime.
    """
    report = design["report"]
    sections = design.get("sections", [])
    tables = design.get("tables", [])

    _validate_id(report["report_id"], "report_id")

    if replace:
        for table in tables:
            _validate_id(table["table_id"], "table.table_id")
        for section in sections:
            _validate_id(section["section_id"], "section.section_id")

    try:
        con.execute("BEGIN")
        upsert_report(con, ReportRecord(
            report_id=report["report_id"],
            report_name=report.get("report_name", report["report_id"]),
            report_title=report.get("report_title", report["report_id"]),
            status=report.get("status", "draft"),
            version=report.get("version", 1),
            metadata=report.get("metadata", {}),
        ))
        for section in sections:
            upsert_section(con, SectionRecord(
                section_id=section["section_id"],
                report_id=report["report_id"],
                section_key=section.get("section_key", section["section_id"]),
                section_title=section.get("section_title", section["section_id"]),
                section_order=section.get("section_order", 0),
                description_prompt=section.get("description_prompt"),
                enabled=section.get("enabled", True),
                metadata=section.get("metadata", {}),
            ))
        for table in tables:
            _validate_id(table["table_id"], "table.table_id")
            upsert_table(con, TableRecord(
                table_id=table["table_id"],
                report_id=report["report_id"],
                section_id=table["section_id"],
                table_title=table.get("table_title", table["table_id"]),
                table_order=table.get("table_order", 0),
                source_md_path=table.get("source_md_path"),
                source_md_hash=table.get("source_md_hash"),
                parsed_payload=table.get("parsed_payload", {}),
                headers=table.get("headers", []),
                orgs=table.get("orgs", []),
                time_info=table.get("time_info", []),
                description_prompt=table.get("description_prompt"),
                approval_status=table.get("approval_status", "draft"),
                query_failure_policy=table.get("query_failure_policy", "continue_with_sentinel"),
                compute_failure_policy=table.get("compute_failure_policy", "stop_on_failure"),
                description_failure_policy=table.get("description_failure_policy", "continue_with_sentinel"),
            ))
            for metric in table.get("metrics", []):
                _validate_id(metric["idx_id"], "metric.idx_id")
                upsert_metric(con, MetricRecord(
                    table_id=table["table_id"],
                    idx_id=metric["idx_id"],
                    period_alias=metric.get("period_alias", "本期"),
                    data_unit=metric.get("data_unit"),
                    header_text=metric.get("header_text"),
                    metric_order=metric.get("metric_order", 0),
                    approval_status=metric.get("approval_status", "draft"),
                ))
            for compute in table.get("computes", []):
                _validate_id(compute["compute_name"], "compute.compute_name")
                upsert_compute(con, ComputeRecord(
                    compute_id=compute["compute_id"],
                    table_id=table["table_id"],
                    compute_name=compute["compute_name"],
                    formula_text=compute.get("formula_text", ""),
                    compute_sql=compute["compute_sql"],
                    dependencies=compute.get("dependencies", []),
                    examples=compute.get("examples", []),
                    approval_status=compute.get("approval_status", "draft"),
                ))
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise