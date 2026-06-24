"""Unit tests for scripts/sqlbot_client.py (real + mock)."""
import json
from pathlib import Path
from unittest import mock

import pytest

import sqlbot_client as sc


def test_real_client_query_report_info_happy(sqlbot_env):
    """Real client POSTs to /api/v1/indicator/query-report-info, no Auth header."""
    fake_response = mock.Mock()
    fake_response.json.return_value = {
        "code": 0,
        "data": [{
            "success": True,
            "msg": "指标数据查询成功。",
            "data": [
                {"data_dt": "2025-12-31", "org_ecd": "王益联社",
                 "idx_name": "贷款收单商户数", "value": "1,420.00"}
            ],
        }],
    }
    fake_response.raise_for_status = mock.Mock()

    with mock.patch.object(sc.requests, "post", return_value=fake_response) as m_post:
        resp = sc.RealSQLBotClient(base_url="http://sqlbot.lan:9070").query_report_info(
            org_info=[{"branch_num": "27020199", "branch_short_name": "王益联社"}],
            index_info=[{"idx_id": "BAS_0263"}],
            time_info=["2025"],
        )

    assert resp.code == 0
    assert len(resp.data) == 1
    assert resp.data[0]["data"][0]["value"] == "1,420.00"

    # 校验 HTTP 调用的形状
    m_post.assert_called_once()
    args, kwargs = m_post.call_args
    assert args[0] == "http://sqlbot.lan:9070/api/v1/indicator/query-report-info"
    body = kwargs["json"]
    assert body["org_info"][0]["branch_num"] == "27020199"
    assert body["index_info"] == [{"idx_id": "BAS_0263"}]
    assert body["time_info"] == ["2025"]
    # 不带 Authorization 头（依规格：SQLBot 无需鉴权）
    assert "Authorization" not in kwargs["headers"]
    assert kwargs["headers"]["Content-Type"] == "application/json"


def test_real_client_raises_sqlbot_error_on_http_failure(sqlbot_env, monkeypatch):
    """4xx/5xx 透传 + @retry 重试到 max_attempts 后才抛。"""
    import requests as real_requests
    fake_response = mock.Mock()
    fake_response.raise_for_status.side_effect = real_requests.HTTPError("500 Server Error")

    # 避免真实 sleep 拖慢测试（@retry 默认 base=1, max_delay=8, 3 次）
    monkeypatch.setattr("retry.time.sleep", lambda _: None)

    with mock.patch.object(sc.requests, "post", return_value=fake_response) as m_post:
        with pytest.raises(real_requests.HTTPError, match="500"):
            sc.RealSQLBotClient(base_url="http://x").query_report_info(
                org_info=[], index_info=[{"idx_id": "X"}], time_info=[]
            )

    # @retry(max_attempts=3) 应当让 post 被调用 3 次
    assert m_post.call_count == 3


def test_real_client_raises_sqlbot_error_on_top_level_code_nonzero(sqlbot_env):
    """HTTP 200 但 code != 0 → SQLBotError，不重试（确定性业务失败）。"""
    fake_response = mock.Mock()
    fake_response.raise_for_status = mock.Mock()
    fake_response.json.return_value = {"code": 401, "msg": "auth failed"}

    with mock.patch.object(sc.requests, "post", return_value=fake_response) as m_post:
        with pytest.raises(sc.SQLBotError, match="code=401"):
            sc.RealSQLBotClient(base_url="http://x").query_report_info(
                org_info=[], index_info=[{"idx_id": "X"}], time_info=[]
            )

    # SQLBotError 不在 retry_on 元组里，应当只调用 1 次
    assert m_post.call_count == 1


def test_mock_client_returns_per_idx_data(fixture_dir):
    """Mock client: queries with single idx_id and returns that idx_id's rows only."""
    client = sc.MockSQLBotClient(fixture_path=str(fixture_dir / "mock_sqlbot" / "query_responses.json"))
    resp = client.query_report_info(
        org_info=[{"branch_num": "27020199", "branch_short_name": "王益联社"}],
        index_info=[{"idx_id": "BAS_0263"}],
        time_info=["2025"],
    )
    assert resp.code == 0
    # 按规格契约，仅返回该 idx 的行
    assert len(resp.data) == 1
    elem = resp.data[0]
    assert elem["success"] is True
    assert all(row.get("idx_name") == "贷款收单商户数" for row in elem["data"])


def test_mock_client_returns_success_false_for_failing_idx(fixture_dir):
    """Mock client for partial_failure fixture: success=false（F18 情形）。"""
    client = sc.MockSQLBotClient(fixture_path=str(fixture_dir / "mock_sqlbot" / "partial_failure.json"))
    resp = client.query_report_info(
        org_info=[], index_info=[{"idx_id": "BAS_0264"}], time_info=[]
    )
    assert resp.code == 0   # 顶层仍然为 0（依规格）
    assert resp.data[0]["success"] is False
