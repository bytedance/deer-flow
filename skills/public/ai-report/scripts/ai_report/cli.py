from __future__ import annotations

import argparse
import json
import os
import sys
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

from ai_report.definition_store import connect_definitions, init_definition_schema
from ai_report.description_generator import generate_descriptions
from ai_report.design_export import export_report_design_markdown
from ai_report.design_import import import_design_json
from ai_report.frontmatter import merge_table_designs, parse_table_md_dir
from ai_report.models import MetricFact, RunParams
from ai_report.render_markdown_v2 import render_markdown
from ai_report.render_payload import build_render_payload
from ai_report.run_store import connect_run, create_run, init_run_schema, insert_metric_facts, snapshot_runtime_plan
from ai_report.runtime_compute import build_table_frame, execute_computes
from ai_report.runtime_plan import build_runtime_plan

DEFAULT_DEFINITIONS_DB = "/mnt/ai-report-data/definitions.duckdb"
DEFAULT_RUNS_DIR = "/mnt/ai-report-data/runs"


def _default_run_db() -> str:
    os.makedirs(DEFAULT_RUNS_DIR, exist_ok=True)
    return f"{DEFAULT_RUNS_DIR}/{int(time.time())}.duckdb"


def _cmd_init_definitions(args: argparse.Namespace) -> int:
    con = connect_definitions(args.definitions_db)
    try:
        init_definition_schema(con)
    finally:
        con.close()
    return 0


def _cmd_export_design_md(args: argparse.Namespace) -> int:
    con = connect_definitions(args.definitions_db)
    try:
        md = export_report_design_markdown(con, args.report_id)
        Path(args.out).write_text(md, encoding="utf-8")
    finally:
        con.close()
    return 0


def _cmd_import_design_json(args: argparse.Namespace) -> int:
    design = json.loads(Path(args.design_json).read_text(encoding="utf-8"))
    con = connect_definitions(args.definitions_db)
    try:
        init_definition_schema(con)
        import_design_json(con, design)
    finally:
        con.close()
    return 0


def _cmd_import_table_md_dir(args: argparse.Namespace) -> int:
    """Parse every *.md under --dir as a partial table design, merge them, and import.

    All .md files must share one report_id (frontmatter validation enforces this
    during merge). Use this for the design spec §10 workflow where each table
    has its own table.md file.
    """
    partials = parse_table_md_dir(args.dir)
    design = merge_table_designs(*partials)
    con = connect_definitions(args.definitions_db)
    try:
        init_definition_schema(con)
        import_design_json(con, design)
    finally:
        con.close()
    return 0


def _cmd_run_report_fixture(args: argparse.Namespace) -> int:
    params = RunParams(period_bindings=json.loads(args.period_bindings), org_scope=[], output_formats=["md"])
    definitions = connect_definitions(args.definitions_db)
    run_db = args.run_db or _default_run_db()
    run = connect_run(run_db)
    try:
        init_run_schema(run)
        plan = build_runtime_plan(definitions, args.report_id, params)
        create_run(run, "fixture-run", plan)
        snapshot_runtime_plan(run, "fixture-run", plan)
        raw_facts = json.loads(Path(args.metric_facts).read_text(encoding="utf-8"))
        facts = [MetricFact(
            run_id="fixture-run",
            table_id=row["table_id"],
            branch_num=row["branch_num"],
            branch_short_name=row["branch_short_name"],
            idx_id=row["idx_id"],
            period_alias=row["period_alias"],
            period_value=row["period_value"],
            raw_value=row["raw_value"],
            numeric_value=Decimal(str(row["numeric_value"])) if row.get("numeric_value") is not None else None,
            data_unit=row.get("data_unit"),
        ) for row in raw_facts]
        insert_metric_facts(run, facts)

        # Execute approved compute_sql per table. A table without approved computes is a no-op.
        computes_by_table: dict[str, list[dict[str, Any]]] = {}
        for compute in plan.get("computes", []):
            computes_by_table.setdefault(compute["table_id"], []).append(compute)
        policy_by_table = {
            table["table_id"]: table.get("compute_failure_policy") or "stop_on_failure"
            for table in plan.get("tables", [])
        }
        for table_id, table_computes in computes_by_table.items():
            build_table_frame(run, "fixture-run", table_id)
            execute_computes(
                run,
                "fixture-run",
                table_id,
                table_computes,
                compute_failure_policy=policy_by_table.get(table_id, "stop_on_failure"),
            )

        descriptions = generate_descriptions(run, "fixture-run")
        payload = build_render_payload(run, "fixture-run", descriptions=descriptions)
        Path(args.out).write_text(render_markdown(payload), encoding="utf-8")
    finally:
        definitions.close()
        run.close()
    return 0


def _cmd_approve_table(args: argparse.Namespace) -> int:
    """Approve a table and its metrics/computes for runtime use.

    Writes approval_status='approved' and last_design_run_id on report_tables,
    table_metrics, and table_computes. The caller is responsible for ensuring
    the design run is sane — this CLI does not re-validate metrics or computes.
    """
    con = connect_definitions(args.definitions_db)
    try:
        init_definition_schema(con)
        existing = con.execute(
            "SELECT table_id FROM report_tables WHERE table_id = ?", [args.table_id]
        ).fetchone()
        if not existing:
            raise ValueError(f"Table not found: {args.table_id}")
        design_run_id = args.design_run_id
        con.execute("""
            UPDATE report_tables
            SET approval_status = 'approved',
                last_design_run_id = ?,
                updated_at = current_timestamp
            WHERE table_id = ?
        """, [design_run_id, args.table_id])
        con.execute("""
            UPDATE table_metrics
            SET approval_status = 'approved',
                last_design_run_id = ?
            WHERE table_id = ?
        """, [design_run_id, args.table_id])
        con.execute("""
            UPDATE table_computes
            SET approval_status = 'approved',
                last_design_run_id = ?
            WHERE table_id = ?
        """, [design_run_id, args.table_id])
    finally:
        con.close()
    return 0


def _cmd_activate_report(args: argparse.Namespace) -> int:
    """Activate a report so runtime can run it.

    Sets reports.status='active' and records activated_run_id. The caller must
    have already approved at least one table; this command does not validate
    that. To re-activate under a different preview_run_id, run it again.
    """
    con = connect_definitions(args.definitions_db)
    try:
        existing = con.execute(
            "SELECT report_id FROM reports WHERE report_id = ?", [args.report_id]
        ).fetchone()
        if not existing:
            raise ValueError(f"Report not found: {args.report_id}")
        con.execute("""
            UPDATE reports
            SET status = 'active',
                activated_run_id = ?,
                updated_at = current_timestamp
            WHERE report_id = ?
        """, [args.preview_run_id, args.report_id])
    finally:
        con.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ai-report")
    sub = parser.add_subparsers(dest="cmd", required=True)

    init_cmd = sub.add_parser("init-definitions")
    init_cmd.add_argument("--definitions-db", default=DEFAULT_DEFINITIONS_DB)
    init_cmd.set_defaults(func=_cmd_init_definitions)

    export_cmd = sub.add_parser("export-design-md")
    export_cmd.add_argument("--definitions-db", default=DEFAULT_DEFINITIONS_DB)
    export_cmd.add_argument("--report-id", required=True)
    export_cmd.add_argument("--out", required=True)
    export_cmd.set_defaults(func=_cmd_export_design_md)

    import_cmd = sub.add_parser("import-design-json")
    import_cmd.add_argument("--definitions-db", default=DEFAULT_DEFINITIONS_DB)
    import_cmd.add_argument("--design-json", required=True)
    import_cmd.set_defaults(func=_cmd_import_design_json)

    import_dir_cmd = sub.add_parser("import-table-md-dir")
    import_dir_cmd.add_argument("--definitions-db", default=DEFAULT_DEFINITIONS_DB)
    import_dir_cmd.add_argument("--dir", required=True, help="directory containing *.md files")
    import_dir_cmd.set_defaults(func=_cmd_import_table_md_dir)

    fixture_cmd = sub.add_parser("run-report-fixture")
    fixture_cmd.add_argument("--definitions-db", default=DEFAULT_DEFINITIONS_DB)
    fixture_cmd.add_argument("--run-db", default=None)
    fixture_cmd.add_argument("--report-id", required=True)
    fixture_cmd.add_argument("--period-bindings", required=True)
    fixture_cmd.add_argument("--metric-facts", required=True)
    fixture_cmd.add_argument("--out", required=True)
    fixture_cmd.set_defaults(func=_cmd_run_report_fixture)

    approve_cmd = sub.add_parser("approve-table")
    approve_cmd.add_argument("--definitions-db", default=DEFAULT_DEFINITIONS_DB)
    approve_cmd.add_argument("--table-id", required=True)
    approve_cmd.add_argument("--design-run-id", required=True)
    approve_cmd.set_defaults(func=_cmd_approve_table)

    activate_cmd = sub.add_parser("activate-report")
    activate_cmd.add_argument("--definitions-db", default=DEFAULT_DEFINITIONS_DB)
    activate_cmd.add_argument("--report-id", required=True)
    activate_cmd.add_argument("--preview-run-id", required=True)
    activate_cmd.set_defaults(func=_cmd_activate_report)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
