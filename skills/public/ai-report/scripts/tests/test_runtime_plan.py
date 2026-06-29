from ai_report.definition_store import upsert_metric, upsert_report, upsert_section, upsert_table
from ai_report.models import MetricRecord, ReportRecord, RunParams, SectionRecord, TableRecord
from ai_report.runtime_plan import build_runtime_plan


def _seed_report(con):
    upsert_report(con, ReportRecord("business_analysis", "经营分析报告", "2024年经营分析报告", status="active"))
    upsert_section(con, SectionRecord("overview", "business_analysis", "overview", "一、总体经营情况", 10))
    upsert_table(con, TableRecord(
        table_id="main_metrics",
        report_id="business_analysis",
        section_id="overview",
        table_title="主要经营指标表",
        table_order=10,
        orgs=[{"branch_num": "27020199", "branch_short_name": "王益联社"}],
        approval_status="approved",
    ))
    upsert_metric(con, MetricRecord(
        table_id="main_metrics",
        idx_id="BAS_0263",
        period_alias="本期",
        data_unit="万元",
        header_text="贷款余额",
        metric_order=1,
        approval_status="approved",
    ))
    upsert_metric(con, MetricRecord(
        table_id="main_metrics",
        idx_id="BAS_0263",
        period_alias="去年同期",
        data_unit="万元",
        header_text="贷款余额",
        metric_order=2,
        approval_status="approved",
    ))


def test_build_runtime_plan_resolves_periods_and_org_scope(definitions_db):
    _seed_report(definitions_db)
    params = RunParams(
        period_bindings={"本期": "2024Q4", "去年同期": "2023Q4"},
        org_scope=[{"branch_num": "27020199", "branch_short_name": "王益联社"}],
        output_formats=["md"],
    )

    plan = build_runtime_plan(definitions_db, "business_analysis", params)

    assert plan["report"]["report_id"] == "business_analysis"
    assert plan["metric_requests"] == [
        {
            "table_id": "main_metrics",
            "idx_id": "BAS_0263",
            "period_alias": "本期",
            "period_value": "2024Q4",
            "data_unit": "万元",
            "org_scope": [{"branch_num": "27020199", "branch_short_name": "王益联社"}],
        },
        {
            "table_id": "main_metrics",
            "idx_id": "BAS_0263",
            "period_alias": "去年同期",
            "period_value": "2023Q4",
            "data_unit": "万元",
            "org_scope": [{"branch_num": "27020199", "branch_short_name": "王益联社"}],
        },
    ]


def test_build_runtime_plan_fails_for_missing_period_binding(definitions_db):
    _seed_report(definitions_db)
    params = RunParams(period_bindings={"本期": "2024Q4"}, org_scope=[], output_formats=["md"])

    try:
        build_runtime_plan(definitions_db, "business_analysis", params)
    except KeyError as exc:
        assert "Missing period binding: 去年同期" in str(exc)
    else:
        raise AssertionError("missing period binding should fail before SQLBot query")