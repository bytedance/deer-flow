from decimal import Decimal

from ai_report.models import MetricFact
from ai_report.run_store import connect_run, init_run_schema, insert_metric_facts
from ai_report.runtime_compute import build_table_frame, execute_computes


def test_execute_compute_sql_writes_computed_facts(tmp_path):
    con = connect_run(tmp_path / "run.duckdb")
    init_run_schema(con)
    insert_metric_facts(con, [
        MetricFact("r001", "main_metrics", "27020199", "王益联社", "BAS_0263", "本期", "2024Q4", "1000", Decimal("1000"), "万元"),
        MetricFact("r001", "main_metrics", "27020199", "王益联社", "BAS_0263", "去年同期", "2023Q4", "900", Decimal("900"), "万元"),
    ])

    build_table_frame(con, "r001", "main_metrics")
    execute_computes(con, "r001", "main_metrics", [{
        "compute_name": "贷款同比增速",
        "compute_sql": '''
            SELECT
              branch_num,
              ("BAS_0263@本期" - "BAS_0263@去年同期") / "BAS_0263@去年同期" AS "贷款同比增速"
            FROM table_frame
        ''',
    }])

    rows = con.execute("SELECT branch_num, compute_name, numeric_value, status FROM computed_facts").fetchall()

    assert rows[0][0] == "27020199"
    assert rows[0][1] == "贷款同比增速"
    assert str(rows[0][2]).startswith("0.111111")
    assert rows[0][3] == "ok"
    con.close()
