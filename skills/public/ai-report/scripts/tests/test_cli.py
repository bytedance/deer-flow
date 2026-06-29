import json
from pathlib import Path

from ai_report.cli import main
from ai_report.definition_store import connect_definitions, init_definition_schema, upsert_compute, upsert_metric, upsert_report, upsert_section, upsert_table
from ai_report.models import ComputeRecord, MetricRecord, ReportRecord, SectionRecord, TableRecord


def test_cli_export_design_md(tmp_path: Path):
    db_path = tmp_path / "definitions.duckdb"
    con = connect_definitions(db_path)
    init_definition_schema(con)
    upsert_report(con, ReportRecord("business_analysis", "经营分析报告", "2024年经营分析报告", status="active"))
    upsert_section(con, SectionRecord("overview", "business_analysis", "overview", "一、总体经营情况", 10))
    upsert_table(con, TableRecord("main_metrics", "business_analysis", "overview", "主要经营指标表", 10, approval_status="approved"))
    upsert_metric(con, MetricRecord("main_metrics", "BAS_0263", "本期", approval_status="approved"))
    con.close()
    out = tmp_path / "business_analysis.report_design.md"

    code = main(["export-design-md", "--definitions-db", str(db_path), "--report-id", "business_analysis", "--out", str(out)])

    assert code == 0
    assert "# 2024年经营分析报告" in out.read_text(encoding="utf-8")


def test_cli_run_report_fixture_outputs_markdown(tmp_path: Path):
    db_path = tmp_path / "definitions.duckdb"
    con = connect_definitions(db_path)
    init_definition_schema(con)
    upsert_report(con, ReportRecord("business_analysis", "经营分析报告", "2024年经营分析报告", status="active"))
    upsert_section(con, SectionRecord("overview", "business_analysis", "overview", "一、总体经营情况", 10))
    upsert_table(con, TableRecord("main_metrics", "business_analysis", "overview", "主要经营指标表", 10, approval_status="approved"))
    upsert_metric(con, MetricRecord("main_metrics", "BAS_0263", "本期", approval_status="approved"))
    con.close()
    facts = tmp_path / "facts.json"
    facts.write_text(json.dumps([{
        "table_id": "main_metrics",
        "branch_num": "27020199",
        "branch_short_name": "王益联社",
        "idx_id": "BAS_0263",
        "period_alias": "本期",
        "period_value": "2024Q4",
        "raw_value": "1000",
        "numeric_value": "1000",
        "data_unit": "万元",
    }], ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "report.md"

    code = main([
        "run-report-fixture",
        "--definitions-db", str(db_path),
        "--run-db", str(tmp_path / "run.duckdb"),
        "--report-id", "business_analysis",
        "--period-bindings", '{"本期":"2024Q4"}',
        "--metric-facts", str(facts),
        "--out", str(out),
    ])

    assert code == 0
    rendered = out.read_text(encoding="utf-8")
    assert "# 2024年经营分析报告" in rendered
    assert "| 27020199 | 王益联社 | 1000 |" in rendered


def test_cli_run_report_fixture_executes_computes(tmp_path: Path):
    """End-to-end: fixture flow must call execute_computes so the rendered Markdown
    includes computed_facts columns, not just metric_facts columns."""
    db_path = tmp_path / "definitions.duckdb"
    con = connect_definitions(db_path)
    init_definition_schema(con)
    upsert_report(con, ReportRecord("business_analysis", "经营分析报告", "2024年经营分析报告", status="active"))
    upsert_section(con, SectionRecord("overview", "business_analysis", "overview", "一、总体经营情况", 10))
    upsert_table(con, TableRecord(
        "main_metrics", "business_analysis", "overview", "主要经营指标表", 10,
        approval_status="approved", compute_failure_policy="continue_with_sentinel",
    ))
    upsert_metric(con, MetricRecord("main_metrics", "BAS_0263", "本期", approval_status="approved"))
    upsert_metric(con, MetricRecord("main_metrics", "BAS_0263", "去年同期", approval_status="approved"))
    upsert_compute(con, ComputeRecord(
        compute_id="main_metrics__贷款同比增速",
        table_id="main_metrics",
        compute_name="贷款同比增速",
        formula_text="(本期-去年同期)/去年同期",
        compute_sql=(
            'SELECT branch_num, ("BAS_0263@本期" - "BAS_0263@去年同期")'
            ' / "BAS_0263@去年同期" AS "贷款同比增速" FROM table_frame'
        ),
        approval_status="approved",
    ))
    con.close()

    facts = tmp_path / "facts.json"
    facts.write_text(json.dumps([
        {
            "table_id": "main_metrics", "branch_num": "27020199",
            "branch_short_name": "王益联社", "idx_id": "BAS_0263",
            "period_alias": "本期", "period_value": "2024Q4",
            "raw_value": "1000", "numeric_value": "1000", "data_unit": "万元",
        },
        {
            "table_id": "main_metrics", "branch_num": "27020199",
            "branch_short_name": "王益联社", "idx_id": "BAS_0263",
            "period_alias": "去年同期", "period_value": "2023Q4",
            "raw_value": "800", "numeric_value": "800", "data_unit": "万元",
        },
    ], ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "report.md"

    code = main([
        "run-report-fixture",
        "--definitions-db", str(db_path),
        "--run-db", str(tmp_path / "run.duckdb"),
        "--report-id", "business_analysis",
        "--period-bindings", '{"本期":"2024Q4","去年同期":"2023Q4"}',
        "--metric-facts", str(facts),
        "--out", str(out),
    ])

    assert code == 0
    rendered = out.read_text(encoding="utf-8")
    # Header must include the compute_name column; the row must include the computed value.
    assert "贷款同比增速" in rendered
    assert "| 27020199 | 王益联社 | 1000 | 800 | 0.25" in rendered


def test_cli_import_design_json(tmp_path: Path):
    db_path = tmp_path / "definitions.duckdb"
    design = {
        "report": {
            "report_id": "business_analysis",
            "report_name": "经营分析报告",
            "report_title": "2024年经营分析报告",
            "status": "draft",
            "version": 1,
        },
        "sections": [{
            "section_id": "overview",
            "section_key": "overview",
            "section_title": "一、总体经营情况",
            "section_order": 10,
        }],
        "tables": [{
            "table_id": "main_metrics",
            "section_id": "overview",
            "table_title": "主要经营指标表",
            "table_order": 10,
            "metrics": [{
                "idx_id": "BAS_0263",
                "period_alias": "本期",
                "data_unit": "万元",
                "metric_order": 1,
            }],
        }],
    }
    design_path = tmp_path / "design.json"
    design_path.write_text(json.dumps(design, ensure_ascii=False), encoding="utf-8")

    code = main([
        "import-design-json",
        "--definitions-db", str(db_path),
        "--design-json", str(design_path),
    ])

    assert code == 0
    verify = connect_definitions(db_path)
    try:
        rows = verify.execute("SELECT report_id, status FROM reports WHERE report_id = 'business_analysis'").fetchall()
    finally:
        verify.close()
    assert rows == [("business_analysis", "draft")]


def test_cli_import_table_md_dir(tmp_path: Path):
    db_path = tmp_path / "definitions.duckdb"
    md_dir = tmp_path / "tables"
    md_dir.mkdir()
    (md_dir / "main_metrics.md").write_text("""---
report_id: business_analysis
report_name: 经营分析报告
report_title: 2024年经营分析报告
section_key: overview
section_title: 一、总体经营情况
section_order: 10
table_id: main_metrics
table_title: 主要经营指标表
table_order: 10
---
""", encoding="utf-8")
    (md_dir / "deposit_balance.md").write_text("""---
report_id: business_analysis
report_name: 经营分析报告
report_title: 2024年经营分析报告
section_key: deposit_loan
section_title: 二、存贷款业务情况
section_order: 20
table_id: deposit_balance
table_title: 存款余额表
table_order: 10
---
""", encoding="utf-8")

    code = main([
        "import-table-md-dir",
        "--definitions-db", str(db_path),
        "--dir", str(md_dir),
    ])
    assert code == 0

    verify = connect_definitions(db_path)
    try:
        report_count = verify.execute("SELECT count(*) FROM reports WHERE report_id = 'business_analysis'").fetchone()[0]
        section_count = verify.execute("SELECT count(*) FROM report_sections WHERE report_id = 'business_analysis'").fetchone()[0]
        table_count = verify.execute("SELECT count(*) FROM report_tables WHERE report_id = 'business_analysis'").fetchone()[0]
    finally:
        verify.close()
    assert report_count == 1
    assert section_count == 2  # overview + deposit_loan, deduped
    assert table_count == 2


def test_cli_approve_table(tmp_path: Path):
    db_path = tmp_path / "definitions.duckdb"
    con = connect_definitions(db_path)
    init_definition_schema(con)
    upsert_report(con, ReportRecord("business_analysis", "经营分析报告", "2024年经营分析报告", status="draft"))
    upsert_section(con, SectionRecord("overview", "business_analysis", "overview", "一、总体经营情况", 10))
    upsert_table(con, TableRecord("main_metrics", "business_analysis", "overview", "主要经营指标表", 10, approval_status="draft"))
    upsert_metric(con, MetricRecord("main_metrics", "BAS_0263", "本期", approval_status="draft"))
    upsert_compute(con, ComputeRecord(
        compute_id="main_metrics__贷款同比增速",
        table_id="main_metrics",
        compute_name="贷款同比增速",
        formula_text="(本期-去年同期)/去年同期",
        compute_sql='SELECT branch_num, 0 AS "贷款同比增速" FROM table_frame',
        approval_status="draft",
    ))
    con.close()

    code = main([
        "approve-table",
        "--definitions-db", str(db_path),
        "--table-id", "main_metrics",
        "--design-run-id", "design-001",
    ])
    assert code == 0

    verify = connect_definitions(db_path)
    try:
        table_status = verify.execute(
            "SELECT approval_status, last_design_run_id FROM report_tables WHERE table_id = 'main_metrics'"
        ).fetchone()
        metric_status = verify.execute(
            "SELECT approval_status, last_design_run_id FROM table_metrics WHERE table_id = 'main_metrics'"
        ).fetchone()
        compute_status = verify.execute(
            "SELECT approval_status, last_design_run_id FROM table_computes WHERE table_id = 'main_metrics'"
        ).fetchone()
    finally:
        verify.close()
    assert table_status == ("approved", "design-001")
    assert metric_status == ("approved", "design-001")
    assert compute_status == ("approved", "design-001")


def test_cli_activate_report(tmp_path: Path):
    db_path = tmp_path / "definitions.duckdb"
    con = connect_definitions(db_path)
    init_definition_schema(con)
    upsert_report(con, ReportRecord("business_analysis", "经营分析报告", "2024年经营分析报告", status="draft"))
    con.close()

    code = main([
        "activate-report",
        "--definitions-db", str(db_path),
        "--report-id", "business_analysis",
        "--preview-run-id", "preview-001",
    ])
    assert code == 0

    verify = connect_definitions(db_path)
    try:
        row = verify.execute(
            "SELECT status, activated_run_id FROM reports WHERE report_id = 'business_analysis'"
        ).fetchone()
    finally:
        verify.close()
    assert row == ("active", "preview-001")


def test_cli_activate_report_missing(tmp_path: Path):
    db_path = tmp_path / "definitions.duckdb"
    con = connect_definitions(db_path)
    init_definition_schema(con)
    con.close()

    code = main([
        "activate-report",
        "--definitions-db", str(db_path),
        "--report-id", "ghost",
        "--preview-run-id", "preview-001",
    ])
    assert code != 0
