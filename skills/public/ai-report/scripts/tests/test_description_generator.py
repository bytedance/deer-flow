from decimal import Decimal

from ai_report.description_generator import generate_descriptions
from ai_report.run_store import connect_run, create_run, init_run_schema, insert_metric_facts, snapshot_runtime_plan
from ai_report.models import MetricFact, RunParams


def test_generate_descriptions_summarizes_metric_ranges(tmp_path):
    con = connect_run(tmp_path / "run.duckdb")
    init_run_schema(con)
    plan = {
        "report": {"report_id": "business_analysis", "report_title": "2024年经营分析报告", "version": 1},
        "sections": [{"section_id": "overview", "report_id": "business_analysis", "section_key": "overview", "section_title": "一、总体经营情况", "section_order": 10, "description_prompt": None, "enabled": True, "metadata": "{}"}],
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
            "description_prompt": "分析主要经营指标。",
            "query_failure_policy": "continue_with_sentinel",
            "compute_failure_policy": "stop_on_failure",
            "description_failure_policy": "continue_with_sentinel",
        }],
        "run_params": RunParams({"本期": "2024Q4"}, [], ["md"]),
    }
    create_run(con, "r001", plan)
    snapshot_runtime_plan(con, "r001", plan)
    insert_metric_facts(con, [
        MetricFact("r001", "main_metrics", "27020199", "王益联社", "BAS_0263", "本期", "2024Q4", "1000", Decimal("1000"), "万元"),
        MetricFact("r001", "main_metrics", "27020299", "耀州联社", "BAS_0263", "本期", "2024Q4", "2000", Decimal("2000"), "万元"),
        MetricFact("r001", "main_metrics", "27020199", "王益联社", "BAS_0263", "去年同期", "2023Q4", "800", Decimal("800"), "万元"),
    ])
    con.execute("""
        INSERT INTO computed_facts VALUES
        ('r001', 'main_metrics', '27020199', '贷款同比增速', '0.25', 0.25, 'ok', NULL)
    """)

    descriptions = generate_descriptions(con, "r001")

    text = descriptions["main_metrics"]
    assert "主要经营指标表" in text
    assert "1000" in text and "2000" in text  # numeric range
    assert "同比增速" in text or "同比" in text  # mentions compute
    assert "王益联社" in text or "耀州联社" in text  # branch names
    con.close()


def test_generate_descriptions_returns_sentinel_when_table_raises(tmp_path):
    con = connect_run(tmp_path / "run.duckdb")
    init_run_schema(con)
    plan = {
        "report": {"report_id": "x", "report_title": "X", "version": 1},
        "sections": [],
        "tables": [{
            "table_id": "broken",
            "report_id": "x",
            "section_id": "s1",
            "table_title": "Broken",
            "table_order": 10,
            "parsed_payload": "{}",
            "headers": "[]",
            "orgs": "[]",
            "time_info": "[]",
            "description_prompt": None,
            "query_failure_policy": "continue_with_sentinel",
            "compute_failure_policy": "continue_with_sentinel",
            "description_failure_policy": "continue_with_sentinel",
        }],
        "run_params": RunParams({}, [], ["md"]),
    }
    create_run(con, "r001", plan)
    snapshot_runtime_plan(con, "r001", plan)

    descriptions = generate_descriptions(con, "r001")

    assert descriptions["broken"] == "—"
    con.close()
