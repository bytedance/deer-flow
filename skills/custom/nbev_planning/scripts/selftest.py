#!/usr/bin/env python3
"""
selftest.py — nbev_planning 自检脚本（随包交付，可重复回归）

不依赖真实后端：mock api_client，覆盖校验/澄清/护栏/不可达/渲染等关键路径。
用法：python scripts/selftest.py   （全部通过打印 ALL PASS）
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from nbev_core import planner          # noqa: E402
from nbev_core.render import render_results  # noqa: E402

_fails = []


def check(name, cond):
    print(("  ✅ " if cond else "  ❌ ") + name)
    if not cond:
        _fails.append(name)


def main():
    print("== 校验 / 澄清路径 ==")
    r = planner.plan(user_id="U1", dimensions=None, target_nbev=None)["results"][0]
    check("无维度无目标→needs_clarification", r["status"] == "needs_clarification")
    check("hint含两问", "维度" in r["error"]["hint"] and "NBEV" in r["error"]["hint"])

    r = planner.plan(user_id="U1", dimensions=["产品"], target_nbev=-5)["results"][0]
    check("负目标→TARGET_NBEV_NONPOSITIVE", r["error"]["error_code"] == "TARGET_NBEV_NONPOSITIVE")

    r = planner.plan(user_id="U1", dimensions=["收入"], target_nbev=6000)["results"][0]
    check("非法维度→DIMENSION_INVALID", r["error"]["error_code"] == "DIMENSION_INVALID")

    r = planner.plan(user_id="U1", dimensions=["产品"], target_nbev=6000, month="2026-7")["results"][0]
    check("非法月份→MONTH_FORMAT_INVALID", r["error"]["error_code"] == "MONTH_FORMAT_INVALID")

    out = planner.plan(user_id="U1", dimensions=["产品"], target_nbev=6000)
    check("月份缺省=下月1号", out["org"]["month"] == "2026-07-01" or out["org"]["month"].endswith("-01"))
    check("机构写死05/深圳", out["org"]["org_id"] == "05" and out["org"]["org_name"] == "深圳")

    print("== 成功 / 护栏 / 不可达（mock 接口）==")

    def fake(dim, payload):
        assert payload["org_id"] == "05"
        if dim == "team":
            return {"calculationSummary": {"onJobHr": 22630, "predictedNbev": 6000.25,
                    "achievementRate": 1.0, "workforceBreakdown": [
                        {"diamondGroup": "双金钻", "hr": 184, "hrRatio": 0.008, "nbev": 2553, "nbevRatio": 0.425},
                        {"diamondGroup": "钻石及以上占比", "hrRatio": 0.043, "nbevRatio": 0.743}]}}
        if dim == "product":
            return {"calculationSummary": {"predictedNbev": 6012.5, "achievementRate": 1.0021},
                    "productPathEstimation": {"productDetails": [{"productName": "御享金越", "items": [
                        {"paymentPeriod": "10年缴", "activityHr": 15468, "activityRate": 0.68, "polNum": 24915,
                         "avgPolNumFyp": 341543, "nbevContribution": 2557.8, "contributionRatio": 0.42,
                         "activityRateStatus": 1, "avgPolNumFypStatus": 0, "isDistributed": True}]}]}}
        return {}  # customer empty -> unreachable

    planner.call_calculation = fake
    out = planner.plan(user_id="U1", dimensions=["产品", "队伍", "客户"], target_nbev=6000)
    st = {r["dimension"]: r["status"] for r in out["results"]}
    check("产品 success", st.get("product") == "success")
    check("队伍 success", st.get("team") == "success")
    check("客户空→target_unreachable", st.get("customer") == "target_unreachable")
    team = next(r for r in out["results"] if r["dimension"] == "team")
    check("C2 护栏识别偏离(74.3%)", team["validation"]["passed"] is False)
    prod = next(r for r in out["results"] if r["dimension"] == "product")
    check("C4 护栏识别触边", prod["validation"]["passed"] is False)

    md = render_results(out)
    check("MD 含表格分隔", "|---" in md or "|--:" in md)
    check("MD 含护栏提示", "护栏提示" in md)

    # 准确性：预测未达目标必须被识别并标红
    planner.call_calculation = lambda d, p: {
        "calculationSummary": {"predictedNbev": 4500, "achievementRate": 0.75, "onJobHr": 22000,
                               "workforceBreakdown": []},
        "productPathEstimation": {"productDetails": [{"productName": "X", "items": [
            {"paymentPeriod": "10年缴", "activityRateStatus": 0, "avgPolNumFypStatus": 0}]}]},
    } if d == "product" else {}
    out2 = planner.plan(user_id="U1", dimensions=["产品"], target_nbev=6000)
    prod2 = out2["results"][0]
    check("未达目标→ACH护栏不通过", any(
        c["code"] == "ACH_target_met" and not c["passed"] for c in prod2["validation"]["checks"]))
    check("未达目标→summary标红", "未达目标" in prod2["summary"])

    # 脏数据鲁棒性：脏字段不应使维度崩溃
    planner.call_calculation = lambda d, p: {"calculationSummary": {"predictedNbev": "脏", "achievementRate": None},
                                             "productPathEstimation": {"productDetails": []}} if d == "product" else {}
    out = planner.plan(user_id="U1", dimensions=["产品"], target_nbev=6000)
    check("脏数据不崩溃", out["results"][0]["status"] in ("success", "validation_error", "runtime_error"))

    print()
    if _fails:
        print(f"FAILED: {len(_fails)} 项 -> {_fails}")
        sys.exit(1)
    print("ALL PASS ✅")


if __name__ == "__main__":
    main()
