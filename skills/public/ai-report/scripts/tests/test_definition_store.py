from ai_report.definition_store import (
    load_active_report,
    upsert_compute,
    upsert_metric,
    upsert_report,
    upsert_section,
    upsert_table,
)
from ai_report.models import ComputeRecord, MetricRecord, ReportRecord, SectionRecord, TableRecord


def test_upsert_and_load_active_report(definitions_db):
    upsert_report(definitions_db, ReportRecord(
        report_id="business_analysis",
        report_name="经营分析报告",
        report_title="2024年经营分析报告",
        status="active",
        version=3,
    ))
    upsert_section(definitions_db, SectionRecord(
        section_id="deposit_loan",
        report_id="business_analysis",
        section_key="deposit_loan",
        section_title="二、存贷款业务情况",
        section_order=20,
    ))
    upsert_table(definitions_db, TableRecord(
        table_id="deposit_balance",
        report_id="business_analysis",
        section_id="deposit_loan",
        table_title="存款余额表",
        table_order=10,
        headers=[[{"text": "存款余额", "idx_id": "BAS_0263", "period": "本期"}]],
        orgs=[{"branch_num": "27020199", "branch_short_name": "王益联社"}],
        time_info=["本期", "去年同期"],
        description_prompt="分析存款余额变化。",
        approval_status="approved",
    ))
    upsert_metric(definitions_db, MetricRecord(
        table_id="deposit_balance",
        idx_id="BAS_0263",
        period_alias="本期",
        data_unit="万元",
        header_text="存款余额",
        metric_order=1,
        approval_status="approved",
    ))
    upsert_compute(definitions_db, ComputeRecord(
        compute_id="deposit_balance__同比",
        table_id="deposit_balance",
        compute_name="同比",
        formula_text="(本期-去年同期)/去年同期",
        compute_sql='SELECT branch_num, 0.1 AS "同比" FROM table_frame',
        dependencies=["BAS_0263@本期", "BAS_0263@去年同期"],
        approval_status="approved",
    ))

    loaded = load_active_report(definitions_db, "business_analysis")

    assert loaded["report"]["report_id"] == "business_analysis"
    assert loaded["sections"][0]["section_id"] == "deposit_loan"
    assert loaded["tables"][0]["table_id"] == "deposit_balance"
    assert loaded["metrics"][0]["idx_id"] == "BAS_0263"
    assert loaded["computes"][0]["compute_name"] == "同比"


def test_load_active_report_rejects_draft(definitions_db):
    upsert_report(definitions_db, ReportRecord(
        report_id="draft_report",
        report_name="草稿",
        report_title="草稿",
        status="draft",
    ))

    try:
        load_active_report(definitions_db, "draft_report")
    except ValueError as exc:
        assert "Active report not found: draft_report" in str(exc)
    else:
        raise AssertionError("draft reports must not run")