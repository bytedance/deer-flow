from decimal import Decimal

from ai_report.models import MetricFact, RunParams
from ai_report.run_store import connect_run, create_run, fetch_metric_facts, init_run_schema, insert_metric_facts, snapshot_runtime_plan


def test_run_store_snapshots_plan_and_metric_facts(tmp_path):
    con = connect_run(tmp_path / "run.duckdb")
    init_run_schema(con)
    plan = {
        "report": {"report_id": "business_analysis", "version": 3},
        "sections": [{
            "section_id": "overview",
            "report_id": "business_analysis",
            "section_key": "overview",
            "section_title": "一、总体经营情况",
            "section_order": 10,
            "description_prompt": None,
            "enabled": True,
            "metadata": "{}",
        }],
        "tables": [{
            "table_id": "main_metrics",
            "report_id": "business_analysis",
            "section_id": "overview",
            "table_title": "主要经营指标表",
            "table_order": 10,
            "parsed_payload": "{}",
            "headers": "[]",
            "orgs": "[]",
            "time_info": "[]",
            "description_prompt": "分析主要经营指标变化。",
            "query_failure_policy": "continue_with_sentinel",
            "compute_failure_policy": "stop_on_failure",
            "description_failure_policy": "continue_with_sentinel",
        }],
        "run_params": RunParams({"本期": "2024Q4"}, [], ["md"]),
    }

    create_run(con, "r001", plan)
    snapshot_runtime_plan(con, "r001", plan)
    insert_metric_facts(con, [MetricFact(
        run_id="r001",
        table_id="main_metrics",
        branch_num="27020199",
        branch_short_name="王益联社",
        idx_id="BAS_0263",
        period_alias="本期",
        period_value="2024Q4",
        raw_value="1000",
        numeric_value=Decimal("1000"),
        data_unit="万元",
    )])

    facts = fetch_metric_facts(con, "r001", "main_metrics")

    assert con.execute("SELECT count(*) FROM run_sections").fetchone()[0] == 1
    assert con.execute("SELECT count(*) FROM run_tables").fetchone()[0] == 1
    assert facts[0]["idx_id"] == "BAS_0263"
    assert facts[0]["period_alias"] == "本期"
    assert str(facts[0]["numeric_value"]) in {"1000.0000000000", "1000"}
    con.close()
