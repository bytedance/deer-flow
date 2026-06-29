from pathlib import Path

from ai_report.design_import import import_design_json
from ai_report.definition_store import load_active_report


def test_import_design_json_upserts_report_sections_tables_metrics_and_computes(definitions_db):
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
            "description_prompt": "整体经营描述。",
        }],
        "tables": [{
            "table_id": "main_metrics",
            "section_id": "overview",
            "table_title": "主要经营指标表",
            "table_order": 10,
            "source_md_path": "/uploads/x.md",
            "source_md_hash": "abc123",
            "parsed_payload": {"rows": []},
            "headers": [[{"text": "贷款余额", "idx_id": "BAS_0263", "period": "本期"}]],
            "orgs": [{"branch_num": "27020199", "branch_short_name": "王益联社"}],
            "time_info": ["本期", "去年同期"],
            "description_prompt": "分析贷款余额变化。",
            "query_failure_policy": "continue_with_sentinel",
            "compute_failure_policy": "stop_on_failure",
            "description_failure_policy": "continue_with_sentinel",
            "approval_status": "approved",
            "metrics": [{
                "idx_id": "BAS_0263",
                "period_alias": "本期",
                "data_unit": "万元",
                "header_text": "贷款余额",
                "metric_order": 1,
                "approval_status": "approved",
            }],
            "computes": [{
                "compute_id": "main_metrics__贷款同比增速",
                "compute_name": "贷款同比增速",
                "formula_text": "(本期-去年同期)/去年同期",
                "compute_sql": 'SELECT branch_num, 0.1 AS "贷款同比增速" FROM table_frame',
                "dependencies": ["BAS_0263@本期", "BAS_0263@去年同期"],
                "approval_status": "approved",
            }],
        }],
    }

    import_design_json(definitions_db, design)

    con = definitions_db
    con.execute("UPDATE reports SET status = 'active' WHERE report_id = 'business_analysis'")
    loaded = load_active_report(con, "business_analysis")
    assert loaded["report"]["report_title"] == "2024年经营分析报告"
    assert loaded["sections"][0]["section_id"] == "overview"
    assert loaded["tables"][0]["table_id"] == "main_metrics"
    assert loaded["metrics"][0]["idx_id"] == "BAS_0263"
    assert loaded["computes"][0]["compute_name"] == "贷款同比增速"


def test_import_design_json_is_atomic(tmp_path: Path, definitions_db):
    """A failed import must roll back every row written during the same call."""
    con = definitions_db

    good_design = {
        "report": {"report_id": "x", "report_name": "X", "report_title": "X"},
        "sections": [{"section_id": "s1", "section_key": "s1", "section_title": "S1", "section_order": 10}],
        "tables": [],
    }
    import_design_json(con, good_design)
    before = con.execute("SELECT count(*) FROM report_sections WHERE report_id = 'x'").fetchone()[0]
    assert before == 1

    bad_design = {
        "report": {"report_id": "x", "report_name": "X", "report_title": "X"},
        # s2 would be inserted BEFORE the metric validation fires and triggers rollback.
        "sections": [{"section_id": "s2", "section_key": "s2", "section_title": "S2", "section_order": 20}],
        "tables": [{
            "table_id": "t2",
            "section_id": "s2",
            "table_title": "T2",
            "table_order": 10,
            "metrics": [{"idx_id": "BAD IDX WITH SPACE", "period_alias": "本期", "metric_order": 1}],
        }],
    }

    try:
        import_design_json(con, bad_design)
    except ValueError:
        pass
    else:
        raise AssertionError("import_design_json should reject invalid idx_id")

    after = con.execute("SELECT count(*) FROM report_sections WHERE report_id = 'x'").fetchone()[0]
    assert after == 1, f"Rollback failed: expected 1 section (s1 only), got {after}"