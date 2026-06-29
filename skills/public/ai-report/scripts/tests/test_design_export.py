from ai_report.definition_store import upsert_compute, upsert_metric, upsert_report, upsert_section, upsert_table
from ai_report.design_export import export_report_design_markdown
from ai_report.models import ComputeRecord, MetricRecord, ReportRecord, SectionRecord, TableRecord


def test_export_report_design_markdown_from_definitions(definitions_db):
    upsert_report(definitions_db, ReportRecord(
        report_id="business_analysis",
        report_name="经营分析报告",
        report_title="2024年经营分析报告",
        status="active",
        version=3,
    ))
    upsert_section(definitions_db, SectionRecord(
        section_id="overview",
        report_id="business_analysis",
        section_key="overview",
        section_title="一、总体经营情况",
        section_order=10,
    ))
    upsert_table(definitions_db, TableRecord(
        table_id="main_metrics",
        report_id="business_analysis",
        section_id="overview",
        table_title="主要经营指标表",
        table_order=10,
        orgs=[{"branch_num": "27020199", "branch_short_name": "王益联社"}],
        time_info=["本期", "去年同期"],
        description_prompt="分析主要经营指标变化。",
        approval_status="approved",
        query_failure_policy="continue_with_sentinel",
    ))
    upsert_metric(definitions_db, MetricRecord(
        table_id="main_metrics",
        idx_id="BAS_0263",
        period_alias="本期",
        data_unit="万元",
        header_text="贷款余额",
        metric_order=1,
        approval_status="approved",
    ))
    upsert_compute(definitions_db, ComputeRecord(
        compute_id="main_metrics__贷款同比增速",
        table_id="main_metrics",
        compute_name="贷款同比增速",
        formula_text="(本期-去年同期)/去年同期",
        compute_sql='SELECT branch_num, 0.1 AS "贷款同比增速" FROM table_frame',
        dependencies=["BAS_0263@本期", "BAS_0263@去年同期"],
        approval_status="approved",
    ))

    md = export_report_design_markdown(definitions_db, "business_analysis")

    assert "# 2024年经营分析报告" in md
    assert "report_id: business_analysis" in md
    assert "## 一、总体经营情况" in md
    assert "### 主要经营指标表" in md
    assert "idx_id: BAS_0263" in md
    assert "贷款同比增速 = (本期-去年同期)/去年同期" in md
    assert '```sql compute_sql:贷款同比增速' in md
    assert 'SELECT branch_num, 0.1 AS "贷款同比增速" FROM table_frame' in md