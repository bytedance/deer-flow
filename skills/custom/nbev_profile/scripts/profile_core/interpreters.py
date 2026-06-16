"""
interpreters.py — 把画像查询的原始行聚合为结构化画像 + 预渲染 Markdown 表格

字段依据接口文档 SQL SELECT 列（已按 field_mapping 转驼峰）：
- 队伍：branchCode, month, diamondScoreGroup, monthOnJobHr, monthAggUndwrtNbev
- 客户：branchCode, month, clientManageTemperatureDesc, clientManageTypeDesc,
        issuedClientNum, granularityFlag
- 产品：branchCode, month, planCodeSplicingAbbrName, premTerm, planCombName,
        billHr, onJobHr, productNbev
"""

from __future__ import annotations

from . import envelope
from .errors import ApiError


def _f(x, default: float = 0.0) -> float:
    """安全转 float：脏数据（None/空/非数字）回退默认，绝不抛异常。"""
    if x is None or x == "":
        return default
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _num(x) -> str:
    try:
        f = float(x)
        return f"{f:,.0f}" if abs(f - round(f)) < 1e-9 else f"{f:,.2f}"
    except (TypeError, ValueError):
        return "—"


def _wan(x) -> str:
    """元 → 万元，1 位小数。"""
    try:
        return f"{float(x) / 10000:,.1f}"
    except (TypeError, ValueError):
        return "—"


# ── 队伍画像 ──
def interpret_team(request_id, month, rows):
    if not rows:
        return envelope.from_error(
            request_id=request_id, dimension="team",
            err=ApiError("DIMENSION_DATA_EMPTY", "未查询到队伍画像数据",
                         hint="请确认该机构该月份是否有数据"),
        )
    # 按钻石等级聚合（同等级可能多行，做求和）
    agg = {}
    for r in rows:
        g = r.get("diamondScoreGroup", "未分类")
        a = agg.setdefault(g, {"hr": 0.0, "nbev": 0.0})
        a["hr"] += _f(r.get("monthOnJobHr"))
        a["nbev"] += _f(r.get("monthAggUndwrtNbev"))
    total_hr = sum(v["hr"] for v in agg.values())
    total_nbev = sum(v["nbev"] for v in agg.values())
    order = ["双金钻", "金钻", "银钻", "钻石", "活动非钻", "非活动人力"]
    items = sorted(agg.items(), key=lambda kv: order.index(kv[0]) if kv[0] in order else 99)
    lines = ["| 钻石人群 | 在职人力 | 人力占比 | NBEV(万) | NBEV占比 |",
             "|---|--:|--:|--:|--:|"]
    for g, v in items:
        hr_r = v["hr"] / total_hr if total_hr else 0
        nb_r = v["nbev"] / total_nbev if total_nbev else 0
        lines.append(f"| {g} | {_num(v['hr'])} | {hr_r*100:.1f}% | {_wan(v['nbev'])} | {nb_r*100:.1f}% |")
    lines.append(f"| **合计** | **{_num(total_hr)}** | 100% | **{_wan(total_nbev)}** | 100% |")
    table = "\n".join(lines)
    summary = (
        f"队伍画像（{month}）：总在职人力 {_num(total_hr)} 人，"
        f"NBEV {_wan(total_nbev)} 万元，覆盖 {len(agg)} 个钻石层级。"
    )
    return envelope.ok(request_id=request_id, dimension="team",
                       data={"groups": agg, "totalHr": total_hr, "totalNbev": total_nbev},
                       summary=summary, table=table)


# ── 客户画像 ──
def interpret_customer(request_id, month, rows):
    if not rows:
        return envelope.from_error(
            request_id=request_id, dimension="customer",
            err=ApiError("DIMENSION_DATA_EMPTY", "未查询到客户画像数据",
                         hint="请确认该机构该月份是否有数据"),
        )
    temps = ["冷却", "低温", "中高温"]
    values = ["A", "BC", "DEF"]
    grid = {}
    for r in rows:
        t = r.get("clientManageTemperatureDesc", "")
        v = r.get("clientManageTypeDesc", "")
        grid[(v, t)] = grid.get((v, t), 0) + int(_f(r.get("issuedClientNum")))
    total = sum(grid.values())
    lines = ["| 客价＼客温 | " + " | ".join(temps) + " | 合计 |",
             "|---" + "|--:" * (len(temps) + 1) + "|"]
    for v in values:
        cells = [str(grid.get((v, t), 0)) for t in temps]
        rowsum = sum(grid.get((v, t), 0) for t in temps)
        lines.append(f"| {v} | " + " | ".join(cells) + f" | {rowsum} |")
    col_tot = [str(sum(grid.get((v, t), 0) for v in values)) for t in temps]
    lines.append(f"| **合计** | " + " | ".join(col_tot) + f" | **{total}** |")
    table = "\n".join(lines)
    summary = f"客户画像（{month}）：签单客户共 {total} 人，已按客温×客价九宫格分布。"
    return envelope.ok(request_id=request_id, dimension="customer",
                       data={"grid": {f"{k[0]}×{k[1]}": val for k, val in grid.items()},
                             "total": total},
                       summary=summary, table=table)


# ── 产品画像 ──
def interpret_product(request_id, month, rows):
    if not rows:
        return envelope.from_error(
            request_id=request_id, dimension="product",
            err=ApiError("DIMENSION_DATA_EMPTY", "未查询到产品画像数据",
                         hint="请确认该机构该月份是否有数据"),
        )
    # 按 产品×缴期 聚合 NBEV，取 Top 排序
    agg = {}
    for r in rows:
        name = r.get("planCodeSplicingAbbrName", "")
        term = r.get("premTerm", "")
        key = (name, term)
        a = agg.setdefault(key, {"billHr": 0.0, "onJobHr": 0.0, "nbev": 0.0})
        a["billHr"] += _f(r.get("billHr"))
        a["onJobHr"] = max(a["onJobHr"], _f(r.get("onJobHr")))
        a["nbev"] += _f(r.get("productNbev"))
    total_nbev = sum(v["nbev"] for v in agg.values())
    items = sorted(agg.items(), key=lambda kv: kv[1]["nbev"], reverse=True)
    lines = ["| 产品 | 缴期 | 出单人力 | 活动率 | NBEV(万) | NBEV占比 |",
             "|---|---|--:|--:|--:|--:|"]
    for (name, term), v in items[:15]:
        act = v["billHr"] / v["onJobHr"] if v["onJobHr"] else 0
        ratio = v["nbev"] / total_nbev if total_nbev else 0
        lines.append(f"| {name} | {term} | {_num(v['billHr'])} | {act*100:.1f}% | "
                     f"{_wan(v['nbev'])} | {ratio*100:.1f}% |")
    table = "\n".join(lines)
    extra = "（仅展示NBEV前15）" if len(items) > 15 else ""
    summary = (
        f"产品画像（{month}）：共 {len(agg)} 个产品×缴期组合，"
        f"NBEV 合计 {_wan(total_nbev)} 万元{extra}。"
    )
    return envelope.ok(request_id=request_id, dimension="product",
                       data={"items": len(agg), "totalNbev": total_nbev},
                       summary=summary, table=table)


INTERPRETERS = {
    "team": interpret_team,
    "customer": interpret_customer,
    "product": interpret_product,
}
