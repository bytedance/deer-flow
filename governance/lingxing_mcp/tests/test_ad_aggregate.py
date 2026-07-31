from unittest.mock import MagicMock

from governance_lingxing_mcp.tools.ad_aggregate import (
    add_ratio_fields,
    fetch_daily_reports,
)


def _make_client(results_by_date: dict) -> MagicMock:
    """按 report_date 返回不同结果。"""
    client = MagicMock()

    def _request(method, path, params, ttl_seconds):
        return results_by_date.get(params["report_date"], {"code": 0, "data": []})

    client.request.side_effect = _request
    return client


def test_daily_loop_calls_each_day_once():
    """日期范围内每天调用一次 API。"""
    client = _make_client({})
    fetch_daily_reports(
        client, "/pb/openapi/newad/spCampaignReports", {"sid": 1},
        "2026-07-01", "2026-07-03", key_fields=("campaign_id",), ttl_seconds=1800,
    )
    assert client.request.call_count == 3
    dates = [c.kwargs["params"]["report_date"] for c in client.request.call_args_list]
    assert dates == ["2026-07-01", "2026-07-02", "2026-07-03"]


def test_merge_sums_absolutes_and_recomputes_ratios():
    """同一 campaign 跨天合并：绝对值求和，acos/roas/cvr 由求和结果重算（非简单平均）。"""
    day1 = {"code": 0, "data": [
        {"campaign_id": 1, "campaign_name": "A", "impressions": 100, "clicks": 10,
         "cost": 20.0, "orders": 2, "sales": 100.0, "units": 2},
    ]}
    day2 = {"code": 0, "data": [
        {"campaign_id": 1, "campaign_name": "A", "impressions": 300, "clicks": 30,
         "cost": 40.0, "orders": 6, "sales": 300.0, "units": 5},
    ]}
    client = _make_client({"2026-07-01": day1, "2026-07-02": day2})

    out = fetch_daily_reports(
        client, "/pb/openapi/newad/spCampaignReports", {"sid": 1},
        "2026-07-01", "2026-07-02", key_fields=("campaign_id",), ttl_seconds=1800,
    )

    assert len(out) == 1
    row = out[0]
    assert row["impressions"] == 400
    assert row["clicks"] == 40
    assert row["cost"] == 60.0
    assert row["orders"] == 8
    assert row["sales"] == 400.0
    assert row["units"] == 7
    # 比率由求和结果重算
    assert row["acos"] == round(60.0 / 400.0, 4)
    assert row["roas"] == round(400.0 / 60.0, 4)
    assert row["cvr"] == round(8 / 40, 4)
    assert row["ctr"] == round(40 / 400, 4)
    assert row["cpc"] == round(60.0 / 40, 4)
    # report_date 被移除（已聚合）
    assert "report_date" not in row


def test_merge_groups_by_key_fields():
    """不同 campaign_id 分行，互不影响。"""
    day = {"code": 0, "data": [
        {"campaign_id": 1, "cost": 10.0, "sales": 50.0},
        {"campaign_id": 2, "cost": 20.0, "sales": 200.0},
    ]}
    client = _make_client({"2026-07-01": day})
    out = fetch_daily_reports(
        client, "/p", {"sid": 1}, "2026-07-01", "2026-07-01",
        key_fields=("campaign_id",), ttl_seconds=0,
    )
    assert len(out) == 2
    ids = {r["campaign_id"] for r in out}
    assert ids == {1, 2}


def test_span_over_31_days_rejected():
    """单次跨度 >31 天返回错误提示，不发请求。"""
    client = _make_client({})
    out = fetch_daily_reports(
        client, "/p", {"sid": 1}, "2026-06-01", "2026-07-15",
        key_fields=("campaign_id",), ttl_seconds=0,
    )
    assert out and "error" in out[0]
    client.request.assert_not_called()


def test_invalid_date_range_rejected():
    client = _make_client({})
    out = fetch_daily_reports(
        client, "/p", {}, "2026-07-30", "2026-07-01",
        key_fields=("campaign_id",), ttl_seconds=0,
    )
    assert "error" in out[0]


def test_partial_day_failure_continues():
    """部分天数失败时跳过该天，用可用数据完成聚合。"""
    ok = {"code": 0, "data": [{"campaign_id": 1, "cost": 10.0, "sales": 100.0}]}
    client = _make_client({"2026-07-01": ok, "2026-07-02": {"code": 500, "message": "boom"}})
    out = fetch_daily_reports(
        client, "/p", {"sid": 1}, "2026-07-01", "2026-07-02",
        key_fields=("campaign_id",), ttl_seconds=0,
    )
    assert len(out) == 1
    assert out[0]["cost"] == 10.0


def test_all_days_failure_returns_error():
    """全部天数失败时返回 error。"""
    client = _make_client({"2026-07-01": {"code": 500, "message": "boom"}})
    out = fetch_daily_reports(
        client, "/p", {"sid": 1}, "2026-07-01", "2026-07-01",
        key_fields=("campaign_id",), ttl_seconds=0,
    )
    assert out and "error" in out[0]


def test_merge_handles_string_numerics():
    """领星数值字段可能是字符串（如 cost="12.34"），聚合需正确求和（回归：
    原实现 isinstance 检查会跳过字符串字段导致求和为 0）。"""
    day1 = {"code": 0, "data": [
        {"campaign_id": 1, "impressions": "100", "clicks": "10", "cost": "20.5", "orders": "2", "sales": "100.0"},
    ]}
    day2 = {"code": 0, "data": [
        {"campaign_id": 1, "impressions": "300", "clicks": "30", "cost": "40.5", "orders": "6", "sales": "300.0"},
    ]}
    client = _make_client({"2026-07-01": day1, "2026-07-02": day2})
    out = fetch_daily_reports(
        client, "/p", {"sid": 1}, "2026-07-01", "2026-07-02",
        key_fields=("campaign_id",), ttl_seconds=0,
    )
    row = out[0]
    assert row["cost"] == 61.0
    assert row["sales"] == 400.0
    assert row["clicks"] == 40
    assert row["acos"] == round(61.0 / 400.0, 4)


def test_add_ratio_fields_zero_denominators_are_none():
    row = {"cost": 0, "sales": 0, "clicks": 0, "impressions": 0, "orders": 0}
    add_ratio_fields(row)
    assert row["acos"] is None
    assert row["roas"] is None
    assert row["cvr"] is None
    assert row["ctr"] is None
    assert row["cpc"] is None
