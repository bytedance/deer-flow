import json

from ai_report.sqlbot_transport import (
    DEFAULT_MOCK_FIXTURE,
    MockSQLBotClient,
    QueryReportInfoResponse,
    RealSQLBotClient,
    SQLBotError,
)


def test_transport_classes_expose_expected_names():
    assert SQLBotError.__name__ == "SQLBotError"
    assert QueryReportInfoResponse.__name__ == "QueryReportInfoResponse"
    assert RealSQLBotClient.__name__ == "RealSQLBotClient"
    assert MockSQLBotClient.__name__ == "MockSQLBotClient"


def test_mock_client_reads_fixture(tmp_path):
    fixture = tmp_path / "mock.json"
    fixture.write_text(json.dumps({
        "BAS_0263@2024Q4": {
            "success": True,
            "data": [{"org_ecd": "王益联社", "value": "1000"}],
        }
    }), encoding="utf-8")

    client = MockSQLBotClient(str(fixture))
    resp = client.query_report_info(
        org_info=[{"branch_num": "27020199", "branch_short_name": "王益联社"}],
        index_info=[{"idx_id": "BAS_0263"}],
        time_info=["2024Q4"],
    )

    assert isinstance(resp, QueryReportInfoResponse)
    assert resp.code == 0
    assert resp.data[0]["success"] is True
    assert resp.data[0]["data"][0]["value"] == "1000"


def test_default_mock_fixture_points_to_ai_report_example():
    assert "skills/public/ai-report" in str(DEFAULT_MOCK_FIXTURE)
    assert DEFAULT_MOCK_FIXTURE.name == "profit_yoy.json"