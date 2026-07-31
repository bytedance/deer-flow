"""临时 E2E 闭环验证脚本：通过 MCP 协议走真实调用链（验证后删除）。

覆盖设计文档的核心闭环链路：
- lx_list_stores → 产品表现 / 广告预算+效果 / 关键词 / 达成率 / 趋势 /
  利润(配送费) / 库存冗余 / 退货 / 差评 / 竞品 / 订单
"""

import asyncio
import json
from datetime import date, timedelta

from mcp import ClientSession
from mcp.client.sse import sse_client

PASS, FAIL = [], []


def payload(r):
    """提取工具返回：优先 structuredContent，否则解析 content 文本 JSON。"""
    sc = getattr(r, "structuredContent", None)
    if sc is not None:
        return sc.get("result", sc)
    texts = [c.text for c in r.content if getattr(c, "type", None) == "text"]
    if not texts:
        return None
    if len(texts) == 1:
        return json.loads(texts[0])
    return [json.loads(t) for t in texts]


def check(name, data, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  [{'OK' if ok else 'FAIL'}] {name} {detail}")


async def main():
    async with sse_client("http://localhost:8102/sse") as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            check("19个工具注册", len(tools.tools) == 19, f"({len(tools.tools)})")

            # ① 闭环总入口
            stores = payload(await session.call_tool("lx_list_stores", {}))
            sid, mid = stores[0]["sid"], stores[0]["mid"]
            check("lx_list_stores", isinstance(stores, list) and len(stores) > 0,
                  f"→ {len(stores)} 店铺, sid={sid} mid={mid}")

            end = date.today() - timedelta(days=1)
            start = end - timedelta(days=6)

            # ② ASIN 全维度表现
            perf = payload(await session.call_tool(
                "lx_product_performance",
                {"sid": [sid], "start_date": start.isoformat(), "end_date": end.isoformat(), "length": 3}))
            rows = (perf or {}).get("list", [])
            asin = None
            if rows:
                asins = rows[0].get("asins") or []
                asin = asins[0]["asin"] if asins else None
            check("lx_product_performance", bool(rows),
                  f"→ total={perf.get('total')}, 首行 volume={rows[0].get('volume') if rows else '-'} "
                  f"acos={rows[0].get('acos') if rows else '-'}")

            # ③ 广告预算 + 效果合并
            camps = payload(await session.call_tool("lx_campaign_list", {"sid": sid, "state": "enabled", "length": 3}))
            ok = isinstance(camps, list) and camps and "error" not in camps[0]
            check("lx_campaign_list(预算)", ok,
                  f"→ {len(camps) if isinstance(camps, list) else '?'} 个活动, "
                  f"首活动 budget={camps[0].get('daily_budget') if ok else camps}")

            reports = payload(await session.call_tool(
                "lx_campaign_reports",
                {"sid": sid, "start_date": start.isoformat(), "end_date": end.isoformat()}))
            ok = isinstance(reports, list) and (not reports or "error" not in reports[0])
            has_ratio = bool(reports) and "acos" in reports[0]
            check("lx_campaign_reports(7天聚合+比率重算)", ok and has_ratio,
                  f"→ {len(reports)} 行, 首行 cost={reports[0].get('cost') if reports else '-'} "
                  f"acos={reports[0].get('acos') if reports else '-'}")

            # ④ 关键词排名（搜索参数）
            kws = payload(await session.call_tool(
                "lx_keyword_rank",
                {"mid": mid, "start_date": start.isoformat(), "end_date": end.isoformat(), "length": 3}))
            ok = isinstance(kws, list) and bool(kws)
            detail = ""
            if ok and "info" in kws[0]:
                detail = "(未监控提示闭环)"
            elif ok:
                detail = f"→ 首词 {kws[0].get('key_word')} rank={kws[0].get('rank')} sponsored={kws[0].get('is_sponsored')}"
            check("lx_keyword_rank", ok, detail)

            # ⑤ 达成率（code=1 特殊成功码）
            tgt = payload(await session.call_tool("lx_sales_target", {"assess_year": str(end.year)}))
            ok = isinstance(tgt, list) and tgt and "error" not in tgt[0]
            check("lx_sales_target(code=1适配)", ok,
                  f"→ {len(tgt) if isinstance(tgt, list) else '?'} 条目标" if ok else f"→ {tgt}")

            # ⑥ 销量趋势（天聚合）
            if asin:
                trend = payload(await session.call_tool(
                    "lx_sales_trend",
                    {"sids": str(sid), "date_start": start.isoformat(), "date_end": end.isoformat(),
                     "summary_field": "asin", "summary_field_value": asin, "granularity": "day"}))
                trows = (trend or {}).get("data", [])
                check("lx_sales_trend(按天聚合)", isinstance(trows, list),
                      f"→ {len(trows)} 天数据 (asin={asin})")

            # ⑦ 利润（配送费 #22）
            profit = payload(await session.call_tool(
                "lx_profit_report_asin",
                {"sids": [sid], "start_date": start.isoformat(), "end_date": end.isoformat(), "length": 2}))
            ok = isinstance(profit, list) and (not profit or "error" not in profit[0])
            check("lx_profit_report_asin(fbaDeliveryFee)", ok,
                  f"→ {len(profit)} 行" + (f", 首行配送费={profit[0].get('fbaDeliveryFee')}" if profit else ""))

            # ⑧ 库存冗余（#23/#24 计算字段）
            inv = payload(await session.call_tool("lx_fba_inventory", {"sid": str(sid), "length": 3}))
            ok = isinstance(inv, list) and inv and "redundant_quantity" in inv[0]
            check("lx_fba_inventory(冗余计算)", ok,
                  f"→ {len(inv) if isinstance(inv, list) else '?'} 行, 首行 redundant_qty="
                  f"{inv[0].get('redundant_quantity') if ok else '-'} cost={inv[0].get('redundant_cost') if ok else '-'}")

            # ⑨ 退货率（#21 records 结构）
            ret = payload(await session.call_tool(
                "lx_return_analysis",
                {"start_date": start.isoformat(), "end_date": end.isoformat(),
                 "asin_type": "asin", "date_type": 0, "store_id": [sid], "offset": 0, "length": 3}))
            ok = isinstance(ret, list) and (not ret or "error" not in ret[0])
            check("lx_return_analysis", ok, f"→ {len(ret)} 行")

            # ⑩ 差评闭环（#20）
            rev = payload(await session.call_tool(
                "lx_review_list",
                {"date_field": "review_time", "start_date": start.isoformat(), "end_date": end.isoformat(),
                 "sids": str(sid), "star": "1,2,3", "length": 3}))
            ok = isinstance(rev, list) and (not rev or "error" not in rev[0])
            check("lx_review_list(star=1,2,3)", ok, f"→ {len(rev)} 条差评")

            # ⑪ 竞品（空结果 hint 闭环）
            comp = payload(await session.call_tool("lx_competitor_monitor", {"length": 3}))
            ok = isinstance(comp, list) and bool(comp)
            check("lx_competitor_monitor", ok,
                  f"→ {len(comp)} 行" if "info" not in comp[0] else "(网页端添加提示闭环)")

            # ⑫ 订单
            orders = payload(await session.call_tool(
                "lx_orders", {"sid": sid, "start_date": start.isoformat(), "end_date": end.isoformat(), "length": 2}))
            ok = isinstance(orders, dict) and "data" in orders
            check("lx_orders", ok, f"→ total={orders.get('total') if ok else orders}")

            print(f"\n===== 结果: {len(PASS)} 通过, {len(FAIL)} 失败 =====")
            if FAIL:
                print("失败项:", FAIL)
                raise SystemExit(1)
            print("设计文档核心闭环链路全部走通 ✓")


asyncio.run(main())
