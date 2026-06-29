from decimal import Decimal

from ai_report.models import MetricFact, RunParams
from ai_report.render_payload import build_render_payload
from ai_report.run_store import connect_run, create_run, init_run_schema, insert_metric_facts, snapshot_runtime_plan


def test_build_render_payload_merges_metric_and_computed_cells(tmp_path):
    con = connect_run(tmp_path / "run.duckdb")
    init_run_schema(con)
    plan = {
        "report": {"report_id": "business_analysis", "report_title": "2024年经营分析报告", "version": 1},
        "sections": [{"section_id": "overview", "report_id": "business_analysis", "section_key": "overview", "section_title": "一、总体经营情况", "section_order": 10, "description_prompt": None, "enabled": True, "metadata": "{}"}],
        "tables": [{"table_id": "main_metrics", "report_id": "business_analysis", "section_id": "overview", "table_title": "主要经营指标表", "table_order": 10, "parsed_payload": "{}", "headers": "[]", "orgs": "[]", "time_info": "[]", "description_prompt": "分析主要经营指标。", "query_failure_policy": "continue_with_sentinel", "compute_failure_policy": "stop_on_failure", "description_failure_policy": "continue_with_sentinel"}],
        "run_params": RunParams({"本期": "2024Q4"}, [], ["md"]),
    }
    create_run(con, "r001", plan)
    snapshot_runtime_plan(con, "r001", plan)
    insert_metric_facts(con, [MetricFact("r001", "main_metrics", "27020199", "王益联社", "BAS_0263", "本期", "2024Q4", "1000", Decimal("1000"), "万元")])
    con.execute("""
        INSERT INTO computed_facts VALUES
        ('r001', 'main_metrics', '27020199', '贷款同比增速', '0.1', 0.1, 'ok', NULL)
    """)

    payload = build_render_payload(con, "r001", descriptions={"main_metrics": "贷款余额同比增长。"})

    table = payload["sections"][0]["tables"][0]
    assert payload["report"]["report_id"] == "business_analysis"
    assert payload["report"]["report_title"] == "2024年经营分析报告"
    assert table["table_id"] == "main_metrics"
    assert table["rows"][0]["cells"]["BAS_0263@本期"] == "1000"
    assert table["rows"][0]["cells"]["贷款同比增速"] == "0.1"
    assert table["description_text"] == "贷款余额同比增长。"
    con.close()
