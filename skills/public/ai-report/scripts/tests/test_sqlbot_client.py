from decimal import Decimal

from ai_report.sqlbot_client import query_metric_facts
from ai_report.sqlbot_transport import QueryReportInfoResponse


class FakeSqlbotTransport:
    def __init__(self):
        self.calls = []

    def query_report_info(self, org_info, index_info, time_info):
        self.calls.append({"org_info": org_info, "index_info": index_info, "time_info": time_info})
        return QueryReportInfoResponse(code=0, data=[{
            "success": True,
            "data": [
                {"org_ecd": "王益联社", "value": "1000"},
                {"org_ecd": "耀州联社", "value": "2000"},
            ],
        }])


def test_query_metric_facts_maps_sqlbot_rows_to_branch_numbers():
    transport = FakeSqlbotTransport()
    requests = [{
        "table_id": "main_metrics",
        "idx_id": "BAS_0263",
        "period_alias": "本期",
        "period_value": "2024Q4",
        "data_unit": "万元",
        "org_scope": [
            {"branch_num": "27020199", "branch_short_name": "王益联社"},
            {"branch_num": "27020299", "branch_short_name": "耀州联社"},
        ],
    }]

    facts = query_metric_facts("r001", requests, transport)

    assert transport.calls == [{
        "org_info": requests[0]["org_scope"],
        "index_info": [{"idx_id": "BAS_0263"}],
        "time_info": ["2024Q4"],
    }]
    assert facts[0].branch_num == "27020199"
    assert facts[0].branch_short_name == "王益联社"
    assert facts[0].idx_id == "BAS_0263"
    assert facts[0].period_alias == "本期"
    assert facts[0].period_value == "2024Q4"
    assert facts[0].raw_value == "1000"
    assert facts[0].numeric_value == Decimal("1000")
    assert facts[0].status == "ok"
    assert facts[1].branch_num == "27020299"
    assert facts[1].raw_value == "2000"


def test_query_metric_facts_writes_missing_branch_as_failed_fact():
    class MissingTransport:
        def query_report_info(self, org_info, index_info, time_info):
            return QueryReportInfoResponse(code=0, data=[{
                "success": True,
                "data": [{"org_ecd": "王益联社", "value": "1000"}],
            }])

    requests = [{
        "table_id": "main_metrics",
        "idx_id": "BAS_0263",
        "period_alias": "本期",
        "period_value": "2024Q4",
        "data_unit": "万元",
        "org_scope": [
            {"branch_num": "27020199", "branch_short_name": "王益联社"},
            {"branch_num": "27020299", "branch_short_name": "耀州联社"},
        ],
    }]

    facts = query_metric_facts("r001", requests, MissingTransport())

    assert facts[1].branch_num == "27020299"
    assert facts[1].raw_value == "—"


def test_query_metric_facts_marks_query_failure_for_all_requested_branches():
    class FailureTransport:
        def query_report_info(self, org_info, index_info, time_info):
            return QueryReportInfoResponse(code=0, data=[{
                "success": False,
                "data": [],
                "error": "backend timeout",
            }])

    requests = [{
        "table_id": "main_metrics",
        "idx_id": "BAS_0263",
        "period_alias": "本期",
        "period_value": "2024Q4",
        "data_unit": "万元",
        "org_scope": [{"branch_num": "27020199", "branch_short_name": "王益联社"}],
    }]

    facts = query_metric_facts("r001", requests, FailureTransport())

    assert facts[0].status == "query_failed"
    assert facts[0].raw_value == "—"
    assert facts[0].numeric_value is None
    assert facts[0].error_message == "backend timeout"


def test_query_metric_facts_raises_when_table_policy_is_stop_on_failure():
    import pytest

    class FailureTransport:
        def query_report_info(self, org_info, index_info, time_info):
            return QueryReportInfoResponse(code=0, data=[{
                "success": False,
                "data": [],
                "error": "backend timeout",
            }])

    from ai_report.sqlbot_transport import SQLBotError

    requests = [{
        "table_id": "critical_metrics",
        "idx_id": "BAS_0263",
        "period_alias": "本期",
        "period_value": "2024Q4",
        "data_unit": "万元",
        "org_scope": [{"branch_num": "27020199", "branch_short_name": "王益联社"}],
    }]

    with pytest.raises(SQLBotError, match="critical_metrics"):
        query_metric_facts(
            "r001",
            requests,
            FailureTransport(),
            table_policies={"critical_metrics": "stop_on_failure"},
        )
