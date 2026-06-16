#!/usr/bin/env python3
"""
selftest.py — nbev_profile 自检脚本（随包交付，可重复回归）

mock api_client.query_dimension，覆盖维度归一化/月份缺省/聚合/空数据/渲染等路径。
用法：python scripts/selftest.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from profile_core import profiler                # noqa: E402
from profile_core.render import render_results   # noqa: E402
from profile_core.validators import normalize_dimensions, normalize_month  # noqa: E402

_fails = []


def check(name, cond):
    print(("  ✅ " if cond else "  ❌ ") + name)
    if not cond:
        _fails.append(name)


def main():
    print("== 归一化 ==")
    check("缺省维度=全部三维", normalize_dimensions(None) == ["team", "customer", "product"])
    check("'全部'展开三维", normalize_dimensions(["全部"]) == ["team", "customer", "product"])
    check("'客户'单维", normalize_dimensions(["客户"]) == ["customer"])
    check("月份缺省=当前月1号", normalize_month(None) == "2026-06-01" or normalize_month(None).endswith("-01"))
    try:
        normalize_dimensions(["收入"])
        check("非法维度报错", False)
    except Exception as e:
        check("非法维度报错", "DIMENSION_INVALID" in str(getattr(e, "code", "")))

    print("== 查询 / 聚合 / 渲染（mock）==")

    def fake_query(dim, *, request_id, org_id, month):
        assert org_id == "05"
        if dim == "team":
            return [{"diamondScoreGroup": "双金钻", "monthOnJobHr": 184, "monthAggUndwrtNbev": 25530000},
                    {"diamondScoreGroup": "非活动人力", "monthOnJobHr": 20799, "monthAggUndwrtNbev": 0}]
        if dim == "customer":
            return [{"clientManageTypeDesc": "A", "clientManageTemperatureDesc": "中高温", "issuedClientNum": 50},
                    {"clientManageTypeDesc": "BC", "clientManageTemperatureDesc": "低温", "issuedClientNum": 23}]
        if dim == "product":
            return [{"planCodeSplicingAbbrName": "御享金越", "premTerm": "10年缴",
                     "billHr": 15468, "onJobHr": 22630, "productNbev": 25578000}]
        return []

    profiler.query_dimension = fake_query
    out = profiler.profile(user_id="U1", dimensions=None, month="2026-06-01")
    st = {r["dimension"]: r["status"] for r in out["results"]}
    check("队伍 success", st.get("team") == "success")
    check("客户 success", st.get("customer") == "success")
    check("产品 success", st.get("product") == "success")
    md = render_results(out)
    check("MD 含队伍表", "钻石人群" in md)
    check("MD 含客户九宫格", "客价＼客温" in md)
    check("MD 含产品表", "出单人力" in md)

    print("== 空数据 / 脏数据 ==")
    profiler.query_dimension = lambda d, **k: []
    r = profiler.profile(user_id="U1", dimensions=["队伍"], month="2026-06-01")["results"][0]
    check("空数据→no_data", r["status"] == "no_data")

    profiler.query_dimension = lambda d, **k: [{"diamondScoreGroup": "双金钻",
                                                "monthOnJobHr": "脏", "monthAggUndwrtNbev": None}]
    r = profiler.profile(user_id="U1", dimensions=["队伍"], month="2026-06-01")["results"][0]
    check("脏数据不崩溃", r["status"] == "success")

    print()
    if _fails:
        print(f"FAILED: {len(_fails)} 项 -> {_fails}")
        sys.exit(1)
    print("ALL PASS ✅")


if __name__ == "__main__":
    main()
